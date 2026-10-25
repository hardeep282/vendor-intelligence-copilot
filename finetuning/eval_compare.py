"""Day 9 steps 3 & 5 -- compare base vs few-shot-base vs QLoRA (vs optional frontier API) on the
held-out split `day9_qlora_colab.ipynb` produced.

Purpose : an honest answer to "did the fine-tune help", measured the same way the rest of this
          project measures text-to-SQL correctness -- re-execute the candidate SQL against the
          real snapshot and compare its rows to the ground-truth SQL's rows, row for row. That
          is exactly `copilot.evals.golden.verify()`'s own pattern; this script reimplements it
          standalone (rather than importing `copilot`) so it can run in Colab, or anywhere else
          with `requirements-colab.txt` installed, without the whole private repo cloned.
Inputs  : --held-out (held_out.jsonl from the notebook), --adapter-dir (the saved LoRA
          adapter), --snapshot-dir (a directory holding snapshot.duckdb -- download it from
          wherever the real snapshot was built; see finetuning/README.md).
Outputs : a results table printed to stdout (and written to --out as JSON) -- execution
          accuracy, executable rate (ran without a SQL error, regardless of correctness) and
          mean latency per model variant. Paste the printed table into
          finetuning/results_template.md.
Run     : python eval_compare.py --adapter-dir qlora_adapter --held-out held_out.jsonl \\
              --snapshot-dir data/snapshot [--include-frontier]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

BASE_MODEL = "Qwen/Qwen2.5-1.5B-Instruct"  # keep in sync with the notebook's own BASE_MODEL


@dataclass
class CaseResult:
    question: str
    generated_sql: str | None
    executable: bool
    correct: bool
    latency_s: float
    error: str | None = None


def load_held_out(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def build_schema_card(manifest_path: Path) -> str:
    """Same rendering as the notebook's own cell 3 and, in production,
    `copilot.sql.schema.build_schema_card` -- reads the same MANIFEST.json, not a separately
    hand-maintained copy."""
    manifest = json.loads(manifest_path.read_text())
    lines = []
    for table in sorted(manifest["tables"]):
        cols = [c for c in manifest["tables"][table]["columns"] if c != "MeetsMinK"]
        lines.append(f"{table}: {', '.join(cols)}")
    return "\n".join(lines)


# Must stay word-for-word identical to the notebook's cell 6 copy: the QLoRA model was trained
# on prompts containing this line, so evaluating it on a different prompt would be train/serve
# skew, and the base variants need the same hint to make the comparison fair.
CASE_HINT = (
    "Vendor names may be stored in any letter case, so filter them case-insensitively: "
    "lower(VendorName) = lower('<name exactly as written in the question>')."
)


def build_prompt(schema_card: str, question: str) -> str:
    return (
        "You are a careful SQL analyst. Given the schema below, write ONE DuckDB SELECT "
        "statement that answers the question. Only use the tables and columns shown. "
        f"{CASE_HINT} "
        "Respond with SQL only, no explanation.\n\n"
        f"### Schema\n{schema_card}\n\n"
        f"### Question\n{question}\n\n"
        "### SQL\n"
    )


def few_shot_pool(
    all_pairs: list[dict[str, Any]], held_out: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """The pairs few-shot retrieval may draw examples from: everything EXCEPT the held-out set.

    Before 25 Oct 2026 this script retrieved from the whole sql_pairs file, held-out rows
    included -- so for 60 of 60 held-out questions the top "similar example" was the test
    question itself with its ground-truth SQL attached, and the few-shot row measured copying,
    not generalisation. Excluded by id and by question text (belt and braces: a re-split or a
    hand-edited file could keep one and change the other).
    """
    held_ids = {p.get("id") for p in held_out if p.get("id") is not None}
    held_questions = {p["question"] for p in held_out}
    return [
        p for p in all_pairs if p.get("id") not in held_ids and p["question"] not in held_questions
    ]


def retrieve_few_shot(question: str, train_pairs: list[dict[str, Any]], k: int = 3) -> str:
    """Minimal token-overlap retrieval -- deliberately the same shape as the production
    system's own `copilot.sql.examples.retrieve_examples` (lexical Jaccard overlap, not
    embeddings, same reasoning: cheap and adequate for a dataset this size), reimplemented
    standalone for the reason given in this file's module docstring."""
    word_re = re.compile(r"[a-z0-9]+")

    def tokens(text: str) -> set[str]:
        return set(word_re.findall(text.lower()))

    q_tokens = tokens(question)
    scored = []
    for pair in train_pairs:
        p_tokens = tokens(pair["question"])
        union = q_tokens | p_tokens
        overlap = len(q_tokens & p_tokens) / len(union) if union else 0.0
        scored.append((overlap, pair))
    scored.sort(key=lambda x: -x[0])
    examples = scored[:k]
    return "\n\n".join(f"Q: {p['question']}\nSQL: {p['sql']}" for _, p in examples)


