import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession
from dotenv import load_dotenv
import os

load_dotenv()

client = TelegramClient(
    StringSession(os.getenv("TELEGRAM_SESSION_STRING")),
    int(os.getenv("TELEGRAM_API_ID")),
    os.getenv("TELEGRAM_API_HASH"),
)

IGNORE = {"tutor_zelimhan", "brosky_manage", "nemok1rra", "kfanenshtil", "andruy28"}

async def main():
    await client.start()
    dialogs = await client.get_dialogs(limit=100)
    total_deleted = 0

    for d in dialogs:
        if not d.is_user or d.entity.bot:
            continue
        uname = (d.entity.username or "").lower()
        if uname in IGNORE:
            continue

        msgs = await client.get_messages(d.entity, limit=20)
        out_msgs = [(m.id, m.text or "") for m in msgs if m.out and m.text]

        to_delete = []
        seen_texts = set()
        for msg_id, text in out_msgs:
            key = text[:100]
            if key in seen_texts:
                to_delete.append(msg_id)
            else:
                seen_texts.add(key)

        if to_delete:
            name = d.entity.first_name or "?"
            await client.delete_messages(d.entity, to_delete)
            total_deleted += len(to_delete)
            print(f"  @{uname} ({name}): deleted {len(to_delete)} dupes")

    print(f"\nTotal deleted: {total_deleted}")
    await client.disconnect()

asyncio.run(main())
