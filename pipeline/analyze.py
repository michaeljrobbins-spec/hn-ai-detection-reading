"""Stage 3: sentiment + topic models, then export the dashboard data.

Reads data/work/corpus.jsonl. Writes docs/data/ (published):
  items.json   one row per item: excerpt (at most half the post, max
               200 characters), never full text
  topics.json  topic-term weights for both topic models
  meta.json    counts, parameters, lexicon notes, coherence scores

Sentiment: VADER, two variants.
  vader       stock lexicon
  vader_tn    "topic-neutral": the subject's own vocabulary (cheating, ban,
              fail, integrity, ...) is set to 0 so that talking *about*
              cheating is not by itself scored as negative.
For every item we also record which lexicon words it contains, so readers
can see why a score came out as it did.

Topics: LDA (counts) and NMF (tf-idf), k chosen per model by NPMI
coherence over the corpus itself. Topics are labelled only by their top
terms; no human-written names.
"""
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np
from sklearn.decomposition import NMF, LatentDirichletAllocation
from sklearn.feature_extraction.text import (ENGLISH_STOP_WORDS,
                                             CountVectorizer, TfidfVectorizer)
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

sys.path.insert(0, str(Path(__file__).parent))
from config import GROUPS, SNAPSHOT_LABEL, WINDOW_END, WINDOW_START  # noqa

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "data" / "work"
OUT = ROOT / "docs" / "data"

EXCERPT_CHARS = 200
EXCERPT_SHARE = 0.5  # never more than half of any post
MIN_TOPIC_TOKENS = 12  # shorter items get no topic assignment
# k starts at 10: fewer topics was judged too coarse to explore (a design
# choice, stated on the Methods page); within the range, NPMI picks.
K_CANDIDATES = [10, 12, 15, 20]
MIN_TOPIC_SHARE = 0.25  # below this, an item has "no dominant topic"
SEED = 42
WORD_MIN_DF = 3
# Posts with fewer words than this are not in the word index (see export).
INDEX_MIN_WORDS = 30
# Must match the tokenizer in docs/app.js (setQuery).
WORD_TOKEN = re.compile(r"[a-z0-9][a-z0-9+#.'-]*[a-z0-9+#]|[a-z0-9]")

TOPIC_NEUTRAL_WORDS = [
    "cheat", "cheated", "cheater", "cheaters", "cheating", "cheats",
    "dishonest", "fraud", "integrity", "honest", "honesty",
    "ban", "banned", "banning", "fail", "failed", "failing", "fails",
    "accused", "accuse", "accusation", "accusations", "penalty", "punish",
    "punishment", "punished", "guilty", "innocent", "fake", "steal",
    "stealing", "lazy",
]

EXTRA_STOP = set("""
just like don people think really ve ll re didn doesn isn wasn aren
going thing things way lot know make makes made want say said use used
using get got good also even much well actually something one would could
should might may still see yes sure need probably maybe pretty kind sort
quite rather bit lot lots yeah ok okay mean point seems seem gt amp quot
link user code http https www com hn
work time years year world right doing better new did does getting look
trying able different long life day days today far real lol
""".split())


def excerpt(text):
    """At most half of the post's own words, and never over EXCERPT_CHARS,
    so no post is ever published in full. Cut at a word boundary."""
    t = re.sub(r"\s+", " ", text).strip()
    limit = min(EXCERPT_CHARS, int(len(t) * EXCERPT_SHARE))
    if limit <= 0:
        return ""
    cut = t[:limit + 1].rsplit(" ", 1)[0] if " " in t[:limit + 1] else ""
    if not cut or len(cut) > limit:
        cut = t[:limit]  # one long word: hard cut
    return cut.rstrip() + " …"


def lexicon_hits(text, lex, k=6):
    toks = re.findall(r"[a-z']+", text.lower())
    c = Counter(t for t in toks if t in lex and lex[t] != 0)
    ranked = sorted(c, key=lambda w: -abs(lex[w]) * c[w])[:k]
    return [[w, round(lex[w], 1)] for w in ranked]


