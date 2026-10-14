"""Heading-aware chunking.

Purpose : turn each KnowledgeDoc's Markdown body into retrieval-sized chunks, carrying the
          doc-level permission metadata (data_class, allowed_roles) onto every chunk so the
          permission filter (Day 4 step 5) can act at chunk granularity without re-opening the
          source file. This is the layer between the raw corpus (step 1) and embedding (step 3).
Inputs  : KnowledgeDoc objects from copilot.rag.corpus.
Outputs : a list of Chunk, one per heading-bounded section (or sub-section, if a section runs
          long enough to need splitting further).

Chunking strategy (recorded here rather than in an ADR -- it is the stock technique the sprint
doc names, not a build-vs-buy decision with real alternatives measured against it):
heading-aware, not fixed-size or semantic. Every knowledge doc in this corpus is itself
curated by section (one topic per `##`/`###` heading -- a metric definition, one ADR summary,
one contract clause), so the headings already are the semantic boundaries; fixed-size chunking
would cut across them for no benefit, and sentence-window chunking solves a problem (isolated
sentences with no context) this corpus doesn't have. No overlap is added between sibling
sections, because they are different topics -- overlap exists to avoid splitting one idea in
two, and the size-based sub-split below (for a single section that runs long) is where that
actually happens, so overlap is added only there.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from copilot.guardrails.policy import DataClass, Role
from copilot.rag.corpus import DocType, KnowledgeDoc

# Soft cap on a single chunk's size. all-MiniLM-L6-v2 (step 3) truncates at 256 tokens
# (~1000-1200 English characters); this is comfortably under that so truncation never silently
# drops the end of a chunk before it even reaches the embedder.
DEFAULT_MAX_CHARS = 1000
# Characters of trailing context carried from one size-based sub-chunk into the next, so a
# sentence split by the size cap still has its immediate context on both sides. Not used between
# sibling headings (see module docstring) -- only within one over-long section.
DEFAULT_OVERLAP_CHARS = 150

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_type: DocType
    vendor: str | None
    version: int
    data_class: DataClass
    allowed_roles: tuple[Role, ...]
    heading_path: tuple[str, ...]
    chunk_index: int  # order within the doc, stable across re-chunks of unchanged content
    text: str
    content_hash: str = field(repr=False)  # sha256(text); step 3's idempotent-upsert key


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _doc_key(doc: KnowledgeDoc) -> str:
    """A stable, filesystem-independent identifier for one document."""
    return f"{doc.doc_type}:{doc.vendor or 'na'}:v{doc.version}"


def _split_into_sections(
    body: str,
) -> list[tuple[tuple[str, ...], str, str]]:
    """Split a Markdown body at every heading line, keeping the ancestor heading path.

    Returns (heading_path, heading_line, content) triples in document order. `content` is
    everything under that heading up to (not including) the next heading of any level, with the
    heading line itself kept separate so a long section can be size-split on its content alone
    and have the heading line re-attached to every resulting piece (see `_split_oversized`) --
    that is what keeps each chunk self-describing without ever duplicating the heading as if it
    were content. Text before the first heading (there normally is none -- every knowledge doc
    opens with a `#` title right after the frontmatter) is dropped if empty, kept as an untitled
    leading section otherwise.
    """
    lines = body.splitlines()
    sections: list[tuple[tuple[str, ...], str, str]] = []
    stack: list[tuple[int, str]] = []  # (heading level, heading text)
    heading_line = ""
    content_lines: list[str] = []

    def _flush() -> None:
        content = "\n".join(content_lines).strip()
        if heading_line or content:
            sections.append((tuple(h for _, h in stack), heading_line, content))

    for line in lines:
        match = _HEADING_RE.match(line)
        if match is None:
            content_lines.append(line)
            continue
        _flush()
        level, heading = len(match.group(1)), match.group(2)
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, heading))
        heading_line = line
        content_lines = []
    _flush()
    return sections


def _split_oversized(
    heading_line: str, content: str, max_chars: int, overlap_chars: int
) -> list[str]:
    """Greedily pack `content`'s paragraphs into pieces, each re-prefixed with `heading_line` so
    every resulting chunk stays self-describing. `max_chars` budgets the whole piece (heading
    included); `overlap_chars` of trailing content is carried into the next piece so a sentence
    split by the cap still has context on both sides. A single paragraph that alone exceeds the
    remaining budget is kept whole rather than cut mid-sentence -- cutting an embedding model's
    input off mid-sentence is a worse failure than one oversized chunk, and no paragraph in this
    corpus is anywhere near that long.
    """
    prefix = f"{heading_line}\n\n" if heading_line else ""
    full = f"{prefix}{content}" if content else heading_line
    if len(full) <= max_chars:
        return [full]

    budget = max(max_chars - len(prefix), overlap_chars + 1)
    paragraphs = re.split(r"\n{2,}", content)
    pieces: list[str] = []
    current = ""
    for para in paragraphs:
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) <= budget or not current:
            current = candidate
        else:
            pieces.append(current)
            carry = current[-overlap_chars:] if overlap_chars else ""
            current = f"{carry}\n\n{para}" if carry else para
    if current:
        pieces.append(current)
    return [f"{prefix}{piece}" if prefix else piece for piece in pieces]


def chunk_doc(
    doc: KnowledgeDoc,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> list[Chunk]:
    """Chunk one document. Deterministic: same input always yields the same chunk_ids."""
    doc_key = _doc_key(doc)
    chunks: list[Chunk] = []
    index = 0
    for heading_path, heading_line, content in _split_into_sections(doc.body):
        for piece in _split_oversized(heading_line, content, max_chars, overlap_chars):
            chunk_id = f"{doc_key}:{index}"
            chunks.append(
                Chunk(
                    chunk_id=chunk_id,
                    doc_type=doc.doc_type,
                    vendor=doc.vendor,
                    version=doc.version,
                    data_class=doc.data_class,
                    allowed_roles=tuple(doc.allowed_roles),
                    heading_path=heading_path,
                    chunk_index=index,
                    text=piece,
                    content_hash=_content_hash(piece),
                )
            )
            index += 1
    return chunks


def chunk_corpus(
    docs: list[KnowledgeDoc],
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> list[Chunk]:
    """Chunk every document in the corpus, in the order given."""
    out: list[Chunk] = []
    for doc in docs:
        out.extend(chunk_doc(doc, max_chars=max_chars, overlap_chars=overlap_chars))
    return out
