"""Tests for heading-aware chunking (Day 4 step 2)."""

from copilot.rag.chunking import Chunk, chunk_corpus, chunk_doc
from copilot.rag.corpus import KnowledgeDoc


def _doc(body: str, **overrides: object) -> KnowledgeDoc:
    defaults: dict[str, object] = {
        "path": __file__,  # not read; chunking never touches disk
        "doc_type": "methodology",
        "vendor": None,
        "version": 1,
        "data_class": "public",
        "allowed_roles": ["viewer", "analyst"],
        "body": body,
    }
    defaults.update(overrides)
    return KnowledgeDoc.model_validate(defaults)


def test_chunk_doc_splits_at_every_heading_level() -> None:
    doc = _doc(
        "# Title\n\nIntro line.\n\n## Section A\n\nBody A.\n\n### Sub A.1\n\nBody A.1.\n\n"
        "## Section B\n\nBody B.\n"
    )
    chunks = chunk_doc(doc)
    heading_paths = [c.heading_path for c in chunks]
    assert heading_paths == [
        ("Title",),
        ("Title", "Section A"),
        ("Title", "Section A", "Sub A.1"),
        ("Title", "Section B"),
    ]


def test_chunk_carries_doc_metadata_onto_every_chunk() -> None:
    doc = _doc(
        "# T\n\nbody\n",
        doc_type="vendor_contract",
        vendor="DIAGEO NORTH AMERICA INC",
        version=2,
        data_class="confidential",
        allowed_roles=["analyst", "approver", "admin"],
    )
    (chunk,) = chunk_doc(doc)
    assert chunk.doc_type == "vendor_contract"
    assert chunk.vendor == "DIAGEO NORTH AMERICA INC"
    assert chunk.version == 2
    assert chunk.data_class == "confidential"
    assert chunk.allowed_roles == ("analyst", "approver", "admin")


def test_chunk_ids_are_stable_across_rechunks() -> None:
    doc = _doc("# T\n\n## A\n\nbody a\n\n## B\n\nbody b\n")
    ids1 = [c.chunk_id for c in chunk_doc(doc)]
    ids2 = [c.chunk_id for c in chunk_doc(doc)]
    assert ids1 == ids2
    assert len(set(ids1)) == len(ids1)  # unique within the doc


def test_chunk_id_changes_if_document_identity_changes() -> None:
    doc_v1 = _doc("# T\n\nbody\n", version=1)
    doc_v2 = _doc("# T\n\nbody\n", version=2)
    assert chunk_doc(doc_v1)[0].chunk_id != chunk_doc(doc_v2)[0].chunk_id


def test_content_hash_reflects_text_not_identity() -> None:
    doc_a = _doc("# T\n\nsame body\n")
    doc_b = _doc("# T\n\nsame body\n")
    # Different chunk_id (different synthetic doc instances would differ in practice, but here
    # they're identical docs) -- the point is content_hash is a pure function of chunk text.
    assert chunk_doc(doc_a)[0].content_hash == chunk_doc(doc_b)[0].content_hash
    changed = _doc("# T\n\ndifferent body\n")
    assert chunk_doc(doc_a)[0].content_hash != chunk_doc(changed)[0].content_hash


def test_oversized_section_is_split_with_overlap() -> None:
    paragraphs = [f"Paragraph {i} " + ("word " * 40) for i in range(10)]
    doc = _doc("# T\n\n## Long section\n\n" + "\n\n".join(paragraphs) + "\n")
    chunks = chunk_doc(doc, max_chars=300, overlap_chars=50)
    long_section_chunks = [c for c in chunks if c.heading_path == ("T", "Long section")]
    assert len(long_section_chunks) > 1
    assert all(len(c.text) <= 300 + 50 + 20 for c in long_section_chunks)  # cap + carried overlap
    # Consecutive pieces share trailing/leading context.
    tail_of_first = long_section_chunks[0].text[-40:]
    assert tail_of_first[-10:] in long_section_chunks[1].text


def test_oversized_single_paragraph_is_kept_whole_not_cut_mid_sentence() -> None:
    one_long_paragraph = "word " * 500
    doc = _doc(f"## Section\n\n{one_long_paragraph}\n")
    chunks = chunk_doc(doc, max_chars=100, overlap_chars=20)
    assert len(chunks) == 1
    assert one_long_paragraph.strip() in chunks[0].text
    assert chunks[0].text.startswith("## Section")


def test_chunk_corpus_concatenates_in_order() -> None:
    doc1 = _doc("# A\n\nbody a\n", doc_type="data_dictionary")
    doc2 = _doc("# B\n\nbody b\n", doc_type="methodology")
    chunks = chunk_corpus([doc1, doc2])
    assert [c.doc_type for c in chunks] == ["data_dictionary", "methodology"]


def test_chunk_is_immutable() -> None:
    doc = _doc("# T\n\nbody\n")
    (chunk,) = chunk_doc(doc)
    assert isinstance(chunk, Chunk)
    try:
        chunk.text = "mutated"  # type: ignore[misc]
        raised = False
    except Exception:
        raised = True
    assert raised
