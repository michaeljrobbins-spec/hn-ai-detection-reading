"""The corpus definition: which items count as being about AI in education.

Text rule (comments, and story body text) -- a text is *matched* when:
  - it names a detector product (Turnitin, GPTZero, ...), or
  - it uses generic "AI detector" language plus an education/writing word, or
  - it has >= MIN_STRONG strong education words, with an AI term within
    PROXIMITY_WINDOW tokens of one of them.

Story rule -- a story is matched when:
  - its title names a detector, or uses generic detector language, or
  - its title has an AI term and a strong education word, or
  - its title has an AI term and a weak education word, and at least
    MIN_THREAD_SUPPORT comments in its thread pass the text rule, or
  - its body text passes the text rule.

Focus tags (an item can carry several):
  detection - detector product or generic detector language
  cheating  - cheating / plagiarism / academic-integrity vocabulary
  response  - assessment and policy changes (blue books, oral exams, bans,
              moratoriums, redesigned assessment, ...)
An item is in the corpus only if it matches AND carries a focus tag. A
matched story without one stays if at least MIN_FOCUS_SUPPORT keyword-
matched comments in its thread carry one; it then takes the tag(s) most
common among them. See build_corpus.py.

These rules were tuned on one hand-labelled sample and measured on a
second, fresh one; see pipeline/audit.py and the Methods page.
"""
import re

from config import (AI_TERMS, CHEATING_TERMS, DETECTOR_BRANDS,
                    GENERIC_DETECTOR, MIN_STRONG, MIN_THREAD_SUPPORT,
                    NON_TEXT_DETECTION, PROXIMITY_WINDOW, RESPONSE_GENERAL,
                    RESPONSE_SPECIFIC, RESPONSE_WINDOW, STRONG_EDU,
                    TEACHING_CONTEXT, WEAK_EDU, WRITING_TERMS)

_TOKEN = re.compile(r"\S+")


def _positions(rx, text):
    """Token indices at which each regex match starts."""
    starts = [m.start() for m in rx.finditer(text)]
    if not starts:
        return []
    tok_starts = [m.start() for m in _TOKEN.finditer(text)]
    out, j = [], 0
    for s in starts:
        while j + 1 < len(tok_starts) and tok_starts[j + 1] <= s:
            j += 1
        out.append(j)
    return out


def _near(a, b, window):
    i = j = 0
    while i < len(a) and j < len(b):
        if abs(a[i] - b[j]) <= window:
            return True
        if a[i] < b[j]:
            i += 1
        else:
            j += 1
    return False


def _detection(text):
    if DETECTOR_BRANDS.search(text):
        return True
    return bool(GENERIC_DETECTOR.search(text)) and bool(
        STRONG_EDU.search(text) or WRITING_TERMS.search(text))


def text_matches(text):
    if not text:
        return False
    if _detection(text):
        return True
    strong = _positions(STRONG_EDU, text)
    if len(strong) < MIN_STRONG:
        return False
    return _near(_positions(AI_TERMS, text), strong, PROXIMITY_WINDOW)


def title_matches(title, thread_support=0):
    if not title:
        return False
    if DETECTOR_BRANDS.search(title) or GENERIC_DETECTOR.search(title):
        return True
    if not AI_TERMS.search(title):
        return False
    if STRONG_EDU.search(title):
        return True
    return bool(WEAK_EDU.search(title)) and thread_support >= MIN_THREAD_SUPPORT


def story_candidate(title, text):
    """Looser test used at collection time to decide which threads to
    fetch (thread support can only be measured once a thread is fetched)."""
    if text_matches(text) or title_matches(title):
        return True
    return bool(title and AI_TERMS.search(title) and WEAK_EDU.search(title))


def groups_for(text, title=""):
    """Focus-group tags for an item; empty if it has none.

    In a story *title*, generic "AI detector" wording counts on its own:
    titles are too short to carry the writing/education words the text
    rule asks for ("AI detectors are a bad idea")."""
    groups = []
    title_detector = bool(title) and bool(GENERIC_DETECTOR.search(title)) \
        and not NON_TEXT_DETECTION.search(title)
    if _detection(text) or title_detector:
        groups.append("detection")
    if CHEATING_TERMS.search(text):
        groups.append("cheating")
    if RESPONSE_SPECIFIC.search(text) or _near(
            _positions(RESPONSE_GENERAL, text),
            _positions(TEACHING_CONTEXT, text), RESPONSE_WINDOW):
        groups.append("response")
    return groups
