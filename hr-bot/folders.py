import asyncio
import sqlite3

from telethon.tl.functions.messages import UpdateDialogFilterRequest
from telethon.tl.types import DialogFilter, InputPeerUser, TextWithEntities

try:
    from config import DB_PATH
except ImportError:
    DB_PATH = "/opt/hr-bot/candidates.db"

FOLDER_DEFS = [
    (11, "🆕 Новые",           ["НОВЫЙ"]),
    (12, "📤 Тестовое",        ["ТЕСТОВОЕ_ОТПРАВЛЕНО", "ТЕСТОВОЕ_ПОЛУЧЕНО", "ТЕСТОВОЕ_НА_ПРОВЕРКЕ"]),
    (21, "📞 К созвону",      ["ГОТОВ_К_СОЗВОНУ"]),
    (22, "👔 У Броского",     ["ПЕРЕДАН_МЕНЕДЖЕРУ"]),
    (15, "📅 Созвон",          ["СОЗВОН_НАЗНАЧЕН"]),
    (23, "📝 Договор",         ["ДОГОВОР_ОТПРАВЛЕН"]),
    (17, "🔑 Аккаунт",         ["АККАУНТ_ПОЛУЧЕН"]),
    (18, "✅ Открыт",          ["ОТКРЫТ"]),
    (19, "❄️ Заморозка",       ["ЗАМОРОЗКА"]),
    (20, "❌ Отказ",           ["ОТКАЗ"]),
]

STATUS_TO_FOLDER_ID = {
    status: fid
    for fid, _, statuses in FOLDER_DEFS
    for status in statuses
}


def _db_candidates():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT user_id, status, access_hash FROM candidates WHERE status IS NOT NULL"
    ).fetchall()
    conn.close()
    return rows


async def _resolve_peers(client, candidates):
    """candidates: list of (user_id, access_hash)"""
    peers = []
    for uid, ah in candidates:
        uid = int(uid)
        ah = ah or 0
        if ah:
            # Знаем access_hash — строим InputPeerUser напрямую
            peers.append(InputPeerUser(user_id=uid, access_hash=ah))
        else:
            # Нет access_hash — пробуем через кэш
            try:
                peer = await client.get_input_entity(uid)
                peers.append(peer)
            except Exception:
                pass
    return peers


def _make_filter(fid, title_str, peers):
    return DialogFilter(
        id=fid,
        title=TextWithEntities(text=title_str, entities=[]),
        pinned_peers=[],
        include_peers=peers,
        exclude_peers=[],
        contacts=False,
        non_contacts=False,
        groups=False,
        broadcasts=False,
        bots=False,
        exclude_muted=False,
        exclude_read=False,
        exclude_archived=False,
    )


async def _update_folder(client, fid, title_str, peers):
    """Обновляет папку. При ошибке — пробует по одному, пропуская проблемных."""
    try:
        await client(UpdateDialogFilterRequest(id=fid, filter=_make_filter(fid, title_str, peers)))
        return len(peers)
    except Exception:
        good = []
        for p in peers:
            try:
                await client(UpdateDialogFilterRequest(id=fid, filter=_make_filter(fid, title_str, good + [p])))
                good.append(p)
            except Exception:
                uid = getattr(p, 'user_id', '?')
                print(f"[folders] Пропускаем пира uid={uid} в '{title_str}'", flush=True)
            await asyncio.sleep(0.1)
        if good:
            await client(UpdateDialogFilterRequest(id=fid, filter=_make_filter(fid, title_str, good)))
        return len(good)


async def sync_all_folders(client):
    candidates = _db_candidates()

    folder_candidates = {fid: [] for fid, _, _ in FOLDER_DEFS}
    for c in candidates:
        fid = STATUS_TO_FOLDER_ID.get(c["status"])
        if fid:
            folder_candidates[fid].append((c["user_id"], c["access_hash"]))

    for fid, title_str, _ in FOLDER_DEFS:
        try:
            peers = await _resolve_peers(client, folder_candidates[fid])

            if not peers:
                print(f"[folders] '{title_str}': пусто или нет entity, пропускаем", flush=True)
                continue

            count = await _update_folder(client, fid, title_str, peers)
            print(f"[folders] '{title_str}': {count}/{len(peers)} чат(ов)", flush=True)

        except Exception as e:
            print(f"[folders] Ошибка '{title_str}': {e}", flush=True)

        await asyncio.sleep(0.3)

    print("[folders] Синк завершён", flush=True)


def trigger_sync(event: asyncio.Event):
    event.set()


async def folder_sync_loop(client, event: asyncio.Event, periodic_sec=300):
    await asyncio.sleep(40)
    print("[folders] Начальный синк...", flush=True)
    try:
        await sync_all_folders(client)
    except Exception as e:
        print(f"[folders] Начальный синк ошибка: {e}", flush=True)

    while True:
        try:
            await asyncio.wait_for(event.wait(), timeout=periodic_sec)
            await asyncio.sleep(5)
            event.clear()
        except asyncio.TimeoutError:
            pass
        try:
            await sync_all_folders(client)
        except Exception as e:
            print(f"[folders] Синк ошибка: {e}", flush=True)
