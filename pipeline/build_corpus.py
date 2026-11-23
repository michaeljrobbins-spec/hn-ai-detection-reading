"""Stage 2: turn raw API records into an anonymized corpus.

Reads data/raw/, writes data/work/corpus.jsonl (gitignored: it still holds
full text, which the analysis needs but the published site does not).

Only items about the three focus topics are kept (see relevance.py).
Corpus layers (the `source` field):
  thread      a matched, focus-tagged story and every reply in its thread
  standalone  a focus-tagged comment that passes the text rule but sits in a
              thread that is not in the corpus

Anonymization, applied before anything is written:
  * author fields are dropped;
  * HN ids are replaced by new sequential ids (ordered by time) and no
    mapping back to HN is written anywhere;
  * timestamps are reduced to a calendar date;
  * "@name"s, any author name that is rare as an English word, and the
    names of people in the same thread unless they are very common words,
    are replaced with "[user]" (best effort; see README);
  * URLs are replaced with "[link]".
Quoted lines (HN convention: lines starting with ">") are separated out so
sentiment and topics reflect what each person wrote, not what they quoted.
"""
import html
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from wordfreq import zipf_frequency

sys.path.insert(0, str(Path(__file__).parent))
from collect import strip_html  # noqa: E402
from config import GROUPS, MIN_FOCUS_SUPPORT  # noqa: E402
from relevance import (groups_for, story_candidate, text_matches,  # noqa
                       title_matches)

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
WORK = ROOT / "data" / "work"

URL = re.compile(r"https?://\S+|www\.\S+")
AT_NAME = re.compile(r"(?<!\w)@[A-Za-z0-9_-]{2,}")
NAME_TOKEN = re.compile(r"(?<![\w-])[A-Za-z0-9_][\w-]*(?<!-)")
# The HN moderator account: a public role, but still a username.
ALWAYS_REDACT = {"dang"}


