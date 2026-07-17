import sys, sqlite3, asyncio
sys.path.insert(0, '/opt/brosky-bot')
from telethon import TelegramClient
from telethon.sessions import StringSession
from config import TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_SESSION_STRING, DB_PATH

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
rows = conn.execute(
    "SELECT user_id, name, username, status FROM candidates WHERE status IN ('ПЕРЕДАН_МЕНЕДЖЕРУ','СОЗВОН_НАЗНАЧЕН','ДОГОВОР_ОТПРАВЛЕН') ORDER BY updated_at DESC LIMIT 8"
).fetchall()
conn.close()

client = TelegramClient(StringSession(TELEGRAM_SESSION_STRING), TELEGRAM_API_ID, TELEGRAM_API_HASH)

async def main():
    await client.start()
    for r in rows:
        print(f"\n========== {r['name']} ({r['username']}) | статус={r['status']} ==========")
        try:
            entity = await client.get_entity(r['user_id'])
            messages = await client.get_messages(entity, limit=20)
            for m in reversed(messages):
                who = "БРОСКИ" if m.out else "КАНДИДАТ"
                text = (m.text or "[медиа/файл]")[:250]
                print(f"[{who}] {text}")
        except Exception as e:
            print(f"  Не удалось прочитать: {e}")
    await client.disconnect()

asyncio.run(main())
