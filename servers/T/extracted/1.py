"""
ASD AI Bot - improved build

Required env vars:
    BOT_TOKEN   - main bot token (from @BotFather)
    MONGO_URL   - MongoDB connection string
Optional env vars:
    OWNER_ID            - your Telegram user id
    DAILY_IMAGE_LIMIT   - images per user per day (0 = unlimited, default 15)
    DAILY_TTS_LIMIT     - voices per user per day (0 = unlimited, default 20)
    REF_BONUS           - extra daily images/voices per referral (default 3)
    REF_BONUS_CAP       - max extra daily limit from referrals (default 60)
    CLONE_PRICE         - clone price in rupees (default 10; owner can change with /setprice)
    FAM_API_KEY         - famgateway key for automatic online payment (optional)
"""
import asyncio
import base64
import io
import logging
import os
import random
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import dns.resolver
import httpx
from pymongo import MongoClient, ReturnDocument

from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import (
    TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter,
)
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand, BotCommandScopeChat, BufferedInputFile, CallbackQuery,
    ErrorEvent, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Config (secrets ONLY from environment) ───────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8604487997:AAGmEUwi8_ojPzmGHyyYIsMJTM0J4-WcQTw").strip()
MONGO_URL = os.environ.get("MONGO_URL", "mongodb+srv://sgamer011141_db_user:sgamer011141_db_user@cluster0.nwgp6ux.mongodb.net/").strip()
OWNER_ID = int(os.getenv("OWNER_ID", "6346795447"))
DAILY_IMAGE_LIMIT = int(os.getenv("DAILY_IMAGE_LIMIT", "15"))
DAILY_TTS_LIMIT = int(os.getenv("DAILY_TTS_LIMIT", "20"))
TTS_MAX_CHARS = 1000
COOLDOWN = 1.0  # seconds between messages per user
REF_BONUS = int(os.getenv("REF_BONUS", "3"))          # extra images/voices per day per referral
REF_BONUS_CAP = int(os.getenv("REF_BONUS_CAP", "60"))  # max extra per day
CLONE_PRICE = int(os.getenv("CLONE_PRICE", "10"))      # rupees
FAM_API_KEY = os.environ.get("FAM_API_KEY", "fam_15c8a1a43ffb20d803b5e25eacd9c268e377bbf5").strip()
FAM_CREATE_URL = "https://famgateway.in/api/create-order.php"
FAM_STATUS_URL = "https://famgateway.in/api/checkout-status.php"
PAY_TIMEOUT = 300        # seconds to wait for online payment
PAY_CHECK_INTERVAL = 3

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable missing")
if not MONGO_URL:
    raise RuntimeError("MONGO_URL environment variable missing")

CREATOR = "@asd_army_1"
POWERED_LINK = "https://t.me/freee_apis_free"

MAIN_BOT_USERNAME = "@asdpawarai_bot"
MAIN_BOT_NAME = "ASD AI BOT"
MAIN_BOT_LINK = "https://t.me/asdpawarai_bot"

MEHEDI_API = "https://mehedi-ai-api.lovable.app"
TTS_API = "https://cute-bangla-voice-bot.lovable.app/api/public/tts"
LLM_URL = "https://us-central1-ai-chat-bot-bf47e.cloudfunctions.net/chat_function_android"

TTS_VOICES = ["Leda", "Aoede", "Callirrhoe", "Autonoe", "Vindemiatrix", "Kore"]
TTS_STYLES = ["friendly", "happy", "calm", "professional", "excited", "sad"]
TOKEN_RE = re.compile(r"^\d{6,12}:[A-Za-z0-9_-]{30,}$")

# ── DNS + Mongo ──────────────────────────────────────────────────────────
resolver = dns.resolver.Resolver(configure=False)
resolver.nameservers = ["8.8.8.8", "1.1.1.1"]
resolver.timeout = 5
resolver.lifetime = 10
dns.resolver.default_resolver = resolver

mongo_client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=10000)
db = mongo_client["darkbot"]
clones_col = db["clones"]
users_col = db["users"]
history_col = db["chat_history"]
usage_col = db["usage"]
settings_col = db["settings"]
orders_col = db["clone_orders"]

# pymongo is blocking -> always run it in a thread so the bot never freezes
dbx = asyncio.to_thread


def now() -> datetime:
    return datetime.now(timezone.utc)


def init_db():
    mongo_client.admin.command("ping")
    users_col.create_index("user_id")
    history_col.create_index("user_id")
    usage_col.create_index([("user_id", 1), ("date", 1)])
    clones_col.create_index("token_short")
    clones_col.create_index("owner_id")
    orders_col.create_index([("user_id", 1), ("status", 1)])


# ── Per-user lock ────────────────────────────────────────────────────────
user_locks: dict[int, asyncio.Lock] = {}


def get_lock(uid: int) -> asyncio.Lock:
    if uid not in user_locks:
        user_locks[uid] = asyncio.Lock()
    return user_locks[uid]


def is_busy(uid: int) -> bool:
    lock = user_locks.get(uid)
    return bool(lock and lock.locked())


async def _delete_later(m: Message, delay: float):
    await asyncio.sleep(delay)
    try:
        await m.delete()
    except Exception:
        pass


async def send_busy_warning(msg: Message):
    try:
        w = await msg.answer(
            q(sc("ruko bhai! pehle wala kaam chal raha hai. "
                 "complete hone do phir naya command bhej 🔒"))
        )
        asyncio.create_task(_delete_later(w, 4))
    except Exception:
        pass


# ── Small caps ───────────────────────────────────────────────────────────
_SC = {
    'a': 'ᴀ', 'b': 'ʙ', 'c': 'ᴄ', 'd': 'ᴅ', 'e': 'ᴇ', 'f': 'ꜰ', 'g': 'ɢ',
    'h': 'ʜ', 'i': 'ɪ', 'j': 'ᴊ', 'k': 'ᴋ', 'l': 'ʟ', 'm': 'ᴍ', 'n': 'ɴ',
    'o': 'ᴏ', 'p': 'ᴘ', 'q': 'ǫ', 'r': 'ʀ', 's': 'ꜱ', 't': 'ᴛ', 'u': 'ᴜ',
    'v': 'ᴠ', 'w': 'ᴡ', 'x': 'x', 'y': 'ʏ', 'z': 'ᴢ',
}
SMALL_CAPS = {**_SC, **{k.upper(): v for k, v in _SC.items()}}


def sc(t: str) -> str:
    return ''.join(SMALL_CAPS.get(c, c) for c in t)


def q(t: str) -> str:
    return f"❝ {t} ❞"


def render(text: str, fancy: bool) -> str:
    return q(sc(text)) if fancy else text


def chunks(text: str, size: int = 3900) -> list[str]:
    out = []
    while len(text) > size:
        cut = text.rfind("\n", 0, size)
        if cut < size // 2:
            cut = text.rfind(" ", 0, size)
        if cut < size // 2:
            cut = size
        out.append(text[:cut])
        text = text[cut:].lstrip()
    out.append(text)
    return out


async def send_text(msg: Message, text: str, reply: bool = False, markup=None):
    parts = chunks(text)
    for i, part in enumerate(parts):
        m = markup if i == len(parts) - 1 else None
        if reply:
            await msg.reply(part, reply_markup=m)
        else:
            await msg.answer(part, reply_markup=m)


async def safe_edit(msg: Message, text: str, reply_markup=None) -> Message:
    """edit_text that survives 'not modified' and photo/audio messages."""
    try:
        return await msg.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as e:
        if "not modified" in str(e).lower():
            return msg
        try:
            await msg.delete()
        except Exception:
            pass
        return await msg.answer(text, reply_markup=reply_markup)


async def safe_delete(m: Message):
    try:
        await m.delete()
    except Exception:
        pass


# ── Buttons / keyboards ──────────────────────────────────────────────────
def btn(text, style, cbd=None, url=None):
    kwargs = {"text": text, "style": style}
    if url:
        kwargs["url"] = url
    else:
        kwargs["callback_data"] = cbd
    return InlineKeyboardButton(**kwargs)


def btn_primary(t, cbd=None, url=None): return btn(t, "primary", cbd=cbd, url=url)
def btn_success(t, cbd=None, url=None): return btn(t, "success", cbd=cbd, url=url)
def btn_danger(t, cbd=None, url=None): return btn(t, "danger", cbd=cbd, url=url)
def powered_btn(): return btn_primary("⚡ NEW UPDATE", url=POWERED_LINK)
def main_bot_btn(): return btn_primary(f"🤖 {MAIN_BOT_NAME}", url=MAIN_BOT_LINK)


def footer(clone: bool):
    rows = []
    if clone:
        rows.append([main_bot_btn()])
    rows.append([powered_btn()])
    return rows


def kb(rows, clone: bool = False, home: bool = True):
    rows = list(rows)
    if home:
        rows.append([btn_primary("🏠 ʜᴏᴍᴇ", cbd="menu_home")])
    return InlineKeyboardMarkup(inline_keyboard=rows + footer(clone))


def foot(clone: bool) -> str:
    return "\n\n⚡ @freee_apis_free" + (f"\n🤖 {MAIN_BOT_USERNAME}" if clone else "")


def box(title: str) -> str:
    return f"╔══════════════════╗\n  {title}\n╚══════════════════╝\n\n"


def main_menu_kb(clone: bool = False, owner: bool = False):
    rows = [
        [btn_primary("🤖 ᴀɪ ᴄʜᴀᴛ", cbd="menu_ai"),
         btn_success("🧰 ᴛᴏᴏʟꜱ", cbd="menu_tools")],
        [btn_primary("🎨 ɪᴍᴀɢᴇ", cbd="menu_image"),
         btn_success("🎙️ ᴠᴏɪᴄᴇ", cbd="menu_voice")],
        [btn_primary("🔊 ᴛᴛꜱ", cbd="menu_tts"),
         btn_success("✨ ᴘʀᴏᴍᴘᴛ", cbd="menu_prompt")],
        [btn_primary("⚙️ ꜱᴇᴛᴛɪɴɢꜱ", cbd="menu_settings"),
         btn_primary("👤 ᴘʀᴏꜰɪʟᴇ", cbd="menu_profile")],
        [btn_success("🎁 ɪɴᴠɪᴛᴇ & ᴇᴀʀɴ", cbd="menu_invite"),
         btn_primary("🏆 ᴛᴏᴘ", cbd="menu_top")],
    ]
    if not clone:
        rows.append([btn_success("🔱 ᴄʟᴏɴᴇ ʙᴏᴛ", cbd="menu_clone")])
    rows.append([btn_primary("❓ ʜᴇʟᴘ", cbd="menu_help"),
                 btn_primary("ℹ️ ᴀʙᴏᴜᴛ", cbd="menu_about")])
    last = [btn_danger("🗑 ᴄʟᴇᴀʀ", cbd="clear_history")]
    if owner:
        last.insert(0, btn_success("📊 ꜱᴛᴀᴛꜱ", cbd="menu_stats"))
    if owner and not clone:
        rows.append([btn_success("👑 ᴀᴅᴍɪɴ ᴘᴀɴᴇʟ", cbd="adm_home")])
    rows.append(last)
    return InlineKeyboardMarkup(inline_keyboard=rows + footer(clone))


def clone_kb(ts):
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn_success("▶️ ꜱᴛᴀʀᴛ", cbd=f"clone_start_{ts}"),
         btn_danger("⏹ ꜱᴛᴏᴘ", cbd=f"clone_stop_{ts}"),
         btn_primary("🔄 ʀᴇꜱᴛᴀʀᴛ", cbd=f"clone_restart_{ts}")],
        [btn_primary("📋 ꜱᴛᴀᴛᴜꜱ", cbd=f"clone_status_{ts}"),
         btn_danger("🗑 ᴅᴇʟᴇᴛᴇ", cbd=f"clone_delete_{ts}")],
        [btn_primary("🏠 ʜᴏᴍᴇ", cbd="menu_home")],
        [powered_btn()],
    ])


def ai_menu_kb(clone):
    return kb([[btn_danger("🗑 ᴄʟᴇᴀʀ ʜɪꜱᴛᴏʀʏ", cbd="clear_history")]], clone)


def ai_reply_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[
        btn_success("🔊 ʟɪꜱᴛᴇɴ", cbd="tts_last"),
        btn_danger("🗑 ᴄʟᴇᴀʀ", cbd="clear_history"),
    ]])


def image_menu_kb(clone):
    return kb([[btn_primary("🎭 ꜱᴛʏʟᴇ", cbd="menu_styles")]], clone)


def image_result_kb(clone):
    return kb([
        [btn_success("🔁 ʀᴇɢᴇɴᴇʀᴀᴛᴇ", cbd="img_regen"),
         btn_primary("🎭 ꜱᴛʏʟᴇ", cbd="menu_styles")],
        [btn_primary("🎨 ɴᴇᴡ ɪᴍᴀɢᴇ", cbd="menu_image")],
    ], clone)


def tts_voices_kb(clone: bool = False):
    rows = []
    for i in range(0, len(TTS_VOICES), 2):
        rows.append([btn_primary(v, cbd=f"ttsv_{v}") for v in TTS_VOICES[i:i + 2]])
    rows.append([btn_danger("❌ ᴄᴀɴᴄᴇʟ", cbd="menu_home")])
    return kb(rows, clone, home=False)


def tts_styles_kb(voice, clone: bool = False):
    rows = []
    for i in range(0, len(TTS_STYLES), 2):
        rows.append([btn_success(s, cbd=f"ttss_{voice}_{s}") for s in TTS_STYLES[i:i + 2]])
    rows.append([btn_primary("⚪ ᴅᴇꜰᴀᴜʟᴛ", cbd=f"ttss_{voice}_none")])
    rows.append([btn_danger("❌ ᴄᴀɴᴄᴇʟ", cbd="menu_home")])
    return kb(rows, clone, home=False)


def prompt_menu_kb(clone: bool = False):
    return kb([[btn_success("🎲 ʀᴀɴᴅᴏᴍ ᴛᴏᴘɪᴄ", cbd="prompt_random")]], clone)


def prompt_result_kb(clone):
    return kb([
        [btn_success("🎨 ɢᴇɴᴇʀᴀᴛᴇ ɪᴍᴀɢᴇ", cbd="useprompt_gen")],
        [btn_primary("🎲 ɴᴇᴡ ᴛᴏᴘɪᴄ", cbd="prompt_random")],
    ], clone)


