import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession
from dotenv import load_dotenv
import os, sqlite3

load_dotenv()

client = TelegramClient(
    StringSession(os.getenv("TELEGRAM_SESSION_STRING")),
    int(os.getenv("TELEGRAM_API_ID")),
    os.getenv("TELEGRAM_API_HASH"),
)

IGNORE = {"tutor_zelimhan", "brosky_manage", "nemok1rra", "kfanenshtil", "andruy28",
          "pro100school_manager", "groupanonymousbot", "channel_bot", "telegram",
          "pro100hrbot", "igorkopylov1"}

async def main():
    await client.start()
    dialogs = await client.get_dialogs(limit=300)

    conn = sqlite3.connect("candidates.db")
    db_uids = set()
    rows = conn.execute("SELECT user_id FROM candidates").fetchall()
    for r in rows:
        db_uids.add(r[0])
    conn.close()

    in_db = []
    not_in_db = []

    for d in dialogs:
        if not d.is_user or d.entity.bot:
            continue
        uname = (d.entity.username or "").lower()
        if uname in IGNORE:
            continue

        uid = d.entity.id
        name = (d.entity.first_name or "") + (" " + (d.entity.last_name or "")).rstrip()

        msgs = await client.get_messages(d.entity, limit=5)
        last_texts = []
        for m in msgs[:3]:
            prefix = "OUT" if m.out else "IN"
            t = (m.text or "[media]")[:80]
            last_texts.append(f"[{prefix}] {t}")

        if uid in db_uids:
            in_db.append({"name": name, "uname": uname, "msgs": last_texts})
        else:
            not_in_db.append({"name": name, "uname": uname, "uid": uid, "msgs": last_texts, "unread": d.unread_count})

    print(f"=== В БД ({len(in_db)}): ===")
    for e in in_db:
        print(f"  @{e['uname']} ({e['name']})")

    print(f"\n=== НЕТ В БД ({len(not_in_db)}): ===")
    for e in not_in_db:
        print(f"  @{e['uname']} ({e['name']}) uid={e['uid']} unread={e['unread']}")
        for t in e["msgs"]:
            print(f"    {t}")
        print()

    await client.disconnect()

asyncio.run(main())
