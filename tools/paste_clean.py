#!/usr/bin/env python3
"""
paste_clean — clipboard HTML/text → token-economical Markdown.

Read clipboard (HTML format if available, fallback text), strip noise,
return GFM-friendly Markdown. Default writes back to clipboard.

Usage :
    LAFORGE_PYTHON tools/paste_clean.py            # clipboard → clipboard
    LAFORGE_PYTHON tools/paste_clean.py --out f.md # → file
    LAFORGE_PYTHON tools/paste_clean.py --keep-links --keep-images
    LAFORGE_PYTHON tools/paste_clean.py --bench    # measure size reduction

Token-economy defaults :
- Strip images (![alt](url) + raw <img>)
- Strip URL targets but KEEP link text ([text](url) → text)
- Collapse 3+ blank lines to 2
- Strip HTML comments + script + style blocks
"""

from __future__ import annotations

import argparse

# Force UTF-8 stdout (Windows cp1252 chokes on accents)
import io as _io
import re
import sys
from pathlib import Path


def read_clipboard() -> tuple[str, str]:
    """Return (content, format_kind) where kind ∈ {'html', 'text', 'empty'}."""
    try:
        import win32clipboard

        win32clipboard.OpenClipboard()
        try:
            CF_HTML = win32clipboard.RegisterClipboardFormat("HTML Format")
            if win32clipboard.IsClipboardFormatAvailable(CF_HTML):
                raw = win32clipboard.GetClipboardData(CF_HTML)
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="replace")
                # Strip Windows clipboard HTML headers
                m = re.search(r"<!--StartFragment-->(.*?)<!--EndFragment-->", raw, re.DOTALL)
                return (m.group(1) if m else raw), "html"
            if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                txt = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
                return (txt or ""), "text"
        finally:
            win32clipboard.CloseClipboard()
    except ImportError:
        pass
    # Fallback : pyperclip
    try:
        import pyperclip

        return pyperclip.paste(), "text"
    except ImportError:
        return "", "empty"


def write_clipboard(content: str) -> bool:
    try:
        import win32clipboard

        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, content)
        finally:
            win32clipboard.CloseClipboard()
        return True
    except ImportError:
        pass
    try:
        import pyperclip

        pyperclip.copy(content)
        return True
    except ImportError:
        return False


def html_to_md(html: str, keep_links: bool, keep_images: bool) -> str:
    """Convert HTML to GFM Markdown via markdownify."""
    from markdownify import markdownify as md

    # markdownify options
    out = md(
        html,
        heading_style="ATX",  # # H1 instead of underline
        bullets="-",
        strip=["script", "style"],  # strip noise
        keep_inline_images_in=["a"] if keep_images else [],
    )
    return out


def post_process(md_text: str, keep_links: bool, keep_images: bool) -> str:
    """Token economy : strip remaining noise."""
    if not keep_images:
        md_text = re.sub(r"!\[[^\]]*\]\([^\)]*\)", "", md_text)
        md_text = re.sub(r"<img[^>]*>", "", md_text)
    if not keep_links:
        # [text](url) → text  (keep label, drop URL)
        md_text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", md_text)
        # bare <http://...> URLs → strip
        md_text = re.sub(r"<https?://[^>]+>", "", md_text)
    # Collapse 3+ blank lines to 2
    md_text = re.sub(r"(\r?\n){3,}", "\n\n", md_text)
    # Strip trailing whitespace per line
    md_text = "\n".join(line.rstrip() for line in md_text.splitlines())
    return md_text.strip()


def main() -> None:
    p = argparse.ArgumentParser(description="Clipboard HTML/text → token-economical Markdown")
    p.add_argument("--out", help="Write to file instead of clipboard")
    p.add_argument("--keep-links", action="store_true", help="Preserve [text](url) full")
    p.add_argument("--keep-images", action="store_true", help="Preserve ![alt](url)")
    p.add_argument("--bench", action="store_true", help="Print size reduction stats")
    p.add_argument("--from-stdin", action="store_true", help="Read from stdin instead of clipboard")
    args = p.parse_args()

    if args.from_stdin:
        raw = sys.stdin.read()
        kind = "html" if "<" in raw[:200] and ">" in raw[:200] else "text"
    else:
        raw, kind = read_clipboard()

    if not raw or kind == "empty":
        print("ERR: clipboard vide", file=sys.stderr)
        sys.exit(1)

    if kind == "html":
        md_text = html_to_md(raw, args.keep_links, args.keep_images)
    else:
        md_text = raw  # already text/markdown

    md_text = post_process(md_text, args.keep_links, args.keep_images)

    sz_before = len(raw)
    sz_after = len(md_text)
    reduction = round((1 - sz_after / max(sz_before, 1)) * 100, 1)

    if args.out:
        Path(args.out).write_text(md_text, encoding="utf-8")
        print(f"OK -> {args.out} ({sz_before} -> {sz_after} chars, -{reduction}%)")
    else:
        ok = write_clipboard(md_text)
        if ok:
            print(f"OK clipboard updated ({sz_before} -> {sz_after} chars, -{reduction}%)")
        else:
            print(md_text)
            print(f"\n--- ({sz_before} -> {sz_after} chars, -{reduction}%) ---", file=sys.stderr)

    if args.bench:
        # Token estimate (rough : chars / 4)
        tok_before = sz_before // 4
        tok_after = sz_after // 4
        print(f"Tokens estimate : {tok_before} -> {tok_after} (-{tok_before - tok_after} tok)")


if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = _io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    main()