# ── Modes / languages / styles / tools ───────────────────────────────────
MODES = {
    "funny": ("😂 Funny",
              "Tum ASD ho, ek mast aur funny AI dost. Casual, friendly, short replies. "
              "Natural emojis use karo. Sirf jawab do."),
    "serious": ("🎯 Serious",
                "Tum ASD ho, ek professional, precise aur helpful AI assistant. "
                "Seedha aur clear jawab do, emojis kam."),
    "teacher": ("👨‍🏫 Teacher",
                "Tum ASD ho, ek patient teacher. Cheezein step-by-step, simple examples ke "
                "saath samjhao."),
    "coder": ("💻 Coder",
              "Tum ASD ho, ek expert programmer. Short explanation do aur code hamesha "
              "markdown code block mein likho."),
    "shayar": ("🌹 Shayar",
               "Tum ASD ho, ek romantic shayar. Jawab shayari-style mein, meethe aur "
               "kavyatmak andaaz mein do."),
}
LANGS = {
    "hinglish": ("Hinglish", "Hamesha Hinglish (Roman Hindi) mein jawab do."),
    "hindi": ("हिन्दी", "Hamesha shuddh Hindi (Devanagari) mein jawab do."),
    "english": ("English", "Always reply in simple English."),
}
STYLES = {
    "none": ("⚪ Default", ""),
    "anime": ("🎌 Anime", ", anime style, vibrant colors, detailed illustration"),
    "realistic": ("📷 Realistic", ", photorealistic, DSLR photo, natural lighting, 8k"),
    "3d": ("🧊 3D Render", ", 3D render, soft lighting, highly detailed"),
    "cyberpunk": ("🌆 Cyberpunk", ", cyberpunk, neon lights, futuristic, cinematic"),
    "fantasy": ("🐉 Fantasy", ", epic fantasy art, magical atmosphere, intricate details"),
    "watercolor": ("🎨 Watercolor", ", watercolor painting, soft pastel tones, artistic"),
    "logo": ("✒️ Logo", ", minimal vector logo, flat design, clean background"),
}
TOOLS = {
    "translate": {
        "label": "🌐 ᴛʀᴀɴꜱʟᴀᴛᴇ",
        "ask": "Text bhej. Language chunni ho to aise likh: hindi: your text",
        "system": ("You are a professional translator. If the text starts with "
                   "'<language>:' translate the rest into that language. Otherwise "
                   "translate English to Hindi (Devanagari) and any other language to "
                   "English. Return ONLY the translation."),
        "use_lang": False,
    },
    "summarize": {
        "label": "📝 ꜱᴜᴍᴍᴀʀɪᴢᴇ",
        "ask": "Lamba text bhej, main chhota summary bana dunga",
        "system": ("Summarize the given text in 3-5 short bullet points, in the same "
                   "language as the text. Return only the summary."),
        "use_lang": False,
    },
    "explain": {
        "label": "🧠 ᴇxᴘʟᴀɪɴ",
        "ask": "Koi bhi topic ya sawal likh, simple bhasha mein samjhaunga",
        "system": ("Explain the topic like I'm 10 years old with one simple real-life "
                   "example. Be brief."),
        "use_lang": True,
    },
    "fix": {
        "label": "✍️ ɢʀᴀᴍᴍᴀʀ ꜰɪx",
        "ask": "Text bhej, main grammar aur spelling theek kar dunga",
        "system": ("Correct grammar, spelling and punctuation without changing the "
                   "meaning or language. Return ONLY the corrected text."),
        "use_lang": False,
    },
    "joke": {
        "label": "😂 ᴊᴏᴋᴇ",
        "no_input": True,
        "default": "Ek naya funny joke sunao",
        "system": "You tell short, clean, genuinely funny jokes. Return only the joke.",
        "use_lang": True,
    },
    "shayari": {
        "label": "🌹 ꜱʜᴀʏᴀʀɪ",
        "ask": "Topic likh (jaise: dosti, chai, barish)",
        "default": "koi bhi mast topic",
        "system": ("You are a poet. Write a short 4-line shayari in Hinglish on the "
                   "given topic. Return only the shayari."),
        "use_lang": False,
    },
}
RANDOM_TOPICS = [
    "dragon flying over mountains", "cyberpunk city at night", "cute cat astronaut",
    "magical forest with glowing trees", "futuristic samurai",
    "space station orbiting earth", "underwater city with mermaids",
    "steampunk robot in rain", "sunset beach with palm trees",
    "ancient temple hidden in jungle", "floating islands in the sky",
    "snowy village at christmas night",
]


def settings_kb(clone):
    return kb([
        [btn_primary("🎭 ᴍᴏᴅᴇ", cbd="menu_modes"),
         btn_primary("🌐 ʟᴀɴɢᴜᴀɢᴇ", cbd="menu_langs")],
        [btn_primary("🖼 ɪᴍᴀɢᴇ ꜱᴛʏʟᴇ", cbd="menu_styles"),
         btn_success("✨ ꜰᴀɴᴄʏ ᴛᴇxᴛ", cbd="set_fancy")],
    ], clone)


def choice_kb(prefix, options, current, clone):
    rows, items = [], list(options.items())
    for i in range(0, len(items), 2):
        rows.append([
            btn_success(("✅ " if k == current else "") + v[0], cbd=f"{prefix}{k}")
            for k, v in items[i:i + 2]
        ])
    rows.append([btn_primary("⬅️ ʙᴀᴄᴋ", cbd="menu_settings")])
    return kb(rows, clone)


def tools_kb(clone):
    rows, items = [], list(TOOLS.items())
    for i in range(0, len(items), 2):
        rows.append([btn_primary(v["label"], cbd=f"tool_{k}") for k, v in items[i:i + 2]])
    return kb(rows, clone)


# ── FSM ──────────────────────────────────────────────────────────────────
class ImgStates(StatesGroup):
    waiting_prompt = State()


class TTSStates(StatesGroup):
    waiting_text = State()


class PromptStates(StatesGroup):
    waiting_topic = State()


class ToolStates(StatesGroup):
    waiting_input = State()


class CloneStates(StatesGroup):
    waiting_token = State()


class AdminStates(StatesGroup):
    waiting_price = State()
    waiting_bcast = State()


# ── Preferences / history / quota ────────────────────────────────────────
DEFAULT_PREFS = {"mode": "funny", "lang": "hinglish", "style": "none", "fancy": True}
prefs_cache: dict[int, dict] = {}
banned_ids: set[int] = set()
tracked_at: dict[tuple, float] = {}
last_hit: dict[int, float] = {}


async def get_prefs(uid: int) -> dict:
    if uid in prefs_cache:
        return prefs_cache[uid]
    doc = await dbx(users_col.find_one, {"user_id": uid}) or {}
    p = {k: doc.get(k, v) for k, v in DEFAULT_PREFS.items()}
    if p["mode"] not in MODES: p["mode"] = "funny"
    if p["lang"] not in LANGS: p["lang"] = "hinglish"
    if p["style"] not in STYLES: p["style"] = "none"
    prefs_cache[uid] = p
    return p


async def set_pref(uid: int, key: str, value):
    p = dict(await get_prefs(uid))
    p[key] = value
    prefs_cache[uid] = p
    await dbx(users_col.update_one, {"user_id": uid}, {"$set": {key: value}}, upsert=True)


async def get_doc(uid: int) -> dict:
    return await dbx(history_col.find_one, {"user_id": uid}) or {}


async def set_fields(uid: int, **fields):
    await dbx(history_col.update_one, {"user_id": uid}, {"$set": fields}, upsert=True)


async def has_history(uid: int) -> bool:
    return bool((await get_doc(uid)).get("messages"))


async def track_user(user, src: str = "main"):
    key = (user.id, src)
    t = time.monotonic()
    if t - tracked_at.get(key, 0) < 120:
        return
    tracked_at[key] = t
    await dbx(
        users_col.update_one, {"user_id": user.id},
        {"$set": {"username": user.username, "first_name": user.first_name,
                  "last_updated": now()},
         "$setOnInsert": {"joined": now()},
         "$addToSet": {"bots": src}},
        upsert=True,
    )


# ── Force-join / referral / VIP ──────────────────────────────────────────
main_bot: Bot | None = None            # set in main(); used to check channel membership
force_channels: list[dict] = []        # [{"chat": id, "title": str, "link": url}]
joined_cache: dict[int, float] = {}
pending_ref: dict[int, int] = {}       # new_user_id -> referrer_id (credited after join)
JOIN_CACHE_SECS = 300


def _aware(dt):
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def ref_bonus(count: int) -> int:
    return min(max(count, 0) * REF_BONUS, REF_BONUS_CAP)


async def get_extras(uid: int) -> dict:
    doc = await dbx(users_col.find_one, {"user_id": uid}) or {}
    vip = _aware(doc.get("vip_until"))
    return {"ref_count": doc.get("ref_count", 0),
            "vip": bool(vip and vip > now()), "vip_until": vip}


async def load_force_channels():
    doc = await dbx(settings_col.find_one, {"_id": "force"}) or {}
    force_channels[:] = list(doc.get("channels", []))
    joined_cache.clear()


async def save_force_channels():
    await dbx(settings_col.update_one, {"_id": "force"},
              {"$set": {"channels": force_channels}}, upsert=True)
    joined_cache.clear()


async def missing_channels(uid: int) -> list[dict]:
    """Channels the user has NOT joined. Fails open if a check errors
    (e.g. bot is not admin there) so a bad config never locks everyone out."""
    if not force_channels or main_bot is None or uid == OWNER_ID:
        return []
    t = time.monotonic()
    if t - joined_cache.get(uid, 0) < JOIN_CACHE_SECS:
        return []
    missing = []
    for ch in list(force_channels):
        try:
            m = await main_bot.get_chat_member(ch["chat"], uid)
            ok = m.status in ("member", "administrator", "creator") or (
                m.status == "restricted" and getattr(m, "is_member", False))
            if not ok:
                missing.append(ch)
        except TelegramRetryAfter as e:
            await asyncio.sleep(min(e.retry_after, 3))
        except Exception as e:
            logger.warning("Force-join check failed for %s: %s", ch.get("chat"), e)
    if not missing:
        if len(joined_cache) > 20000:
            joined_cache.clear()
        joined_cache[uid] = t
    return missing


