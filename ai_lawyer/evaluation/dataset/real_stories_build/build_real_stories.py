"""Build the real-story dataset from public write-ups of consumer-commission orders.

Checks (any failure aborts, nothing is written):
* every number in a story appears in its source article text (no invented facts);
* no redacted personal name appears in the story or the stored excerpt;
* every source file hash matches the downloaded original.

usage: python -I build_real_stories.py <config.json> <stories_src_dir> <out_jsonl> <out_sources_json>
"""
import hashlib
import json
import re
import sys
from pathlib import Path

config_path, src_root, out_jsonl, out_sources = map(Path, sys.argv[1:5])
config = json.loads(config_path.read_text(encoding="utf-8"))
index = json.loads((src_root / "index.json").read_text(encoding="utf-8"))
RETRIEVED_AT = "2026-11-08"
DEV_COUNT = 7

NUM = re.compile(r"\d[\d,./:-]*\d|\d")
errors, rows, sources = [], [], {}


def norm_num(token: str) -> str:
    return token.rstrip(".,")


for story in config:
    sid = story["id"]
    texts = []
    for src in story["src"]:
        folder = src_root / src
        raw = (folder / "page.html").read_bytes()
        if hashlib.sha256(raw).hexdigest() != index[src]["sha256"]:
            errors.append(f"{sid}: {src} hash changed")
        texts.append((folder / "text.txt").read_text(encoding="utf-8"))
    corpus = "\n".join(texts)
    for token in {norm_num(t) for t in NUM.findall(story["story"])}:
        if token not in corpus:
            errors.append(f"{sid}: number {token!r} not found in the source text")
    for name in story["redact"]:
        if name.lower() in story["story"].lower():
            errors.append(f"{sid}: redacted name {name!r} appears in the story")

    lines = texts[0].split("\n")
    excerpt = "\n".join(lines[n - 1] for n in story["facts_paras"])
    for name in sorted(story["redact"], key=len, reverse=True):
        excerpt = re.sub(re.escape(name), "[complainant]", excerpt, flags=re.IGNORECASE)
    for name in story["redact"]:
        if name.lower() in excerpt.lower():
            errors.append(f"{sid}: redacted name left in excerpt")

    record_sources = []
    for i, src in enumerate(story["src"]):
        entry = {"url": index[src]["url"], "sha256": index[src]["sha256"], "bytes": index[src]["bytes"],
                 "retrieved_at": RETRIEVED_AT, "role": "primary" if i == 0 else "corroborating"}
        if i == 0:
            entry["passage_used"] = excerpt
            entry["passage_lines"] = story["facts_paras"]
        record_sources.append(entry)
    sources[sid] = record_sources
    rows.append({
        "test_id": sid,
        "data_origin": "public_commission_order",
        "source_kind": "news_report_of_consumer_commission_order",
        "source_record_id": index[story["src"][0]]["url"].rstrip("/").rsplit("/", 1)[-1][:80],
        "retrieved_at": RETRIEVED_AT,
        "anonymised": True,
        "category": story["category"],
        "now": "2026-11-08",
        "turns": [{"message": story["story"]}],
        "case_facts": story["case_facts"],
        "expected": story["expected"],
    })

if errors:
    print("ABORTED, nothing written:")
    for e in errors:
        print("  -", e)
    sys.exit(2)

# Split before any run or tuning: order by SHA-256 of the primary source URL.
order = sorted(rows, key=lambda r: hashlib.sha256(sources[r["test_id"]][0]["url"].encode()).hexdigest())
dev = {r["test_id"] for r in order[:DEV_COUNT]}
for r in rows:
    r["split"] = "development" if r["test_id"] in dev else "test"

out_jsonl.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
out_sources.write_text(json.dumps({
    "about": "Sources for real_stories.jsonl: public news reports of Indian consumer-commission orders. "
             "Stories restate only the facts the report describes, in the first person, with personal names removed. "
             "Commission reasoning and outcomes are not part of the stories.",
    "split_rule": f"sorted by sha256(primary url); first {DEV_COUNT} = development, rest = test; fixed before any run",
    "stories": sources,
}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
from collections import Counter
print(f"wrote {len(rows)} stories:", dict(Counter(r["split"] for r in rows)))
print("expected outcomes:", dict(Counter(r["expected"]["outcome"] for r in rows)))
