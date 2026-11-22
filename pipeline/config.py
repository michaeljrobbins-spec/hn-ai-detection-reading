"""Everything that defines *what* is in the corpus lives in this file.

Two stages, deliberately separate:

1. SEED QUERIES (collect.py) cast a wide net through the HN Algolia search API.
   They only need to find a superset of relevant items; precision does not
   matter here.
2. RELEVANCE RULES (build_corpus.py) are the actual definition of the corpus.
   They are plain regular expressions so anyone can read and audit them.
"""
import re
from datetime import datetime, timezone

# --- Time window -----------------------------------------------------------
WINDOW_START = datetime(2025, 11, 22, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 11, 22, tzinfo=timezone.utc)
SNAPSHOT_LABEL = "2026-11-22"

# --- Seed queries ----------------------------------------------------------
# Algolia requires every word in a query and folds plurals, so each pair
# below means "item mentions both words somewhere". typoTolerance is turned
# off in collect.py because by default "turnitin" also matches "turnstile".
SEED_AI_TERMS = ["ai", "llm", "chatgpt", "gpt", "claude", "gemini", "copilot",
                 "chatbot", "genai"]
SEED_EDU_TERMS = ["student", "teacher", "professor", "school", "university",
                  "college", "classroom", "homework", "essay", "exam",
                  "plagiarism", "cheating", "academic", "lecturer",
                  "instructor", "educator", "syllabus", "grading", "tutor",
                  "undergrad", "coursework"]
SEED_STANDALONE = ["turnitin", "gptzero", "originality.ai", "copyleaks",
                   "zerogpt", "ai detector", "ai detection", "ai checker",
                   "ai writing detector", "blue book", "oral exam",
                   "handwritten exam", "academic integrity"]


def seed_queries():
    qs = [f"{a} {e}" for a in SEED_AI_TERMS for e in SEED_EDU_TERMS]
    return sorted(set(qs + SEED_STANDALONE))


# --- Relevance rules -------------------------------------------------------
def _rx(pattern):
    return re.compile(pattern, re.IGNORECASE)


AI_TERMS = _rx(
    r"\b(ai|a\.i\.|llms?|chat ?gpt|gpt-?[345o]\w*|gpts?|openai|claude|gemini|"
    r"copilot|chatbots?|gen-?ai|generative|language models?|deepseek|grok)\b")

# "Strong" education words mostly mean education wherever they appear.
STRONG_EDU = _rx(
    r"\b(students?|teachers?|professors?|profs?|classrooms?|homework|"
    r"coursework|schoolwork|syllabus|syllabi|curricul(?:um|a)|pedagog\w*|"
    r"educators?|tutors?|tutoring|lecturers?|instructors?|undergrad\w*|k-?12|"
    r"(?:high|middle|grade|elementary|primary|secondary) ?schools?|essays?|"
    r"exams?|quiz(?:zes)?|academic (?:integrity|honesty|dishonesty|misconduct)|"
    r"grading|teaching|educational|education)\b")
# "Weak" ones often don't ("summer school", "academic paper", "college grad
# unemployment"), so on their own they need support from the discussion.
WEAK_EDU = _rx(
    r"\b(schools?|universit(?:y|ies)|colleges?|campus(?:es)?|academia|"
    r"academics?|degrees?|semesters?|lectures?|courses|freshm[ae]n)\b")

# A detector product name is relevant on its own.
DETECTOR_BRANDS = _rx(r"\b(turnitin|gptzero|zerogpt|originality\.ai|copyleaks|"
                      r"winston ai|quillbot|undetectable\.ai|stealthgpt)\b")
# Generic "AI detector" language is relevant only near writing/education words
# (otherwise it is often about images, deepfakes, malware, etc.).
GENERIC_DETECTOR = _rx(
    r"\b(ai|llm|gpt|chat ?gpt|machine|ai-generated|ai generated)[- ]"
    r"(?:writing |text |content |essay )?(?:detect\w*|checkers?)\b"
    r"|\bdetect\w* (?:ai|llm|chatgpt|gpt)[- ](?:generated|written|writing|text)")
WRITING_TERMS = _rx(r"\b(essays?|writing|written|papers?|prose|text|"
                    r"assignments?|submissions?)\b")

CHEATING_TERMS = _rx(
    r"\b(cheat\w*|plagiari\w+|academic (?:dis)?honesty|academic integrity|"
    r"academic misconduct|ghost-?writ\w*|contract cheating|dishonest\w*)\b")

RESPONSE_TERMS = _rx(
    r"\b(blue ?books?|oral (?:exam|test|defen[cs]e)s?|vivas?|viva voce|"
    r"handwrit\w*|hand-?written|in[- ]class (?:essay|writing|exam|test)s?|"
    r"in[- ]person (?:exam|test)s?|proctor\w*|pen(?:cil)?[- ]and[- ]paper|"
    r"flipped classroom|lockdown browser|(?:ai|chatgpt|llm) polic(?:y|ies)|"
    r"syllabus|syllabi|ban(?:s|ned|ning)? (?:ai|chatgpt|llms?)|"
    r"redesign\w*|rethink\w*|assessment\w*|google docs? (?:history|version)|"
    r"version history|keystroke\w*)\b")

# A text counts as AI-and-education when it has at least MIN_STRONG strong
# education words and an AI term within PROXIMITY_WINDOW tokens of one.
PROXIMITY_WINDOW = 8  # tokens
MIN_STRONG = 2
# A story whose title pairs an AI term with only a *weak* education word is
# included when at least this many comments in its thread pass the text rule.
MIN_THREAD_SUPPORT = 3

GROUPS = {
    "detection": "AI detectors (Turnitin, GPTZero, ...)",
    "cheating": "Students cheating with AI",
    "response": "How teachers are responding",
    "other": "Other AI-in-education",
}
