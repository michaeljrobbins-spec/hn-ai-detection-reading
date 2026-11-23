# HN AI Education Reader

A browsable snapshot of a year of Hacker News discussion about AI in
education: AI-writing detectors (Turnitin, GPTZero, ...), students cheating
with AI, and how teachers are responding. It is built for **exploring the
conversation, not for drawing conclusions from it**. The dashboard has no
headline findings: topics are named only by their top words, and sentiment
is shown as full distributions, with the words that drove each score.

- **Dashboard:** `docs/index.html` (served by GitHub Pages from `/docs`)
- **Methods and limits:** `docs/methods.html`: read this before citing anything

Snapshot: 22 Nov 2025 – 22 Nov 2026, collected 22 Nov 2026.
195 stories with their threads, plus 814 relevant comments from other
threads: 7,565 items in all. Only items about the three focus topics are
included; general AI-in-education talk (AI tutors, edtech launches, AI and
graduate jobs) is left out.

## Privacy

- Usernames are dropped. HN ids are replaced with new ids, and nothing links back to HN.
- Timestamps are reduced to dates. URLs become `[link]`.
- Name mentions inside text become `[user]`:
  - `@name`s;
  - any of the ~21,500 collected author names that is rare as an English word
    (by `wordfreq` frequency), wherever it appears;
  - names of people in the same thread, unless they are very common words.

  This is best effort. A username that is also an everyday word ("coffee",
  "david"), mentioned from another thread, is not caught. Some real words
  and real names (e.g. textbook authors) will be over-redacted.
- The site publishes only the **opening of each post's own words: at most
  half the post, and never more than 200 characters**, so no post appears in
  full.
- It also publishes a word index (which posts contain which words, for words
  used in at least 3 posts), so longer posts can be searched without being
  published. **Posts under 30 words are left out of the index**, because for a
  very short post the word list says most of what it says. They are searched
  through their published excerpt only. Story titles, which are shown in full,
  are indexed.
- Raw API data (`data/raw/`) and full-text working files (`data/work/`) are
  gitignored and never committed.

HN is public and searchable, so an excerpt pasted into a search engine will
usually find the original post and its author. These steps keep the
dashboard from pointing at people; they do not make the text untraceable.

## Pipeline

Python 3.11+.

```bash
pip install -r requirements.txt
```

```bash
python pipeline/collect.py               # ~10 min; writes data/raw/ (needs hn.algolia.com)
```

```bash
python pipeline/build_corpus.py          # filter + anonymize -> data/work/corpus.jsonl
```

```bash
python pipeline/analyze.py               # sentiment + topics -> docs/data/ (~5 min)
```

```bash
python pipeline/audit.py 2026 30         # draw a stratified sample to hand-check
```

| File | Role |
|---|---|
| `pipeline/config.py` | time window, seed searches, word lists and thresholds (the corpus definition) |
| `pipeline/relevance.py` | the rules that decide which items count, and their group tags |
| `pipeline/collect.py` | Algolia searches (typo tolerance off, windows split under the 1000-hit cap) and thread fetches |
| `pipeline/build_corpus.py` | relevance filtering, quote removal, anonymization |
| `pipeline/analyze.py` | VADER (stock and topic-neutral), NMF and LDA topics, excerpt and word-index export |
| `pipeline/audit_results.json` | hand-labelled precision sample (validation set) |

`collect.py --threads-only` reuses saved search results and fetches only
missing threads.

## Known limits (short version; details on the Methods page)

- **Relevance is keyword-based.** On a fresh hand-labelled sample, about 83%
  of matched stories, 70% of comments from other threads and 93% of
  keyword-matched thread comments were about the focus topics, but only
  about a third of non-matched thread replies. Recall was not measured.
- **Most detector discussion is not about school.** About three-quarters of
  items tagged "AI detectors" have no education word: people running Pangram
  or GPTZero on blog posts and HN submissions. The group covers AI-writing
  detection generally.
- **VADER sentiment is not stance**, and it scores the subject's own words
  ("cheating", "ban", "fail") as negative. That is why there is a
  topic-neutral variant.
- **Topic models are exploratory.** NMF and LDA split the same text
  differently, and small changes to the corpus change which topics appear.
- **HN is not the public, students, or teachers.** It is a self-selected,
  mostly tech-industry audience.

## Publishing on GitHub Pages

Settings → Pages → *Deploy from a branch* → choose the branch and `/docs`.
D3 v7.9.0 is vendored in `docs/vendor/` (ISC license), so the site makes no
third-party requests.
