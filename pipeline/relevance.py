"""The corpus definition: which items count as being about AI in education.

Text rule (comments, and story body text) -- a text is *matched* when:
  - it mentions AI detectors in a school setting (Turnitin, or any other
    detector with a school word within DETECTOR_SCHOOL_WINDOW tokens), or
  - it has >= MIN_STRONG strong education words, with an AI term within
    PROXIMITY_WINDOW tokens of one of them.

Story rule -- a story is matched when:
  - its title names a detector, or uses generic detector language, or
  - its title has an AI term and a strong education word, or
  - its title has an AI term and a weak education word, and at least
    MIN_THREAD_SUPPORT comments in its thread pass the text rule, or
  - its body text passes the text rule.

Focus tags (an item can carry several):
  detection - AI detectors in a school setting (see _detection)
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
                    DETECTOR_SCHOOL_WINDOW, GENERIC_DETECTOR, MIN_STRONG,
                    MIN_THREAD_SUPPORT, NON_TEXT_DETECTION, PROXIMITY_WINDOW,
                    RESPONSE_GENERAL, RESPONSE_SPECIFIC, RESPONSE_WINDOW,
                    SCHOOL_CONTEXT, SCHOOL_DETECTORS, STRONG_EDU,
                    TEACHING_CONTEXT, WEAK_EDU)

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
    """AI-detector talk in a school setting: Turnitin, or any other detector
    mention with a school word within DETECTOR_SCHOOL_WINDOW tokens."""
    if SCHOOL_DETECTORS.search(text):
        return True
    mentions = sorted(_positions(DETECTOR_BRANDS, text)
                      + _positions(GENERIC_DETECTOR, text))
    if not mentions:
        return False
    return _near(mentions, _positions(SCHOOL_CONTEXT, text),
                 DETECTOR_SCHOOL_WINDOW)


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

    For a story, `text` is its title plus body and `title` its title."""
    groups = []
    # A detector title ("AI detectors are a bad idea") counts when the
    # story's title or text has a school word anywhere: titles are too short
    # for the proximity test.
    title_detector = bool(title) \
        and bool(GENERIC_DETECTOR.search(title) or DETECTOR_BRANDS.search(title)) \
        and not NON_TEXT_DETECTION.search(title) \
        and bool(SCHOOL_CONTEXT.search(text))
    other_kind = bool(title) and bool(NON_TEXT_DETECTION.search(title))
    if (_detection(text) or title_detector) and not other_kind:
        groups.append("detection")
    if CHEATING_TERMS.search(text):
        groups.append("cheating")
    if RESPONSE_SPECIFIC.search(text) or _near(
            _positions(RESPONSE_GENERAL, text),
            _positions(TEACHING_CONTEXT, text), RESPONSE_WINDOW):
        groups.append("response")
    return groups
