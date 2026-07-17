import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession
from dotenv import load_dotenv
import os, sqlite3, json

load_dotenv()

client = TelegramClient(
    StringSession(os.getenv("TELEGRAM_SESSION_STRING")),
    int(os.getenv("TELEGRAM_API_ID")),
    os.getenv("TELEGRAM_API_HASH"),
)

IGNORE = {"tutor_zelimhan", "brosky_manage", "nemok1rra", "kfanenshtil", "andruy28",
          "pro100school_manager", "groupanonymousbot", "channel_bot", "telegram",
          "pro100hrbot", "igorkopylov1", "managman121", "duh_poligona",
          "iliya_999999", "hobyaka", "wh3teee", "chateaulafite_e", "iveze",
          "el_sstell", "wenatt", "arcosinus", "amirhansh", "mkoshkina",
          "osipovvvns", "crranberry24", "ss_s_r", "diasshhha17", "marynik13",
          "melbezi", "hadllee", "floiru", "jmih_pojil", "alinss06",
          "sonia_popova", "wildmaxxxx", "alchemistalehandro", "aashanfr",
          "saybesk", "dianatokmakova", "eyesonjewelry", "slaskalsls",
          "evuyan", "la_si_enne", "darkext", "x9micexd"}

async def main():
    await client.start()
    dialogs = await client.get_dialogs(limit=300)

    unanswered = []

    for d in dialogs:
        if not d.is_user or d.entity.bot:
            continue
        uname = (d.entity.username or "").lower()
        if uname in IGNORE:
            continue

        msgs = await client.get_messages(d.entity, limit=5)
        if not msgs:
            continue

        last = msgs[0]
        if last.out:
            continue

        # Last message is from candidate - brosky hasn't replied
        name = (d.entity.first_name or "") + (" " + (d.entity.last_name or "")).rstrip()
        last_text = (last.text or "[media]")[:100]
        hours = 0
        if last.date:
            from datetime import datetime, timezone
            hours = (datetime.now(timezone.utc) - last.date).total_seconds() / 3600

        unanswered.append({
            "uname": uname or "?",
            "name": name,
            "hours": hours,
            "text": last_text,
            "uid": d.entity.id,
        })

    unanswered.sort(key=lambda x: -x["hours"])

    print(f"=== БРОУСКИ НЕ ОТВЕТИЛ ({len(unanswered)}) ===\n")
    for e in unanswered:
        h = e["hours"]
        icon = "🔴" if h >= 72 else "🟡" if h >= 48 else "🟠" if h >= 24 else "⚪"
        print(f"  {icon} @{e['uname']} ({e['name']}) | {h:.0f}ч назад")
        print(f"      > {e['text']}")
        print()

    await client.disconnect()

asyncio.run(main())
