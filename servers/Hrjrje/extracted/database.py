# language: Python, file: database.py, runtime: 3.10+
import json
import os
import time
from config import DB_FILE

def _load() -> dict:
    if not os.path.exists(DB_FILE):
        return {
            "firebase_accounts": [],
            "users": {},
            "referrals": {},
            "settings": {
                "page_size": 6,
                "force_channel": "",
                "force_channel_link": "",
                "referral_hours": 1,
            },
            "stats": {"total_otps": 0, "total_devices": 0},
            "join_requests": {},
        }
    with open(DB_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("referrals", {})
    data.setdefault("settings", {})
    data.setdefault("users", {})
    data.setdefault("firebase_accounts", [])
    data.setdefault("join_requests", {})
    return data

def _save(data: dict) -> None:
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def get_all() -> dict:
    return _load()

# NAYA FUNCTION BROADCAST KE LIYE
def get_all_users() -> list:
    data = _load()
    return [int(uid) for uid in data.get("users", {}).keys()]

def add_firebase(name: str, url: str, key: str) -> bool:
    data = _load()
    for acc in data["firebase_accounts"]:
        if acc["url"] == url:
            return False
    data["firebase_accounts"].append({
        "id": f"fb_{int(time.time())}",
        "name": name,
        "url": url.rstrip("/"),
        "key": key,
        "added_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "active": True,
    })
    _save(data)
    return True

def remove_firebase(fb_id: str) -> bool:
    data = _load()
    before = len(data["firebase_accounts"])
    data["firebase_accounts"] = [a for a in data["firebase_accounts"] if a["id"] != fb_id]
    _save(data)
    return len(data["firebase_accounts"]) < before

def list_firebase() -> list:
    return _load()["firebase_accounts"]

def get_firebase(fb_id: str) -> dict | None:
    for a in _load()["firebase_accounts"]:
        if a["id"] == fb_id:
            return a
    return None

def set_user_access(user_id: int, hours: float = 24) -> None:
    data = _load()
    uid = str(user_id)
    now = time.time()
    u = data["users"].get(uid, {})
    current_expire = u.get("expire", 0)
    base = max(now, current_expire)
    data["users"][uid] = {
        "expire": base + hours * 3600,
        "granted_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "referrer": u.get("referrer"),
        "ref_count": u.get("ref_count", 0),
    }
    _save(data)

def add_hours(user_id: int, hours: float) -> None:
    set_user_access(user_id, hours)

def check_access(user_id: int, admin_ids: list) -> bool:
    if user_id in admin_ids:
        return True
    data = _load()
    u = data["users"].get(str(user_id))
    if not u:
        return False
    return time.time() < u.get("expire", 0)

def get_access_left(user_id: int) -> str:
    data = _load()
    u = data["users"].get(str(user_id))
    if not u:
        return "0h 0m"
    left = max(0, u["expire"] - time.time())
    h = int(left // 3600)
    m = int((left % 3600) // 60)
    return f"{h}h {m}m"

def register_referral(new_user_id: int, referrer_id: int) -> bool:
    if new_user_id == referrer_id:
        return False
    data = _load()
    uid = str(new_user_id)
    rid = str(referrer_id)

    if uid in data.get("users", {}):
        u = data["users"][uid]
        if u.get("referrer") or u.get("expire", 0) or u.get("seen"):
            return False

    u = data["users"].setdefault(uid, {"expire": 0, "ref_count": 0})
    if u.get("referrer"):
        return False
    u["referrer"] = referrer_id
    u["seen"] = True
    u["ref_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    u.setdefault("granted_at", u["ref_at"])

    r = data["users"].setdefault(rid, {"expire": 0, "ref_count": 0})
    refs = data.setdefault("referrals", {}).setdefault(rid, [])
    if new_user_id in refs:
        return False
    refs.append(new_user_id)
    r["ref_count"] = len(refs)
    _save(data)
    return True

def mark_user_seen(user_id: int) -> None:
    data = _load()
    uid = str(user_id)
    u = data["users"].setdefault(uid, {"expire": 0, "ref_count": 0})
    u["seen"] = True
    _save(data)

def get_ref_stats(user_id: int) -> dict:
    data = _load()
    u = data["users"].get(str(user_id), {})
    refs = data.get("referrals", {}).get(str(user_id), [])
    return {
        "count": u.get("ref_count", len(refs)),
        "refs": refs,
    }

def get_settings() -> dict:
    return _load().get("settings", {})

def set_setting(key: str, value) -> None:
    data = _load()
    data.setdefault("settings", {})[key] = value
    _save(data)

def update_stats(devices: int, otps: int) -> None:
    data = _load()
    data["stats"]["total_devices"] = devices
    data["stats"]["total_otps"] = otps
    _save(data)

def get_stats() -> dict:
    return _load().get("stats", {})

def list_force_channels() -> list:
    data = _load()
    chans = data.get("settings", {}).get("force_channels")
    if isinstance(chans, list) and chans:
        return chans
    old = (data.get("settings") or {}).get("force_channel") or ""
    old_link = (data.get("settings") or {}).get("force_channel_link") or ""
    if old:
        chans = [{"id": "ch_legacy", "username": old, "link": old_link, "mode": "normal", "title": old}]
        data.setdefault("settings", {})["force_channels"] = chans
        _save(data)
        return chans
    return []

def add_force_channel(title: str, chat_id: int, link: str = "", mode: str = "normal") -> dict:
    data = _load()
    chans = data.setdefault("settings", {}).setdefault("force_channels", [])
    if not isinstance(chans, list):
        chans = []
        data["settings"]["force_channels"] = chans
    
    for c in chans:
        if c.get("chat_id") == chat_id:
            c["link"] = link or c.get("link", "")
            c["mode"] = mode
            c["title"] = title
            _save(data)
            return c
            
    item = {
        "id": f"ch_{int(time.time())}", 
        "title": title, 
        "chat_id": chat_id, 
        "username": str(chat_id), 
        "link": link, 
        "mode": mode
    }
    chans.append(item)
    _save(data)
    return item

def remove_force_channel(ch_id: str) -> bool:
    data = _load()
    chans = data.get("settings", {}).get("force_channels") or []
    before = len(chans)
    chans = [c for c in chans if c.get("id") != ch_id]
    data.setdefault("settings", {})["force_channels"] = chans
    if not chans:
        data["settings"]["force_channel"] = ""
        data["settings"]["force_channel_link"] = ""
    _save(data)
    return len(chans) < before

def grant_start_bonus(user_id: int, minutes: float = 10) -> bool:
    data = _load()
    uid = str(user_id)
    u = data["users"].setdefault(uid, {"expire": 0, "ref_count": 0})
    if u.get("start_bonus"):
        return False
    now = time.time()
    base = max(now, u.get("expire", 0))
    u["expire"] = base + minutes * 60
    u["start_bonus"] = True
    u["seen"] = True
    u["granted_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _save(data)
    return True

# --- JOIN REQUEST TRACKING ---
def save_join_request(user_id: int, chat_id: int):
    data = _load()
    reqs = data.setdefault("join_requests", {})
    chat_str = str(chat_id)
    if chat_str not in reqs:
        reqs[chat_str] = []
    if user_id not in reqs[chat_str]:
        reqs[chat_str].append(user_id)
        _save(data)

def has_requested(user_id: int, chat_id: int) -> bool:
    data = _load()
    reqs = data.get("join_requests", {}).get(str(chat_id), [])
    return user_id in reqs

def clear_join_request(user_id: int, chat_id: int):
    data = _load()
    reqs = data.get("join_requests", {}).get(str(chat_id), [])
    if user_id in reqs:
        reqs.remove(user_id)
        _save(data)