"""
Single source of truth for every filesystem path in the project.

Before this module existed, ~9 different files each computed their own
"project root" via os.path.dirname(__file__) and then descended into data/,
voices/, etc. That's fragile — every one of those had to be updated by hand
if the file computing it ever moved into a subdirectory. Here, PROJECT_ROOT
is anchored once, from this file's own location, and everything else is
derived from it.
"""
import os

# bmo/paths.py -> up one level -> project root. Robust to CWD and to however
# the entry point was invoked, unlike an entry-point-relative computation.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CONFIG_PATH        = os.path.join(PROJECT_ROOT, "config.json")
DATA_DIR           = os.path.join(PROJECT_ROOT, "data")
SOUNDS_DIR         = os.path.join(PROJECT_ROOT, "sounds")
VOICES_DIR         = os.path.join(PROJECT_ROOT, "voices")
WAKEWORD_DIR       = os.path.join(PROJECT_ROOT, "wakeword")
FACES_DIR          = os.path.join(PROJECT_ROOT, "faces")
WEB_DIR            = os.path.join(PROJECT_ROOT, "web")
DYNAMIC_SKILLS_DIR = os.path.join(PROJECT_ROOT, "dynamic_skills")

# data/ — shared across multiple modules; kept as named constants so every
# consumer resolves the exact same path instead of re-deriving it.
MEMORY_FILE          = os.path.join(DATA_DIR, "memory.json")           # BMOMemory + NotesSkill (intentionally shared)
JOURNAL_FILE         = os.path.join(DATA_DIR, "journal.json")          # JournalManager + BMOMemory's journal snippet
ALARMS_FILE          = os.path.join(DATA_DIR, "alarms.json")
REMINDERS_FILE       = os.path.join(DATA_DIR, "reminders.json")
SEMANTIC_MEMORY_FILE = os.path.join(DATA_DIR, "semantic_memory.json")
VOICEPRINTS_FILE     = os.path.join(DATA_DIR, "voiceprints.json")

# Instagram data/ files (bmo/instagram/scheduler.py + web.py)
IG_SESSION_FILE = os.path.join(DATA_DIR, "ig_session.json")
IG_REPLIED_FILE = os.path.join(DATA_DIR, "ig_replied.json")
IG_HISTORY_FILE = os.path.join(DATA_DIR, "ig_history.json")
IG_STATS_FILE   = os.path.join(DATA_DIR, "ig_stats.json")
IG_COOKIES_FILE = os.path.join(DATA_DIR, "ig_cookies.json")
IG_TMP_DIR      = os.path.join(DATA_DIR, "ig_tmp")
