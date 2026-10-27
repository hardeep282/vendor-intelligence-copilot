"""Build the Code Map HTML page from docs/CODE_MAP.md.

Purpose : docs/CODE_MAP.md is the source of truth for what every file does. The browsable page
          (docs/code-map/index.html, published as a shared page) used to be a hand-maintained
          JS array that drifted from the markdown -- by Day 10 it was five days behind. This
          script regenerates the page's data from the markdown so the two cannot drift again.
Inputs  : docs/CODE_MAP.md (headings `### `path` -- `Symbol` *(day: N, isNew: true)*`, then a
          description and optional **Takes in:** / **Gives out:** / **Talks to:** lines) and
          docs/code-map/template.html (the page shell, with a /*__FILES__*/ placeholder).
Outputs : docs/code-map/index.html.
Run     : uv run python scripts/build_code_map_page.py
"""

from __future__ import annotations

import html
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "CODE_MAP.md"
TEMPLATE = ROOT / "docs" / "code-map" / "template.html"
OUTPUT = ROOT / "docs" / "code-map" / "index.html"

HEADING_SEP = re.compile(r"\s+(?:—|--)\s+")
MARKER = re.compile(r"\*\(day:\s*(\d+)(?:,\s*isNew:\s*true)?\)\*")
FIELD = re.compile(r"^\*\*(Takes in|Gives out|Talks to):\*\*\s*(.*)$")
MAX_TALKS = 10


@dataclass
class Entry:
    group: str
    path: str
    sym: str = ""
    day: int | None = None
    is_new: bool = False
    body: list[str] = field(default_factory=list)
    fields: dict[str, list[str]] = field(default_factory=dict)


def inline(md: str) -> str:
    """Markdown inline spans -> HTML. Code spans are protected first so `*.md` stays literal."""
    codes: list[str] = []

    def stash(m: re.Match[str]) -> str:
        codes.append(f"<code>{html.escape(m.group(1))}</code>")
        return f"\x00{len(codes) - 1}\x00"

    text = re.sub(r"`([^`]+)`", stash, md)
    text = html.escape(text, quote=False)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", text)
    return re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], text)


def block(lines: list[str]) -> str:
    """Paragraphs and pipe tables -> HTML. Lines inside a paragraph are joined with spaces."""
    out: list[str] = []
    para: list[str] = []
    table: list[list[str]] = []

    def flush_para() -> None:
        if para:
            out.append("<p>" + inline(" ".join(para)) + "</p>")
            para.clear()

    def flush_table() -> None:
        if table:
            head, *rows = table
            th = "".join(f"<th>{inline(c)}</th>" for c in head)
            trs = "".join(
                "<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in rows
            )
            out.append(f'<div class="tbl"><table><tr>{th}</tr>{trs}</table></div>')
            table.clear()

    for raw in lines:
        line = raw.strip()
        if line.startswith("|"):
            flush_para()
            cells = [c.strip() for c in line.strip("|").split("|")]
            if not all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
                table.append(cells)
            continue
        flush_table()
        if not line:
            flush_para()
        else:
            para.append(line)
    flush_para()
    flush_table()
    if len(out) == 1 and out[0].startswith("<p>"):
        return out[0][3:-4]
    return "".join(out)


def parse(md: str) -> list[Entry]:
    entries: list[Entry] = []
    group = ""
    current: Entry | None = None
    active_field: str | None = None
    for line in md.split("\n"):
        if line.startswith("## "):
            group = re.sub(r"\s*\(.*\)\s*$", "", line[3:].strip())
            group = HEADING_SEP.split(group)[0].strip()
            current = Entry(group=group, path="", day=None)
            entries.append(current)
            active_field = None
            continue
        if line.startswith("### "):
            head = line[4:].strip()
            m = MARKER.search(head)
            day = int(m.group(1)) if m else None
            is_new = bool(m and "isNew" in m.group(0))
            head = MARKER.sub("", head).strip()
            parts = HEADING_SEP.split(head, maxsplit=1)
            path = parts[0].replace("`", "").strip()
            sym = parts[1].replace("`", "").strip() if len(parts) > 1 else ""
            current = Entry(group=group, path=path, sym=sym, day=day, is_new=is_new)
            entries.append(current)
            active_field = None
            continue
        if current is None or line.strip() == "---":
            continue
        fm = FIELD.match(line.strip())
        if fm:
            active_field = fm.group(1)
            current.fields[active_field] = [fm.group(2)]
        elif active_field and line.strip():
            current.fields[active_field].append(line.strip())
        else:
            active_field = None
            current.body.append(line)
    # A `##` section with no `###` children becomes one entry of its own (e.g. the scripts table).
    kept: list[Entry] = []
    for i, e in enumerate(entries):
        if e.path:
            kept.append(e)
            continue
        nxt = entries[i + 1] if i + 1 < len(entries) else None
        has_children = bool(nxt and nxt.path and nxt.group == e.group)
        text = "\n".join(e.body).strip()
        if not has_children and text and not text.startswith("What every file"):
            e.path = e.group
            kept.append(e)
    return kept


