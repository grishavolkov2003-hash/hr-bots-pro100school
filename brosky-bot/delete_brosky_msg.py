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

async def main():
    await client.start()

    # Find last outgoing messages to XKsesss0
    msgs = await client.get_messages("XKsesss0", limit=10)
    for m in msgs:
        prefix = "OUT" if m.out else "IN"
        t = (m.text or "[media]")[:100]
        print(f"  [{prefix}] id={m.id} | {t}")

    # Delete our outgoing messages that are garbage
    to_delete = []
    for m in msgs:
        if m.out and m.text:
            if "коллега подтвердит" in m.text or "Спасибо, Ксения" in m.text:
                to_delete.append(m.id)
                print(f"  -> Will delete: {m.text[:80]}")

    if to_delete:
        await client.delete_messages("XKsesss0", to_delete)
        print(f"\nDeleted {len(to_delete)} messages from Telegram")
    else:
        print("\nNothing to delete")

    await client.disconnect()

asyncio.run(main())