def join_kb(missing: list[dict]):
    rows = [[btn_primary(f"📢 {ch.get('title') or 'Channel'}", url=ch["link"])]
            for ch in missing]
    rows.append([btn_success("✅ ᴊᴏɪɴ ᴋᴀʀ ʟɪʏᴀ", cbd="fs_check")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def join_text(missing: list[dict]) -> str:
    names = "\n".join(f"📢 {ch.get('title') or ch.get('chat')}" for ch in missing)
    return (f"🔒 {sc('Bot use karne ke liye pehle ye channel join karo')}:\n\n{names}\n\n"
            f"{sc('Join karke')} ✅ {sc('button dabao')}")


async def capture_ref(event, user):
    """Remember /start ref_<id> for brand-new users (credited after they join)."""
    if not isinstance(event, Message) or user.id in pending_ref:
        return
    m = re.match(r"^/start(?:@\w+)?\s+ref_(\d+)\s*$", event.text or "")
    if not m:
        return
    ref = int(m.group(1))
    if ref == user.id:
        return
    if await dbx(users_col.find_one, {"user_id": user.id}):
        return  # not a new user
    if not await dbx(users_col.find_one, {"user_id": ref}):
        return
    pending_ref[user.id] = ref


async def credit_pending_ref(user):
    ref = pending_ref.pop(user.id, None)
    if not ref:
        return
    await dbx(users_col.update_one, {"user_id": user.id},
              {"$set": {"ref_by": ref}}, upsert=True)
    res = await dbx(users_col.find_one_and_update, {"user_id": ref},
                    {"$inc": {"ref_count": 1}}, return_document=ReturnDocument.AFTER)
    if not res or main_bot is None:
        return
    n = res.get("ref_count", 1)
    try:
        await main_bot.send_message(
            ref,
            f"🎉 {user.first_name or 'Ek dost'} tere invite link se join hua!\n\n"
            f"👥 Total referrals: {n}\n"
            f"🎁 Tera daily bonus: +{ref_bonus(n)} images & voices\n\n"
            f"/invite se aur dost bula 🚀")
    except Exception:
        pass


async def invite_text(uid: int, clone: bool = False):
    ex = await get_extras(uid)
    n = ex["ref_count"]
    link = f"{MAIN_BOT_LINK}?start=ref_{uid}"
    text = (
        box(f"🎁 {sc('Invite & Earn')} 🎁") +
        f"{sc('Har dost ke join karne par')} +{REF_BONUS} {sc('images & voices roz extra!')}\n\n"
        f"👥 {sc('Tere referrals')}: {n}\n"
        f"🎁 {sc('Current bonus')}: +{ref_bonus(n)} / {sc('roz')} ({sc('max')} +{REF_BONUS_CAP})\n\n"
        f"🔗 {sc('Tera link')}:\n{link}"
    )
    share = ("https://t.me/share/url?url=" + quote(link) + "&text="
             + quote("🤖 Free AI bot: chat, images, voice aur bahut kuch! Try karo 👇"))
    markup = kb([
        [btn_success("📤 ꜱʜᴀʀᴇ ᴋᴀʀᴏ", url=share)],
        [btn_primary("🏆 ʟᴇᴀᴅᴇʀʙᴏᴀʀᴅ", cbd="menu_top")],
    ], clone)
    return text, markup


async def top_text() -> str:
    docs = await dbx(lambda: list(
        users_col.find({"ref_count": {"$gt": 0}},
                       {"first_name": 1, "username": 1, "ref_count": 1})
        .sort("ref_count", -1).limit(10)))
    head = f"🏆 {sc('Top Inviters')}\n\n"
    if not docs:
        return head + sc("Abhi koi nahi! /invite se pehle ban ja 🔥")
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, d in enumerate(docs):
        name = (d.get("first_name") or d.get("username") or "User")[:20]
        mark = medals[i] if i < 3 else f"{i + 1}."
        lines.append(f"{mark} {name} - {d.get('ref_count', 0)}")
    return head + "\n".join(lines) + f"\n\n{sc('Tu bhi invite karke top pe aa')} 👉 /invite"


async def consume_quota(uid: int, kind: str, limit: int) -> bool:
    if uid == OWNER_ID or limit <= 0:
        return True
    ex = await get_extras(uid)
    if ex["vip"]:
        return True
    limit += ref_bonus(ex["ref_count"])
    day = now().strftime("%Y-%m-%d")
    flt = {"user_id": uid, "date": day}
    doc = await dbx(usage_col.find_one_and_update, flt, {"$inc": {kind: 1}},
                    upsert=True, return_document=ReturnDocument.AFTER)
    if doc.get(kind, 0) > limit:
        await dbx(usage_col.update_one, flt, {"$inc": {kind: -1}})
        return False
    return True


async def refund_quota(uid: int, kind: str):
    if uid == OWNER_ID:
        return
    day = now().strftime("%Y-%m-%d")
    await dbx(usage_col.update_one, {"user_id": uid, "date": day}, {"$inc": {kind: -1}})


# ── LLM ──────────────────────────────────────────────────────────────────
AI_ERR = "Bhai, AI server se reply nahi mil raha. Thodi der baad try kar! 😴"


async def llm(messages: list, retries: int = 2) -> str | None:
    payload = {"data": {"messages": messages, "model": "gpt-4o-mini"}}
    for attempt in range(retries + 1):
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.post(LLM_URL, json=payload)
                r.raise_for_status()
                data = r.json()
            ans = ((data.get("result") or {}).get("choices") or [{}])[0] \
                .get("message", {}).get("content", "")
            if ans and ans.strip():
                return ans.strip()
        except (httpx.HTTPError, ValueError, KeyError, IndexError, AttributeError) as e:
            logger.warning("LLM attempt %s failed: %s", attempt + 1, e)
        if attempt < retries:
            await asyncio.sleep(1.5 * (attempt + 1))
    return None


async def get_ai(prompt: str, uid: int) -> str | None:
    doc = await get_doc(uid)
    prefs = await get_prefs(uid)
    history = doc.get("messages", [])
    system = MODES[prefs["mode"]][1] + " " + LANGS[prefs["lang"]][1]
    messages = [{"role": "system", "content": system}]
    for item in history[-10:]:
        if item.get("role") in ("user", "assistant"):
            messages.append({"role": item["role"], "content": item.get("content", "")})
    messages.append({"role": "user", "content": prompt[:2000]})

    answer = await llm(messages)
    if not answer:
        return None
    history.extend([{"role": "user", "content": prompt[:2000]},
                    {"role": "assistant", "content": answer}])
    await set_fields(uid, messages=history[-30:], last_ai_reply=answer, updated=now())
    return answer


PROMPT_SYSTEM = (
    "You are an expert AI image prompt engineer. "
    "User will give a topic, you must return ONE single rich, detailed image prompt in English only. "
    "Include subject, environment, lighting, mood, camera angle, art style, colors, "
    "and quality boosters like 'ultra detailed, 8k, cinematic'. "
    "Return ONLY the prompt, no explanations, no quotes, no prefix. Max 2-3 sentences."
)


async def generate_prompt_with_ai(topic: str) -> str:
    ans = await llm([
        {"role": "system", "content": PROMPT_SYSTEM},
        {"role": "user", "content": f"Topic: {topic}"},
    ])
    if not ans:
        return ""
    ans = ans.strip().strip('"').strip("'").strip()
    for pref in ("prompt:", "image prompt:"):
        if ans.lower().startswith(pref):
            ans = ans[len(pref):].strip()
    return ans


# ── Feature handlers ─────────────────────────────────────────────────────
async def do_image_generation(msg: Message, uid: int, prompt: str, clone: bool = False):
    prompt = prompt.strip()[:1000]
    if not prompt:
        return
    lock = get_lock(uid)
    if lock.locked():
        await send_busy_warning(msg)
        return
    async with lock:
        if not await consume_quota(uid, "image", DAILY_IMAGE_LIMIT):
            await msg.answer(
                q(sc("aaj ki image limit khatam! kal phir aana ya /invite se dost bulao aur limit badhao 🎁")),
                reply_markup=kb([], clone),
            )
            return
        prefs = await get_prefs(uid)
        full_prompt = prompt + STYLES[prefs["style"]][1]
        await set_fields(uid, last_image_req=prompt)
        wait = await msg.answer(q(sc("image ban rahi hai... ⏳ please wait")))
        try:
            async with httpx.AsyncClient(timeout=180) as client:
                resp = await client.post(MEHEDI_API + "/api/public/image",
                                         json={"prompt": full_prompt})
            try:
                data = resp.json()
            except ValueError:
                data = {}
            if not resp.is_success:
                raise RuntimeError(data.get("error") or f"HTTP {resp.status_code}")
            b64 = data.get("image")
            if not b64:
                raise RuntimeError("API ne image nahi di")
            if "," in b64:
                b64 = b64.split(",", 1)[1]
            img = base64.b64decode(b64)

            caption = (
                f"🎨 {sc('Image Ready!')}\n\n"
                f"📝 {sc('Prompt')}: {prompt[:200]}\n"
                f"🎭 {sc('Style')}: {STYLES[prefs['style']][0]}"
                f"{foot(clone)}"
            )
            await msg.answer_photo(
                BufferedInputFile(img, filename="asd-ai-image.png"),
                caption=caption[:1000],
                reply_markup=image_result_kb(clone),
            )
            await safe_delete(wait)
        except Exception as e:
            await refund_quota(uid, "image")
            logger.error("Image gen failed: %s", e)
            try:
                await wait.edit_text(q(sc(f"image nahi bani: {str(e)[:150]}")),
                                     reply_markup=image_menu_kb(clone))
            except Exception:
                pass


async def do_prompt_generation(msg: Message, uid: int, topic: str, clone: bool = False):
    lock = get_lock(uid)
    if lock.locked():
        await send_busy_warning(msg)
        return
    async with lock:
        wait = await msg.answer(q(sc("prompt ban raha hai... ✨")))
        try:
            prompt = await generate_prompt_with_ai(topic[:300])
            if not prompt:
                raise RuntimeError("AI ne prompt nahi banaya")
            await set_fields(uid, last_image_prompt=prompt)
            body = (f"✨ {sc('Prompt Ready!')}\n\n❝ {prompt} ❞\n\n"
                    f"{sc('Isse image banao?')}")
            if clone:
                body += f"\n\n🤖 {MAIN_BOT_USERNAME}"
            await safe_edit(wait, body, prompt_result_kb(clone))
        except Exception as e:
            logger.error("Prompt gen failed: %s", e)
            try:
                await wait.edit_text(q(sc(f"prompt fail: {str(e)[:150]}")),
                                     reply_markup=prompt_menu_kb(clone))
            except Exception:
                pass


def clean_tts_text(text: str) -> str:
    """Strip things TTS engines choke on: code blocks, markdown, URLs, emojis."""
    t = re.sub(r"```.*?```", " ", text, flags=re.S)
    t = re.sub(r"https?://\S+", " ", t)
    t = re.sub(r"[*_`#>~|\[\]{}<>]", " ", t)
    t = re.sub(r"[\U0001F000-\U0001FAFF☀-➿️‍]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t or text.strip()


def parse_tts_response(r) -> bytes:
    ctype = (r.headers.get("content-type") or "").lower()
    if "json" in ctype:
        try:
            data = r.json()
        except Exception:
            data = {}
        b64 = (data.get("audio") or data.get("audio_base64") or data.get("data")
               or data.get("result") or data.get("file") or "")
        if isinstance(b64, dict):
            b64 = b64.get("audio") or b64.get("base64") or ""
        if not (isinstance(b64, str) and b64):
            raise RuntimeError(data.get("error") or data.get("message") or "audio field nahi mila")
        if b64.startswith("data:"):
            b64 = b64.split(",", 1)[1]
        return base64.b64decode(b64)
    return r.content


async def tts_primary(text: str, voice: str, style: str) -> bytes:
    body = {"text": text, "voice": voice}
    if style and style != "none":
        body["style"] = style
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(TTS_API, json=body, headers={
            "Content-Type": "application/json", "Accept": "audio/*,application/json"})
    if not r.is_success:
        err = f"HTTP {r.status_code}"
        try:
            ed = r.json()
            err = ed.get("error") or ed.get("message") or err
        except Exception:
            pass
        raise RuntimeError(err)
    audio = parse_tts_response(r)
    if not audio or len(audio) < 100:
        raise RuntimeError("Empty audio received")
    return audio


def _split_chunks(text: str, limit: int = 180) -> list:
    parts, cur = [], ""
    for sent in re.split(r"(?<=[.!?।\n,;:])\s+", text):
        while len(sent) > limit:                       # very long run without punctuation
            cut = sent.rfind(" ", 0, limit)
            cut = cut if cut > 0 else limit
            if cur:
                parts.append(cur); cur = ""
            parts.append(sent[:cut].strip()); sent = sent[cut:].strip()
        if len(cur) + len(sent) + 1 <= limit:
            cur = f"{cur} {sent}".strip()
        else:
            if cur:
                parts.append(cur)
            cur = sent
    if cur:
        parts.append(cur)
    return [p for p in parts if p.strip()]


async def tts_backup(text: str) -> bytes:
    """Free Google Translate TTS (mp3) as a last-resort engine."""
    lang = "hi" if re.search(r"[ऀ-ॿ]", text) else "en"
    out = b""
    async with httpx.AsyncClient(timeout=30, headers={"User-Agent": "Mozilla/5.0"}) as client:
        for chunk in _split_chunks(text)[:12]:
            r = await client.get("https://translate.google.com/translate_tts", params={
                "ie": "UTF-8", "client": "tw-ob", "tl": lang, "q": chunk})
            if not r.is_success or len(r.content) < 100:
                raise RuntimeError(f"backup HTTP {r.status_code}")
            out += r.content
    return out


async def tts_generate(text: str, voice: str, style: str) -> bytes:
    """Try the main engine with retries / simpler settings, then a backup engine."""
    cleaned = clean_tts_text(text)
    others = [v for v in TTS_VOICES if v != voice]
    attempts = [
        (cleaned, voice, style),
        (cleaned, voice, ""),                       # style sometimes breaks generation
        (cleaned, others[0], ""),                   # other voice
        (cleaned[:400], others[1], ""),             # shorter text, another voice
    ]
    last = None
    for i, (t, v, s) in enumerate(attempts):
        try:
            return await tts_primary(t, v, s)
        except Exception as e:
            last = e
            logger.warning("TTS attempt %d failed: %s", i + 1, e)
            await asyncio.sleep(1.5)
    try:
        audio = await tts_backup(cleaned)
        logger.info("TTS served by backup engine")
        return audio
    except Exception as e2:
        logger.error("TTS backup failed: %s", e2)
        raise RuntimeError(f"{last} (backup bhi fail)")


async def do_tts(msg: Message, uid: int, text: str, voice: str, style: str,
                 clone: bool = False):
    text = text.strip()[:TTS_MAX_CHARS]
    lock = get_lock(uid)
    if lock.locked():
        await send_busy_warning(msg)
        return
    if voice not in TTS_VOICES:
        voice = "Leda"
    async with lock:
        if not await consume_quota(uid, "tts", DAILY_TTS_LIMIT):
            await msg.answer(
                q(sc("aaj ki voice limit khatam! kal phir aana ya /invite se dost bulao aur limit badhao 🎁")),
                reply_markup=kb([], clone),
            )
            return
        wait = await msg.answer(q(sc("voice ban rahi hai... ⏳")))
        try:
            audio_bytes = await tts_generate(text, voice, style)

            filename = "asd-ai-voice.mp3"
            if audio_bytes[:4] == b"RIFF": filename = "asd-ai-voice.wav"
            elif audio_bytes[:4] == b"OggS": filename = "asd-ai-voice.ogg"

            style_display = style if style and style != "none" else "Default"
            caption = (
                f"🔊 {sc('Voice Ready!')}\n\n"
                f"🎤 {sc('Voice')}: {voice}\n"
                f"🎭 {sc('Style')}: {style_display}\n"
                f"📦 {sc('Size')}: {len(audio_bytes) // 1024} KB{foot(clone)}"
            )
            markup = kb([[btn_primary("🔊 ᴀɢᴀɪɴ", cbd="menu_tts")]], clone)
            await safe_delete(wait)
            try:
                await msg.answer_audio(BufferedInputFile(audio_bytes, filename=filename),
                                       title="ASD AI Voice", caption=caption,
                                       reply_markup=markup)
            except TelegramBadRequest:
                await msg.answer_document(BufferedInputFile(audio_bytes, filename=filename),
                                          caption=caption, reply_markup=markup)
        except Exception as e:
            await refund_quota(uid, "tts")
            logger.error("TTS failed: %s", e)
            try:
                await wait.edit_text(q(sc(f"voice nahi bani: {str(e)[:150]}")),
                                     reply_markup=kb([], clone))
            except Exception:
                pass


async def do_transcribe(msg: Message, clone: bool = False):
    uid = msg.from_user.id
    lock = get_lock(uid)
    if lock.locked():
        await send_busy_warning(msg)
        return
    voice = msg.voice or msg.audio
    if voice.file_size and voice.file_size > 20 * 1024 * 1024:
        await msg.answer(q(sc("file 20MB se badi hai, chhoti bhej 🙏")))
        return
    async with lock:
        wait = await msg.answer(q(sc("voice sun raha hoon... 🎙️")))
        try:
            buf = io.BytesIO()
            await msg.bot.download(voice.file_id, destination=buf)
            ext = "ogg" if msg.voice else "mp3"
            mime = "audio/ogg" if msg.voice else "audio/mpeg"
            files = {"file": (f"voice.{ext}", buf.getvalue(), mime)}
            async with httpx.AsyncClient(timeout=180) as client:
                r = await client.post(MEHEDI_API + "/api/public/transcribe", files=files)
            try:
                data = r.json()
            except ValueError:
                data = {}
            if not r.is_success:
                raise RuntimeError(data.get("error") or f"HTTP {r.status_code}")
            text = (data.get("text") or "").strip()
            if not text:
                await wait.edit_text(q(sc("koi baat sunai nahi di! 😅")))
                return

            await set_fields(uid, last_voice_text=text)
            body = (f"🎙️ {sc('Transcription')}:\n\n❝ {text[:3000]} ❞\n\n"
                    f"{sc('AI se jawab chahiye?')}")
            if clone:
                body += f"\n\n🤖 {MAIN_BOT_USERNAME}"
            await safe_edit(wait, body, kb([
                [btn_success("🤖 ᴀꜱᴋ ᴀɪ", cbd=f"ask_ai_{msg.message_id}")],
            ], clone))
        except Exception as e:
            logger.error("STT failed: %s", e)
            try:
                await wait.edit_text(q(sc(f"transcribe fail: {str(e)[:150]}")))
            except Exception:
                pass


async def run_tool(msg: Message, uid: int, tool: str, text: str, clone: bool = False):
    lock = get_lock(uid)
    if lock.locked():
        await send_busy_warning(msg)
        return
    spec = TOOLS[tool]
    async with lock:
        try:
            await msg.bot.send_chat_action(msg.chat.id, "typing")
        except Exception:
            pass
        prefs = await get_prefs(uid)
        system = spec["system"]
        if spec.get("use_lang"):
            system += " " + LANGS[prefs["lang"]][1]
        ans = await llm([
            {"role": "system", "content": system},
            {"role": "user", "content": (text or spec.get("default", ""))[:3000]},
        ])
        if not ans:
            await msg.answer(AI_ERR)
            return
        markup = None
        if spec.get("no_input"):
            markup = kb([[btn_success("🔁 ᴀᴜʀ ꜱᴜɴᴀᴏ", cbd=f"tool_{tool}")]], clone)
        else:
            markup = tools_kb(clone)
        head = f"{spec['label']}\n\n"
        await send_text(msg, head + ans, markup=markup)


# ── Texts ────────────────────────────────────────────────────────────────
async def home_text(user, clone: bool) -> str:
    returning = await has_history(user.id)
    name = user.first_name or "Dost"
    greet = q(sc(f"wapas {name}! 🔥" if returning else f"aye {name}! kya haal! 🔥"))
    t = (f"{greet}\n\n" + box(f"🌟 {sc('ASD AI Bot')} 🌟") +
         f"{sc('Chat • Image • Voice • TTS • Tools')}\n\n")
    if returning:
        t += "🔁 " + sc("Pichli conversation continue!") + "\n"
    if clone:
        t += f"🔗 {sc('Main Bot')}: {MAIN_BOT_USERNAME}\n"
    t += f"👨‍💻 {sc('Dev')}: {CREATOR}\n⚡ @freee_apis_free"
    return t


def help_text(clone: bool) -> str:
    t = (
        box(f"🆘 {sc('Help')} 🆘") +
        f"🤖 {sc('AI Chat')}: {sc('kuch bhi type karo')}\n"
        f"🎨 /image <prompt>\n"
        f"✨ /prompt <topic>\n"
        f"🎙️ {sc('voice message bhejo (speech to text)')}\n"
        f"🔊 /tts <text>\n\n"
        f"🧰 {sc('Tools')}: /translate /summarize /explain /fix /joke /shayari\n"
        f"   {sc('(kisi message pe reply karke bhi chalte hain)')}\n\n"
        f"⚙️ /settings - mode, language, image style\n"
        f"🎁 /invite - dost bulao, extra limit pao\n"
        f"🏆 /top - leaderboard\n"
        f"👤 /profile - tera usage\n"
        f"🗑 /clear - history saaf\n"
        f"🧹 /reset - agar bot atak jaye\n"
    )
    if clone:
        t += f"\n🔗 {sc('Main Bot')}: {MAIN_BOT_USERNAME}"
    else:
        t += f"🔱 /clone <token> - apna bot banao\n\n👑 {sc('Owner')}: /broadcast /stats /ban /unban /addchannel /delchannel /channels /vip /admin /setprice /clonelist /delclone"
    return t


async def settings_text(uid: int) -> str:
    p = await get_prefs(uid)
    return (
        f"⚙️ {sc('Settings')}\n\n"
        f"🎭 {sc('Mode')}: {MODES[p['mode']][0]}\n"
        f"🌐 {sc('Language')}: {LANGS[p['lang']][0]}\n"
        f"🖼 {sc('Image Style')}: {STYLES[p['style']][0]}\n"
        f"✨ {sc('Fancy text')}: {'ON' if p['fancy'] else 'OFF'}"
    )


async def profile_text(user) -> str:
    uid = user.id
    p = await get_prefs(uid)
    udoc = await dbx(users_col.find_one, {"user_id": uid}) or {}
    hdoc = await get_doc(uid)
    day = now().strftime("%Y-%m-%d")
    u = await dbx(usage_col.find_one, {"user_id": uid, "date": day}) or {}
    joined = udoc.get("joined")
    joined_s = joined.strftime("%d %b %Y") if joined else "-"
    ex = await get_extras(uid)
    bonus = ref_bonus(ex["ref_count"])
    unlimited_i = uid == OWNER_ID or DAILY_IMAGE_LIMIT <= 0 or ex["vip"]
    unlimited_t = uid == OWNER_ID or DAILY_TTS_LIMIT <= 0 or ex["vip"]
    return (
        f"👤 {sc('Profile')}\n\n"
        f"🆔 {uid}\n"
        f"📛 {user.first_name or '-'}\n"
        f"📅 {sc('Joined')}: {joined_s}\n"
        f"💬 {sc('Chats')}: {len(hdoc.get('messages', [])) // 2}\n\n"
        f"📊 {sc('Aaj ka usage')}\n"
        f"🎨 {sc('Images')}: {u.get('image', 0)}/{'∞' if unlimited_i else DAILY_IMAGE_LIMIT + bonus}\n"
        f"🔊 {sc('Voices')}: {u.get('tts', 0)}/{'∞' if unlimited_t else DAILY_TTS_LIMIT + bonus}\n\n"
        f"👥 {sc('Referrals')}: {ex['ref_count']} (+{bonus}/{sc('roz')})"
        f"{'  👑 VIP' if ex['vip'] else ''}\n"
        f"🎭 {MODES[p['mode']][0]}  •  🌐 {LANGS[p['lang']][0]}"
    )


async def stats_text() -> str:
    def work():
        day = now().strftime("%Y-%m-%d")
        since = now().replace(hour=0, minute=0, second=0, microsecond=0)
        agg = list(usage_col.aggregate([
            {"$match": {"date": day}},
            {"$group": {"_id": None, "image": {"$sum": "$image"}, "tts": {"$sum": "$tts"}}},
        ]))
        a = agg[0] if agg else {}
        return {
            "users": users_col.count_documents({}),
            "active": users_col.count_documents({"last_updated": {"$gte": since}}),
            "banned": users_col.count_documents({"banned": True}),
            "clones": clones_col.count_documents({}),
            "img": a.get("image", 0), "tts": a.get("tts", 0),
        }
    s = await asyncio.to_thread(work)
    return (
        f"📊 Stats\n\n"
        f"👥 Users: {s['users']}  (aaj active: {s['active']})\n"
        f"🚫 Banned: {s['banned']}\n"
        f"🔱 Clones: {s['clones']}  (running: {len(clone_apps)})\n"
        f"📢 Force-join channels: {len(force_channels)}\n"
        f"🎨 Aaj images: {s['img']}\n"
        f"🔊 Aaj voices: {s['tts']}"
    )


# ── Middleware: ban + anti-spam ──────────────────────────────────────────
class GuardMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if user and user.id != OWNER_ID:
            if user.id in banned_ids:
                if isinstance(event, CallbackQuery):
                    try:
                        await event.answer("🚫 Tum banned ho.", show_alert=True)
                    except Exception:
                        pass
                return
            if isinstance(event, Message):
                t = time.monotonic()
                if t - last_hit.get(user.id, 0) < COOLDOWN:
                    return
                if len(last_hit) > 20000:
                    last_hit.clear()
                last_hit[user.id] = t

            # force-join (private chats only) + referral crediting
            chat = event.chat if isinstance(event, Message) else (
                event.message.chat if isinstance(event, CallbackQuery) and event.message else None)
            if chat is not None and chat.type == "private":
                await capture_ref(event, user)
                missing = await missing_channels(user.id)
                if missing:
                    if isinstance(event, CallbackQuery):
                        if event.data == "fs_check":
                            return await handler(event, data)
                        try:
                            await event.answer("🔒 Pehle channel join karo!", show_alert=True)
                        except Exception:
                            pass
                    else:
                        await event.answer(join_text(missing), reply_markup=join_kb(missing))
                    return
                await credit_pending_ref(user)
        return await handler(event, data)


class Acker:
    """Answers a callback query exactly once."""
    def __init__(self, cb: CallbackQuery):
        self.cb = cb
        self.done = False

    async def __call__(self, text=None, alert=False):
        if self.done:
            return
        self.done = True
        try:
            await self.cb.answer(text, show_alert=alert)
        except Exception:
            pass


# ── Clone runtime ────────────────────────────────────────────────────────
clone_apps: dict[str, tuple[Bot, Dispatcher, asyncio.Task]] = {}

CLONE_COMMANDS = [
    BotCommand(command="start", description="Bot start"),
    BotCommand(command="help", description="Help"),
    BotCommand(command="image", description="AI image banao"),
    BotCommand(command="prompt", description="AI prompt generator"),
    BotCommand(command="tts", description="Text to speech"),
    BotCommand(command="translate", description="Translate"),
    BotCommand(command="summarize", description="Summary"),
    BotCommand(command="explain", description="Simple explain"),
    BotCommand(command="fix", description="Grammar fix"),
    BotCommand(command="joke", description="Joke"),
    BotCommand(command="shayari", description="Shayari"),
    BotCommand(command="settings", description="Mode / language / style"),
    BotCommand(command="profile", description="Mera profile"),
    BotCommand(command="invite", description="Dost bulao, extra limit pao"),
    BotCommand(command="top", description="Top inviters"),
    BotCommand(command="reset", description="Atak gaya? reset"),
    BotCommand(command="clear", description="History clear"),
]
MAIN_COMMANDS = CLONE_COMMANDS + [
    BotCommand(command="clone", description="Clone bot banao"),
    BotCommand(command="myclone", description="Clone manage"),
]
OWNER_COMMANDS = MAIN_COMMANDS + [
    BotCommand(command="broadcast", description="Broadcast (owner)"),
    BotCommand(command="stats", description="Stats (owner)"),
    BotCommand(command="ban", description="Ban user (owner)"),
    BotCommand(command="unban", description="Unban user (owner)"),
    BotCommand(command="addchannel", description="Force-join channel add (owner)"),
    BotCommand(command="delchannel", description="Force-join channel remove (owner)"),
    BotCommand(command="channels", description="Force-join list (owner)"),
    BotCommand(command="vip", description="Give VIP (owner)"),
    BotCommand(command="setprice", description="Clone price set (owner)"),
    BotCommand(command="admin", description="Admin panel (owner)"),
    BotCommand(command="clonelist", description="All clones list (owner)"),
    BotCommand(command="delclone", description="Delete a clone (owner)"),
]


async def run_clone(ts: str, cbot: Bot, cdp: Dispatcher):
    try:
        await cdp.start_polling(cbot, handle_signals=False)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error("Clone %s crashed: %s", ts, e)
        await dbx(clones_col.update_one, {"token_short": ts},
                  {"$set": {"status": "error", "error": str(e)}})
    finally:
        cur = clone_apps.get(ts)
        if cur and cur[1] is cdp:
            clone_apps.pop(ts, None)


async def start_clone_bot(token: str, owner_id: int) -> bool:
    ts = token.split(":")[0]
    if ts in clone_apps:
        return True
    try:
        cbot = Bot(token=token, default=DefaultBotProperties())
        cdp = Dispatcher(storage=MemoryStorage())
        cdp.include_router(build_router(clone=True))
        await cbot.delete_webhook(drop_pending_updates=True)
        try:
            await cbot.set_my_commands(CLONE_COMMANDS)
        except Exception:
            pass
        task = asyncio.create_task(run_clone(ts, cbot, cdp))
        clone_apps[ts] = (cbot, cdp, task)
        await dbx(clones_col.update_one, {"token_short": ts},
                  {"$set": {"status": "running", "last_started": now()},
                   "$unset": {"error": ""}})
        logger.info("Clone started: %s", ts)
        return True
    except Exception as e:
        logger.error("Clone failed %s: %s", ts, e)
        await dbx(clones_col.update_one, {"token_short": ts},
                  {"$set": {"status": "error", "error": str(e)}})
        return False


async def stop_clone(ts: str) -> bool:
    entry = clone_apps.pop(ts, None)
    if not entry:
        return False
    cbot, cdp, task = entry
    try:
        await cdp.stop_polling()
    except Exception:
        pass
    try:
        await asyncio.wait_for(task, timeout=10)
    except Exception:
        task.cancel()
    try:
        await cbot.session.close()
    except Exception:
        pass
    return True


async def load_clones():
    docs = await dbx(lambda: list(clones_col.find({"status": {"$in": ["running", "starting"]}})))
    await asyncio.gather(*[start_clone_bot(d["token"], d["owner_id"]) for d in docs],
                         return_exceptions=True)
    logger.info("Loaded %s clones from DB", len(docs))


async def _clone_panel(target: Message, clone_doc: dict, edit: bool = False):
    ts = clone_doc["token_short"]
    running = ts in clone_apps
    text = (
        f"🔱 {sc('My Clone')}\n\n"
        f"🤖 @{clone_doc.get('bot_username', 'N/A')}\n"
        f"📛 {clone_doc.get('bot_name', 'N/A')}\n"
        f"🆔 {ts}\n"
        f"{'🟢 Running' if running else '🔴 Stopped'}\n\n"
        f"⚡ @freee_apis_free"
    )
    if edit:
        await safe_edit(target, text, clone_kb(ts))
    else:
        await target.answer(text, reply_markup=clone_kb(ts))


# ── Paid clone: price, orders, online / screenshot payment ───────────────
FAM_PAID = {"success", "paid", "completed", "complete", "confirmed", "captured",
            "verified", "approved"}
FAM_DEAD = {"expired", "failed", "cancelled", "canceled", "timeout", "timed_out",
            "declined"}
bg_tasks: set = set()


def spawn(coro):
    t = asyncio.create_task(coro)
    bg_tasks.add(t)
    t.add_done_callback(bg_tasks.discard)
    return t


async def get_clone_settings() -> dict:
    doc = await dbx(settings_col.find_one, {"_id": "clone"}) or {}
    return {"price": int(doc.get("price", CLONE_PRICE)),
            "auto_approve": bool(doc.get("auto_approve", False))}


async def set_clone_setting(key: str, value):
    await dbx(settings_col.update_one, {"_id": "clone"}, {"$set": {key: value}}, upsert=True)


async def notify(uid: int, text: str, markup=None):
    if main_bot is None:
        return
    try:
        await main_bot.send_message(uid, text, reply_markup=markup)
    except Exception as e:
        logger.warning("notify %s failed: %s", uid, e)


def admin_pay_kb(oid: str):
    return InlineKeyboardMarkup(inline_keyboard=[[
        btn_success("✅ Approve", cbd=f"cpa_ok_{oid}"),
        btn_danger("❌ Reject", cbd=f"cpa_no_{oid}")]])


async def fam_create_order(amount):
    if not FAM_API_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(
                FAM_CREATE_URL,
                headers={"Authorization": f"Bearer {FAM_API_KEY}",
                         "Content-Type": "application/json"},
                json={"amount": round(float(amount), 2), "redirect_url": "https://t.me/"})
        data = r.json()
        if data.get("status") == "success":
            return data.get("data")
        logger.warning("FAM create failed: %s", data)
    except Exception as e:
        logger.error("FAM create error: %s", e)
    return None


async def fam_status(order_id: str):
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(FAM_STATUS_URL, params={"order_id": order_id})
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        logger.warning("FAM status error: %s", e)
    return None


def fam_state(sd) -> str:
    """'paid' | 'dead' | 'pending' | 'unknown'"""
    if not isinstance(sd, dict):
        return "unknown"
    block = sd.get("data") if isinstance(sd.get("data"), dict) else sd
    for k in ("payment_status", "order_status", "status", "state"):
        v = block.get(k)
        if v:
            v = str(v).strip().lower()
            if v in FAM_PAID:
                return "paid"
            if v in FAM_DEAD:
                return "dead"
    return "pending"


async def finalize_clone(order: dict) -> bool:
    """Create + start the clone for a PAID/approved order."""
    uid, token = order["user_id"], order["token"]
    ts = token.split(":")[0]
    dup = await dbx(clones_col.find_one, {"$or": [{"owner_id": uid}, {"token": token}]})
    if dup:
        await notify(uid, f"⚠️ Clone pehle se hai ya ye token already use ho raha hai.\n"
                          f"Payment ka issue ho to {CREATOR} se contact karo (order {order['_id']}).")
        await notify(OWNER_ID, f"⚠️ Duplicate clone, refund check karo: user {uid}, "
                               f"order {order['_id']}, ₹{order.get('amount')}")
        return False
    await dbx(clones_col.insert_one, {
        "owner_id": uid, "owner_username": order.get("username"),
        "token": token, "token_short": ts,
        "bot_username": order.get("bot_username"), "bot_name": order.get("bot_name"),
        "status": "stopped", "created": now(), "paid": order.get("amount", 0),
    })
    ok = await start_clone_bot(token, uid)
    await dbx(orders_col.update_one, {"_id": order["_id"]}, {"$set": {"clone_ts": ts}})
    await notify(
        uid,
        f"{'✅' if ok else '⚠️'} {sc('Clone Ready!' if ok else 'Clone bana par start nahi hua')}\n\n"
        f"🤖 @{order.get('bot_username')}\n📛 {order.get('bot_name')}\n🆔 {ts}\n\n"
        f"⚡ @freee_apis_free",
        clone_kb(ts))
    if uid != OWNER_ID:
        await notify(OWNER_ID, f"🔱 New clone @{order.get('bot_username')} | user {uid} "
                               f"| {order.get('method', '-')} | ₹{order.get('amount')}")
    return ok


async def delete_qr(order: dict):
    mid = order.get("qr_msg_id")
    if mid and main_bot is not None:
        try:
            await main_bot.delete_message(order["user_id"], mid)
        except Exception:
            pass


async def complete_online(oid: str):
    """Payment verified automatically -> send to admin for approve/reject
    (or create directly when auto-approve is ON)."""
    order = await dbx(orders_col.find_one_and_update,
                      {"_id": oid, "status": "awaiting_online"},
                      {"$set": {"status": "paid", "paid_at": now()}},
                      return_document=ReturnDocument.AFTER)
    if not order:
        return
    await delete_qr(order)
    uid = order["user_id"]
    cfg = await get_clone_settings()
    if cfg["auto_approve"] or uid == OWNER_ID:
        await dbx(orders_col.update_one, {"_id": oid}, {"$set": {"status": "approved"}})
        await notify(uid, f"✅ {sc('Payment mil gaya! clone ban raha hai...')}")
        await finalize_clone(order)
        return
    await dbx(orders_col.update_one, {"_id": oid}, {"$set": {"status": "pending_admin"}})
    await notify(uid, f"✅ {sc('Payment verify ho gaya!')}\n⏳ "
                      f"{sc('Admin approval ka wait kar, approve hote hi clone ban jayega')}")
    await notify(
        OWNER_ID,
        f"💸 Payment verified - clone approval\n\n"
        f"👤 {order.get('first_name') or '-'} (@{order.get('username') or '-'})\n🆔 {uid}\n"
        f"🤖 @{order.get('bot_username')}\n💰 ₹{order.get('amount')}\n"
        f"🧾 Order: {oid}\n🏦 Gateway: {order.get('fam_order_id')}",
        admin_pay_kb(oid))


async def monitor_clone_payment(oid: str, fam_id: str, timeout: float = PAY_TIMEOUT):
    deadline = time.monotonic() + timeout
    st = "unknown"
    while time.monotonic() < deadline:
        st = fam_state(await fam_status(fam_id))
        if st == "paid":
            await complete_online(oid)
            return
        if st == "dead":
            break
        await asyncio.sleep(PAY_CHECK_INTERVAL)
    if st != "dead" and fam_state(await fam_status(fam_id)) == "paid":
        await complete_online(oid)
        return
    order = await dbx(orders_col.find_one_and_update,
                      {"_id": oid, "status": "awaiting_online"},
                      {"$set": {"status": "expired"}})
    if order:
        await delete_qr(order)
        await notify(order["user_id"],
                     q(sc("QR expire ho gaya (5 min), payment nahi mila. /clone se naya QR le. "
                          f"paisa kat gaya ho to {CREATOR} se contact kar")))


async def resume_payment_monitors():
    """After a restart: resume live payments, expire stale ones + delete their QR."""
    since = now() - timedelta(seconds=PAY_TIMEOUT)
    docs = await dbx(lambda: list(orders_col.find({"status": "awaiting_online"})))
    for d in docs:
        started = _aware(d.get("online_started"))
        left = PAY_TIMEOUT - (now() - started).total_seconds() if started else 0
        if d.get("fam_order_id") and started and started >= since:
            spawn(monitor_clone_payment(d["_id"], d["fam_order_id"], max(left, 20)))
        else:
            spawn(monitor_clone_payment(d["_id"], d.get("fam_order_id") or "-", 0))


async def send_payment_qr(wait: Message, order: dict, fam: dict):
    amount = fam.get("amount", order["amount"])
    cap = (f"💳 ₹{amount}\n🆔 {fam['order_id']}\n\n"
           f"📲 {sc('QR scan karke pay karo')}\n"
           f"⏳ {sc('Payment auto-verify hoga. 5 min baad QR delete ho jayega')}")
    sent = None
    qr_url = fam.get("qr_url")
    if qr_url:
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                resp = await c.get(qr_url)
            if resp.status_code == 200 and resp.content:
                sent = await wait.answer_photo(
                    BufferedInputFile(resp.content, filename="pay-qr.png"), caption=cap)
        except Exception as e:
            logger.warning("QR download/send failed: %s", e)
    if sent is None:
        sent = await wait.answer(cap + (f"\n\n🔗 {qr_url}" if qr_url else ""))
    await dbx(orders_col.update_one, {"_id": order["_id"]}, {"$set": {"qr_msg_id": sent.message_id}})
    await safe_delete(wait)
    spawn(monitor_clone_payment(order["_id"], fam["order_id"]))


async def clone_intro(price: int):
    text = (f"🔱 {sc('Clone Bot')}\n\n"
            f"1️⃣ @BotFather {sc('se apna bot banao aur token copy karo')}\n"
            f"2️⃣ {sc('Token yahin bhej do')}\n"
            f"3️⃣ " + (f"₹{price} {sc('ka QR aayega, pay karo, auto-verify hoga')}\n"
                       f"4️⃣ {sc('Admin approve karega to clone ban jayega')}"
                       if price > 0 else sc("free hai, turant ban jayega")))
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [btn_success("🤖 @ʙᴏᴛꜰᴀᴛʜᴇʀ", url="https://t.me/BotFather")],
        [btn_danger("❌ ᴄᴀɴᴄᴇʟ", cbd="menu_home")],
        [powered_btn()],
    ])
    return text, markup


async def process_clone_token(msg: Message, token: str):
    uid = msg.from_user.id
    await safe_delete(msg)  # the token is a secret -> remove it from chat
    if await dbx(clones_col.find_one, {"owner_id": uid}):
        await msg.answer(q(sc("tera clone pehle se hai! /myclone")))
        return
    if await dbx(clones_col.find_one, {"token": token}):
        await msg.answer(q(sc("ye token le liya kisi ne!")))
        return
    since = now() - timedelta(seconds=PAY_TIMEOUT + 30)
    if await dbx(orders_col.find_one, {"user_id": uid, "$or": [
            {"status": "pending_admin"},
            {"status": "awaiting_online", "online_started": {"$gte": since}}]}):
        await msg.answer(q(sc("tera pehla payment abhi process mein hai, wait kar ⏳")))
        return
    wait = await msg.answer(q(sc("token verify ho raha hai... ⏳")))
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            resp = await c.get(f"https://api.telegram.org/bot{token}/getMe")
        data = resp.json()
        if not data.get("ok"):
            await wait.edit_text(q(sc("token fail! sahi token bhej")))
            return
        info = data["result"]
    except Exception:
        await wait.edit_text(q(sc("token verify fail! thodi der baad try kar")))
        return
    price = (await get_clone_settings())["price"]
    order = {
        "_id": uuid.uuid4().hex[:12], "user_id": uid,
        "username": msg.from_user.username, "first_name": msg.from_user.first_name,
        "token": token, "bot_username": info.get("username"),
        "bot_name": info.get("first_name"), "amount": price,
        "status": "awaiting_online", "method": "online", "created": now(),
    }
    if uid == OWNER_ID or price <= 0:
        order["method"] = "free"
        await safe_delete(wait)
        await finalize_clone(order)
        return
    if not FAM_API_KEY:
        await wait.edit_text(q(sc(f"payment gateway set nahi hai. {CREATOR} se contact kar")))
        return
    fam = await fam_create_order(price)
    if not fam or not fam.get("order_id"):
        await wait.edit_text(q(sc("payment gateway abhi kaam nahi kar raha, thodi der baad try kar")))
        return
    order["fam_order_id"] = fam["order_id"]
    order["online_started"] = now()
    await dbx(orders_col.insert_one, order)
    await send_payment_qr(wait, order, fam)


# ── Admin panel ──────────────────────────────────────────────────────────
def admin_kb(price: int, auto: bool, pend: int):
    rows = [
        [btn_primary("📋 ᴄʟᴏɴᴇ ʟɪꜱᴛ", cbd="adm_clones"),
         btn_success(f"⏳ ᴘᴇɴᴅɪɴɢ ({pend})", cbd="adm_pending")],
        [btn_primary(f"💰 ᴘʀɪᴄᴇ: ₹{price}", cbd="adm_price"),
         btn_success(f"🔁 ᴀᴜᴛᴏ-ᴀᴘᴘʀᴏᴠᴇ: {'ON' if auto else 'OFF'}", cbd="adm_auto")],
        [btn_primary("📊 ꜱᴛᴀᴛꜱ", cbd="menu_stats"),
         btn_primary("📢 ᴄʜᴀɴɴᴇʟꜱ", cbd="adm_channels")],
        [btn_success("📣 ʙʀᴏᴀᴅᴄᴀꜱᴛ", cbd="adm_bcast"),
         btn_primary("ℹ️ ᴄᴏᴍᴍᴀɴᴅꜱ", cbd="adm_cmds")],
        [btn_primary("🏠 ʜᴏᴍᴇ", cbd="menu_home")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows + [[powered_btn()]])


async def admin_panel():
    cfg = await get_clone_settings()
    pend = await dbx(orders_col.count_documents, {"status": "pending_admin"})
    total = await dbx(clones_col.count_documents, {})
    text = (f"👑 Admin Panel\n\n"
            f"💰 Clone price: ₹{cfg['price']}\n"
            f"🔁 Auto-approve: {'ON' if cfg['auto_approve'] else 'OFF (har clone pe approval)'}\n"
            f"🔱 Clones: {total} (running: {len(clone_apps)})\n"
            f"⏳ Pending approvals: {pend}")
    return text, admin_kb(cfg["price"], cfg["auto_approve"], pend)


def admin_back_kb(target: str = "adm_home"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn_primary("⬅️ ʙᴀᴄᴋ", cbd=target)], [powered_btn()]])


