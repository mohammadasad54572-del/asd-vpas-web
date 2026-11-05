# language: Python, file: config.py, runtime: 3.10+
import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
_admin_raw = os.getenv("ADMIN_IDS", "6346795447").strip()
ADMIN_IDS = [int(x) for x in _admin_raw.split(",") if x.strip().isdigit()]
if not ADMIN_IDS:
    ADMIN_IDS = [6346795447]

DEFAULT_FB_URL = os.getenv("FB_URL", "").strip()
DEFAULT_FB_KEY = os.getenv("FB_KEY", "").strip()

# Force join channel (public @username or -100id). Empty = disabled
FORCE_CHANNEL = os.getenv("FORCE_CHANNEL", "").strip()  # e.g. @mychannel or -1001234567890
FORCE_CHANNEL_LINK = os.getenv("FORCE_CHANNEL_LINK", "").strip()  # invite link shown to user

# Referral
REFERRAL_HOURS = float(os.getenv("REFERRAL_HOURS", "1"))  # hours granted per successful referral
START_BONUS_MINUTES = float(os.getenv("START_BONUS_MINUTES", "10"))  # free access on first /start

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
DB_FILE = os.path.join(DATA_DIR, "bot_data.json")
os.makedirs(DATA_DIR, exist_ok=True)

BOT_NAME = "ERA x OTP BOT"
PAGE_SIZE = 6
SYNC_INTERVAL = 30
