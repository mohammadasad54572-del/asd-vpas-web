import asyncio
import os
import random
import time
import logging
import httpx
from datetime import datetime, timedelta
from pymongo import MongoClient
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, BotCommand
from aiogram.filters import Command, CommandStart
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════════════════════════
BOT_TOKEN = os.getenv("BOT_TOKEN", "8946878537:AAGIUXKkPTfl2GccLTeB83naEBm4wFL0kbI")
MONGO_URL = os.getenv(
    "MONGO_URL",
    "mongodb+srv://sgamer011141_db_user:sgamer011141_db_user@cluster0.nwgp6ux.mongodb.net/",
)
OWNER_ID = int(os.getenv("OWNER_ID", "8620006563"))

mongo_client = MongoClient(MONGO_URL)
db = mongo_client["baka_bot"]
users_col = db["users"]
groups_col = db["groups"]
filters_col = db["filters"]
banned_col = db["banned_users"]
history_col = db["chat_history"]

START_TIME = time.time()

# ─── Small Caps ──────────────────────────────────────────────────
SMALL_CAPS = {
    'a': 'ᴀ', 'b': 'ʙ', 'c': 'ᴄ', 'd': 'ᴅ', 'e': 'ᴇ', 'f': 'ꜰ', 'g': 'ɢ', 'h': 'ʜ',
    'i': 'ɪ', 'j': 'ᴊ', 'k': 'ᴋ', 'l': 'ʟ', 'm': 'ᴍ', 'n': 'ɴ', 'o': 'ᴏ', 'p': 'ᴘ',
    'q': 'ǫ', 'r': 'ʀ', 's': 'ꜱ', 't': 'ᴛ', 'u': 'ᴜ', 'v': 'ᴠ', 'w': 'ᴡ', 'x': 'x',
    'y': 'ʏ', 'z': 'ᴢ',
    'A': 'ᴀ', 'B': 'ʙ', 'C': 'ᴄ', 'D': 'ᴅ', 'E': 'ᴇ', 'F': 'ꜰ', 'G': 'ɢ', 'H': 'ʜ',
    'I': 'ɪ', 'J': 'ᴊ', 'K': 'ᴋ', 'L': 'ʟ', 'M': 'ᴍ', 'N': 'ɴ', 'O': 'ᴏ', 'P': 'ᴘ',
    'Q': 'ǫ', 'R': 'ʀ', 'S': 'ꜱ', 'T': 'ᴛ', 'U': 'ᴜ', 'V': 'ᴠ', 'W': 'ᴡ', 'X': 'x',
    'Y': 'ʏ', 'Z': 'ᴢ',
    '0': '𝟶', '1': '𝟷', '2': '𝟸', '3': '𝟹', '4': '𝟺', '5': '𝟻',
    '6': '𝟼', '7': '𝟽', '8': '𝟾', '9': '𝟿',
}

def sc(t: str) -> str:
    return ''.join(SMALL_CAPS.get(c, c) for c in t)

def q(t: str) -> str:
    return f"❝ {t} ❞"

# ══════════════════════════════════════════════════════════════════
#  AI — Baka System Prompt
# ══════════════════════════════════════════════════════════════════
BAKA_SYSTEM = (
    "Tu Baka hai — ek savage, rude, unbothered, yet lovable Gen-Z anime bestie girl. "
    "Tu short punchy sentences mein baat karti hai with heavy attitude, sarcasm, Hinglish slang, "
    "aur emojis (🙄, 💀, 😭, 🤌, ✨, 😤). Tu users ko playfully roast karti hai but never truly mean. "
    "Hinglish use kar: bhai, yaar, arrey, chup, matlab, bas, kya bol raha, baka. "
    "Replies SHORT rakh (1-2 lines max). Never break character. "
    "Sirf jawab de — 'Assistant:' ya 'Bot:' prefix mat lagana. "
    "Tu Baka naam ki hai, kabhi Uraraka mat bolna."
)

async def baka_reply(user_text: str, user_id: int) -> str:
    doc = history_col.find_one({"user_id": user_id})
    history = doc.get("messages", []) if doc else []

    messages = [{"role": "system", "content": BAKA_SYSTEM}]
    for item in history[-8:]:
        if item.get("role") in ("user", "assistant"):
            messages.append({"role": item["role"], "content": item.get("content", "")})
    messages.append({"role": "user", "content": user_text})

    url = "https://us-central1-ai-chat-bot-bf47e.cloudfunctions.net/chat_function_android"
    payload = {"data": {"messages": messages, "model": "gpt-4o-mini"}}

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(url, json=payload)
            r.raise_for_status()
            data = r.json()
        answer = (
            data.get("result", {})
                .get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
        )
        if not answer:
            return sc("Bhai, is baar AI ka reply nahi aaya. Dobara try kar! 😅")
    except Exception as e:
        logger.error("AI failed: %s", e)
        return sc("Bhai, AI server down hai 💀 thoda baad try kar")

    history.extend([
        {"role": "user", "content": user_text},
        {"role": "assistant", "content": answer},
    ])
    history_col.update_one(
        {"user_id": user_id},
        {"$set": {"messages": history[-30:], "updated": datetime.utcnow()}},
        upsert=True,
    )
    return answer