def _extract_sql(generated_text: str) -> str:
    """Generated text may include markdown fences or trailing prose -- take the first
    statement-shaped chunk. Not a safety validator (this script measures a research baseline,
    not a production path) -- `copilot.sql.validator` is what the real app runs candidate SQL
    through; this is a much smaller "get the SQL out of the model's text" extraction."""
    text = generated_text.strip()
    text = re.sub(r"^```sql\s*|^```\s*|```$", "", text, flags=re.MULTILINE).strip()
    # Stop at the first blank line or a second statement, if the model kept talking.
    first_block = text.split("\n\n")[0]
    return first_block.strip().rstrip(";")


def _casefold_value(v: Any) -> Any:
    """Lowercase string leaves, recurse into dicts/lists; mirrors `copilot.evals.golden`'s own
    `_casefold_value` (same reasoning: `ACME CORP` vs `Acme Corp` is the same vendor, not a wrong
    answer -- a candidate query shouldn't be marked incorrect purely for returning different
    string casing than the ground truth)."""
    if isinstance(v, str):
        return v.lower()
    if isinstance(v, dict):
        return {k: _casefold_value(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_casefold_value(x) for x in v]
    return v


def run_against_snapshot(con: duckdb.DuckDBPyConnection, sql: str) -> list[dict[str, Any]]:
    cur = con.execute(sql)
    cols = [d[0] for d in cur.description]
    rows = []
    for row in cur.fetchall():
        rows.append(
            {
                c: (round(v, 2) if isinstance(v, float) else v)
                for c, v in zip(cols, row, strict=True)
            }
        )
    return rows


def evaluate_variant(
    name: str,
    generate_fn: Any,
    held_out: list[dict[str, Any]],
    con: duckdb.DuckDBPyConnection,
) -> list[CaseResult]:
    results = []
    for example in held_out:
        start = time.perf_counter()
        try:
            generated = generate_fn(example["question"])
        except Exception as exc:  # noqa: BLE001 -- a generation failure is a result, not a crash
            results.append(
                CaseResult(example["question"], None, False, False, 0.0, f"generation error: {exc}")
            )
            continue
        latency = time.perf_counter() - start

        candidate_sql = _extract_sql(generated)
        try:
            ground_truth_rows = run_against_snapshot(con, example["sql"])
        except duckdb.Error as exc:
            # The ground truth itself should always execute (it came from generate_sql_pairs.py's
            # own execution filter) -- if it doesn't, the snapshot given to this script doesn't
            # match the one the pairs were generated against. Surface that loudly, don't hide it.
            raise RuntimeError(
                f"ground-truth SQL failed against this snapshot -- wrong/stale snapshot.duckdb? "
                f"question={example['question']!r} error={exc}"
            ) from exc

        try:
            candidate_rows = run_against_snapshot(con, candidate_sql)
            executable = True
            # Case-insensitive on string values -- see `_casefold_value` docstring.
            correct = _casefold_value(candidate_rows) == _casefold_value(ground_truth_rows)
            error = None
        except duckdb.Error as exc:
            executable = False
            correct = False
            error = str(exc)

        results.append(
            CaseResult(example["question"], candidate_sql, executable, correct, latency, error)
        )
    return results


def summarize(name: str, results: list[CaseResult]) -> dict[str, Any]:
    n = len(results)
    executable = sum(r.executable for r in results)
    correct = sum(r.correct for r in results)
    mean_latency = sum(r.latency_s for r in results) / n if n else 0.0
    return {
        "variant": name,
        "n": n,
        "executable_rate": round(executable / n, 3) if n else 0.0,
        "execution_accuracy": round(correct / n, 3) if n else 0.0,
        "mean_latency_s": round(mean_latency, 3),
    }


def _load_model_and_tokenizer(adapter_dir: Path | None):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL, quantization_config=bnb_config, device_map="auto"
    )
    if adapter_dir is not None:
        from peft import PeftModel

        model = PeftModel.from_pretrained(model, str(adapter_dir))
    model.eval()
    return model, tokenizer


def _hf_generate_fn(model: Any, tokenizer: Any, prompt_builder: Any) -> Any:
    import torch

    def generate(question: str) -> str:
        prompt = prompt_builder(question)
        inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
        with torch.no_grad():
            out = model.generate(**inputs, max_new_tokens=150, do_sample=False)
        return tokenizer.decode(out[0][inputs["input_ids"].shape[1] :], skip_special_tokens=True)

    return generate


