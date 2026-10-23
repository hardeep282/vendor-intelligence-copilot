# Day 9 fine-tuning benchmark (B7) — Colab scaffolding

Scope: Day 9 steps 2-3 and 5-6 of the 10-day sprint (`docs/HANDOFF.md`) — QLoRA SFT of a small
open model on the execution-verified question→SQL pairs, a base vs few-shot vs QLoRA
comparison, and an honest results table + ADR. Step 1 (generating the pairs) and step 4 (the
MCP server) are already done for real — see `docs/BUILD_LOG.md`'s Day 9 entries.

**Why this lives outside `src/` and `scripts/`, as its own top-level folder:** everything in
`src/copilot` is strict-mypy'd, ruff-checked, and deployed as part of the running app
(`pyproject.toml`'s `dependencies`). Fine-tuning needs `torch`, `transformers`, `peft`,
`bitsandbytes` and `trl` — multi-gigabyte, GPU-oriented packages the deployed API has no use
for and that would bloat every `uv sync` and every CI run for code that only ever runs once,
offline, on a GPU this project doesn't otherwise have. Keeping them in `finetuning/
requirements-colab.txt` instead of `pyproject.toml` is the same "don't add a dependency this
environment can't actually support" judgment already made elsewhere (e.g. pinning `mcp<2.0`,
keeping Docker-only infra in `infra/local/`) — not a new policy, just applied to a new case.

**Why this couldn't be run for real in this session:** no GPU in this cloud sandbox. Everything
here is written and ready to run, but the actual training run, the actual comparison numbers,
and the actual ADR decision all still need you to open `day9_qlora_colab.ipynb` in Google Colab
with a (free) T4 runtime. That's the honest state as of 23 Oct — recorded here and in
`docs/BUILD_LOG.md` rather than implied otherwise.

## What's here

| File | What it is |
|---|---|
| `day9_qlora_colab.ipynb` | The Colab notebook: loads `evals/datasets/sql_pairs_v1.jsonl`, splits train/held-out, fine-tunes a small base model with QLoRA (4-bit NF4 + LoRA adapter), completion-only loss, saves the adapter |
| `requirements-colab.txt` | The Colab-only pip install list — never added to `pyproject.toml` |
| `eval_compare.py` | Runs after training (in Colab, or anywhere with a GPU/enough RAM and these packages): compares base model, few-shot base, and QLoRA-adapted model on the held-out split, each answer re-executed against the real snapshot and checked row-for-row — same "re-execute and compare" convention `copilot.evals.golden.verify()` already uses, not a new one invented for this script. Frontier-API row is optional (`--include-frontier`, needs `ANTHROPIC_API_KEY`) and is the sprint's own named cut-first item if time runs short |
| `results_template.md` | Where the real numbers go once you've run the notebook + eval script. Currently a template, not a result. |

`docs/adr/007-finetuning-outcome.md` is the ADR itself — decision framework now, filled in with
the real outcome (adopt or don't, either is a valid, honest result per the sprint brief) once
you've run this.

## The base model, and why

**Qwen2.5-1.5B-Instruct** (Apache 2.0). Checked against current practice rather than assumed:
small enough to QLoRA-finetune on a free Colab T4 (4-bit base + LoRA adapter fits comfortably in
T4's 16GB), and there's an established, documented pattern of fine-tuning this exact model size
for text-to-SQL (e.g. the Spider-dataset QLoRA write-ups below) — not a novel or unverified
choice for this task.

Sources:
- [Fine-tuning Qwen 1.5B for text-to-SQL generation using QLoRA on the Spider dataset](https://app.readytensor.ai/publications/fine-tuning-qwen-15b-for-text-to-sql-generation-using-qlora-on-the-spider-dataset-lWoJuAsWC4BS)
- [From prose to SQL: QLoRA fine-tuning of Qwen2.5-1.5B](https://app.readytensor.ai/publications/from-prose-to-sql-qlora-fine-tuning-of-qwen25-15b-QDo6h0YmjV0N)
- [Fine-Tune Open-Source LLMs: LoRA, QLoRA, Gemma (2026)](https://www.kunalganglani.com/blog/fine-tune-open-source-llm-lora-qlora)

If you'd rather use a different base model, swap the `BASE_MODEL` constant at the top of the
notebook and `eval_compare.py` — nothing else in either file assumes Qwen specifically.

## How to run it

1. Open `day9_qlora_colab.ipynb` in Google Colab (Runtime → Change runtime type → T4 GPU, the
   free tier is enough).
2. When the notebook asks, upload `evals/datasets/sql_pairs_v1.jsonl` and
   `data/snapshot/MANIFEST.json` from this repo (both already committed, both licence-safe —
   the manifest is column names only, no data).
3. Run all cells. It installs `requirements-colab.txt`'s packages, trains, and ends by
   downloading two files: the LoRA adapter (`qlora_adapter/`, zipped) and `held_out.jsonl` (the
   15% split the model never trained on — `eval_compare.py` needs this exact file, not a
   re-split, so the comparison is apples-to-apples).
4. Also download `data/snapshot/snapshot.duckdb` from wherever you built the real snapshot
   (your machine, or this session if you still have it open) — `eval_compare.py` executes every
   candidate SQL against this real database to check correctness, not just "did it parse."
5. Either in the same Colab notebook (one more cell: `!python eval_compare.py ...`) or on your
   own machine with `pip install -r requirements-colab.txt`, run:
   ```
   python eval_compare.py --adapter-dir qlora_adapter --held-out held_out.jsonl --snapshot-dir data/snapshot
   ```
   Add `--include-frontier` if you want the frontier-API row too (needs `ANTHROPIC_API_KEY`;
   this is the sprint's own cut-first item, so leave it off if you're short on time).
6. Paste the printed table into `results_template.md`, and fill in `docs/adr/
   007-finetuning-outcome.md`'s decision with the real numbers — adopt the fine-tuned model or
   don't, either outcome is fine, but it should be the one the numbers actually show.

## What "completion-only loss" means here (per the sprint spec)

The notebook builds each training example as `prompt + sql`, tokenizes the whole thing, then
sets every label at a prompt-token position to `-100` (PyTorch's "ignore this position"
sentinel for `CrossEntropyLoss`) so the model is only ever graded on predicting the SQL tokens,
never on reproducing the schema card or the question back. Masking is done by re-tokenizing the
prompt alone to find its token length and zeroing out labels up to that length — the standard,
simplest-correct way to do this (no special tokenizer feature needed), not something invented
for this notebook.