def slug(path: str) -> str:
    first = re.split(r"\s*(?:·|\+|,| / )\s*", path)[0]
    return re.sub(r"[^a-z0-9]+", "-", first.lower()).strip("-") or "entry"


def first_sentence(text: str) -> tuple[str, str]:
    """Split off a headline: the first sentence if it is short enough, else the first clause."""
    plain = " ".join(text.split())
    m = re.search(r"(?<=[.!?])(?<!e\.g\.)(?<!i\.e\.)(?<!vs\.)\s+(?=\S)", plain)
    if m and m.start() <= 200:
        return plain[: m.start()], plain[m.end() :]
    cut = plain.rfind(" ", 0, 150)
    if len(plain) <= 200 or cut < 0:
        return plain, ""
    return plain[:cut] + " …", plain


def resolve(token: str, by_key: dict[str, str]) -> str | None:
    t = re.sub(r"\s+", "", token).rstrip("()").split("(")[0]
    candidates = [t, t.split("/")[-1]]
    if t.startswith("copilot."):
        parts = t.split(".")
        # copilot.agents.orchestrator._guardian_node -> try the longest prefix that is a module
        for k in range(len(parts), 1, -1):
            candidates.append("src/" + "/".join(parts[:k]) + ".py")
    for c in candidates:
        if c in by_key:
            return by_key[c]
    return None


def is_file_like(token: str) -> bool:
    t = re.sub(r"\s+", "", token)
    return "/" in t or t.startswith("copilot.") or t.endswith((".py", ".md", ".yaml", ".jsonl"))


def to_files(entries: list[Entry]) -> list[dict[str, object]]:
    ids: dict[int, str] = {}
    seen: set[str] = set()
    by_key: dict[str, str] = {}
    for idx, e in enumerate(entries):
        base = slug(e.path)
        eid, n = base, 2
        while eid in seen:
            eid, n = f"{base}-{n}", n + 1
        seen.add(eid)
        ids[idx] = eid
        for tok in re.split(r"\s*(?:·|\+|,| / )\s*", e.path):
            tok = tok.strip()
            if tok:
                by_key.setdefault(tok, eid)
                by_key.setdefault(tok.split("/")[-1], eid)
        if e.sym:
            by_key.setdefault(e.sym.split("(")[0].split("/")[0].strip(), eid)

    files: list[dict[str, object]] = []
    for idx, e in enumerate(entries):
        body_lines = [ln for ln in e.body if ln.strip() or True]
        paragraphs = "\n".join(body_lines).strip()
        has_table = any(ln.strip().startswith("|") for ln in body_lines)
        if has_table:
            headline = e.path if e.path == e.group else e.group
            does = block(body_lines)
        else:
            head, rest = first_sentence(paragraphs.split("\n\n")[0])
            remainder = paragraphs[len(paragraphs.split("\n\n")[0]) :].strip()
            headline = head
            tail = rest + ("\n\n" + remainder if remainder else "")
            does = block(tail.split("\n")) if tail.strip() else ""
        talks: list[dict[str, str]] = []
        labels: set[str] = set()
        for tok in re.findall(r"`([^`]+)`", " ".join(e.fields.get("Talks to", []))):
            if tok in labels or len(talks) >= MAX_TALKS:
                continue
            target = resolve(tok, by_key)
            if target == ids[idx] or (target is None and not is_file_like(tok)):
                continue
            label = re.sub(r"\s+", "", tok)
            labels.add(tok)
            talks.append({"id": target, "label": label} if target else {"label": label})
        item: dict[str, object] = {
            "id": ids[idx],
            "group": e.group,
            "day": e.day,
            "path": e.path,
            "headline": inline(headline),
            "does": does or inline(headline),
            "talksTo": talks,
        }
        if e.sym:
            item["sym"] = e.sym
        if "Takes in" in e.fields:
            item["takes"] = inline(" ".join(e.fields["Takes in"]))
        if "Gives out" in e.fields:
            item["gives"] = inline(" ".join(e.fields["Gives out"]))
        if e.is_new:
            item["isNew"] = True
        files.append(item)
    return files


def main() -> int:
    entries = parse(SOURCE.read_text(encoding="utf-8"))
    files = to_files(entries)
    template = TEMPLATE.read_text(encoding="utf-8")
    data = json.dumps(files, ensure_ascii=False, indent=1).replace("</", "<\\/")
    stamp = f"{len(files)} entries, built {date.today().isoformat()}"
    page = template.replace("/*__FILES__*/[]", data).replace("/*__STAMP__*/", stamp)
    OUTPUT.write_text(page, encoding="utf-8")
    days = sorted({f["day"] for f in files if isinstance(f["day"], int)})
    out = OUTPUT.relative_to(ROOT)
    print(f"{len(files)} entries across {len(days)} days ({days[0]}-{days[-1]}) -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