def clean_html(s):
    if not s:
        return ""
    s = re.sub(r"<pre><code>.*?</code></pre>", " [code] ", s, flags=re.S)
    s = re.sub(r"<p>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    return html.unescape(s).strip()


def split_quotes(text):
    own, quoted = [], []
    for line in text.split("\n"):
        (quoted if line.lstrip().startswith(">") else own).append(line)
    return "\n".join(own).strip(), "\n".join(quoted).strip()


def flatten(node, story_id, depth=0, parent=None):
    yield {"hn_id": node["id"], "type": node.get("type"),
           "author": node.get("author"), "t": node.get("created_at_i"),
           "title": node.get("title") or "", "raw": node.get("text"),
           "points": node.get("points"), "story": story_id, "parent": parent,
           "depth": depth}
    for ch in node.get("children") or []:
        yield from flatten(ch, story_id, depth + 1, node["id"])


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    hits = [json.loads(line) for line in open(RAW / "hits.jsonl")]

    threads = {}
    for f in sorted((RAW / "threads").glob("*.json")):
        tree = json.loads(f.read_text())
        # Only threads a fresh collection run would fetch, so a rerun
        # reproduces the same corpus.
        if not story_candidate(tree.get("title") or "",
                               strip_html(tree.get("text"))):
            continue
        threads[tree["id"]] = [r for r in flatten(tree, tree["id"])
                               if r["type"] in ("story", "comment")]
    in_threads = {r["hn_id"] for rs in threads.values() for r in rs}

    loose = []
    for h in hits:
        if "comment" in h["_tags"] and int(h["objectID"]) not in in_threads:
            loose.append({"hn_id": int(h["objectID"]), "type": "comment",
                          "author": h.get("author"), "t": h["created_at_i"],
                          "title": h.get("story_title") or "",
                          "raw": h.get("comment_text"), "points": None,
                          "story": h.get("story_id"),
                          "parent": h.get("parent_id"), "depth": None})

    every = [r for rs in threads.values() for r in rs] + loose
    for r in every:
        r["text"] = clean_html(r["raw"])

    # Usernames to redact: authors in the same thread, unless the name is
    # also an ordinary word (appears in >= 5 items' text, case-insensitive).
    thread_authors = {}
    for r in every:
        if r["author"]:
            thread_authors.setdefault(r["story"], set()).add(r["author"])
    # Which author names are also ordinary English words? Decided by general
    # English word frequency (wordfreq Zipf scale), not by this corpus, since
    # prolific users are mentioned often enough to look "common" here.
    def ordinary(name, cutoff):
        return zipf_frequency(name.lower(), "en") >= cutoff

    # Redacted wherever they appear: names that are rare as English words,
    # or username-shaped (digits, underscores, inner capitals) and not
    # everyday words. A standalone comment's thread was never fetched, so the
    # same-thread rule below cannot cover it.
    all_authors = {a for rs in thread_authors.values() for a in rs}
    global_names = {a.lower() for a in all_authors
                    if len(a) >= 4 and not a.isdigit()
                    and (not ordinary(a, 3.0)
                         or (re.search(r"[0-9_]|[a-z][A-Z]", a)
                             and not ordinary(a, 4.0)))}
    global_names |= ALWAYS_REDACT

    def redact_global(m):
        return "[user]" if m.group(0).lower() in global_names else m.group(0)

    def prepare(r):
        text = URL.sub("[link]", r["text"])
        text = AT_NAME.sub("[user]", text)
        text = NAME_TOKEN.sub(redact_global, text)
        # Same thread: any participant's name that isn't a very common word.
        for name in thread_authors.get(r["story"], ()):
            if len(name) >= 3 and not ordinary(name, 4.5):
                text = re.sub(rf"(?<![\w-]){re.escape(name)}(?![\w-])",
                              "[user]", text)
        r["own"], quoted = split_quotes(text)
        r["quoted_chars"] = len(quoted)
        r["tm"] = text_matches(r["own"])

    for r in every:
        prepare(r)

    # Keyword-matched AND carrying a focus tag (detection / cheating /
    # response). General AI-in-education talk without one is left out.
    for r in every:
        r["focus"] = groups_for(r["own"]) if r["tm"] else []

    out = []
    stats = Counter()
    for sid, rs in threads.items():
        story = rs[0]
        comments = [r for r in rs[1:] if r["own"]]
        support = sum(r["tm"] for r in comments)
        story_matched = title_matches(story["title"], support) or story["tm"]
        story_groups = groups_for(story["title"] + "\n" + story["own"],
                                  title=story["title"]) if story_matched else []
        focus_comments = [r for r in comments if r["focus"]]
        if story_matched and not story_groups and \
                len(focus_comments) >= MIN_FOCUS_SUPPORT:
            # Untagged story whose discussion is about the focus topics:
            # it takes the tag(s) most common among those comments.
            tally = Counter(g for r in focus_comments for g in r["focus"])
            top = max(tally.values())
            story_groups = [g for g in GROUPS if tally.get(g) == top]
            stats["stories tagged from their thread"] += 1
        if story_groups:
            stats["threads kept"] += 1
            story.update(matched=True, groups=story_groups, source="thread")
            out.append(story)
            for r in comments:
                r.update(matched=bool(r["focus"]), groups=r["focus"],
                         source="thread")
                out.append(r)
        else:
            if story_matched:
                stats["matched stories dropped (no focus tag)"] += 1
            for r in comments:
                if r["focus"]:
                    r.update(matched=True, groups=r["focus"],
                             source="standalone", title=story["title"])
                    out.append(r)
    for r in loose:
        if r["focus"]:
            r.update(matched=True, groups=r["focus"], source="standalone")
            out.append(r)
        elif r["tm"]:
            stats["standalone comments dropped (no focus tag)"] += 1

    # New ids, ordered by time; HN ids are dropped before anything is saved.
    out.sort(key=lambda r: (r["t"], r["hn_id"]))
    new_id = {r["hn_id"]: i for i, r in enumerate(out)}
    with open(WORK / "corpus.jsonl", "w") as f:
        for r in out:
            thread = r["source"] == "thread"
            f.write(json.dumps({
                "id": new_id[r["hn_id"]],
                "type": r["type"],
                "thread": new_id.get(r["story"]) if thread else None,
                "parent": new_id.get(r["parent"]) if thread else None,
                "depth": r["depth"] if thread else None,
                "date": datetime.fromtimestamp(r["t"], timezone.utc)
                                .strftime("%Y-%m-%d"),
                "title": r["title"],
                "text": r["own"],
                "quoted_chars": r["quoted_chars"],
                "points": r["points"],
                "matched": r["matched"],
                "groups": r["groups"],
                "source": r["source"],
            }) + "\n")

    c = Counter((r["type"], r["source"], r["matched"]) for r in out)
    print(f"{len(threads)} candidate threads; {len(out)} items")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    for k, v in sorted(c.items(), key=str):
        print(" ", k, v)


if __name__ == "__main__":
    main()
