"""Event settings. Every value can also be overridden with an environment variable."""
import os


def env(name, default, cast=str):
    return cast(os.environ.get(name, default))


EVENT_NAME = "Code Reverse Engineering"
ORG_NAME = "IET-KJSIT"
EVENT_SUBTITLE = "IET Renaissance 2026"

# ---- CHANGE THESE BEFORE THE EVENT -------------------------------------
ADMIN_PASSWORD = env("CRE_ADMIN_PASSWORD", "admin@iet2026")   # for /admin
ACCESS_CODE = env("CRE_ACCESS_CODE", "RENAISSANCE")           # volunteers tell participants this at the door
# ------------------------------------------------------------------------

PORT = env("CRE_PORT", 5000, int)
MAX_ACTIVE = env("CRE_MAX_ACTIVE", 15, int)        # participants allowed in the lab at the same time
IDLE_SECONDS = 180                                  # no heartbeat for this long -> slot is freed
DB_PATH = env("CRE_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "event.db"))

# Round layout. per_q = marks per question.
ROUNDS = {
    1: {"name": "Decode",  "questions": 5, "minutes": 5, "per_q": 2,  "level": "Easy"},
    2: {"name": "Analyse", "questions": 4, "minutes": 5, "per_q": 5,  "level": "Medium"},
    3: {"name": "Reverse", "questions": 3, "minutes": 5, "per_q": 10, "level": "Hard"},
}

# Round 3 partial marks. 0 = every Round 3 question is plain auto-graded MCQ (10 marks).
# e.g. 4 = 6 marks for the correct option + up to 4 marks that an organiser awards
# for the one-line explanation the participant types (graded on the admin page).
R3_EXPLAIN_MARKS = env("CRE_R3_EXPLAIN_MARKS", 0, int)

SHOW_SCORE_TO_PARTICIPANT = False   # keep False: results are announced by the organisers
