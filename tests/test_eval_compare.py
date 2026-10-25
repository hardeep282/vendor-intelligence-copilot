"""Tests for finetuning/eval_compare.py -- the Day 9 base vs few-shot vs QLoRA comparison.

The script is deliberately standalone (it runs in Colab without the package installed), so it is
loaded by file path here rather than imported from `copilot`. Only the pure helpers are tested:
nothing below loads a model, needs a GPU, or touches the real snapshot.

What these pin down (both found 25 Oct 2026, see docs/BUILD_LOG.md):
1. Few-shot leakage -- retrieval used to draw examples from the full pairs file, held-out rows
   included, so 60 of 60 held-out questions got themselves (with the answer) as the top example.
2. Train/serve prompt parity -- the notebook trains on its own copy of `build_prompt`; the
   script evaluates with this one. They must produce identical text.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "finetuning" / "eval_compare.py"
NOTEBOOK = REPO_ROOT / "finetuning" / "day9_qlora_colab.ipynb"
PAIRS_V2 = REPO_ROOT / "evals" / "datasets" / "sql_pairs_v2.jsonl"


@pytest.fixture(scope="module")
def ec():
    spec = importlib.util.spec_from_file_location("eval_compare", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before exec: `CaseResult` is a `@dataclass` with `from __future__ import
    # annotations` in eval_compare.py, so the decorator resolves its field types by looking
    # the module up in `sys.modules[cls.__module__]` while `_process_class` runs at class-body
    # execution time. A module built via `module_from_spec` isn't in `sys.modules` until
    # something puts it there, so without this line that lookup finds nothing and dataclasses
    # crashes with "'NoneType' object has no attribute '__dict__'" -- not a bug in
    # eval_compare.py itself, just this test file loading it in a way normal imports don't need.
    sys.modules["eval_compare"] = module
    spec.loader.exec_module(module)
    return module


def _pair(i: int, question: str) -> dict:
    return {"id": f"p-{i}", "question": question, "sql": f"SELECT {i}"}


# -- few-shot leakage ------------------------------------------------------------------------


def test_few_shot_pool_excludes_every_held_out_row(ec):
    all_pairs = [_pair(i, f"What is Vendor {i}'s total revenue?") for i in range(10)]
    held_out = all_pairs[7:]
    pool = ec.few_shot_pool(all_pairs, held_out)
    assert {p["id"] for p in pool} == {f"p-{i}" for i in range(7)}


def test_few_shot_pool_excludes_by_question_text_even_if_ids_differ(ec):
    all_pairs = [_pair(1, "What is Acme's margin?"), _pair(2, "What is Zed's margin?")]
    held_out = [{"id": "renamed", "question": "What is Acme's margin?", "sql": "SELECT 1"}]
    pool = ec.few_shot_pool(all_pairs, held_out)
    assert [p["id"] for p in pool] == ["p-2"]


def test_a_held_out_question_is_never_its_own_few_shot_example(ec):
    all_pairs = [_pair(i, f"What is Vendor {i}'s total revenue?") for i in range(10)]
    held_out = all_pairs[7:]
    pool = ec.few_shot_pool(all_pairs, held_out)
    for h in held_out:
        block = ec.retrieve_few_shot(h["question"], pool)
        assert f"Q: {h['question']}" not in block


# -- prompt parity and the casing hint -------------------------------------------------------


def _notebook_build_prompt():
    nb = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    cell = next(
        "".join(c["source"])
        for c in nb["cells"]
        if c["cell_type"] == "code" and "def build_prompt" in "".join(c["source"])
    )
    # Drop the manifest-loading half of the cell; inject a fixed schema card instead.
    cell = cell[cell.index("# Must stay word-for-word") :]
    namespace = {"SCHEMA_CARD": "t: a, b"}
    exec(cell, namespace)  # noqa: S102 -- our own committed notebook cell, not external input
    return namespace


def test_notebook_and_script_build_identical_prompts(ec):
    nb = _notebook_build_prompt()
    question = "What is Harbor Wine Brokers's blended margin?"
    assert nb["build_prompt"](question) == ec.build_prompt("t: a, b", question)
    assert nb["CASE_HINT"] == ec.CASE_HINT


def test_prompt_tells_the_model_to_match_vendor_names_case_insensitively(ec):
    assert "lower(VendorName) = lower(" in ec.build_prompt("t: a", "q?")


# -- extraction: trailing prose after a fenced answer -----------------------------------------
# Found 25 Oct 2026 re-running the comparison for real: an instruct model very commonly writes
# ```sql ... ``` and then keeps explaining itself afterward. The old extraction stripped fence
# markers with one greedy regex that also ate the blank line separating the SQL from that
# prose, so the "extracted SQL" was valid SQL with an English paragraph glued directly onto the
# end -- a DuckDB syntax error on every one of these, which is why `executable_rate` looked far
# worse than the model's answers actually were.


def test_extraction_drops_prose_that_follows_a_closed_fence(ec):
    raw = (
        "```sql\nSELECT VendorName FROM vendor_rankings WHERE VendorName = 'X';\n```\n\n"
        "This query joins the `vendor_rankings` table to answer the question."
    )
    sql = ec._extract_sql(raw)
    assert sql == "SELECT VendorName FROM vendor_rankings WHERE VendorName = 'X'"
    assert "This query" not in sql


def test_extraction_still_works_with_no_fence_at_all(ec):
    raw = "SELECT VendorName FROM vendor_rankings WHERE VendorName = 'X'"
    assert ec._extract_sql(raw) == raw


def test_extraction_falls_back_to_blank_line_split_on_an_unclosed_fence(ec):
    raw = "```sql\nSELECT VendorName FROM vendor_rankings WHERE VendorName = 'X'"
    assert ec._extract_sql(raw) == "SELECT VendorName FROM vendor_rankings WHERE VendorName = 'X'"


# -- the committed v2 dataset ----------------------------------------------------------------


def test_committed_v2_pairs_never_filter_vendors_case_sensitively():
    pairs = [json.loads(line) for line in PAIRS_V2.read_text().splitlines() if line.strip()]
    assert len(pairs) == 400
    literal = re.compile(r"lower\('((?:[^']|'')*)'\)")
    for p in pairs:
        assert not re.search(r"WHERE VendorName (=|IN)", p["sql"]), p["id"]
        for value in literal.findall(p["sql"]):
            assert value.replace("''", "'") in p["question"], p["id"]
