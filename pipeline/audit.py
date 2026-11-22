"""Draw a stratified random sample of the corpus for a precision check.

Prints 30 items per layer (matched stories, standalone comments, matched
thread comments, unmatched thread replies) with enough text to judge them.
Label each against the criterion in audit_results.json and record the
results there; analyze.py copies them onto the Methods page.

Usage: python pipeline/audit.py [seed] [per_stratum]
"""
import json
import random
import re
import sys
from pathlib import Path

WORK = Path(__file__).resolve().parent.parent / "data" / "work"


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
    k = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    rows = [json.loads(line) for line in open(WORK / "corpus.jsonl")]
    by_id = {r["id"]: r for r in rows}
    strata = {
        "story": [r for r in rows if r["type"] == "story"],
        "standalone": [r for r in rows if r["source"] == "standalone"],
        "thread_matched": [r for r in rows if r["type"] == "comment"
                           and r["source"] == "thread" and r["matched"]],
        "thread_unmatched": [r for r in rows if r["type"] == "comment"
                             and r["source"] == "thread" and not r["matched"]],
    }
    rnd = random.Random(seed)
    n = 0
    for name, pool in strata.items():
        for r in rnd.sample(pool, min(k, len(pool))):
            if r["type"] == "story":
                ctx = r["title"]
            elif r["thread"] is not None:
                ctx = "[thread] " + by_id[r["thread"]]["title"]
            else:
                ctx = "[other thread] " + r["title"]
            text = re.sub(r"\s+", " ", r["text"])[:400]
            print(f"{n}\t{name}\tid={r['id']}\t{ctx[:80]}\t{text}")
            n += 1


if __name__ == "__main__":
    main()