def price_kb():
    rows = [
        [btn_danger("➖5", cbd="adm_p_-5"), btn_danger("➖1", cbd="adm_p_-1"),
         btn_success("➕1", cbd="adm_p_1"), btn_success("➕5", cbd="adm_p_5"),
         btn_success("➕10", cbd="adm_p_10")],
        [btn_primary("✏️ ᴄᴜꜱᴛᴏᴍ", cbd="adm_pset"), btn_primary("🆓 ꜰʀᴇᴇ", cbd="adm_pfree")],
        [btn_primary("⬅️ ʙᴀᴄᴋ", cbd="adm_home")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows + [[powered_btn()]])


async def price_view():
    cfg = await get_clone_settings()
    return f"💰 Clone price: ₹{cfg['price']}\n\nBadalne ke liye button dabao:", price_kb()


async def clones_list_view():
    docs = await dbx(lambda: list(clones_col.find({}).sort("created", -1).limit(60)))
    if not docs:
        return "🔱 Koi clone nahi bana abhi.", admin_back_kb()
    rows = []
    for d in docs:
        ts = d.get("token_short")
        rows.append([btn_primary(
            f"{'🟢' if ts in clone_apps else '🔴'} @{d.get('bot_username', '?')} • {d.get('owner_id')}",
            cbd=f"adm_c_{ts}")])
    rows.append([btn_primary("⬅️ ʙᴀᴄᴋ", cbd="adm_home")])
    return (f"🔱 Clones ({len(docs)}) | running: {len(clone_apps)}\n\nKisi pe tap karo:",
            InlineKeyboardMarkup(inline_keyboard=rows + [[powered_btn()]]))


async def clone_detail_view(ts: str):
    d = await dbx(clones_col.find_one, {"token_short": ts})
    if not d:
        return None
    running = ts in clone_apps
    text = (f"🔱 Clone\n\n🤖 @{d.get('bot_username', '?')}\n📛 {d.get('bot_name', '-')}\n"
            f"👤 {d.get('owner_id')} (@{d.get('owner_username') or '-'})\n"
            f"💰 Paid: ₹{d.get('paid', 0)}\n🆔 {ts}\n"
            f"{'🟢 Running' if running else '🔴 Stopped'}")
    rows = [
        [btn_success("▶️ ꜱᴛᴀʀᴛ", cbd=f"adm_ca_start_{ts}"),
         btn_danger("⏹ ꜱᴛᴏᴘ", cbd=f"adm_ca_stop_{ts}"),
         btn_primary("🔄 ʀᴇꜱᴛᴀʀᴛ", cbd=f"adm_ca_restart_{ts}")],
        [btn_danger("🗑 ᴅᴇʟᴇᴛᴇ", cbd=f"adm_ca_del_{ts}")],
        [btn_primary("⬅️ ʟɪꜱᴛ", cbd="adm_clones")],
    ]
    return text, InlineKeyboardMarkup(inline_keyboard=rows + [[powered_btn()]])


async def pending_view():
    docs = await dbx(lambda: list(orders_col.find({"status": "pending_admin"}).sort("created", 1).limit(20)))
    if not docs:
        return "⏳ Koi pending approval nahi ✅", admin_back_kb()
    lines, rows = [], []
    for i, d in enumerate(docs, 1):
        lines.append(f"{i}. @{d.get('bot_username')} | 👤 {d['user_id']} "
                     f"(@{d.get('username') or '-'}) | ₹{d.get('amount')}")
        rows.append([btn_success(f"✅ {i}", cbd=f"cpa_ok_{d['_id']}"),
                     btn_danger(f"❌ {i}", cbd=f"cpa_no_{d['_id']}")])
    rows.append([btn_primary("⬅️ ʙᴀᴄᴋ", cbd="adm_home")])
    return ("⏳ Pending approvals (payment verified):\n\n" + "\n".join(lines),
            InlineKeyboardMarkup(inline_keyboard=rows + [[powered_btn()]]))


async def run_broadcast(msg: Message, text: str):
    bcast = f"📢 Broadcast\n━━━━━━━━━\n\n{text}\n\n⚡ @freee_apis_free"
    markup = InlineKeyboardMarkup(inline_keyboard=[[powered_btn()]])
    query = {"$and": [{"banned": {"$ne": True}},
                      {"$or": [{"bots": "main"}, {"bots": {"$exists": False}}]}]}
    ids = await dbx(lambda: [u["user_id"] for u in users_col.find(query, {"user_id": 1})])
    status = await msg.answer(f"📢 {len(ids)} users ko bhej raha hoon...")
    sent = failed = 0
    for target in ids:
        try:
            await msg.bot.send_message(target, bcast, reply_markup=markup)
            sent += 1
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            try:
                await msg.bot.send_message(target, bcast, reply_markup=markup)
                sent += 1
            except Exception:
                failed += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)
    await status.edit_text(f"✅ Sent: {sent}, Failed: {failed}")


