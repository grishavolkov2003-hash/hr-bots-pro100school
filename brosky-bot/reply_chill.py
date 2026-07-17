import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession
from dotenv import load_dotenv
import os, sqlite3, json
from llm import get_response
from storage import get_candidate, get_conversation, add_message, update_candidate

load_dotenv()

client = TelegramClient(
    StringSession(os.getenv("TELEGRAM_SESSION_STRING")),
    int(os.getenv("TELEGRAM_API_ID")),
    os.getenv("TELEGRAM_API_HASH"),
)

async def main():
    await client.start()

    candidate = get_candidate(1771292017)
    if not candidate:
        print("Not found!")
        return

    conv = get_conversation(1771292017)
    print(f"Candidate: {candidate['name']} | Status: {candidate['status']} | Conv: {len(conv)}")

    response = get_response(conv, candidate)
    if response:
        # Strip signals
        import re
        clean = re.sub(r'>>>.*?<<<', '', response).strip()
        if clean:
            await client.send_message("always_on_chill", clean)
            add_message(1771292017, "bot", clean)
            print(f"Sent: {clean[:100]}")
    else:
        print("No LLM response")

    await client.disconnect()

asyncio.run(main())
