"""Extract readable text from archived official HTML and text PDFs."""
from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
import re
import subprocess


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self.hidden += 1
        if tag in {"p", "div", "br", "h1", "h2", "h3", "h4", "li", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self.hidden:
            self.hidden -= 1
        if tag in {"p", "div", "h1", "h2", "h3", "h4", "li", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def normalize_text(value: str) -> str:
    lines = [re.sub(r"[\t\u00a0\u3000 ]+", " ", line).strip() for line in value.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def extract_text(path: Path, content_type: str, encoding: str | None = None) -> str:
    if content_type == "pdf":
        result = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", str(path), "-"],
                                capture_output=True, text=True, check=True, timeout=60)
        return normalize_text(result.stdout)
    parser = _TextParser()
    parser.feed(path.read_text(encoding=encoding or "utf-8", errors="replace"))
    return normalize_text("".join(parser.parts))
