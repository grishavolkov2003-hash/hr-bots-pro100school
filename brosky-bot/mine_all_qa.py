import sys, sqlite3, asyncio
sys.path.insert(0, '/opt/brosky-bot')
from telethon import TelegramClient
from telethon.sessions import StringSession
from config import TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_SESSION_STRING, DB_PATH

STATUSES = ('ПЕРЕДАН_МЕНЕДЖЕРУ', 'СОЗВОН_НАЗНАЧЕН', 'ДОГОВОР_ОТПРАВЛЕН', 'АККАУНТ_ПОЛУЧЕН', 'ОТКРЫТ')

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
rows = conn.execute(
    f"SELECT user_id, name, username, status FROM candidates WHERE status IN {STATUSES} ORDER BY updated_at DESC"
).fetchall()
conn.close()

print(f"Всего кандидатов для сканирования: {len(rows)}", file=sys.stderr)

client = TelegramClient(StringSession(TELEGRAM_SESSION_STRING), TELEGRAM_API_ID, TELEGRAM_API_HASH)

async def main():
    await client.start()
    qa_pairs = []
    scanned = 0
    failed = 0

    for r in rows:
        try:
            entity = await client.get_entity(r['user_id'])
            messages = await client.get_messages(entity, limit=60)
            messages = list(reversed(messages))
            scanned += 1

            for i, m in enumerate(messages):
                if m.out:
                    continue
                text = (m.text or "").strip()
                if len(text) < 15 or '?' not in text:
                    continue
                # ищем ответ Броски после этого сообщения
                reply_texts = []
                for m2 in messages[i+1:i+4]:
                    if m2.out and m2.text:
                        reply_texts.append(m2.text.strip())
                    elif not m2.out:
                        break
                if reply_texts:
                    qa_pairs.append({
                        'candidate': r['name'],
                        'question': text[:500],
                        'answer': " / ".join(reply_texts)[:800],
                    })
        except Exception as e:
            failed += 1
        await asyncio.sleep(0.3)

    print(f"Просканировано: {scanned}, не удалось прочитать: {failed}", file=sys.stderr)
    print(f"Найдено Q&A пар: {len(qa_pairs)}", file=sys.stderr)

    for qa in qa_pairs:
        print(f"\n### {qa['candidate']}")
        print(f"В: {qa['question']}")
        print(f"О: {qa['answer']}")

    await client.disconnect()

asyncio.run(main())