def _frontier_generate_fn(schema_card: str) -> Any:
    """The cut-first row (sprint spec: "Cut first: drop the frontier-API row"). Calls the
    Anthropic API directly rather than importing `copilot.sql.service.TextToSqlService` --
    same standalone-script reasoning as `retrieve_few_shot` above -- so this still measures a
    comparable "one-shot generate the SQL" baseline, not the production service's own
    validator/self-correction loop (that loop is what makes production safe; it would make this
    comparison apples-to-oranges against the other three variants, which also get one shot)."""
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    def generate(question: str) -> str:
        prompt = build_prompt(schema_card, question)
        message = client.messages.create(
            model="claude-sonnet-5",
            max_tokens=150,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(block.text for block in message.content if hasattr(block, "text"))

    return generate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--held-out", type=Path, required=True)
    parser.add_argument("--adapter-dir", type=Path, required=True)
    parser.add_argument("--snapshot-dir", type=Path, required=True)
    parser.add_argument(
        "--manifest", type=Path, default=None, help="defaults to <snapshot-dir>/MANIFEST.json"
    )
    parser.add_argument(
        "--train-pairs",
        type=Path,
        default=None,
        help="evals/datasets/sql_pairs_v2.jsonl, for few-shot retrieval (defaults to a file of "
        "that name next to --held-out). Held-out rows are always removed from it first.",
    )
    parser.add_argument("--include-frontier", action="store_true")
    parser.add_argument("--out", type=Path, default=Path("eval_compare_results.json"))
    args = parser.parse_args()

    manifest_path = args.manifest or (args.snapshot_dir / "MANIFEST.json")
    schema_card = build_schema_card(manifest_path)
    held_out = load_held_out(args.held_out)

    train_pairs_path = args.train_pairs or (args.held_out.parent / "sql_pairs_v2.jsonl")
    all_pairs = load_held_out(train_pairs_path) if train_pairs_path.exists() else []
    train_pairs = few_shot_pool(all_pairs, held_out)
    if all_pairs:
        print(
            f"few-shot pool: {len(train_pairs)} pairs "
            f"({len(all_pairs) - len(train_pairs)} held-out rows removed from {len(all_pairs)})"
        )
    if not train_pairs:
        print(
            f"warning: no train-pairs file found at {train_pairs_path} -- few-shot variant will "
            "run with zero examples (degrades to the base variant). Pass --train-pairs explicitly."
        )

    db_path = args.snapshot_dir / "snapshot.duckdb"
    con = duckdb.connect(str(db_path), read_only=True)

    print("loading base model (4-bit)...")
    base_model, tokenizer = _load_model_and_tokenizer(adapter_dir=None)
    base_generate = _hf_generate_fn(base_model, tokenizer, lambda q: build_prompt(schema_card, q))

    def few_shot_generate(question: str) -> str:
        examples_block = retrieve_few_shot(question, train_pairs)
        prompt = build_prompt(schema_card, question) + f"\n(Similar examples:\n{examples_block})\n"
        inputs = tokenizer(prompt, return_tensors="pt").to(base_model.device)
        import torch

        with torch.no_grad():
            out = base_model.generate(**inputs, max_new_tokens=150, do_sample=False)
        return tokenizer.decode(out[0][inputs["input_ids"].shape[1] :], skip_special_tokens=True)

    summaries = []

    print("evaluating: base (zero-shot)")
    summaries.append(
        summarize(
            "base_zero_shot", evaluate_variant("base_zero_shot", base_generate, held_out, con)
        )
    )

    print("evaluating: base + few-shot")
    summaries.append(
        summarize(
            "base_few_shot", evaluate_variant("base_few_shot", few_shot_generate, held_out, con)
        )
    )

    print("loading QLoRA-adapted model...")
    # Reassign rather than `del` -- `del` would unbind the name that `few_shot_generate`'s
    # closure above still refers to, which a linter's flow analysis flags as a potential
    # use-after-free even though every call to that closure already happened above. Freeing the
    # underlying GPU memory still happens via gc + empty_cache.
    base_model = None
    import gc

    import torch

    gc.collect()
    torch.cuda.empty_cache()

    qlora_model, qlora_tokenizer = _load_model_and_tokenizer(adapter_dir=args.adapter_dir)
    qlora_generate = _hf_generate_fn(
        qlora_model, qlora_tokenizer, lambda q: build_prompt(schema_card, q)
    )
    print("evaluating: QLoRA fine-tuned")
    summaries.append(summarize("qlora", evaluate_variant("qlora", qlora_generate, held_out, con)))

    if args.include_frontier:
        print("evaluating: frontier API (cut-first row)")
        frontier_generate = _frontier_generate_fn(schema_card)
        summaries.append(
            summarize(
                "frontier_api", evaluate_variant("frontier_api", frontier_generate, held_out, con)
            )
        )

    print()
    header = (
        f"{'variant':<16} {'n':>4} {'executable_rate':>16} "
        f"{'execution_accuracy':>19} {'mean_latency_s':>15}"
    )
    print(header)
    print("-" * len(header))
    for s in summaries:
        print(
            f"{s['variant']:<16} {s['n']:>4} {s['executable_rate']:>16} "
            f"{s['execution_accuracy']:>19} {s['mean_latency_s']:>15}"
        )

    args.out.write_text(json.dumps(summaries, indent=2), encoding="utf-8")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
