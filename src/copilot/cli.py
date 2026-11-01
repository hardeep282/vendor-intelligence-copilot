"""Small helpers shared by the command-line scripts in `scripts/`.

Purpose : make every script's printed output safe on a Windows console.
Inputs  : none.
Outputs : none; `use_utf8_output()` changes how `sys.stdout`/`sys.stderr` encode text.

Added 2 Nov 2026. On Windows, Python's console output defaults to the old cp1252 code page when
it's piped (for example into PowerShell's `Tee-Object`). The full real-key golden run then
crashed part-way with `UnicodeEncodeError` on a "≈" in a model's answer, losing the questions
after it. The workaround was setting `PYTHONUTF8=1` by hand before each run. Now each script
switches its own output to UTF-8 at start-up, and any character that still can't be encoded
is replaced with "?" instead of crashing.

What this can't fix: how the PowerShell window *displays* the bytes. If symbols look garbled
on screen, also run
`[Console]::OutputEncoding = [System.Text.Encoding]::UTF8` in that window. The file written by
`Tee-Object` is unaffected either way.
"""

from __future__ import annotations

import io
import sys


def use_utf8_output() -> None:
    """Switch stdout and stderr to UTF-8, replacing anything unencodable instead of crashing.

    Safe to call more than once, and a no-op for streams that aren't ordinary text streams
    (pytest's capture, for instance).
    """
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors="replace")


__all__ = ["use_utf8_output"]
