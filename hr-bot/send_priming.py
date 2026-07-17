"""One-shot script to send priming messages to all approved candidates."""
import asyncio
import random
import sqlite3
import sys
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.messages import SetTypingRequest
from telethon.tl.types import SendMessageTypingAction, SendMessageCancelAction

API_ID = 36669184
API_HASH = "3976ae2af478e360569ecfc0cb728bfe"
DB_PATH = "candidates.db"

# Read session from .env
with open(".env") as f:
    for line in f:
        if line.startswith("TELEGRAM_SESSION_STRING="):
            SESSION = line.strip().split("=", 1)[1]
            break

client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)


async def simulate_typing(peer, text_length):
    chars_per_sec = random.uniform(3.5, 5.5)
    typing_time = text_length / chars_per_sec
    typing_time = max(5, min(typing_time, 120))
    num_chunks = random.randint(3, 6)
    chunk_times = []
    remaining = typing_time
    for i in range(num_chunks):
        if i == num_chunks - 1:
            chunk_times.append(remaining)
        else:
            chunk = remaining * random.uniform(0.15, 0.35)
            chunk_times.append(chunk)
            remaining -= chunk
    for i, ct in enumerate(chunk_times):
        try:
            await client(SetTypingRequest(peer=peer, action=SendMessageTypingAction()))
        except:
            pass
        await asyncio.sleep(ct)
        if i < len(chunk_times) - 1:
            try:
                await client(SetTypingRequest(peer=peer, action=SendMessageCancelAction()))
            except:
                pass
            pt = random.choice(["think", "reread", "short"])
            if pt == "think":
                await asyncio.sleep(random.uniform(2.0, 5.0))
            elif pt == "reread":
                await asyncio.sleep(random.uniform(1.5, 3.5))
            else:
                await asyncio.sleep(random.uniform(0.5, 1.5))


async def main():
    await client.start()
    print("Connected. Loading dialogs to cache entities...")

    # Load recent dialogs to populate entity cache
    dialogs = await client.get_dialogs(limit=200)
    print(f"Loaded {len(dialogs)} dialogs")

    # Build entity map from dialogs
    entity_map = {}
    for d in dialogs:
        if hasattr(d.entity, 'id'):
            entity_map[d.entity.id] = d.entity
            if hasattr(d.entity, 'username') and d.entity.username:
                entity_map[d.entity.username.lower()] = d.entity

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Get all unprocessed approved decisions from today
    rows = conn.execute(
        "SELECT * FROM manager_decisions WHERE processed = 0 AND decision = 'approved'"
    ).fetchall()
    print(f"Found {len(rows)} unprocessed approved decisions")

    for row in rows:
        d = dict(row)
        user_id = d["candidate_user_id"]

        # Get candidate info
        cand = conn.execute("SELECT * FROM candidates WHERE user_id = ?", (user_id,)).fetchone()
        if not cand:
            print(f"  SKIP: candidate {user_id} not found in DB")
            conn.execute("UPDATE manager_decisions SET processed = 1 WHERE id = ?", (d["id"],))
            conn.commit()
            continue

        cand = dict(cand)
        name = cand.get("name", "?")
        username = cand.get("username", "?").lstrip("@")
        print(f"\n--- Processing: {name} (@{username}, uid={user_id}) ---")

        # Find entity
        entity = entity_map.get(user_id) or entity_map.get(username.lower() if username else "")
        if not entity:
            print(f"  NOT in dialogs cache, trying resolve...")
            try:
                entity = await client.get_entity(username)
                print(f"  Resolved via username")
            except Exception as e:
                print(f"  FAILED to resolve: {e}")
                conn.execute("UPDATE manager_decisions SET processed = 1 WHERE id = ?", (d["id"],))
                conn.commit()
                continue

        # Send 3 priming messages
        try:
            msg1 = f"{name}, посмотрел вашу визитку - реально понравилось. Видно что вы увлечены предметом и умеете подать себя. Именно такой подход мы и ищем."
            print(f"  Typing msg1 ({len(msg1)} chars)...", flush=True)
            await simulate_typing(entity, len(msg1))
            await client.send_message(entity, msg1)
            print(f"  Sent msg1 ✓")

            await asyncio.sleep(random.uniform(5, 15))

            msg2 = (
                "Расскажу коротко как мы работаем.\n\n"
                "Мы обеспечиваем репетиторов учениками и берём на себя всю организацию: поиск, расчёты. "
                "Вы занимаетесь только преподаванием.\n\n"
                "Работаем с вашим аккаунтом на Профи.ру:\n"
                "- Полностью ведём профиль и откликаемся на заявки\n"
                "- Обеспечиваем стабильный поток учеников\n"
                "- Комиссию платформы платите вы, но мы помогаем её минимизировать. При досрочном уходе ученика комиссия пересчитывается\n"
                "- Все расчёты официально через ИП, вы как самозанятый\n\n"
                "Условия: вы получаете 75% от того что платит ученик. "
                "Ставка 2000р/час - на руки 1500р. Ставка 2500р - на руки 1875р.\n\n"
                "Аккаунт остаётся вашим, можете зайти в любой момент. "
                "Захотите уйти - вернём доступ за 24 часа."
            )
            print(f"  Typing msg2 ({len(msg2)} chars)...", flush=True)
            await simulate_typing(entity, len(msg2))
            await client.send_message(entity, msg2)
            print(f"  Sent msg2 ✓")

            await asyncio.sleep(random.uniform(3, 8))

            msg3 = "Хочу познакомиться поближе и обсудить детали. Когда вам удобно созвониться на 30-40 минут - сегодня или завтра?"
            print(f"  Typing msg3 ({len(msg3)} chars)...", flush=True)
            await simulate_typing(entity, len(msg3))
            await client.send_message(entity, msg3)
            print(f"  Sent msg3 ✓")

            # Update DB
            import json
            conv = json.loads(cand.get("conversation", "[]"))
            conv.append({"role": "bot", "content": msg1})
            conv.append({"role": "bot", "content": msg2})
            conv.append({"role": "bot", "content": msg3})
            conn.execute(
                "UPDATE candidates SET status='ГОТОВ_К_СОЗВОНУ', conversation=?, updated_at=datetime('now') WHERE user_id=?",
                (json.dumps(conv, ensure_ascii=False), user_id)
            )
            print(f"  Status -> ГОТОВ_К_СОЗВОНУ ✓")

        except Exception as e:
            print(f"  ERROR sending: {e}")

        conn.execute("UPDATE manager_decisions SET processed = 1 WHERE id = ?", (d["id"],))
        conn.commit()
        print(f"  Done with {name}")

    conn.close()
    print("\n=== All done ===")


with client:
    client.loop.run_until_complete(main())
