"""copilot.sql.examples: lexical retrieval of similar golden question/SQL pairs."""

from __future__ import annotations

from copilot.evals.golden import GoldenQuestion
from copilot.sql.examples import format_examples, retrieve_examples


def _q(
    id_: str, question: str, role: str = "viewer", sql: str | None = "SELECT 1"
) -> GoldenQuestion:
    return GoldenQuestion(
        id=id_,
        split="dev",
        category="lookup",
        difficulty="easy",
        question=question,
        role=role,  # type: ignore[arg-type]
        expect="answer",
        sql=sql,
        expected_rows=[{"x": 1}] if sql else None,
        reference_answer="n/a",
        answer_source="sql",
    )


_POOL = [
    _q("gq-a", "What is Diageo's total revenue?"),
    _q("gq-b", "What is total revenue across all vendors?"),
    _q("gq-c", "How many vendors are in the portfolio?"),
    _q("gq-d", "What is the approval history for this contract?", role="analyst", sql=None),
    _q("gq-e", "Show me analyst-only margin breakdown", role="analyst"),
]


def test_retrieves_the_most_lexically_similar_question_first() -> None:
    top = retrieve_examples("What is Diageo's revenue this year?", "viewer", k=1, golden=_POOL)
    assert top[0].id == "gq-a"


def test_never_retrieves_an_example_with_no_verified_sql() -> None:
    results = retrieve_examples("What is the approval history?", "viewer", k=5, golden=_POOL)
    assert all(g.id != "gq-d" for g in results)


def test_viewer_never_gets_an_analyst_only_example() -> None:
    results = retrieve_examples("Show me margin breakdown", "viewer", k=5, golden=_POOL)
    assert all(g.id != "gq-e" for g in results)


def test_analyst_can_get_an_analyst_only_example() -> None:
    results = retrieve_examples("Show me margin breakdown please", "analyst", k=5, golden=_POOL)
    assert any(g.id == "gq-e" for g in results)


def test_respects_k() -> None:
    results = retrieve_examples("total revenue", "viewer", k=2, golden=_POOL)
    assert len(results) == 2


def test_format_examples_renders_question_and_sql() -> None:
    text = format_examples(_POOL[:1])
    assert "Q: What is Diageo's total revenue?" in text
    assert "SQL: SELECT 1" in text


def test_format_examples_handles_empty_list() -> None:
    assert format_examples([]) == "(no similar examples found)"
