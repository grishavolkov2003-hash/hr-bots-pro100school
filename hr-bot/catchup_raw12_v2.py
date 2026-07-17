import asyncio, sys, os, sqlite3
sys.path.insert(0, '/opt/hr-bot')
env = dict(line.strip().split('=', 1) for line in open('/opt/hr-bot/.env') if '=' in line and not line.startswith('#'))
os.environ.update(env)

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import InputPeerUser

import main as botmain
from storage import get_candidate, update_access_hash, get_conversation, add_message

IDS = [837520215, 6156213808, 1925056823, 5551723270, 1770458529, 1121790107, 5242225668, 283784212, 1092489809, 802402334]  # без Nandi (уже обработан)

DB_PATH = '/opt/hr-bot/candidates.db'


async def warm(client, uid):
    conn = sqlite3.connect(DB_PATH, timeout=10)
    row = conn.execute("SELECT access_hash, username FROM candidates WHERE user_id=?", (uid,)).fetchone()
    conn.close()
    if row and row[0]:
        try:
            peer = InputPeerUser(user_id=uid, access_hash=row[0])
            return await client.get_entity(peer)
        except Exception:
            pass
    if row and row[1]:
        try:
            entity = await client.get_entity(row[1].lstrip('@'))
            update_access_hash(uid, entity.access_hash)
            return entity
        except Exception:
            pass
    try:
        return await client.get_entity(uid)
    except Exception:
        return None


async def run():
    my_client = TelegramClient(StringSession(env['TELEGRAM_SESSION_STRING']),
                                int(env['TELEGRAM_API_ID']), env['TELEGRAM_API_HASH'])
    await my_client.connect()
    botmain.client = my_client

    done, failed = 0, 0
    for uid in IDS:
        candidate = get_candidate(uid)
        if not candidate:
            print(f"{uid}: не найден")
            continue
        name = candidate.get('name') or ''
        username = candidate.get('username') or ''

        entity = await warm(my_client, uid)
        if not entity:
            print(f"  {uid} {name}: НЕ РЕЗОЛВИТСЯ", flush=True)
            failed += 1
            continue

        # Проверяем, есть ли расхождение между БД и реальным Telegram
        conv = get_conversation(uid)
        db_last_role = conv[-1]['role'] if conv else None

        try:
            real_msgs = await my_client.get_messages(entity, limit=5)
            # Собираем непрочитанные сообщения от кандидата (те, что не 'out') в хронологии
            missing = []
            for m in reversed(real_msgs):
                if not m.out and m.text:
                    missing.append(m.text)
            if db_last_role == 'bot' and missing:
                # Догоняем историю недостающими сообщениями кандидата
                combined = "\n".join(missing[-3:])  # последние несколько на случай нескольких сообщений подряд
                add_message(uid, "candidate", combined)
                print(f"  {uid} {name}: догнал историю ({len(missing)} сообщ.)", flush=True)
        except Exception as e:
            print(f"  {uid} {name}: ошибка чтения истории Telegram: {e}", flush=True)

        candidate = get_candidate(uid)  # перечитать после возможного add_message

        try:
            await botmain._do_process(uid, username, name, uid, candidate)
            done += 1
            print(f"  {name} ({username}): OK ({done+failed}/{len(IDS)})", flush=True)
        except Exception as e:
            failed += 1
            print(f"  {uid} {name}: ОШИБКА: {e}", flush=True)

        await asyncio.sleep(2)

    await my_client.disconnect()
    print(f"Готово. Успешно: {done}, ошибок: {failed}", flush=True)


asyncio.run(run())