# ── Router factory: ONE set of handlers for main bot AND clones ──────────
def build_router(clone: bool = False) -> Router:
    r = Router()
    guard = GuardMiddleware()
    r.message.outer_middleware(guard)
    r.callback_query.outer_middleware(guard)
    src = "clone" if clone else "main"
    NOT_CMD = F.text & ~F.text.startswith("/")

    @r.errors()
    async def on_error(event: ErrorEvent):
        logger.error("Unhandled error: %s", event.exception, exc_info=event.exception)
        return True

    # ── basic commands ──
    @r.message(CommandStart())
    async def cmd_start(msg: Message, state: FSMContext):
        if not msg.from_user:
            return
        await state.clear()
        await track_user(msg.from_user, src)
        if msg.chat.type != "private":
            name = msg.from_user.first_name or "Dost"
            await msg.reply(q(sc(f"kya scene hai {name}! 😎")))
            return
        await msg.answer(await home_text(msg.from_user, clone),
                         reply_markup=main_menu_kb(clone, msg.from_user.id == OWNER_ID))

    @r.message(Command("help"))
    async def cmd_help(msg: Message):
        await msg.answer(help_text(clone), reply_markup=kb([], clone) if msg.chat.type == "private" else None)

    @r.message(Command("reset"))
    async def cmd_reset(msg: Message, state: FSMContext):
        await state.clear()
        # drop the lock object: a running task keeps its own reference and
        # releases it normally, new requests get a fresh lock
        user_locks.pop(msg.from_user.id, None)
        await msg.answer(q(sc("reset ho gaya! fresh se try kar 🔄")), reply_markup=kb([], clone))

    @r.message(Command("clear"))
    async def cmd_clear(msg: Message):
        await dbx(history_col.delete_one, {"user_id": msg.from_user.id})
        await msg.answer(q(sc("done! history saaf 🗑️")), reply_markup=kb([], clone))

    @r.message(Command("settings"))
    async def cmd_settings(msg: Message):
        await msg.answer(await settings_text(msg.from_user.id), reply_markup=settings_kb(clone))

    @r.message(Command("profile"))
    async def cmd_profile(msg: Message):
        await msg.answer(await profile_text(msg.from_user), reply_markup=kb([], clone))

    @r.callback_query(F.data == "fs_check")
    async def fs_check(cb: CallbackQuery):
        uid = cb.from_user.id
        missing = await missing_channels(uid)
        if missing:
            try:
                await cb.answer(sc("Abhi sab channel join nahi kiye!"), show_alert=True)
            except Exception:
                pass
            return
        try:
            await cb.answer("✅")
        except Exception:
            pass
        if isinstance(cb.message, Message):
            await safe_edit(cb.message, await home_text(cb.from_user, clone),
                            main_menu_kb(clone, uid == OWNER_ID))

    @r.message(Command("invite"))
    async def cmd_invite(msg: Message):
        text, markup = await invite_text(msg.from_user.id, clone)
        await msg.answer(text, reply_markup=markup)

    @r.message(Command("top"))
    async def cmd_top(msg: Message):
        await msg.answer(await top_text(), reply_markup=kb([], clone))

    # ── prompt / image / tts ──
    @r.message(Command("prompt"))
    async def cmd_prompt(msg: Message, command: CommandObject, state: FSMContext):
        if msg.chat.type != "private":
            await msg.reply(q(sc("prompt gen bhai DM mein! ✨")))
            return
        topic = (command.args or "").strip()
        if not topic:
            await state.set_state(PromptStates.waiting_topic)
            await msg.answer(
                box(f"✨ {sc('Prompt Generator')} ✨") +
                f"{sc('Topic likh, AI mast prompt banayega!')}\n\n"
                f"📝 {sc('Example')}:\n• {sc('dragon in space')}\n"
                f"• {sc('cute cat with sunglasses')}{foot(clone)}",
                reply_markup=prompt_menu_kb(clone),
            )
            return
        await do_prompt_generation(msg, msg.from_user.id, topic, clone)

    @r.message(Command("image", "imagine"))
    async def cmd_image(msg: Message, command: CommandObject, state: FSMContext):
        if msg.chat.type != "private":
            await msg.reply(q(sc("image gen bhai DM mein! 🎨")))
            return
        if is_busy(msg.from_user.id):
            await send_busy_warning(msg)
            return
        prompt = (command.args or "").strip()
        if not prompt:
            await state.set_state(ImgStates.waiting_prompt)
            p = await get_prefs(msg.from_user.id)
            await msg.answer(
                box(f"🎨 {sc('Image Gen')} 🎨") +
                f"{sc('Bhai prompt likh, kya banana hai?')}\n\n"
                f"🎭 {sc('Style')}: {STYLES[p['style']][0]}\n"
                f"💡 {sc('Tip')}: /prompt {sc('se AI prompt banwao!')}{foot(clone)}",
                reply_markup=image_menu_kb(clone),
            )
            return
        await do_image_generation(msg, msg.from_user.id, prompt, clone)

    @r.message(Command("tts"))
    async def cmd_tts(msg: Message, command: CommandObject, state: FSMContext):
        if msg.chat.type != "private":
            await msg.reply(q(sc("tts bhai DM mein! 🔊")))
            return
        if is_busy(msg.from_user.id):
            await send_busy_warning(msg)
            return
        text = (command.args or "").strip()
        if not text and msg.reply_to_message:
            text = (msg.reply_to_message.text or "").strip()
        if not text:
            await state.set_state(TTSStates.waiting_text)
            await msg.answer(
                box(f"🔊 {sc('Text to Speech')} 🔊") +
                f"{sc('Bhai jo bolna hai likh!')} ({TTS_MAX_CHARS} {sc('chars tak')}){foot(clone)}",
                reply_markup=tts_voices_kb(clone),
            )
            return
        await set_fields(msg.from_user.id, tts_text=text[:TTS_MAX_CHARS])
        await msg.answer(q(sc("achha! ab voice chun le 🔊")), reply_markup=tts_voices_kb(clone))

    # ── AI tools (/translate /summarize /explain /fix /joke /shayari) ──
    @r.message(Command(*TOOLS.keys()))
    async def cmd_tool(msg: Message, command: CommandObject, state: FSMContext):
        if not msg.from_user:
            return
        tool = command.command.lower()
        arg = (command.args or "").strip()
        if not arg and msg.reply_to_message:
            arg = (msg.reply_to_message.text or msg.reply_to_message.caption or "").strip()
        spec = TOOLS[tool]
        if arg or spec.get("default"):
            await run_tool(msg, msg.from_user.id, tool, arg, clone)
            return
        await state.set_state(ToolStates.waiting_input)
        await state.update_data(tool=tool)
        await msg.answer(f"{spec['label']}\n\n{sc(spec['ask'])}", reply_markup=kb([], clone))

    @r.message(ToolStates.waiting_input, NOT_CMD)
    async def tool_input(msg: Message, state: FSMContext):
        data = await state.get_data()
        await state.clear()
        tool = data.get("tool")
        if tool in TOOLS:
            await run_tool(msg, msg.from_user.id, tool, msg.text.strip(), clone)

    # ── STT ──
    @r.message(F.voice | F.audio)
    async def handle_voice(msg: Message):
        if msg.chat.type != "private" or not msg.from_user:
            return
        await track_user(msg.from_user, src)
        await do_transcribe(msg, clone)

    # ── FSM text inputs ──
    @r.message(ImgStates.waiting_prompt, NOT_CMD)
    async def img_prompt_received(msg: Message, state: FSMContext):
        await state.clear()
        await do_image_generation(msg, msg.from_user.id, msg.text.strip(), clone)

    @r.message(TTSStates.waiting_text, NOT_CMD)
    async def tts_text_received(msg: Message, state: FSMContext):
        await state.clear()
        await set_fields(msg.from_user.id, tts_text=msg.text.strip()[:TTS_MAX_CHARS])
        await msg.answer(q(sc("achha! ab voice chun le 🔊")), reply_markup=tts_voices_kb(clone))

    @r.message(PromptStates.waiting_topic, NOT_CMD)
    async def prompt_topic_received(msg: Message, state: FSMContext):
        await state.clear()
        await do_prompt_generation(msg, msg.from_user.id, msg.text.strip(), clone)

    # ── main-bot only: clone / owner commands ──
    if not clone:
        @r.message(Command("clone"))
        async def cmd_clone(msg: Message, command: CommandObject, state: FSMContext):
            if msg.chat.type != "private":
                await msg.reply(q(sc("DM mein aa bhai! 🔱")))
                return
            token = (command.args or "").strip()
            if token:
                await state.clear()
                if not TOKEN_RE.match(token):
                    await safe_delete(msg)
                    await msg.answer(q(sc("token galat hai!")))
                    return
                await process_clone_token(msg, token)
                return
            doc = await dbx(clones_col.find_one, {"owner_id": msg.from_user.id})
            if doc:
                await _clone_panel(msg, doc, edit=False)
                return
            await state.set_state(CloneStates.waiting_token)
            text, markup = await clone_intro((await get_clone_settings())["price"])
            await msg.answer(text, reply_markup=markup)

        @r.message(CloneStates.waiting_token, NOT_CMD)
        async def clone_token_received(msg: Message, state: FSMContext):
            token = (msg.text or "").strip()
            if not TOKEN_RE.match(token):
                await msg.answer(q(sc("ye token jaisa nahi lag raha. @BotFather wala sahi token bhej "
                                      "ya /start se cancel kar")))
                return
            await state.clear()
            await process_clone_token(msg, token)

        @r.message(Command("myclone"))
        async def cmd_myclone(msg: Message):
            if msg.chat.type != "private":
                return
            doc = await dbx(clones_col.find_one, {"owner_id": msg.from_user.id})
            if not doc:
                await msg.answer(
                    q(sc("tera koi clone nahi! /clone se bana")),
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [btn_success("🔱 ᴄʟᴏɴᴇ ʙᴀɴᴀᴏ", cbd="menu_clone")],
                        [powered_btn()],
                    ]),
                )
                return
            await _clone_panel(msg, doc, edit=False)

        @r.message(Command("broadcast"))
        async def cmd_broadcast(msg: Message, command: CommandObject):
            if msg.from_user.id != OWNER_ID:
                return
            text = (command.args or "").strip()
            if not text and msg.reply_to_message:
                text = (msg.reply_to_message.text or "").strip()
            if not text:
                await msg.reply("Use: /broadcast <text>  (ya kisi message pe reply karke)")
                return
            bcast = f"📢 Broadcast\n━━━━━━━━━\n\n{text}\n\n⚡ @freee_apis_free"
            markup = InlineKeyboardMarkup(inline_keyboard=[[powered_btn()]])
            query = {"$and": [{"banned": {"$ne": True}},
                              {"$or": [{"bots": "main"}, {"bots": {"$exists": False}}]}]}
            ids = await dbx(lambda: [u["user_id"] for u in users_col.find(query, {"user_id": 1})])
            status = await msg.reply(f"📢 {len(ids)} users ko bhej raha hoon...")
            sent = failed = 0
            for uid in ids:
                try:
                    await msg.bot.send_message(uid, bcast, reply_markup=markup)
                    sent += 1
                except TelegramRetryAfter as e:
                    await asyncio.sleep(e.retry_after)
                    try:
                        await msg.bot.send_message(uid, bcast, reply_markup=markup)
                        sent += 1
                    except Exception:
                        failed += 1
                except (TelegramForbiddenError, TelegramBadRequest):
                    failed += 1
                except Exception:
                    failed += 1
                await asyncio.sleep(0.05)
            await status.edit_text(f"✅ Sent: {sent}, Failed: {failed}")

        @r.message(Command("addchannel"))
        async def cmd_addchannel(msg: Message, command: CommandObject):
            if msg.from_user.id != OWNER_ID:
                return
            args = (command.args or "").split()
            if not args:
                await msg.reply(
                    "Use: /addchannel @username\n"
                    "Private channel: /addchannel -100123456 https://t.me/+invite\n"
                    "(Pehle bot ko us channel mein admin banao)")
                return
            raw = args[0]
            chat = int(raw) if raw.lstrip("-").isdigit() else (raw if raw.startswith("@") else "@" + raw)
            try:
                info = await msg.bot.get_chat(chat)
                me = await msg.bot.me()
                member = await msg.bot.get_chat_member(info.id, me.id)
            except Exception as e:
                await msg.reply(f"❌ Channel nahi mila ya bot wahan nahi hai: {str(e)[:150]}")
                return
            if member.status not in ("administrator", "creator"):
                await msg.reply("⚠️ Bot ko pehle us channel ka admin banao, phir dubara try karo.")
                return
            link = args[1] if len(args) > 1 else (f"https://t.me/{info.username}" if info.username else "")
            if not link:
                await msg.reply("Ye private channel hai, invite link bhi do:\n"
                                "/addchannel -100123456 https://t.me/+xxxx")
                return
            force_channels[:] = [c for c in force_channels if c.get("chat") != info.id]
            force_channels.append({"chat": info.id, "title": info.title or raw, "link": link})
            await save_force_channels()
            await msg.reply(f"✅ Force-join ON: {info.title}\nTotal channels: {len(force_channels)}")

        @r.message(Command("delchannel"))
        async def cmd_delchannel(msg: Message, command: CommandObject):
            if msg.from_user.id != OWNER_ID:
                return
            raw = (command.args or "").strip().lstrip("@").lower()
            if not raw:
                await msg.reply("Use: /delchannel @username  (ya channel id)")
                return
            before = len(force_channels)
            force_channels[:] = [
                c for c in force_channels
                if str(c.get("chat")) != raw and not str(c.get("link", "")).lower().endswith(raw)
                and (c.get("title") or "").lower() != raw
            ]
            await save_force_channels()
            removed = before - len(force_channels)
            await msg.reply(f"🗑 Removed: {removed}\nBaaki channels: {len(force_channels)}")

        @r.message(Command("channels"))
        async def cmd_channels(msg: Message):
            if msg.from_user.id != OWNER_ID:
                return
            if not force_channels:
                await msg.reply("Force-join OFF hai. /addchannel @username se on karo.")
                return
            await msg.reply("📢 Force-join channels:\n\n" + "\n".join(
                f"{i}. {c.get('title')} ({c.get('chat')})\n   {c.get('link')}"
                for i, c in enumerate(force_channels, 1)))

        @r.message(Command("vip"))
        async def cmd_vip(msg: Message, command: CommandObject):
            if msg.from_user.id != OWNER_ID:
                return
            args = (command.args or "").split()
            if len(args) != 2 or not args[0].lstrip("-").isdigit() or not args[1].isdigit():
                await msg.reply("Use: /vip <user_id> <days>   (days=0 se VIP hata do)")
                return
            target, days = int(args[0]), int(args[1])
            if days > 0:
                await dbx(users_col.update_one, {"user_id": target},
                          {"$set": {"vip_until": now() + timedelta(days=days)}}, upsert=True)
                note = f"👑 Tumhe {days} din ka VIP mila! Unlimited images & voices 🔥"
            else:
                await dbx(users_col.update_one, {"user_id": target},
                          {"$unset": {"vip_until": ""}})
                note = None
            await msg.reply(f"{'👑 VIP diya' if days > 0 else '❌ VIP hataya'}: {target}")
            if note:
                try:
                    await msg.bot.send_message(target, note)
                except Exception:
                    pass

        @r.message(Command("admin"))
        async def cmd_admin(msg: Message, state: FSMContext):
            if msg.from_user.id != OWNER_ID or msg.chat.type != "private":
                return
            await state.clear()
            text, markup = await admin_panel()
            await msg.answer(text, reply_markup=markup)

        @r.message(AdminStates.waiting_price, NOT_CMD)
        async def adm_price_received(msg: Message, state: FSMContext):
            if msg.from_user.id != OWNER_ID:
                return
            arg = (msg.text or "").strip().lstrip("₹")
            if not arg.isdigit():
                await msg.answer("Sirf number bhej (jaise 10). 0 = free")
                return
            await state.clear()
            await set_clone_setting("price", int(arg))
            text, markup = await admin_panel()
            await msg.answer(f"✅ Price ₹{int(arg)} set\n\n" + text, reply_markup=markup)

        @r.message(AdminStates.waiting_bcast, NOT_CMD)
        async def adm_bcast_received(msg: Message, state: FSMContext):
            if msg.from_user.id != OWNER_ID:
                return
            await state.clear()
            await run_broadcast(msg, (msg.text or "").strip())

        @r.message(Command("setprice"))
        async def cmd_setprice(msg: Message, command: CommandObject):
            if msg.from_user.id != OWNER_ID:
                return
            arg = (command.args or "").strip().lstrip("₹")
            cur = (await get_clone_settings())["price"]
            if not arg.isdigit():
                await msg.reply(f"Abhi clone price: ₹{cur}\nUse: /setprice <rupees>  (0 = free)")
                return
            await set_clone_setting("price", int(arg))
            await msg.reply(f"✅ Clone price: ₹{cur} -> ₹{int(arg)}")

        @r.message(Command("clonelist"))
        async def cmd_clonelist(msg: Message):
            if msg.from_user.id != OWNER_ID:
                return
            docs = await dbx(lambda: list(clones_col.find({}).sort("created", -1)))
            pend = await dbx(orders_col.count_documents, {"status": "pending_admin"})
            price = (await get_clone_settings())["price"]
            if not docs:
                await msg.reply(f"Koi clone nahi.\n💰 Price: ₹{price}  |  ⏳ Pending approval: {pend}")
                return
            lines = []
            for i, d in enumerate(docs, 1):
                ts = d.get("token_short")
                lines.append(
                    f"{i}. {'🟢' if ts in clone_apps else '🔴'} @{d.get('bot_username', '?')}\n"
                    f"   👤 {d.get('owner_id')} (@{d.get('owner_username') or '-'}) | 💰 ₹{d.get('paid', 0)}\n"
                    f"   🆔 {ts}")
            head = (f"🔱 Clone list ({len(docs)})  |  running: {len(clone_apps)}\n"
                    f"💰 Price: ₹{price}  |  ⏳ Pending approval: {pend}\n\n")
            await send_text(msg, head + "\n".join(lines) + "\n\nHatane ke liye: /delclone <id>")

        @r.message(Command("delclone"))
        async def cmd_delclone(msg: Message, command: CommandObject):
            if msg.from_user.id != OWNER_ID:
                return
            ts = (command.args or "").strip()
            if not ts:
                await msg.reply("Use: /delclone <id>  (id /clonelist mein hai)")
                return
            doc = await dbx(clones_col.find_one, {"token_short": ts})
            if not doc:
                await msg.reply("Clone nahi mila.")
                return
            await stop_clone(ts)
            await dbx(clones_col.delete_one, {"token_short": ts})
            await msg.reply(f"🗑 Deleted: @{doc.get('bot_username')} ({ts})")

        @r.message(Command("stats"))
        async def cmd_stats(msg: Message):
            if msg.from_user.id != OWNER_ID:
                return
            await msg.answer(await stats_text())

        @r.message(Command("ban", "unban"))
        async def cmd_ban(msg: Message, command: CommandObject):
            if msg.from_user.id != OWNER_ID:
                return
            arg = (command.args or "").strip()
            target = None
            if arg.lstrip("-").isdigit():
                target = int(arg)
            elif msg.reply_to_message and msg.reply_to_message.from_user:
                target = msg.reply_to_message.from_user.id
            if not target or target == OWNER_ID:
                await msg.reply("Use: /ban <user_id>  ya kisi ke message pe reply karke")
                return
            ban = command.command.lower() == "ban"
            await dbx(users_col.update_one, {"user_id": target},
                      {"$set": {"banned": ban}}, upsert=True)
            if ban:
                banned_ids.add(target)
            else:
                banned_ids.discard(target)
            await msg.reply(f"{'🚫 Banned' if ban else '✅ Unbanned'}: {target}")

    # ── AI chat (private + group mention/reply) ──
    @r.message(F.text)
    async def handle_message(msg: Message):
        if not msg.from_user:
            return
        text = (msg.text or "").strip()
        if not text or text.startswith("/"):
            return
        await track_user(msg.from_user, src)
        uid = msg.from_user.id
        private = msg.chat.type == "private"

        if not private:
            me = await msg.bot.me()
            tag = f"@{me.username}"
            mentioned = tag.lower() in text.lower()
            replied_bot = bool(
                msg.reply_to_message and msg.reply_to_message.from_user
                and msg.reply_to_message.from_user.id == me.id
            )
            if not mentioned and not replied_bot:
                return
            text = re.sub(re.escape(tag), "", text, flags=re.I).strip() or "Kya scene hai?"

        lock = get_lock(uid)
        if lock.locked():
            if private:
                await send_busy_warning(msg)
            return
        async with lock:
            try:
                await msg.bot.send_chat_action(msg.chat.id, "typing")
            except Exception:
                pass
            reply = await get_ai(text, uid)
            prefs = await get_prefs(uid)
            if not reply:
                await (msg.answer if private else msg.reply)(AI_ERR)
                return
            fancy = prefs["fancy"] and prefs["mode"] != "coder"
            await send_text(msg, render(reply, fancy), reply=not private,
                            markup=ai_reply_kb() if private else None)

    # ── Callbacks ──
    @r.callback_query()
    async def handle_cb(cb: CallbackQuery, state: FSMContext):
        data = cb.data or ""
        user = cb.from_user
        msg = cb.message
        ack = Acker(cb)
        if not isinstance(msg, Message):
            await ack()
            return
        uid = user.id
        owner = uid == OWNER_ID

        manual = data.startswith(("ttsv_", "ttss_", "ask_ai_", "clone_", "tool_", "cpa_", "adm_")) or data in {
            "useprompt_gen", "img_regen", "prompt_random", "tts_last", "menu_stats"}
        heavy = data.startswith(("ttss_", "ask_ai_")) or data in {
            "useprompt_gen", "img_regen", "prompt_random"} or (
            data.startswith("tool_") and TOOLS.get(data[5:], {}).get("no_input"))
        try:
            if heavy and is_busy(uid):
                await ack(sc("⏳ Ruko bhai, kaam chal raha hai!"), True)
                return
            if not manual:
                await ack()

            # ---- menus ----
            if data == "menu_home":
                await state.clear()
                await safe_edit(msg, await home_text(user, clone), main_menu_kb(clone, owner))

            elif data == "menu_ai":
                await safe_edit(msg, f"🤖 {sc('AI Chat')}\n\n{sc('Kuch bhi type karo!')}",
                                ai_menu_kb(clone))

            elif data == "menu_tools":
                await safe_edit(msg, f"🧰 {sc('Tools')}\n\n{sc('Kya karna hai?')}", tools_kb(clone))

            elif data == "menu_image":
                await state.set_state(ImgStates.waiting_prompt)
                p = await get_prefs(uid)
                await safe_edit(
                    msg,
                    f"🎨 {sc('Image Generator')}\n\n{sc('Prompt likh, kya banana hai?')}\n\n"
                    f"🎭 {sc('Style')}: {STYLES[p['style']][0]}\n"
                    f"💡 {sc('Tip')}: /prompt {sc('se AI prompt banwao!')}",
                    image_menu_kb(clone))

            elif data == "menu_voice":
                await safe_edit(msg, f"🎙️ {sc('Voice to Text')}\n\n{sc('Bas voice message bhej!')}",
                                kb([], clone))

            elif data == "menu_tts":
                await state.set_state(TTSStates.waiting_text)
                await safe_edit(msg, f"🔊 {sc('Text to Speech')}\n\n{sc('Jo bolna hai likh!')}",
                                tts_voices_kb(clone))

            elif data == "menu_prompt":
                await state.set_state(PromptStates.waiting_topic)
                await safe_edit(
                    msg,
                    f"✨ {sc('Prompt Generator')} ✨\n\n{sc('Topic likh, AI mast prompt banayega!')}\n\n"
                    f"📝 {sc('Example')}: {sc('dragon in space')}",
                    prompt_menu_kb(clone))

            elif data == "menu_settings":
                await safe_edit(msg, await settings_text(uid), settings_kb(clone))

            elif data == "menu_profile":
                await safe_edit(msg, await profile_text(user), kb([], clone))

            elif data == "menu_invite":
                text, markup = await invite_text(uid, clone)
                await safe_edit(msg, text, markup)

            elif data == "menu_top":
                await safe_edit(msg, await top_text(), kb([[btn_success("🎁 ɪɴᴠɪᴛᴇ ᴋᴀʀᴏ", cbd="menu_invite")]], clone))

            elif data == "menu_modes":
                p = await get_prefs(uid)
                await safe_edit(msg, f"🎭 {sc('AI Mode chun')}", choice_kb("set_mode_", MODES, p["mode"], clone))

            elif data == "menu_langs":
                p = await get_prefs(uid)
                await safe_edit(msg, f"🌐 {sc('Language chun')}", choice_kb("set_lang_", LANGS, p["lang"], clone))

            elif data == "menu_styles":
                p = await get_prefs(uid)
                await safe_edit(msg, f"🖼 {sc('Image style chun')}", choice_kb("set_style_", STYLES, p["style"], clone))

            elif data.startswith("set_mode_") and data[9:] in MODES:
                await set_pref(uid, "mode", data[9:])
                await safe_edit(msg, f"🎭 {sc('AI Mode chun')}", choice_kb("set_mode_", MODES, data[9:], clone))

            elif data.startswith("set_lang_") and data[9:] in LANGS:
                await set_pref(uid, "lang", data[9:])
                await safe_edit(msg, f"🌐 {sc('Language chun')}", choice_kb("set_lang_", LANGS, data[9:], clone))

            elif data.startswith("set_style_") and data[10:] in STYLES:
                await set_pref(uid, "style", data[10:])
                await safe_edit(msg, f"🖼 {sc('Image style chun')}", choice_kb("set_style_", STYLES, data[10:], clone))

            elif data == "set_fancy":
                p = await get_prefs(uid)
                await set_pref(uid, "fancy", not p["fancy"])
                await safe_edit(msg, await settings_text(uid), settings_kb(clone))

            elif data == "menu_about":
                await safe_edit(
                    msg,
                    f"ℹ️ {sc('About')}\n\n🌟 {sc('ASD AI Bot')}\n"
                    f"Chat • Image • Voice • TTS • Tools\n\n"
                    + (f"🔗 {sc('Main Bot')}: {MAIN_BOT_USERNAME}\n" if clone else "")
                    + f"👨‍💻 {CREATOR}\n⚡ @freee_apis_free",
                    kb([], clone))

            elif data == "menu_help":
                await safe_edit(msg, help_text(clone), kb([], clone))

            elif data == "menu_stats":
                if not owner:
                    await ack(sc("Owner only!"), True)
                    return
                await ack()
                await safe_edit(msg, await stats_text(), kb([], clone))

            elif data == "clear_history":
                await dbx(history_col.delete_one, {"user_id": uid})
                await ack()
                await safe_edit(msg, q(sc("done! history saaf 🗑️")), kb([], clone))

            # ---- tools ----
            elif data.startswith("tool_"):
                tool = data[5:]
                if tool not in TOOLS:
                    await ack()
                    return
                await ack()
                spec = TOOLS[tool]
                if spec.get("no_input"):
                    await run_tool(msg, uid, tool, "", clone)
                else:
                    await state.set_state(ToolStates.waiting_input)
                    await state.update_data(tool=tool)
                    await safe_edit(msg, f"{spec['label']}\n\n{sc(spec['ask'])}", kb([], clone))

            # ---- prompt / image ----
            elif data == "prompt_random":
                await ack()
                await do_prompt_generation(msg, uid, random.choice(RANDOM_TOPICS), clone)

            elif data == "useprompt_gen":
                prompt = (await get_doc(uid)).get("last_image_prompt", "")
                if not prompt:
                    await ack(sc("Prompt nahi mila!"), True)
                    return
                await ack()
                await safe_delete(msg)
                await do_image_generation(msg, uid, prompt, clone)

            elif data == "img_regen":
                prompt = (await get_doc(uid)).get("last_image_req", "")
                if not prompt:
                    await ack(sc("Purana prompt nahi mila!"), True)
                    return
                await ack()
                await do_image_generation(msg, uid, prompt, clone)

            # ---- voice ----
            elif data.startswith("ask_ai_"):
                text = (await get_doc(uid)).get("last_voice_text", "")
                if not text:
                    await ack(sc("Text nahi mila!"), True)
                    return
                await ack()
                msg = await safe_edit(msg, q(sc("soch raha hoon... 🤔")))
                async with get_lock(uid):
                    reply = await get_ai(text, uid) or AI_ERR
                await safe_edit(
                    msg,
                    f"🎙️ {sc('Tumne bola')}: {text[:200]}\n\n🤖 {sc('ASD')}:\n❝ {reply[:3300]} ❞",
                    kb([], clone))

            elif data == "tts_last":
                text = ((await get_doc(uid)).get("last_ai_reply") or "").strip()
                if not text:
                    await ack(sc("Koi reply nahi mila!"), True)
                    return
                await ack()
                await set_fields(uid, tts_text=text[:TTS_MAX_CHARS])
                await msg.answer(q(sc("voice chun le 🔊")), reply_markup=tts_voices_kb(clone))

            elif data.startswith("ttsv_"):
                voice = data[5:]
                tts_text = ((await get_doc(uid)).get("tts_text") or "").strip()
                if not tts_text:
                    await ack(sc("Pehle text bhej!"), True)
                    return
                await ack()
                await safe_edit(msg, f"🔊 {sc('Voice')}: {voice}\n\n{sc('Style chun:')}",
                                tts_styles_kb(voice, clone))

            elif data.startswith("ttss_"):
                rest = data[5:]
                voice, style = rest.rsplit("_", 1) if "_" in rest else (rest, "none")
                tts_text = ((await get_doc(uid)).get("tts_text") or "").strip()
                if not tts_text:
                    await ack(sc("Text nahi mila!"), True)
                    return
                await ack()
                await do_tts(msg, uid, tts_text, voice, style, clone)

            # ---- paid clone: admin approve / reject ----
            elif data.startswith("cpa_") and not clone:
                if not owner:
                    await ack(sc("Owner only!"), True)
                    return
                action, _, oid = data[4:].partition("_")
                approve = action == "ok"
                order = await dbx(orders_col.find_one_and_update,
                                  {"_id": oid, "status": "pending_admin"},
                                  {"$set": {"status": "approved" if approve else "rejected",
                                            "decided_at": now()}},
                                  return_document=ReturnDocument.AFTER)
                if not order:
                    await ack(sc("Pehle hi handle ho chuka!"), True)
                    return
                await ack()
                await safe_edit(
                    msg,
                    f"{'✅ APPROVED' if approve else '❌ REJECTED'}\n\n"
                    f"🤖 @{order.get('bot_username')} | 👤 {order['user_id']} | ₹{order.get('amount')}\n"
                    f"🧾 {oid}",
                    InlineKeyboardMarkup(inline_keyboard=[
                        [btn_primary("⏳ ᴘᴇɴᴅɪɴɢ", cbd="adm_pending")],
                        [btn_primary("👑 ᴀᴅᴍɪɴ ᴘᴀɴᴇʟ", cbd="adm_home")]]))
                if approve:
                    await notify(order["user_id"], f"✅ {sc('Admin ne approve kar diya! clone ban raha hai...')}")
                    await finalize_clone(order)
                else:
                    await notify(order["user_id"],
                                 q(sc(f"admin ne request reject kar di. refund/help ke liye {CREATOR} se contact kar")))

            # ---- admin panel ----
            elif data.startswith("adm_") and not clone:
                if not owner:
                    await ack(sc("Owner only!"), True)
                    return
                await ack()
                await state.clear()
                if data == "adm_home":
                    text, markup = await admin_panel()
                    await safe_edit(msg, text, markup)

                elif data == "adm_auto":
                    cfg = await get_clone_settings()
                    await set_clone_setting("auto_approve", not cfg["auto_approve"])
                    text, markup = await admin_panel()
                    await safe_edit(msg, text, markup)

                elif data == "adm_price":
                    text, markup = await price_view()
                    await safe_edit(msg, text, markup)

                elif data == "adm_pfree":
                    await set_clone_setting("price", 0)
                    text, markup = await price_view()
                    await safe_edit(msg, text, markup)

                elif data == "adm_pset":
                    await state.set_state(AdminStates.waiting_price)
                    await safe_edit(msg, "✏️ Naya clone price (rupees) likh bhej.\n0 = free",
                                    InlineKeyboardMarkup(inline_keyboard=[
                                        [btn_danger("❌ ᴄᴀɴᴄᴇʟ", cbd="adm_price")]]))

                elif data.startswith("adm_p_"):
                    try:
                        delta = int(data[6:])
                    except ValueError:
                        return
                    cfg = await get_clone_settings()
                    await set_clone_setting("price", max(0, cfg["price"] + delta))
                    text, markup = await price_view()
                    await safe_edit(msg, text, markup)

                elif data == "adm_clones":
                    text, markup = await clones_list_view()
                    await safe_edit(msg, text, markup)

                elif data.startswith("adm_c_"):
                    view = await clone_detail_view(data[6:])
                    if view:
                        await safe_edit(msg, view[0], view[1])
                    else:
                        text, markup = await clones_list_view()
                        await safe_edit(msg, text, markup)

                elif data.startswith("adm_ca_"):
                    action, _, ts = data[7:].partition("_")
                    doc = await dbx(clones_col.find_one, {"token_short": ts})
                    if not doc:
                        text, markup = await clones_list_view()
                        await safe_edit(msg, text, markup)
                    elif action == "del":
                        await safe_edit(
                            msg, f"🗑 @{doc.get('bot_username')} delete karna hai? Wapas nahi aayega.",
                            InlineKeyboardMarkup(inline_keyboard=[
                                [btn_danger("✅ ʜᴀᴀɴ ᴅᴇʟᴇᴛᴇ", cbd=f"adm_ca_delok_{ts}"),
                                 btn_primary("❌ ɴᴀʜɪ", cbd=f"adm_c_{ts}")]]))
                    elif action == "delok":
                        await stop_clone(ts)
                        await dbx(clones_col.delete_one, {"token_short": ts})
                        text, markup = await clones_list_view()
                        await safe_edit(msg, "🗑 Deleted\n\n" + text, markup)
                    else:
                        if action == "start":
                            if ts not in clone_apps:
                                await start_clone_bot(doc["token"], doc["owner_id"])
                        elif action == "stop":
                            if await stop_clone(ts):
                                await dbx(clones_col.update_one, {"token_short": ts},
                                          {"$set": {"status": "stopped"}})
                        elif action == "restart":
                            await stop_clone(ts)
                            await asyncio.sleep(1)
                            await start_clone_bot(doc["token"], doc["owner_id"])
                        view = await clone_detail_view(ts)
                        if view:
                            await safe_edit(msg, view[0], view[1])

                elif data == "adm_pending":
                    text, markup = await pending_view()
                    await safe_edit(msg, text, markup)

                elif data == "adm_channels":
                    if force_channels:
                        body = "\n".join(f"{i}. {c.get('title')} ({c.get('chat')})\n   {c.get('link')}"
                                         for i, c in enumerate(force_channels, 1))
                    else:
                        body = "Force-join OFF hai."
                    await safe_edit(msg, "📢 Force-join channels\n\n" + body +
                                    "\n\n/addchannel @username  |  /delchannel @username",
                                    admin_back_kb())

                elif data == "adm_bcast":
                    await state.set_state(AdminStates.waiting_bcast)
                    await safe_edit(msg, "📣 Broadcast ka message likh bhej (sab users ko jayega).",
                                    InlineKeyboardMarkup(inline_keyboard=[
                                        [btn_danger("❌ ᴄᴀɴᴄᴇʟ", cbd="adm_home")]]))

                elif data == "adm_cmds":
                    await safe_edit(
                        msg,
                        "ℹ️ Owner commands\n\n/admin - ye panel\n/setprice <rupees> - clone price\n"
                        "/clonelist - clones list\n/delclone <id> - clone hatao\n"
                        "/ban <id> /unban <id>\n/vip <id> <days>\n"
                        "/addchannel /delchannel /channels\n/broadcast <text>\n/stats",
                        admin_back_kb())

            # ---- clone management (main bot only) ----
            # ---- clone management (main bot only) ----
            elif data == "menu_clone" and not clone:
                doc = await dbx(clones_col.find_one, {"owner_id": uid})
                if doc:
                    await _clone_panel(msg, doc, edit=True)
                else:
                    await state.set_state(CloneStates.waiting_token)
                    text, markup = await clone_intro((await get_clone_settings())["price"])
                    await safe_edit(msg, text, markup)

            elif data.startswith("clone_") and not clone:
                parts = data.split("_", 2)
                action = parts[1]
                ts = parts[2] if len(parts) > 2 else ""
                doc = await dbx(clones_col.find_one, {"token_short": ts, "owner_id": uid})
                if not doc:
                    await ack(sc("Clone nahi mila!"), True)
                    return
                if action == "start":
                    if ts in clone_apps:
                        await ack(sc("Pehle se chal raha!"), True)
                    else:
                        ok = await start_clone_bot(doc["token"], uid)
                        await ack(sc("Started ✅" if ok else "Start fail ❌"), True)
                elif action == "stop":
                    if await stop_clone(ts):
                        await dbx(clones_col.update_one, {"token_short": ts},
                                  {"$set": {"status": "stopped"}})
                        await ack(sc("Stopped!"), True)
                    else:
                        await ack(sc("Already stopped!"), True)
                elif action == "restart":
                    await stop_clone(ts)
                    await asyncio.sleep(1)
                    ok = await start_clone_bot(doc["token"], uid)
                    await ack(sc("Restarted ✅" if ok else "Restart fail ❌"), True)
                elif action == "status":
                    await ack(f"Status: {'🟢 Running' if ts in clone_apps else '🔴 Stopped'}", True)
                    return
                elif action == "delete":
                    await stop_clone(ts)
                    await dbx(clones_col.delete_one, {"token_short": ts, "owner_id": uid})
                    await ack()
                    await safe_edit(msg, q(sc("clone delete! /clone se naya bana")), kb([], False))
                    return
                fresh = await dbx(clones_col.find_one, {"token_short": ts})
                if fresh:
                    await _clone_panel(msg, fresh, edit=True)
        finally:
            await ack()

    return r


# ── Entry point ──────────────────────────────────────────────────────────
async def main():
    global main_bot
    await asyncio.to_thread(init_db)
    docs = await dbx(lambda: [d["user_id"] for d in users_col.find({"banned": True}, {"user_id": 1})])
    banned_ids.update(docs)

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties())
    main_bot = bot
    await load_force_channels()
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(build_router(clone=False))

    await bot.set_my_commands(MAIN_COMMANDS)
    try:
        await bot.set_my_commands(OWNER_COMMANDS, scope=BotCommandScopeChat(chat_id=OWNER_ID))
    except Exception as e:
        logger.warning("Owner commands not set: %s", e)
    await bot.delete_webhook(drop_pending_updates=True)

    await load_clones()
    await resume_payment_monitors()
    logger.info("ASD AI Bot - live")
    try:
        await dp.start_polling(bot)
    finally:
        for ts in list(clone_apps):
            await stop_clone(ts)  # DB status untouched, so they auto-resume next boot


if __name__ == "__main__":
    asyncio.run(main())