def npmi_coherence(topic_terms, X_bin):
    """Mean NPMI over top-term pairs, from document co-occurrence."""
    n_docs = X_bin.shape[0]
    df = np.asarray(X_bin.sum(axis=0)).ravel()
    scores = []
    for terms in topic_terms:
        sub = X_bin[:, terms]
        co = (sub.T @ sub).toarray()
        vals = []
        for i in range(len(terms)):
            for j in range(i + 1, len(terms)):
                pij = co[i, j] / n_docs
                if pij == 0:
                    vals.append(-1.0)
                    continue
                pi, pj = df[terms[i]] / n_docs, df[terms[j]] / n_docs
                vals.append(math.log(pij / (pi * pj)) / -math.log(pij))
        scores.append(float(np.mean(vals)))
    return float(np.mean(scores)), scores


def fit_topics(kind, docs, stop):
    if kind == "lda":
        vec = CountVectorizer(stop_words=stop, min_df=10, max_df=0.4,
                              token_pattern=r"(?u)\b[a-z][a-z0-9+#.-]*[a-z0-9+#]\b",
                              lowercase=True, ngram_range=(1, 2),
                              max_features=8000)
    else:
        vec = TfidfVectorizer(stop_words=stop, min_df=10, max_df=0.4,
                              token_pattern=r"(?u)\b[a-z][a-z0-9+#.-]*[a-z0-9+#]\b",
                              lowercase=True, ngram_range=(1, 2),
                              max_features=8000, sublinear_tf=True)
    X = vec.fit_transform(docs)
    X_bin = (X > 0).astype(np.int32).tocsc()
    vocab = np.array(vec.get_feature_names_out())
    trials = []
    for k in K_CANDIDATES:
        if kind == "lda":
            m = LatentDirichletAllocation(n_components=k, random_state=SEED,
                                          learning_method="batch",
                                          max_iter=30)
        else:
            m = NMF(n_components=k, random_state=SEED, init="nndsvda",
                    max_iter=600)
        W = m.fit_transform(X)
        top = [list(np.argsort(-row)[:10]) for row in m.components_]
        coh, per = npmi_coherence(top, X_bin)
        trials.append({"k": k, "coherence": round(coh, 4)})
        print(f"  {kind} k={k}: NPMI {coh:.3f}")
        if trials[-1]["coherence"] >= max(t["coherence"] for t in trials):
            best = (k, m, W, per)
    k, m, W, per = best
    W = W / np.maximum(W.sum(axis=1, keepdims=True), 1e-12)
    topics = []
    for t, row in enumerate(m.components_):
        idx = np.argsort(-row)[:15]
        w = row[idx] / row[idx].max()
        topics.append({"id": t, "coherence": round(per[t], 3),
                       "terms": [[vocab[i], round(float(x), 3)]
                                 for i, x in zip(idx, w)]})
    return {"k": k, "trials": trials, "topics": topics}, W


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    corpus = [json.loads(l) for l in open(WORK / "corpus.jsonl")]
    print(f"{len(corpus)} items")

    # --- sentiment -------------------------------------------------------
    sia = SentimentIntensityAnalyzer()
    sia_tn = SentimentIntensityAnalyzer()
    for w in TOPIC_NEUTRAL_WORDS:
        sia_tn.lexicon[w] = 0.0
    lex = sia.lexicon

    for r in corpus:
        body = (r["title"] + "\n" + r["text"]) if r["type"] == "story" \
            else r["text"]
        r["_body"] = body.strip()
        r["s"] = round(sia.polarity_scores(r["_body"])["compound"], 3)
        r["s_tn"] = round(sia_tn.polarity_scores(r["_body"])["compound"], 3)
        r["lex"] = lexicon_hits(r["_body"], lex)

    # --- topics ----------------------------------------------------------
    stop = sorted(ENGLISH_STOP_WORDS | EXTRA_STOP)
    eligible = [i for i, r in enumerate(corpus)
                if len(re.findall(r"\w+", r["_body"])) >= MIN_TOPIC_TOKENS]
    docs = [corpus[i]["_body"] for i in eligible]
    print(f"{len(docs)} items long enough for topic modeling")
    models = {}
    for kind in ("nmf", "lda"):
        print(f"fitting {kind}")
        res, W = fit_topics(kind, docs, stop)
        models[kind] = res
        counts = Counter()
        for row_i, ci in enumerate(eligible):
            t = int(np.argmax(W[row_i]))
            share = float(W[row_i, t])
            if share < MIN_TOPIC_SHARE:
                continue  # no dominant topic
            corpus[ci][kind] = t
            corpus[ci][kind + "_w"] = round(share, 2)
            counts[t] += 1
        for t in res["topics"]:
            t["n"] = counts[t["id"]]

    # --- export ----------------------------------------------------------
    cols = ["id", "type", "thread", "parent", "depth", "date", "title",
            "excerpt", "chars", "points", "matched", "groups", "source",
            "s", "s_tn", "lex", "nmf", "nmf_w", "lda", "lda_w"]
    rows = []
    for r in corpus:
        r["excerpt"] = excerpt(r["text"])
        r["chars"] = len(r["text"])
        rows.append([r.get(c) for c in cols])
    (OUT / "items.json").write_text(
        json.dumps({"columns": cols, "rows": rows}, separators=(",", ":")))
    (OUT / "topics.json").write_text(json.dumps(models, indent=1))

    # Word index: lets the dashboard search full posts without publishing
    # them. Only words found in >= WORD_MIN_DF items are indexed (rare
    # words are the most identifying, and dominate the file size).
    # A short post's words are left out entirely: for a post of a few
    # words, the unordered word list says most of what the post says. The
    # dashboard searches short posts through their published excerpt only.
    # Story titles are always indexed, since they are published in full.
    post = {}
    n_short = 0
    for r in corpus:
        words = set()
        if r["type"] == "story":
            words |= set(WORD_TOKEN.findall(r["title"].lower()))
        if len(re.findall(r"\w+", r["text"])) >= INDEX_MIN_WORDS:
            words |= set(WORD_TOKEN.findall(r["text"].lower()))
        elif r["text"]:
            n_short += 1
        for w in words:
            post.setdefault(w, []).append(r["id"])
    vocab = sorted(w for w, ids in post.items() if len(ids) >= WORD_MIN_DF)
    deltas = []
    for w in vocab:
        ids = sorted(post[w])
        deltas.append([ids[0]] + [b - a for a, b in zip(ids, ids[1:])])
    (OUT / "words.json").write_text(json.dumps(
        {"min_df": WORD_MIN_DF, "min_words": INDEX_MIN_WORDS,
         "vocab": vocab, "postings": deltas},
        separators=(",", ":")))

    type_counts = Counter(r["type"] for r in corpus)
    meta = {
        "snapshot": SNAPSHOT_LABEL,
        "window": [WINDOW_START.strftime("%Y-%m-%d"),
                   WINDOW_END.strftime("%Y-%m-%d")],
        "n_items": len(corpus),
        "n_stories": type_counts["story"],
        "n_comments": type_counts["comment"],
        "n_threads": len({r["thread"] for r in corpus if r["thread"] is not None}),
        "n_matched": sum(r["matched"] for r in corpus),
        "n_standalone": sum(r["source"] == "standalone" for r in corpus),
        "n_topic_docs": len(docs),
        "groups": GROUPS,
        "excerpt_chars": EXCERPT_CHARS,
        "excerpt_share": EXCERPT_SHARE,
        "index_min_words": INDEX_MIN_WORDS,
        "n_short_unindexed": n_short,
        "min_topic_tokens": MIN_TOPIC_TOKENS,
        "min_topic_share": MIN_TOPIC_SHARE,
        "k_candidates": K_CANDIDATES,
        "topic_neutral_words": [[w, lex.get(w)] for w in TOPIC_NEUTRAL_WORDS
                                if lex.get(w) is not None],
    }
    audit = ROOT / "pipeline" / "audit_results.json"
    if audit.exists():
        meta["audit"] = json.loads(audit.read_text())
    (OUT / "meta.json").write_text(json.dumps(meta, indent=1))
    print(json.dumps({k: v for k, v in meta.items()
                      if k.startswith("n_")}, indent=1))


if __name__ == "__main__":
    main()
