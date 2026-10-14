"""Tests for the knowledge corpus loader (Day 4 step 1)."""

from pathlib import Path

import pytest

from copilot.rag.corpus import (
    CorpusError,
    KnowledgeDoc,
    check_corpus_against_policy,
    load_corpus,
    load_doc,
)


def test_load_corpus_finds_all_real_documents() -> None:
    docs = load_corpus()
    # 4 methodology-family docs + 10 synthetic vendor contracts.
    assert len(docs) == 14
    assert all(isinstance(d, KnowledgeDoc) for d in docs)


def test_corpus_has_expected_doc_type_spread() -> None:
    docs = load_corpus()
    by_type: dict[str, int] = {}
    for d in docs:
        by_type[d.doc_type] = by_type.get(d.doc_type, 0) + 1
    assert by_type == {
        "data_dictionary": 1,
        "metric_definitions": 1,
        "decision_log": 1,
        "methodology": 1,
        "vendor_contract": 10,
    }


def test_corpus_has_expected_data_class_spread() -> None:
    docs = load_corpus()
    by_class: dict[str, int] = {}
    for d in docs:
        by_class[d.data_class] = by_class.get(d.data_class, 0) + 1
    # Public (data dict, metric defs, methodology) + internal (decision log) + confidential
    # (10 contracts) gives the permission filter (step 5) real classes to discriminate between.
    assert by_class == {"public": 3, "internal": 1, "confidential": 10}


def test_no_restricted_documents_in_corpus() -> None:
    # Nothing in the RAG corpus should ever be Restricted -- that class never leaves the system.
    docs = load_corpus()
    assert all(d.data_class != "restricted" for d in docs)


def test_every_contract_is_labelled_synthetic() -> None:
    docs = load_corpus()
    contracts = [d for d in docs if d.doc_type == "vendor_contract"]
    assert len(contracts) == 10
    for c in contracts:
        assert "SYNTHETIC" in c.body
        assert c.vendor is not None
        assert c.data_class == "confidential"


def test_corpus_matches_disclosure_policy() -> None:
    # Will fail loudly if policies/disclosure.yaml changes a role's access and nobody updated
    # the corpus's hand-authored allowed_roles frontmatter to match.
    check_corpus_against_policy(load_corpus())


def test_load_doc_rejects_missing_frontmatter(tmp_path: Path) -> None:
    bad = tmp_path / "bad.md"
    bad.write_text("# No frontmatter here\n", encoding="utf-8")
    with pytest.raises(CorpusError, match="missing opening"):
        load_doc(bad)


def test_load_doc_rejects_unclosed_frontmatter(tmp_path: Path) -> None:
    bad = tmp_path / "bad.md"
    bad.write_text("---\ndoc_type: methodology\n# never closed\n", encoding="utf-8")
    with pytest.raises(CorpusError, match="missing closing"):
        load_doc(bad)


def test_load_doc_rejects_invalid_data_class(tmp_path: Path) -> None:
    bad = tmp_path / "bad.md"
    bad.write_text(
        "---\n"
        "doc_type: methodology\n"
        "vendor: null\n"
        "version: 1\n"
        "data_class: top_secret\n"  # not one of the four valid classes
        "allowed_roles: [viewer]\n"
        "---\n"
        "body text\n",
        encoding="utf-8",
    )
    with pytest.raises(CorpusError):
        load_doc(bad)


def test_load_corpus_is_deterministically_ordered() -> None:
    docs1 = load_corpus()
    docs2 = load_corpus()
    assert [d.path for d in docs1] == [d.path for d in docs2]
