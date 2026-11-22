"""Stage 1: collect raw data from the Hacker News Algolia API.

Writes to data/raw/ (gitignored -- raw records contain usernames and HN ids,
and are never committed or published):
  hits.jsonl     every search hit (stories and comments) from the seed queries
  threads/ID.json full comment tree for every *candidate* story

Usage: python pipeline/collect.py [--threads-only]
"""
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import WINDOW_END, WINDOW_START, seed_queries  # noqa: E402
from relevance import story_candidate  # noqa: E402

API = "https://hn.algolia.com/api/v1"
RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
MAX_PAGE = 1000  # Algolia never returns more than 1000 hits per query


def get(url, params=None, tries=5):
    if params:
        url += "?" + urllib.parse.urlencode(params)
    for attempt in range(tries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "hn-research-collector/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            if attempt == tries - 1:
                raise
            wait = 2 ** attempt
            print(f"  retry in {wait}s: {e}", file=sys.stderr)
            time.sleep(wait)


def search_window(query, tag, start, end):
    """All hits for query/tag in [start, end), splitting the window if
    Algolia's 1000-hit cap would truncate it."""
    params = {"query": query, "tags": tag, "typoTolerance": "false",
              "numericFilters": f"created_at_i>={start},created_at_i<{end}",
              "hitsPerPage": MAX_PAGE}
    d = get(f"{API}/search_by_date", params)
    if d["nbHits"] > MAX_PAGE and end - start > 3600:
        mid = (start + end) // 2
        return (search_window(query, tag, start, mid)
                + search_window(query, tag, mid, end))
    return d["hits"]


def strip_html(s):
    s = re.sub(r"<p>", "\n\n", s or "")
    s = re.sub(r"<[^>]+>", "", s)
    return html.unescape(s)


def search_all(start, end):
    queries = seed_queries()
    jobs = [(q, t) for q in queries for t in ("story", "comment")]
    print(f"{len(jobs)} seed searches")
    hits = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        for (q, t), res in zip(jobs, ex.map(
                lambda j: search_window(j[0], j[1], start, end), jobs)):
            for h in res:
                hits.setdefault(h["objectID"], h)
            print(f"  {t:7s} {q!r}: {len(res)}  (union {len(hits)})")
    with open(RAW / "hits.jsonl", "w") as f:
        for h in hits.values():
            f.write(json.dumps(h) + "\n")
    return hits


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / "threads").mkdir(exist_ok=True)
    start, end = int(WINDOW_START.timestamp()), int(WINDOW_END.timestamp())
    if "--threads-only" in sys.argv:  # reuse saved search hits
        hits = {h["objectID"]: h for h in map(json.loads,
                                              open(RAW / "hits.jsonl"))}
    else:
        hits = search_all(start, end)

    stories = [h for h in hits.values() if "story" in h["_tags"]]
    matched = [h for h in stories if story_candidate(
        h.get("title") or "", strip_html(h.get("story_text")))]
    print(f"{len(hits)} hits; {len(stories)} stories, "
          f"{len(matched)} candidate stories -> fetching threads")

    todo = [h["objectID"] for h in matched
            if not (RAW / "threads" / f"{h['objectID']}.json").exists()]

    def fetch(sid):
        d = get(f"{API}/items/{sid}")
        (RAW / "threads" / f"{sid}.json").write_text(json.dumps(d))
        return sid

    with ThreadPoolExecutor(max_workers=4) as ex:
        for i, _ in enumerate(ex.map(fetch, todo), 1):
            if i % 50 == 0:
                print(f"  {i}/{len(todo)} threads")
    print("done")


if __name__ == "__main__":
    main()