# ══════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════
def is_owner(uid: int) -> bool:
    return uid == OWNER_ID

def uptime_str() -> str:
    s = int(time.time() - START_TIME)
    h, r = divmod(s, 3600)
    m, sec = divmod(r, 60)
    return f"{h}h {m}m {sec}s"

def cooldown_left(last, hours: float):
    if not last:
        return None
    if isinstance(last, str):
        try:
            last = datetime.fromisoformat(last)
        except Exception:
            return None
    delta = (last + timedelta(hours=hours)) - datetime.utcnow()
    secs = int(delta.total_seconds())
    return secs if secs > 0 else None

def mention(user) -> str:
    name = user.first_name or "User"
    return f"[{name}](tg://user?id={user.id})"

def ensure_user(uid: int, username=None, first_name=None):
    users_col.update_one(
        {"user_id": uid},
        {
            "$set": {
                "username": username,
                "first_name": first_name,
                "last_updated": datetime.utcnow(),
            },
            "$setOnInsert": {
                "joined": datetime.utcnow(),
                "credits": 30,
                "coins": 0,
                "warnings": 0,
            },
        },
        upsert=True,
    )

def get_user(uid: int):
    return users_col.find_one({"user_id": uid})

def update_credits(uid: int, delta: int):
    users_col.update_one({"user_id": uid}, {"$inc": {"credits": delta}})

def update_coins(uid: int, delta: int):
    users_col.update_one({"user_id": uid}, {"$inc": {"coins": delta}})

async def is_banned(uid: int) -> bool:
    return banned_col.find_one({"user_id": uid}) is not None

async def is_admin(bot: Bot, chat_id: int, uid: int) -> bool:
    try:
        m = await bot.get_chat_member(chat_id, uid)
        return m.status in ("administrator", "creator")
    except Exception:
        return False

async def auto_delete(msg: Message, delay: int = 60):
    try:
        await asyncio.sleep(delay)
        await msg.delete()
    except Exception:
        pass

def schedule_delete(msg: Message, delay: int = 60):
    if delay > 0:
        asyncio.create_task(auto_delete(msg, delay))

# ══════════════════════════════════════════════════════════════════
#  ROUTER
# ══════════════════════════════════════════════════════════════════
router = Router()

# ─── /start ─────────────────────────────────────────────────────
@router.message(CommandStart())
async def cmd_start(msg: Message):
    ensure_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name)
    if await is_banned(msg.from_user.id):
        return await msg.reply(sc("tu globally banned hai bhai 💀"))

    name = msg.from_user.first_name or "Dost"
    if msg.chat.type != "private":
        return await msg.reply(q(sc(f"ʜᴇʏ {name}! ᴅᴍ ᴍᴇɪɴ ᴀᴀ ᴄʜᴀᴛ ᴋᴀʀᴛᴇ ʜᴀɪɴ 😎")))

    text = (
        f"✨ **{sc('BAKA BOT')}** ✨\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{q(sc(f'Aye aye {name}! Kya haal hai mere jaan! 🔥'))}\n\n"
        f"{sc('Main teri anime bestie hoon — savage but lovable 😤')}\n"
        f"{sc('Kuch bhi type kar, main roast karti hoon ya help karti hoon 💀')}\n\n"
        f"📖 {sc('Commands dekhne ke liye')}: /help\n\n"
        f"⚡ {sc('Powered By')}: @DARK_GIVEAWAYSS"
    )
    sent = await msg.answer(text)
    schedule_delete(sent, 300)

