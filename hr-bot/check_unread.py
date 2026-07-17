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
          "GroupAnonymousBot", "Channel_Bot", "Telegram", "telegram"}

async def main():
    await client.start()
    dialogs = await client.get_dialogs(limit=300)

    conn = sqlite3.connect("candidates.db")
    conn.row_factory = sqlite3.Row

    db_uids = set()
    rows = conn.execute("SELECT user_id FROM candidates").fetchall()
    for r in rows:
        db_uids.add(r["user_id"])

    unread = []
    new_people = []

    for d in dialogs:
        if not d.is_user or d.entity.bot:
            continue
        uname = (d.entity.username or "").lower()
        if uname in IGNORE:
            continue
        if d.unread_count == 0:
            continue

        uid = d.entity.id
        name = (d.entity.first_name or "") + (" " + (d.entity.last_name or "")).rstrip()
        username = d.entity.username or ""

        msgs = await client.get_messages(d.entity, limit=5)
        last_texts = []
        for m in msgs:
            if m.out:
                break
            t = m.text or "[media]"
            last_texts.append(t[:100])

        in_db = uid in db_uids

        entry = {
            "uid": uid,
            "name": name,
            "username": username,
            "unread": d.unread_count,
            "in_db": in_db,
            "last_msgs": last_texts,
        }

        if in_db:
            r = conn.execute("SELECT status FROM candidates WHERE user_id = ?", (uid,)).fetchone()
            entry["status"] = r["status"] if r else "?"
            unread.append(entry)
        else:
            new_people.append(entry)

    print(f"=== НЕПРОЧИТАННЫЕ (уже в БД): {len(unread)} ===")
    for e in unread:
        print(f"  @{e['username']} ({e['name']}) | {e['status']} | unread: {e['unread']}")
        for t in e['last_msgs'][:2]:
            print(f"    > {t}")

    print(f"\n=== НОВЫЕ ЛЮДИ (нет в БД): {len(new_people)} ===")
    for e in new_people:
        print(f"  @{e['username']} ({e['name']}) | unread: {e['unread']}")
        for t in e['last_msgs'][:2]:
            print(f"    > {t}")

    conn.close()
    await client.disconnect()

asyncio.run(main())
