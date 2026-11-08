"""Extract paragraph text from downloaded article pages and hash the originals.

usage: python -I extract_articles.py <stories_src_dir>
"""
import hashlib
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path


class Paragraphs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.depth = 0
        self.skip = 0
        self.buf = []
        self.paras = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.skip += 1
        if tag == "p":
            self.depth += 1
            self.buf = []

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self.skip:
            self.skip -= 1
        if tag == "p" and self.depth:
            self.depth -= 1
            text = re.sub(r"\s+", " ", "".join(self.buf)).strip()
            if len(text) > 60:
                self.paras.append(text)

    def handle_data(self, data):
        if self.depth and not self.skip:
            self.buf.append(data)


root = Path(sys.argv[1])
index = {}
for folder in sorted(p for p in root.iterdir() if p.is_dir()):
    raw = (folder / "page.html").read_bytes()
    parser = Paragraphs()
    parser.feed(raw.decode("utf-8", errors="replace"))
    seen, paras = set(), []
    for p in parser.paras:
        if p not in seen:
            seen.add(p)
            paras.append(p)
    text = "\n\n".join(paras)
    (folder / "text.txt").write_text(text, encoding="utf-8")
    index[folder.name] = {
        "url": (folder / "url.txt").read_text(encoding="utf-8").strip(),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "text_chars": len(text),
    }
    print(folder.name, len(raw), len(text))
(root / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