# ─── /help ──────────────────────────────────────────────────────
@router.message(Command("help"))
async def cmd_help(msg: Message):
    text = (
        f"📖 **{sc('Help & Commands')}**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🤖 **{sc('AI')}**\n"
        f"  /clear — history saaf\n"
        f"  /credits — balance dekho\n"
        f"  Group mein: reply / mention / 'baka' bolke AI chalao\n\n"
        f"💰 **{sc('Economy')}**\n"
        f"  /daily — daily coins (24h)\n"
        f"  /work — earn coins (1h)\n"
        f"  /crime — risky (2h)\n"
        f"  /rob — steal (reply, 6h)\n"
        f"  /pay — send coins (reply + amount)\n"
        f"  /wallet — balance\n\n"
        f"🎮 **{sc('Fun')}**\n"
        f"  /kiss /slap /hug /punch /kick — reply to user\n"
        f"  /ship — love score (reply)\n"
        f"  /roll — dice\n"
        f"  /trivia — quiz\n\n"
        f"🛡️ **{sc('Moderation')}** _(group admins)_\n"
        f"  /kill — reply to user (instant ban)\n"
        f"  /ban /unban — reply to user\n"
        f"  /setwelcome <text> — welcome set\n"
        f"  /welcome on|off\n"
        f"  /save <kw> <resp> — filter add\n"
        f"  /stop <kw> — filter remove\n"
        f"  /filters — list filters\n\n"
        f"👑 **{sc('Owner')}**\n"
        f"  /admin — panel\n"
        f"  /stats — stats\n"
        f"  /broadcast <msg>\n"
        f"  /gban <uid> [reason]\n"
        f"  /ungban <uid>\n\n"
        f"⚡ @DARK_GIVEAWAYSS"
    )
    sent = await msg.answer(text)
    schedule_delete(sent, 300)

# ─── /clear ─────────────────────────────────────────────────────
@router.message(Command("clear"))
async def cmd_clear(msg: Message):
    history_col.delete_one({"user_id": msg.from_user.id})
    sent = await msg.answer(q(sc("ᴅᴏɴᴇ! ʜɪꜱᴛᴏʀʏ ꜱᴀᴀꜰ! 🗑️")))
    schedule_delete(sent, 60)

