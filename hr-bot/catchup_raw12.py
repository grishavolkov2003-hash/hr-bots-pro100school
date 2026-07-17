import asyncio, sys, os, sqlite3
sys.path.insert(0, '/opt/hr-bot')
env = dict(line.strip().split('=', 1) for line in open('/opt/hr-bot/.env') if '=' in line and not line.startswith('#'))
os.environ.update(env)

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import InputPeerUser

import main as botmain
from storage import get_candidate, update_access_hash

IDS = [863603294, 1321439954, 5802653810, 6483486167, 856566904, 894952012, 1049854116, 5179078412, 1143363080, 628942584, 824057662, 2048067555]

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