# ══════════════════════════════════════════════════════════════════
#  ⚡ /KILL COMMAND
# ══════════════════════════════════════════════════════════════════
@router.message(Command("kill"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_kill(msg: Message):
    try:
        if not await is_admin(msg.bot, msg.chat.id, msg.from_user.id):
            return await msg.reply(sc("tu admin nahi hai bhai 💀"))

        if not msg.reply_to_message or not msg.reply_to_message.from_user:
            return await msg.reply(sc("kisi ke message pe reply karke /kill kar 🙄"))

        target = msg.reply_to_message.from_user

        if target.id == msg.from_user.id:
            return await msg.reply(sc("khud ko kill? 💀 pagal hai kya"))

        me = await msg.bot.get_me()
        if target.id == me.id:
            return await msg.reply(sc("mujhe kill karega? 💀 try kar"))

        if await is_admin(msg.bot, msg.chat.id, target.id):
            return await msg.reply(sc("wo admin hai bhai, use nahi kar sakti 💀"))

        try:
            await msg.reply_to_message.delete()
        except Exception:
            pass

        try:
            await msg.bot.ban_chat_member(msg.chat.id, target.id)
        except Exception as e:
            logger.error(f"Kill ban failed: {e}")
            return await msg.reply(sc("mujhe ban rights do bhai 💀"))

        sent = await msg.reply(
            f"⚡ **{sc('KILLED')}** ⚡\n\n"
            f"{mention(target)} {sc('ko maara gaya 💀')}\n"
            f"_{sc('by')} {mention(msg.from_user)}_"
        )
        schedule_delete(sent, 60)
    except Exception as e:
        logger.error(f"Kill error: {e}")

# ══════════════════════════════════════════════════════════════════
#  MODERATION
# ══════════════════════════════════════════════════════════════════
@router.message(Command("ban"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_ban(msg: Message):
    if not await is_admin(msg.bot, msg.chat.id, msg.from_user.id):
        return await msg.reply(sc("tu admin nahi hai 💀"))
    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        return await msg.reply(sc("reply karo jise ban karna hai"))
    target = msg.reply_to_message.from_user
    try:
        await msg.bot.ban_chat_member(msg.chat.id, target.id)
        sent = await msg.reply(f"🚫 {mention(target)} **{sc('banned')}** ✅")
        schedule_delete(sent, 60)
    except Exception:
        await msg.reply(sc("ban nahi hua 💀 mujhe admin rights do"))

@router.message(Command("unban"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_unban(msg: Message):
    if not await is_admin(msg.bot, msg.chat.id, msg.from_user.id):
        return await msg.reply(sc("tu admin nahi hai 💀"))
    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        return await msg.reply(sc("reply karo jise unban karna hai"))
    target = msg.reply_to_message.from_user
    try:
        await msg.bot.unban_chat_member(msg.chat.id, target.id)
        sent = await msg.reply(f"✅ {mention(target)} **{sc('unbanned')}**")
        schedule_delete(sent, 60)
    except Exception:
        await msg.reply(sc("unban nahi hua 💀"))

# ══════════════════════════════════════════════════════════════════
#  WELCOME
# ══════════════════════════════════════════════════════════════════
@router.message(F.new_chat_members)
async def on_new_member(msg: Message):
    try:
        chat_id = msg.chat.id
        groups_col.update_one(
            {"chat_id": chat_id},
            {"$setOnInsert": {
                "welcome_enabled": True,
                "welcome_text": "Hey {first}, welcome to {chatname}! 🎉",
            }},
            upsert=True,
        )
        grp = groups_col.find_one({"chat_id": chat_id}) or {}
        if not grp.get("welcome_enabled", True):
            return
        for m in msg.new_chat_members:
            if m.is_bot:
                continue
            wtext = grp.get("welcome_text", "Hey {first}, welcome!")
            wtext = wtext.replace("{first}", m.first_name or "friend")
            wtext = wtext.replace("{username}",
                                   f"@{m.username}" if m.username else m.first_name or "")
            wtext = wtext.replace("{chatname}", msg.chat.title or "this group")
            sent = await msg.reply(wtext)
            schedule_delete(sent, 60)
    except Exception as e:
        logger.error(f"Welcome error: {e}")

@router.message(Command("setwelcome"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_setwelcome(msg: Message):
    if not await is_admin(msg.bot, msg.chat.id, msg.from_user.id):
        return await msg.reply(sc("tu admin nahi hai 💀"))
    parts = msg.text.split(maxsplit=1)
    if len(parts) < 2:
        return await msg.reply(sc("welcome text de\nVars: {first} {username} {chatname}"))
    groups_col.update_one(
        {"chat_id": msg.chat.id},
        {"$set": {"welcome_text": parts[1], "welcome_enabled": True}},
        upsert=True,
    )
    sent = await msg.reply(sc("welcome message set ✅"))
    schedule_delete(sent, 30)

@router.message(Command("welcome"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_welcome(msg: Message):
    if not await is_admin(msg.bot, msg.chat.id, msg.from_user.id):
        return await msg.reply(sc("tu admin nahi hai 💀"))
    args = msg.text.split(maxsplit=1)
    arg = args[1].lower() if len(args) > 1 else ""
    if arg not in ("on", "off"):
        return await msg.reply(sc("/welcome on ya /welcome off"))
    groups_col.update_one(
        {"chat_id": msg.chat.id},
        {"$set": {"welcome_enabled": arg == "on"}},
        upsert=True,
    )
    sent = await msg.reply(sc(f"welcome turned {arg} ✅"))
    schedule_delete(sent, 30)

# ══════════════════════════════════════════════════════════════════
#  FILTERS
# ══════════════════════════════════════════════════════════════════
@router.message(Command("save"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_save(msg: Message):
    if not await is_admin(msg.bot, msg.chat.id, msg.from_user.id):
        return await msg.reply(sc("tu admin nahi hai 💀"))
    parts = msg.text.split(maxsplit=2)
    if len(parts) < 3:
        return await msg.reply(sc("/save [keyword] [response]"))
    kw, resp = parts[1].lower(), parts[2]
    filters_col.update_one(
        {"chat_id": msg.chat.id, "keyword": kw},
        {"$set": {"response": resp}},
        upsert=True,
    )
    sent = await msg.reply(sc(f"filter saved: '{kw}' ✅"))
    schedule_delete(sent, 30)

@router.message(Command("stop"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_stop(msg: Message):
    if not await is_admin(msg.bot, msg.chat.id, msg.from_user.id):
        return await msg.reply(sc("tu admin nahi hai 💀"))
    parts = msg.text.split(maxsplit=1)
    if len(parts) < 2:
        return await msg.reply(sc("/stop [keyword]"))
    kw = parts[1].lower()
    filters_col.delete_one({"chat_id": msg.chat.id, "keyword": kw})
    sent = await msg.reply(sc(f"filter removed: '{kw}' ✅"))
    schedule_delete(sent, 30)

@router.message(Command("filters"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_filters(msg: Message):
    rows = list(filters_col.find({"chat_id": msg.chat.id}))
    if not rows:
        return await msg.reply(sc("koi filter nahi set hai 🙄"))
    kws = "\n".join(f"• `{r['keyword']}`" for r in rows)
    sent = await msg.reply(f"🔍 **{sc('Active Filters')}**\n\n{kws}")
    schedule_delete(sent, 60)

# ══════════════════════════════════════════════════════════════════
#  GROUP MESSAGE — anti-channel + anti-abuse + filters + AI
# ══════════════════════════════════════════════════════════════════
GAALI = [
    "fuck", "shit", "bitch", "bastard", "asshole", "chutiya", "madarchod",
    "bhenchod", "gaandu", "randi", "haramzada", "kamina", "saala", "kutte",
    "harami", "madar", "bc", "mc", "bkl", "behenchod",
]

@router.message(
    F.chat.type.in_({"group", "supergroup"}),
    F.text,
    ~F.text.startswith("/"),   # Commands ko bilkul mat pakdo
)
async def group_msg(msg: Message):
    try:
        if not msg.from_user:
            return

        chat_id = msg.chat.id
        text = msg.text or ""
        text_lo = text.lower()
        me = await msg.bot.get_me()

        # Anti-channel
        if msg.sender_chat:
            if msg.sender_chat.id == chat_id:
                return
            try:
                await msg.bot.ban_chat_member(chat_id, msg.sender_chat.id)
                sent = await msg.reply(
                    f"⚡ **{sc('AUTO-KILL')}** ⚡\n\n"
                    f"Channel se spam karne ki koshish? 💀\n"
                    f"**{sc('Banned instantly')}** 🚫"
                )
                schedule_delete(sent, 30)
            except Exception:
                pass
            return

        # Filters (work for everyone)
        for f in filters_col.find({"chat_id": chat_id}):
            if f["keyword"] in text_lo:
                sent = await msg.reply(f["response"])
                schedule_delete(sent, 60)
                break

        # AI in groups — only on reply to bot / pure mention / "baka" word
        is_reply_to_bot = (
            msg.reply_to_message
            and msg.reply_to_message.from_user
            and msg.reply_to_message.from_user.id == me.id
        )
        is_mentioned = f"@{me.username}".lower() in text_lo if me.username else False
        has_baka = "baka" in text_lo

        if is_reply_to_bot or is_mentioned or has_baka:
            if await is_banned(msg.from_user.id):
                return
            ensure_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name)

            # Clean text for AI (remove bot mention)
            clean_text = text
            if me.username:
                clean_text = clean_text.replace(f"@{me.username}", "").replace(f"@{me.username.lower()}", "")
            clean_text = clean_text.strip()
            if not clean_text:
                clean_text = "hi"

            await msg.bot.send_chat_action(msg.chat.id, "typing")
            reply = await baka_reply(clean_text, msg.from_user.id)
            sent = await msg.reply(q(sc(reply)))
            schedule_delete(sent, 180)
            return

        # Skip further processing for admins
        if await is_admin(msg.bot, chat_id, msg.from_user.id):
            return

        # Anti-abuse (soft version)
        if any(g in text_lo for g in GAALI):
            try:
                await msg.delete()
            except Exception:
                pass

            users_col.update_one(
                {"user_id": msg.from_user.id},
                {"$inc": {"warnings": 1}},
                upsert=True,
            )
            u = get_user(msg.from_user.id) or {}
            warns = u.get("warnings", 0)

            if warns >= 3:
                try:
                    await msg.bot.ban_chat_member(chat_id, msg.from_user.id)
                    users_col.update_one(
                        {"user_id": msg.from_user.id},
                        {"$set": {"warnings": 0}},
                    )
                    sent = await msg.reply(
                        f"🚫 {mention(msg.from_user)} **{sc('banned')}**!\n"
                        f"_{sc('3 strikes = out bhai 💀')}_"
                    )
                except Exception:
                    sent = await msg.reply(sc("mujhe admin rights do 💀"))
            else:
                roasts = [
                    sc("seedha baat kar, gaali se kuch nahi milta 💀"),
                    sc("itna gussa? thanda pani pi 😤"),
                    sc("yaar ye sab kya bol raha tu 🤌"),
                    sc("language clean rakh baka 🙄"),
                ]
                sent = await msg.reply(
                    f"⚠️ {mention(msg.from_user)}, {random.choice(roasts)}\n"
                    f"_**{sc('Warning')} {warns}/3**_"
                )
            schedule_delete(sent, 60)

    except Exception as e:
        logger.error(f"group_msg error: {e}")

# ══════════════════════════════════════════════════════════════════
#  ECONOMY
# ══════════════════════════════════════════════════════════════════
WORK_JOBS = [
    ("delivered pizza to 47 houses 🍕", 80, 150),
    ("coded someone's assignment 💻", 100, 200),
    ("sold chai on the street ☕", 60, 120),
    ("walked someone's dog in rain 🐕", 50, 100),
    ("moderated a Discord for 6h 😭", 90, 180),
]
CRIME_JOBS = [
    ("stole a politician's speech 📄", 200, 400, True),
    ("hacked into a WiFi router 🕵️", 150, 350, True),
    ("scammed a scammer 😈", 300, 500, True),
    ("got caught shoplifting 🚓", -100, -50, False),
    ("slipped mid-heist on banana 🍌", -80, -20, False),
]

@router.message(Command("daily"))
async def cmd_daily(msg: Message):
    ensure_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name)
    u = get_user(msg.from_user.id)
    cd = cooldown_left(u.get("daily_last"), 24)
    if cd:
        h, r = divmod(cd, 3600)
        m = r // 60
        return await msg.reply(sc(f"kal aa, {h}h {m}m baaki hai 🙄"))
    reward = random.randint(150, 300)
    update_coins(msg.from_user.id, reward)
    users_col.update_one({"user_id": msg.from_user.id}, {"$set": {"daily_last": datetime.utcnow()}})
    sent = await msg.reply(
        f"🎁 **{sc('Daily Reward')}**\n\n+`{reward}` {sc('coins')}! 💰"
    )
    schedule_delete(sent, 120)

@router.message(Command("work"))
async def cmd_work(msg: Message):
    ensure_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name)
    u = get_user(msg.from_user.id)
    cd = cooldown_left(u.get("work_last"), 1)
    if cd:
        return await msg.reply(sc(f"thak gaya? {cd // 60}m {cd % 60}s baad aa 😤"))
    desc, lo, hi = random.choice(WORK_JOBS)
    earned = random.randint(lo, hi)
    update_coins(msg.from_user.id, earned)
    users_col.update_one({"user_id": msg.from_user.id}, {"$set": {"work_last": datetime.utcnow()}})
    sent = await msg.reply(f"💼 **{sc('Work Done')}**\n\ntu {desc}\n+`{earned}` {sc('coins')}! 💰")
    schedule_delete(sent, 120)

@router.message(Command("crime"))
async def cmd_crime(msg: Message):
    ensure_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name)
    u = get_user(msg.from_user.id)
    cd = cooldown_left(u.get("crime_last"), 2)
    if cd:
        return await msg.reply(sc(f"itna crime mat kar, {cd // 60}m baad aa 😭"))
    desc, lo, hi, ok = random.choice(CRIME_JOBS)
    amt = abs(random.randint(lo, hi))
    users_col.update_one({"user_id": msg.from_user.id}, {"$set": {"crime_last": datetime.utcnow()}})
    if ok:
        update_coins(msg.from_user.id, amt)
        sent = await msg.reply(f"😈 **{sc('Crime Win')}**\ntu {desc}\n+`{amt}` {sc('coins')}! 💰")
    else:
        update_coins(msg.from_user.id, -amt)
        sent = await msg.reply(f"🚓 **{sc('Crime Fail')}**\ntu {desc}\n-`{amt}` {sc('coins')} fine 😭")
    schedule_delete(sent, 120)

@router.message(Command("rob"))
async def cmd_rob(msg: Message):
    ensure_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name)
    u = get_user(msg.from_user.id)
    cd = cooldown_left(u.get("rob_last"), 6)
    if cd:
        h, r = divmod(cd, 3600)
        m = r // 60
        return await msg.reply(sc(f"chill bhai, {h}h {m}m baad 🙄"))
    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        return await msg.reply(sc("reply karo jise rob karna hai 🙄"))
    target = msg.reply_to_message.from_user
    if target.id == msg.from_user.id:
        return await msg.reply(sc("khud ko rob? 💀"))
    t_data = get_user(target.id)
    if not t_data or t_data.get("coins", 0) < 50:
        return await msg.reply(sc("us garib ke paas kuch nahi 💀"))
    users_col.update_one({"user_id": msg.from_user.id}, {"$set": {"rob_last": datetime.utcnow()}})
    amt = random.randint(30, min(200, t_data["coins"]))
    if random.random() < 0.5:
        update_coins(msg.from_user.id, amt)
        update_coins(target.id, -amt)
        sent = await msg.reply(
            f"💸 **{sc('Robbery!')}**\n"
            f"tu {mention(target)} se `{amt}` {sc('coins')} le gaya 😈"
        )
    else:
        fine = random.randint(20, 80)
        update_coins(msg.from_user.id, -fine)
        sent = await msg.reply(
            f"🚓 **{sc('Caught!')}**\n"
            f"{mention(target)} ne pakad liya 💀\n-`{fine}` {sc('coins')} fine!"
        )
    schedule_delete(sent, 120)

@router.message(Command("pay"))
async def cmd_pay(msg: Message):
    ensure_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name)
    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        return await msg.reply(sc("reply karo + /pay [amount] 🙄"))
    target = msg.reply_to_message.from_user
    parts = msg.text.split()
    try:
        amt = int(parts[-1])
        assert amt > 0
    except Exception:
        return await msg.reply(sc("valid amount de 🙄"))
    sender = get_user(msg.from_user.id)
    if not sender or sender.get("coins", 0) < amt:
        return await msg.reply(sc("itne coins nahi hain tere paas 💀"))
    update_coins(msg.from_user.id, -amt)
    update_coins(target.id, amt)
    sent = await msg.reply(f"✅ `{amt}` {sc('coins')} → {mention(target)} ✨")
    schedule_delete(sent, 120)

@router.message(Command("wallet"))
@router.message(Command("credits"))
async def cmd_wallet(msg: Message):
    ensure_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name)
    u = get_user(msg.from_user.id)
    sent = await msg.reply(
        f"💼 **{sc('Wallet')}** — {mention(msg.from_user)}\n\n"
        f"🪙 **{sc('Credits')}:** `{u.get('credits', 0)}`\n"
        f"💰 **{sc('Coins')}:** `{u.get('coins', 0)}`"
    )
    schedule_delete(sent, 120)

# ══════════════════════════════════════════════════════════════════
#  FUN
# ══════════════════════════════════════════════════════════════════
ROASTS = {
    "kiss": ["aww filmi scene 🎬 cringe hai par cute 😭", "ek dum romantic 💀"],
    "slap": ["straight up violence 😭", "deserved tha 🤌"],
    "hug": ["aww wholesome moment 🌱✨", "mujhe bhi hug chahiye 😭"],
    "punch": ["ek aur dushman bana liya 💀", "bhai ladai 😤"],
    "kick": ["straight disrespect 😭💀", "kya hua bhai 🤌"],
}

def make_action(name, emoji, verb):
    @router.message(Command(name))
    async def _h(msg: Message):
        if not msg.reply_to_message or not msg.reply_to_message.from_user:
            return await msg.reply(sc(f"reply karo kisi ko {name} karne ke liye 🙄"))
        target = msg.reply_to_message.from_user
        sent = await msg.reply(
            f"{emoji} {mention(msg.from_user)} **{sc(verb)}** {mention(target)}\n"
            f"_{random.choice(ROASTS[name])}_"
        )
        schedule_delete(sent, 120)
    return _h

make_action("kiss", "💋", "kisses")
make_action("slap", "👋", "slaps")
make_action("hug", "🤗", "hugs")
make_action("punch", "👊", "punches")
make_action("kick", "🦵", "kicks")

@router.message(Command("ship"))
async def cmd_ship(msg: Message):
    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        return await msg.reply(sc("reply karo kisi ko ship karne ke liye 💕"))
    target = msg.reply_to_message.from_user
    score = random.randint(0, 100)
    bar = "❤️" * (score // 10) + "🖤" * (10 - score // 10)
    verdict = (
        sc("soulmates ho bhai 💕") if score > 85 else
        sc("acha match hai 🌟") if score > 65 else
        sc("thoda effort lagao 😤") if score > 40 else
        sc("flop ship hai 💀")
    )
    sent = await msg.reply(
        f"💕 **{sc('Ship Score')}**\n\n"
        f"{mention(msg.from_user)} + {mention(target)}\n\n"
        f"**{score}%** {bar}\n\n_{verdict}_"
    )
    schedule_delete(sent, 120)

@router.message(Command("roll"))
async def cmd_roll(msg: Message):
    val = random.randint(1, 6)
    faces = ["⚀", "⚁", "⚂", "⚃", "⚄", "⚅"]
    sent = await msg.reply(f"🎲 **{sc('Dice Roll')}**\n\n{faces[val-1]} {sc('tu rolled')} **{val}**!")
    schedule_delete(sent, 60)

TRIVIA_Q = [
    ("Capital of Japan?", "Tokyo", ["Beijing", "Seoul", "Tokyo", "Bangkok"]),
    ("Sides of a hexagon?", "6", ["5", "6", "7", "8"]),
    ("Red Planet?", "Mars", ["Venus", "Mars", "Jupiter", "Saturn"]),
    ("7 × 8 = ?", "56", ["48", "54", "56", "63"]),
    ("Number of continents?", "7", ["5", "6", "7", "8"]),
]

@router.message(Command("trivia"))
async def cmd_trivia(msg: Message):
    q_, ans, choices = random.choice(TRIVIA_Q)
    random.shuffle(choices)
    opts = "\n".join(f"  **{i+1}.** {c}" for i, c in enumerate(choices))
    sent = await msg.reply(
        f"❓ **{sc('Trivia Time')}**\n\n**{q_}**\n\n{opts}\n\n_{sc('reply with number!')}_"
    )
    schedule_delete(sent, 180)

# ══════════════════════════════════════════════════════════════════
#  OWNER COMMANDS
# ══════════════════════════════════════════════════════════════════
@router.message(Command("admin"))
async def cmd_admin(msg: Message):
    if not is_owner(msg.from_user.id):
        return await msg.reply(sc("tu admin nahi hai bhai 💀"))
    await msg.reply(
        f"👑 **{sc('Admin Panel')}**\n\n"
        f"👥 {sc('Users')}: `{users_col.count_documents({})}`\n"
        f"💬 {sc('Groups')}: `{groups_col.count_documents({})}`\n"
        f"🚫 {sc('Banned')}: `{banned_col.count_documents({})}`\n"
        f"⏱️ {sc('Uptime')}: `{uptime_str()}`"
    )

@router.message(Command("stats"))
async def cmd_stats(msg: Message):
    if not is_owner(msg.from_user.id):
        return await msg.reply(sc("tu admin nahi hai 💀"))
    await msg.reply(
        f"📊 **{sc('Stats')}**\n\n"
        f"👥 {sc('Users')}: `{users_col.count_documents({})}`\n"
        f"💬 {sc('Groups')}: `{groups_col.count_documents({})}`\n"
        f"🚫 {sc('Banned')}: `{banned_col.count_documents({})}`\n"
        f"⏱️ {sc('Uptime')}: `{uptime_str()}`"
    )

@router.message(Command("broadcast"))
async def cmd_broadcast(msg: Message):
    if not is_owner(msg.from_user.id):
        return
    parts = msg.text.split(maxsplit=1)
    if len(parts) < 2:
        return await msg.reply(sc("kya broadcast karoon? 🙄"))
    text = parts[1]
    users = list(users_col.find({}))
    status = await msg.reply(sc(f"broadcasting to {len(users)} users..."))
    ok = fail = 0
    for u in users:
        try:
            await msg.bot.send_message(u["user_id"], f"📢 **{sc('Broadcast')}**\n\n{text}")
            ok += 1
            await asyncio.sleep(0.05)
        except Exception:
            fail += 1
    await status.edit_text(sc(f"done! sent: {ok}, failed: {fail}"))

@router.message(Command("gban"))
async def cmd_gban(msg: Message):
    if not is_owner(msg.from_user.id):
        return
    parts = msg.text.split(maxsplit=2)
    try:
        uid = int(parts[1])
    except Exception:
        return await msg.reply(sc("/gban [uid] [reason]"))
    reason = parts[2] if len(parts) > 2 else "no reason"
    banned_col.update_one({"user_id": uid}, {"$set": {"reason": reason}}, upsert=True)
    await msg.reply(sc(f"globally banned {uid} 🚫"))

@router.message(Command("ungban"))
async def cmd_ungban(msg: Message):
    if not is_owner(msg.from_user.id):
        return
    parts = msg.text.split()
    try:
        uid = int(parts[1])
    except Exception:
        return await msg.reply(sc("/ungban [uid]"))
    banned_col.delete_one({"user_id": uid})
    await msg.reply(sc(f"unbanned {uid} ✅"))

# ══════════════════════════════════════════════════════════════════
#  DM AI CHAT
# ══════════════════════════════════════════════════════════════════
@router.message(F.chat.type == "private", F.text)
async def ai_chat(msg: Message):
    if msg.text.startswith("/"):
        return
    if await is_banned(msg.from_user.id):
        return
    ensure_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name)
    await msg.bot.send_chat_action(msg.chat.id, "typing")
    reply = await baka_reply(msg.text.strip(), msg.from_user.id)
    sent = await msg.reply(q(sc(reply)))
    schedule_delete(sent, 120)

# ══════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════
async def main():
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties())
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    await bot.set_my_commands([
        BotCommand(command="start", description="Bot start karo"),
        BotCommand(command="help", description="Help dekho"),
        BotCommand(command="kill", description="User ko kill (ban) karo"),
        BotCommand(command="ban", description="Ban karo"),
        BotCommand(command="unban", description="Unban karo"),
        BotCommand(command="daily", description="Daily reward"),
        BotCommand(command="work", description="Kaam karke coins"),
        BotCommand(command="crime", description="Crime karo"),
        BotCommand(command="rob", description="Rob karo"),
        BotCommand(command="wallet", description="Wallet dekho"),
        BotCommand(command="clear", description="History clear"),
    ])

    logger.info("=" * 50)
    logger.info("BAKA BOT LIVE!")
    logger.info(f"Owner: {OWNER_ID}")
    logger.info("=" * 50)

    await dp.start_polling(bot, drop_pending_updates=True)

if __name__ == "__main__":
    asyncio.run(main())