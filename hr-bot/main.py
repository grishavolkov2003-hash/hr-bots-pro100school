import random
import asyncio
import folders as _folders
import re
import os
import io
import sqlite3
from datetime import datetime, timedelta
from telethon import TelegramClient, events
from telethon.tl.functions.messages import SetTypingRequest
from telethon.tl.types import SendMessageTypingAction, SendMessageCancelAction
from telethon.sessions import StringSession
from config import (
    TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_SESSION_STRING,
    MANAGER_USERNAME, ZADANIE_PATH, DB_PATH,
)
from storage import (
    init_db, get_candidate, create_candidate, add_message, update_conversation_bot,
    update_candidate, get_conversation, get_all_candidates,
    get_stale_candidates, update_access_hash,
)
from llm import get_response, get_manager_response
import sheets as sheets_module
from sheets import add_candidate as sheets_add, update_status, update_anketa, update_score

client = TelegramClient(
    StringSession(TELEGRAM_SESSION_STRING),
    TELEGRAM_API_ID,
    TELEGRAM_API_HASH,
)

SIGNAL_PATTERN = re.compile(r">>>\s*СИГНАЛ МЕНЕДЖЕРУ:\s*(.+?)<<<", re.DOTALL)
FILE_PATTERN = re.compile(r">>>\s*ОТПРАВИТЬ_ФАЙЛ:\s*(\S+)\s*<<<")
ANKETA_PATTERN = re.compile(r">>>\s*АНКЕТА:\s*(.+?)<<<", re.DOTALL)
STATUS_PATTERN = re.compile(r">>>\s*СТАТУС:\s*(\S+)\s*<<<")
SCORE_PATTERN = re.compile(r">>>\s*СКОР:\s*(\d+)\s*<<<")
CREDS_PATTERN = re.compile(r"(?i)(?:логин|login)\s*[:=\-]?\s*(\S+)[\s\n]+(?:пароль|password|pass)\s*[:=\-]?\s*(\S+)")

VALID_STATUSES = {
    "НОВЫЙ", "ТЕСТОВОЕ_ОТПРАВЛЕНО", "ТЕСТОВОЕ_ПОЛУЧЕНО", "ТЕСТОВОЕ_НА_ПРОВЕРКЕ",
    "ГОТОВ_К_СОЗВОНУ", "ПЕРЕДАН_МЕНЕДЖЕРУ", "СОЗВОН_НАЗНАЧЕН", "ДОГОВОР_ОТПРАВЛЕН",
    "ДОГОВОР_ПОДПИСАН", "АККАУНТ_ПОЛУЧЕН", "ОТКРЫТ", "ОТКАЗ", "ЗАМОРОЗКА",
}

IGNORE_USERS = {"tutor_zelimhan", "brosky_manage", "nemok1rra", "kfanenshtil", "andruy28"}
INSTANT_USERS = {"ooot345266", "igorkopylov1"}
BROSKY_ID = 8009920862

# Debounce — собираем сообщения в пачку перед ответом
_pending_messages = {}  # user_id -> asyncio.Task
_message_buffer = {}    # user_id -> list of texts
_active_responding = set()  # user_id's currently being responded to (event or patrol)

_folder_event = asyncio.Event()
IGNORE_STATUSES = {"ОТКАЗ", "АККАУНТ_ПОЛУЧЕН", "ОТКРЫТ", "СОЗВОН_НАЗНАЧЕН", "ГОТОВ_К_СОЗВОНУ", "ПЕРЕДАН_МЕНЕДЖЕРУ", "ДОГОВОР_ОТПРАВЛЕН", "ДОГОВОР_ПОДПИСАН"}

GARBAGE_MARKERS = [
    "I'm a coding", "coding-focused", "I can only help with software",
    "ПРЕДПОЛЁТНАЯ ПРОВЕРКА", "ПРЕДПОЛЕТНАЯ ПРОВЕРКА",
    "getSchedule()", "```python", "```js", "```bash",
    "I am Claude", "I'm Claude", "As an AI",
    "Let me analyze", "conversation history", "pre-flight check",
    "Here's my", "I'll respond", "Based on the",
    "Thinking Process",
]

# Барьер против дублей: точечная защита, вызывается ТОЛЬКО из
# _do_process/_patrol_respond непосредственно перед отправкой, НЕ является
# глобальной обёрткой над client.send_message и НЕ применяется к decision_loop
# (там легитимные многошаговые каскады сообщений подряд).
# N=50 сек: typing-симуляция упирается в потолок 30 сек + паузы 2-8 сек
# + сетевые задержки - реалистичный максимум ~35-40 сек, запас до 50.
DUPLICATE_GUARD_WINDOW_SEC = 50


def _recently_sent(user_id):
    """Был ли уже отправлен ЛЮБОЙ ответ этому кандидату за последние
    DUPLICATE_GUARD_WINDOW_SEC секунд, независимо от текста - защита от
    гонок (TOCTOU в patrol_loop, необязанная .cancel() в дебаунсе), а не
    от повторения конкретной фразы."""
    conversation = get_conversation(user_id)
    bot_msgs = [m for m in conversation if m.get("role") == "bot"]
    if not bot_msgs:
        return False
    last_time = bot_msgs[-1].get("time", "")
    if not last_time:
        return False
    try:
        last_dt = datetime.fromisoformat(last_time)
        return (datetime.now() - last_dt).total_seconds() < DUPLICATE_GUARD_WINDOW_SEC
    except Exception:
        return False




def parse_anketa(raw):
    data = {}
    for pair in raw.split("|"):
        if "=" in pair:
            k, v = pair.split("=", 1)
            data[k.strip()] = v.strip()
    return data


NO_EXPERIENCE_MARKERS = ["нет", "без опыта", "не было", "отсутствует", "не имею"]


def evaluate_auto_criteria(anketa):
    """Автоотбор по анкете: ЕГЭ >= 60 (если сдавал) + опыт > 0 + возраст >= 18.

    Поля не по формату (без цифр, старая анкета без вопроса о возрасте) не должны
    блокировать явно сильных кандидатов - там где нет прямого "нет"/явно малого
    возраста, критерий считается пройденным.
    """
    reasons = []

    ege_raw = (anketa.get("егэ") or "").strip().lower()
    ege_nums = re.findall(r'\d+', ege_raw)
    if ege_nums:
        ege_ok = int(ege_nums[0]) >= 60
    else:
        # цифр нет - "не сдавал" или просто не указано, критерий условный, не блокируем
        ege_ok = True
    if not ege_ok:
        reasons.append(f"ЕГЭ={ege_raw or '?'}")

    exp_raw = (anketa.get("опыт") or "").strip().lower()
    exp_nums = re.findall(r'\d+', exp_raw)
    if exp_nums:
        exp_ok = int(exp_nums[0]) > 0
    elif any(m in exp_raw for m in NO_EXPERIENCE_MARKERS):
        exp_ok = False
    else:
        # без цифр, но и без явного отказа ("около года", "пару лет") - считаем что опыт есть
        exp_ok = bool(exp_raw) and exp_raw != "-"
    if not exp_ok:
        reasons.append(f"опыт={exp_raw or '?'}")

    age_raw = (anketa.get("возраст") or "").strip().lower()
    age_nums = re.findall(r'\d+', age_raw)
    if age_nums:
        age_ok = int(age_nums[0]) >= 18
    else:
        # возраст не указан (старая анкета/пропущен вопрос) - не блокируем по одному полю
        age_ok = True
    if not age_ok:
        reasons.append(f"возраст={age_raw or '?'}")

    qualified = ege_ok and exp_ok and age_ok
    return qualified, "; ".join(reasons)


def _split_numbered(text):
    """Разбивает текст на {номер: контент} по пронумерованным пунктам 1-9."""
    matches = list(re.finditer(r'^\s*(\d+)[\.\)]\s*', text, re.MULTILINE))
    items = {}
    for i, m in enumerate(matches):
        num = int(m.group(1))
        if num < 1 or num > 9:
            continue
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[start:end].strip()
        if content:
            items[num] = content
    return items


def _extract_score_like(content):
    """Из блока текста достаёт правдоподобный балл (2-3 цифры), а не год/что-то ещё."""
    m = re.search(r'\b(\d{2,3})\b', content)
    return m.group(1) if m else content


def parse_anketa_fallback(text):
    """Подстраховка на случай если LLM не проставил тег АНКЕТА: разбирает пронумерованный
    ответ кандидата на анкету напрямую регуляркой (по позиции пункта), независимо от LLM.
    Возвращает dict в формате как parse_anketa(), либо None если сообщение не похоже на
    ответ на анкету или не удалось найти минимум 2 из 3 ключевых полей (ЕГЭ/опыт/возраст)."""
    if not text or len(text) < 15:
        return None

    items = _split_numbered(text)
    if len(items) < 3:
        return None

    # Определяем формат: 8 пунктов с правдоподобным возрастом (14-70) на позиции 2 -> новый формат
    has_age_format = False
    if 2 in items and len(items) >= 6:
        m = re.match(r'^(\d{1,2})\b', items[2])
        if m and 14 <= int(m.group(1)) <= 70:
            has_age_format = True

    if has_age_format:
        pos = {'возраст': 2, 'образование': 3, 'предмет': 4, 'егэ': 5, 'опыт': 6, 'часы': 7}
    else:
        pos = {'образование': 2, 'предмет': 3, 'егэ': 4, 'опыт': 5, 'часы': 6}

    result = {}
    for key, num in pos.items():
        if num in items and items[num]:
            result[key] = items[num]

    if 'егэ' in result:
        result['егэ'] = _extract_score_like(result['егэ'])

    # Явное ключевое слово "возраст" в тексте надёжнее позиции
    age_kw = re.search(r'возраст[:\s]*(\d{1,2})\b', text, re.IGNORECASE)
    if age_kw:
        result['возраст'] = age_kw.group(1)

    found_key_fields = len([k for k in ('егэ', 'опыт', 'возраст') if k in result])
    if found_key_fields < 2:
        return None
    return result


async def send_signal(text):
    try:
        manager = await client.get_entity(MANAGER_USERNAME)
        await client.send_message(manager, text)
    except Exception as e:
        print(f"Failed to send signal: {e}")


@client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
async def handler(event):
    sender = await event.get_sender()
    if not sender or getattr(sender, "bot", False):
        return

    if sender.username and sender.username.lower() in IGNORE_USERS:
        if sender.username.lower() == "tutor_zelimhan":
            msg_text = event.message.text or ""
            if not msg_text.strip():
                return

            candidates = get_all_candidates()
            response = get_manager_response(msg_text, candidates)
            if response:
                await event.respond(response)
        return

    user_id = sender.id
    if hasattr(sender, "access_hash") and sender.access_hash:
        update_access_hash(user_id, sender.access_hash)
    username = f"@{sender.username}" if sender.username else ""
    name = (sender.first_name or "") + (" " + (sender.last_name or "")).rstrip()

    candidate = get_candidate(user_id)
    if not candidate:
        create_candidate(user_id, username, name)
        candidate = get_candidate(user_id)
        sheets_add(candidate)

    if candidate["status"] in IGNORE_STATUSES:
        return
    if candidate.get("conversation_bot") == "brosky":
        print(f"[hr-bot] Скип {candidate.get('name','?')} — в чате у Броского")
        return

    msg_text = event.message.text or ""

    if event.message.video or event.message.video_note:
        msg_text = "[Отправлено медиа: видео/голосовое]"
        if candidate["status"] in ("НОВЫЙ", "ТЕСТОВОЕ_ОТПРАВЛЕНО", "ТЕСТОВОЕ_НА_ПРОВЕРКЕ", "ТЕСТОВОЕ_ПОЛУЧЕНО"):
            update_candidate(user_id, status="ТЕСТОВОЕ_ПОЛУЧЕНО", video_received_at=datetime.now().isoformat())
            update_status(username, "ТЕСТОВОЕ_ПОЛУЧЕНО")
    elif event.message.voice:
        msg_text = "[Отправлено голосовое сообщение]"
        # Голосовое НЕ является видеовизиткой — статус не меняем
    elif event.message.document:
        doc = event.message.document
        mime = doc.mime_type or ""
        if "pdf" in mime or "word" in mime or "document" in mime:
            try:
                data = await client.download_media(event.message, file=io.BytesIO())
                if data:
                    data.seek(0)
                    text_content = data.read().decode("utf-8", errors="ignore")[:3000]
                    msg_text = f"[Содержимое резюме: {text_content}]"
            except Exception as e:
                print(f"Doc download error: {e}")
                msg_text = msg_text or "[Отправлен документ]"
        else:
            msg_text = msg_text or "[Отправлен файл]"
    elif event.message.photo:
        msg_text = msg_text or "[Отправлено фото]"

    if not msg_text.strip():
        return

    # Прочитать сообщение сразу (галочки)
    try:
        await client.send_read_acknowledge(event.chat_id)
    except:
        pass

    # Кредсы проверяем ДО записи сырого текста в историю/Sheets - логин/пароль
    # от аккаунта profi.ru не должны попадать открытым текстом ни в conversation
    # (SQLite), ни в таблицу; единственное легитимное место, куда они уходят -
    # личка коллеге mx_mish, который реально настраивает аккаунт.
    creds_match = CREDS_PATTERN.search(msg_text)
    if creds_match:
        login, password = creds_match.group(1), creds_match.group(2)
        creds_str = f"{login} / {password}"
        add_message(user_id, "candidate", "[получены учётные данные аккаунта]")
        update_candidate(user_id, reminder_count=0, status="АККАУНТ_ПОЛУЧЕН")
        try:
            sh = sheets_module._get_sheet()
            ws = sh.sheet1
            cell = ws.find(username)
            if cell:
                ws.update_cell(cell.row, 8, "АККАУНТ_ПОЛУЧЕН")
        except Exception as e:
            print(f"Sheets creds error: {e}")
        confirm = f"Отлично, {name}! Данные получил, передам коллегам для настройки аккаунта."
        try:
            await client.send_message(event.chat_id, confirm)
            add_message(user_id, "bot", confirm)
        except Exception:
            pass
        try:
            await client.send_message("mx_mish", f"🔑 Готов отдать аккаунт: {name} ({username})\nЛогин/пароль: {creds_str}")
        except Exception as e:
            print(f"Notify mx_mish error: {e}")
        print(f"Кредсы получены от {name}: {login} / ***")
        return

    add_message(user_id, "candidate", msg_text)
    update_candidate(user_id, reminder_count=0)

    # Подстраховка: если анкета ещё не разобрана, пробуем распарсить прямо из сырого
    # сообщения кандидата регуляркой - на случай если LLM не проставит тег АНКЕТА
    if not re.search(r'\d', candidate.get("comment") or ""):
        fallback_anketa = parse_anketa_fallback(msg_text)
        if fallback_anketa:
            qualified, reasons = evaluate_auto_criteria(fallback_anketa)
            comment = f"Обр: {fallback_anketa.get('образование', '')} | ЕГЭ: {fallback_anketa.get('егэ', '')} | Опыт: {fallback_anketa.get('опыт', '')} | Часы: {fallback_anketa.get('часы', '')} [regex-fallback]"
            if not qualified and reasons:
                comment += f" | Не прошёл автоотбор: {reasons}"
            update_candidate(user_id, comment=comment, auto_qualified=1 if qualified else 0)
            print(f"Анкета (fallback-регулярка): {name} — {fallback_anketa} | Автоотбор: {'ДА' if qualified else 'НЕТ'} ({reasons})")

    # Debounce — ждём 5 секунд, собираем все сообщения в пачку
    if user_id not in _message_buffer:
        _message_buffer[user_id] = []
    _message_buffer[user_id].append(msg_text)

    if user_id in _pending_messages:
        _pending_messages[user_id].cancel()

    # Определяем задержку
    import random
    if sender.username and sender.username.lower() in INSTANT_USERS:
        delay = 3
        _pending_messages[user_id] = asyncio.create_task(
            _process_after_delay(user_id, username, name, event.chat_id, delay)
        )
        return

    conversation = get_conversation(user_id)
    bot_msgs = [m for m in conversation if m["role"] == "bot"]
    if len(bot_msgs) == 0:
        # Первый контакт - 5-10 минут
        delay = random.randint(300, 600)
    else:
        last_bot_time = bot_msgs[-1].get("time", "") if bot_msgs else ""
        if last_bot_time:
            try:
                last_dt = datetime.fromisoformat(last_bot_time)
                mins_since = (datetime.now() - last_dt).total_seconds() / 60
                if mins_since < 15:
                    # Активный диалог - 30 сек
                    delay = 30
                else:
                    # Давно не писали - 5-10 мин
                    delay = random.randint(300, 600)
            except:
                delay = random.randint(300, 600)
        else:
            delay = random.randint(300, 600)

    _pending_messages[user_id] = asyncio.create_task(
        _process_after_delay(user_id, username, name, event.chat_id, delay)
    )
    return


async def _simulate_typing(chat_id, text_length):
    """Имитация печатания как реальный человек — ~4-5 символов в секунду"""
    import random

    # Реальная скорость печати человека на телефоне: ~4-5 символов/сек
    chars_per_sec = random.uniform(3.5, 5.5)
    typing_time = text_length / chars_per_sec

    # Ограничение - макс 120 сек (2 мин), мин 5 сек
    typing_time = max(3, min(typing_time, 30))

    # Разбиваем на куски: печатает - думает - печатает - исправляет - печатает
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

    for i, chunk_time in enumerate(chunk_times):
        # Печатает
        try:
            await client(SetTypingRequest(peer=chat_id, action=SendMessageTypingAction()))
        except:
            pass
        await asyncio.sleep(chunk_time)

        if i < len(chunk_times) - 1:
            # Пауза между кусками - "думает" или "перечитывает"
            try:
                await client(SetTypingRequest(peer=chat_id, action=SendMessageCancelAction()))
            except:
                pass
            pause_type = random.choice(["think", "reread", "short"])
            if pause_type == "think":
                await asyncio.sleep(random.uniform(2.0, 5.0))
            elif pause_type == "reread":
                await asyncio.sleep(random.uniform(1.5, 3.5))
            else:
                await asyncio.sleep(random.uniform(0.5, 1.5))


async def _wait_and_reserve(user_id, max_wait_sec=30):
    """Живым тестом (гонка двух параллельных вызовов через asyncio.gather)
    обнаружено на brosky-bot: барьер _recently_sent сам по себе не atomic -
    между чтением "недавно ли отвечали" и фактической записью ответа есть
    await (_simulate_typing), и два по-настоящему одновременных запуска оба
    успевают пройти проверку. .cancel() в дебаунсе тоже не 100% гарантия.
    Жёсткая сериализация по user_id: ждём пока _active_responding
    освободится, бронируем СРАЗУ без await между проверкой и записью
    (set.add - атомарно в пределах event loop)."""
    for _ in range(max_wait_sec):
        if user_id not in _active_responding:
            _active_responding.add(user_id)
            return True
        await asyncio.sleep(1)
    return False


async def _process_after_delay(user_id, username, name, chat_id, delay):
    await asyncio.sleep(delay)

    candidate = get_candidate(user_id)
    if not candidate or candidate["status"] in IGNORE_STATUSES:
        _message_buffer.pop(user_id, None)
        _pending_messages.pop(user_id, None)
        return
    if candidate.get("conversation_bot") == "brosky":
        _message_buffer.pop(user_id, None)
        _pending_messages.pop(user_id, None)
        return

    if not await _wait_and_reserve(user_id):
        return
    try:
        await _do_process(user_id, username, name, chat_id, candidate)
    finally:
        _active_responding.discard(user_id)


async def _do_process(user_id, username, name, chat_id, candidate):
    conversation = get_conversation(user_id)

    # Короткая пауза "читает сообщение"
    import random
    await asyncio.sleep(random.uniform(1.5, 3.0))

    # Начинаем "печатать" пока LLM генерирует
    try:
        await client(SetTypingRequest(peer=chat_id, action=SendMessageTypingAction()))
    except:
        pass

    response = await asyncio.to_thread(get_response, conversation, candidate)
    _message_buffer.pop(user_id, None)
    _pending_messages.pop(user_id, None)

    try:
        await client(SetTypingRequest(peer=chat_id, action=SendMessageCancelAction()))
    except:
        pass

    if not response:
        return

    for marker in GARBAGE_MARKERS:
        if marker in response:
            print(f"Filtered garbage response: {marker}", flush=True)
            return

    clean = re.sub(r'>>>.*?<<<', '', response)
    ascii_ratio = sum(1 for c in clean if c.isascii() and c.isalpha()) / max(len(clean.strip()), 1)
    if ascii_ratio > 0.5:
        print(f"Filtered English response (ascii_ratio={ascii_ratio:.2f})", flush=True)
        return

    signals = SIGNAL_PATTERN.findall(response)
    files = FILE_PATTERN.findall(response)
    anketas = ANKETA_PATTERN.findall(response)
    statuses = STATUS_PATTERN.findall(response)
    scores = SCORE_PATTERN.findall(response)

    clean_response = SIGNAL_PATTERN.sub("", response)
    clean_response = FILE_PATTERN.sub("", clean_response)
    clean_response = ANKETA_PATTERN.sub("", clean_response)
    clean_response = STATUS_PATTERN.sub("", clean_response)
    clean_response = SCORE_PATTERN.sub("", clean_response).strip()

    if clean_response and _recently_sent(user_id):
        print(f"[guard] Пропущена отправка {name} - уже отвечали за последние {DUPLICATE_GUARD_WINDOW_SEC} сек", flush=True)
        clean_response = ""

    if clean_response:
        clean_response = clean_response.replace("—", "-").replace("–", "-")

        # Имитация печатания (скип для тестовых)
        candidate_now = get_candidate(user_id)
        c_username = (candidate_now or {}).get("username", "")
        if not (c_username and c_username.lower().lstrip("@") in INSTANT_USERS):
            await _simulate_typing(chat_id, len(clean_response))

        add_message(user_id, "bot", clean_response)
        await client.send_message(chat_id, clean_response)
        update_conversation_bot(user_id, "hr")

    for file_name in files:
        path = os.path.join(os.path.dirname(__file__) or ".", file_name.strip())
        if os.path.exists(path):
            await client.send_file(chat_id, path, caption="Вот задания в картинке, ссылка что-то барахлит.")

    for anketa_raw in anketas:
        anketa = parse_anketa(anketa_raw)
        if anketa:
            qualified, reasons = evaluate_auto_criteria(anketa)
            comment = f"Обр: {anketa.get('образование', '')} | ЕГЭ: {anketa.get('егэ', '')} | Опыт: {anketa.get('опыт', '')} | Часы: {anketa.get('часы', '')}"
            if not qualified and reasons:
                comment += f" | Не прошёл автоотбор: {reasons}"
            update_candidate(user_id,
                subject=anketa.get("предмет", ""),
                comment=comment,
                auto_qualified=1 if qualified else 0,
            )
            update_anketa(username, anketa)
            print(f"Анкета: {name} — {anketa} | Автоотбор: {'ДА' if qualified else 'НЕТ'} ({reasons})")

    if scores:
        score = min(int(scores[-1]), 10)
        update_candidate(user_id, score=score)
        update_score(username, score)
        print(f"Скор: {name} — {score}/10")

    for signal in signals:
        signal_text = f"🔔 СИГНАЛ:\nКандидат: {name} ({username})\n{signal.strip()}"
        await send_signal(signal_text)

    old_status = candidate["status"]
    new_status = old_status
    if statuses:
        llm_status = statuses[-1].strip()
        # LLM не может ставить ТЕСТОВОЕ_ПОЛУЧЕНО — только код ставит при реальном медиа
        # ПЕРЕДАН_МЕНЕДЖЕРУ — статус заблокирован для LLM, дальше ведёт менеджер вручную
        if llm_status in VALID_STATUSES and llm_status != "ТЕСТОВОЕ_ПОЛУЧЕНО" and old_status != "ПЕРЕДАН_МЕНЕДЖЕРУ":
            new_status = llm_status
            print(f"Статус: {name} {old_status} -> {new_status}")

    if new_status != old_status:
        update_candidate(user_id, status=new_status)
        update_status(username, new_status)
        _folders.trigger_sync(_folder_event)

        if new_status == "ТЕСТОВОЕ_НА_ПРОВЕРКЕ":
            fresh = get_candidate(user_id)
            if fresh:
                comment = fresh.get("comment") or ""
                decision = None
                if fresh.get("auto_qualified") == 1:
                    decision = "approved"
                elif "Не прошёл автоотбор" in comment:
                    # Отказываем только когда есть чёткая зафиксированная причина
                    # (анкета реально распарсилась и не прошла критерии). Если
                    # auto_qualified=0 просто потому что анкету не смогли разобрать -
                    # НЕ отказываем автоматом, оставляем человеку на ручную проверку.
                    decision = "rejected"
                if decision:
                    conn_auto = sqlite3.connect(DB_PATH, timeout=10)
                    conn_auto.execute(
                        "INSERT INTO manager_decisions (candidate_user_id, decision, created_at, approved_by) VALUES (?, ?, ?, ?)",
                        (user_id, decision, datetime.now().isoformat(), None)
                    )
                    conn_auto.commit()
                    conn_auto.close()
                    if decision == "approved":
                        print(f"Автоотбор: {name} прошёл по анкете, одобрен автоматически")
                    else:
                        # Поштучно в группу больше не шлём (шумно) - список за день
                        # собирается прямо в daily_stats_job по comment+updated_at
                        print(f"Автоотбор: {name} НЕ прошёл по анкете, авто-отказ ({comment})")


async def reminder_loop():
    while True:
        await asyncio.sleep(1800)
        try:
            stale_24 = get_stale_candidates(hours=24)
            for c in stale_24:
                hours = c["hours_since_update"]
                count = c.get("reminder_count", 0)
                name = c.get("name", "?")
                username = c.get("username", "?")
                user_id = c["user_id"]

                if count >= 3:
                    continue

                if hours >= 72 and count < 3:
                    update_candidate(user_id, status="ЗАМОРОЗКА", reminder_count=3)
                    update_status(username, "ЗАМОРОЗКА")
                    await send_signal(f"❄️ ЗАМОРОЗКА:\n{name} ({username}) не отвечает 72+ часов.")
                elif hours >= 48 and count < 2:
                    status = c.get("status", "")
                    if status not in ("ТЕСТОВОЕ_ОТПРАВЛЕНО",):
                        continue
                    msg = f"{name}, напоминаю про задания для отбора. Когда планируете выполнить?"
                    try:
                        await client.send_message(user_id, msg)
                        add_message(user_id, "bot", msg)
                        update_candidate(user_id, reminder_count=2, last_reminder=datetime.now().isoformat())
                        print(f"Напоминание 2: {name}")
                    except:
                        pass
                elif hours >= 24 and count < 1:
                    status = c.get("status", "")
                    if status not in ("ТЕСТОВОЕ_ОТПРАВЛЕНО",):
                        continue
                    msg = f"{name}, как дела с заданиями? Если есть вопросы — пишите, помогу."
                    try:
                        await client.send_message(user_id, msg)
                        add_message(user_id, "bot", msg)
                        update_candidate(user_id, reminder_count=1, last_reminder=datetime.now().isoformat())
                        print(f"Напоминание 1: {name}")
                    except:
                        pass
        except Exception as e:
            print(f"Reminder error: {e}")


def _apply_decision_status(user_id, username, decision, approved_by):
    """Обновляет статус кандидата по решению менеджера без отправки сообщения (peer недоступен)."""
    if decision == "approved":
        # Все одобренные автоматически передаются Броски - у Зелимхана они не задерживаются
        update_candidate(user_id, status="ПЕРЕДАН_МЕНЕДЖЕРУ")
        update_status(username, "ПЕРЕДАН_МЕНЕДЖЕРУ", "Одобрен и передан @brosky_manage (сообщение не доставлено)")
    elif decision == "rejected":
        update_candidate(user_id, status="ОТКАЗ")
        update_status(username, "ОТКАЗ")
    elif decision == "transfer":
        update_candidate(user_id, status="ПЕРЕДАН_МЕНЕДЖЕРУ")
        update_status(username, "ПЕРЕДАН_МЕНЕДЖЕРУ", "Передан @brosky_manage (сообщение не доставлено)")
    _folders.trigger_sync(_folder_event)


async def _process_one_decision(d):
    user_id = d["candidate_user_id"]
    decision = d["decision"]
    approved_by = d.get("approved_by")

    # Защита от гонки: decision_loop вычитывает пачку processed=0 решений разом
    # и потом минуты обрабатывает их по одной (typing-симуляция, resolve peer).
    # Если пока это решение ждало своей очереди по тому же кандидату появилось
    # более новое (например человек вручную одобрил, пока автоотказ ещё стоял
    # в очереди) - действует только последнее, устаревшее тихо пропускаем.
    conn_race = sqlite3.connect(DB_PATH, timeout=10)
    newer_id = conn_race.execute(
        "SELECT id FROM manager_decisions WHERE candidate_user_id = ? AND id > ?",
        (user_id, d["id"])
    ).fetchone()
    conn_race.close()
    if newer_id:
        print(f"Decision id={d['id']} ({decision}) для uid={user_id} пропущено - есть более новое решение id={newer_id[0]}", flush=True)
        return

    candidate = get_candidate(user_id)
    if not candidate:
        print(f"Decision skipped: candidate {user_id} not found")
        return

    name = candidate.get("name", "?")
    username = candidate.get("username", "?")

    is_test_user = username and username.lower().lstrip("@") in INSTANT_USERS
    uname = username.lstrip("@") if username and username != "?" else None
    print(f'Processing {name} (@{uname}, uid={user_id})', flush=True)
    # Определяем peer: сначала access_hash (не подвержен FloodWait на ResolveUsername), потом username/uid
    peer = None
    cand_ah = candidate.get("access_hash")
    if cand_ah:
        try:
            from telethon.tl.types import InputPeerUser
            peer = await client.get_entity(InputPeerUser(user_id=user_id, access_hash=cand_ah))
        except Exception:
            peer = None
    if peer is None and uname:
        try:
            peer = await client.get_entity(uname)
        except Exception as e:
            print(f"Cannot resolve @{uname}: {e}", flush=True)
            # Статус в БД всё равно обновляем чтобы не висело в НА_ПРОВЕРКЕ
            _apply_decision_status(user_id, username, decision, approved_by)
            return
    if peer is None:
        try:
            peer = await client.get_entity(user_id)
        except Exception as e:
            print(f"Cannot resolve uid {user_id}: {e}", flush=True)
            # Статус в БД всё равно обновляем чтобы не висело в НА_ПРОВЕРКЕ
            _apply_decision_status(user_id, username, decision, approved_by)
            return
    peer_id = peer.id

    try:
        if decision == "approved":
            # Комплимент
            msg1 = f"{name}, посмотрел вашу визитку - реально понравилось. Видно что вы увлечены предметом и умеете подать себя. Именно такой подход мы и ищем."
            if not is_test_user:
                await _simulate_typing(peer_id, len(msg1))
            await client.send_message(peer, msg1)
            add_message(user_id, "bot", msg1)

            if not is_test_user:
                await asyncio.sleep(random.uniform(2, 4))
            else:
                await asyncio.sleep(1)

            # Условия
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
            if not is_test_user:
                await _simulate_typing(peer_id, len(msg2))
            await client.send_message(peer, msg2)
            add_message(user_id, "bot", msg2)

            if not is_test_user:
                await asyncio.sleep(random.uniform(1, 3))
            else:
                await asyncio.sleep(1)

            # Все одобренные автоматически передаются Броски - у Зелимхана не задерживаются
            msg3 = "Для обсуждения деталей и назначения созвона свяжитесь с моим коллегой - @brosky_manage. Он всё расскажет подробнее."
            if not is_test_user:
                await _simulate_typing(peer_id, len(msg3))
            await client.send_message(peer, msg3)
            add_message(user_id, "bot", msg3)
            update_candidate(user_id, status="ПЕРЕДАН_МЕНЕДЖЕРУ")
            _folders.trigger_sync(_folder_event)
            update_status(username, "ПЕРЕДАН_МЕНЕДЖЕРУ", "Одобрен и автоматически передан @brosky_manage")
            print(f"Одобрен: {name} — статус ПЕРЕДАН_МЕНЕДЖЕРУ (авто-передача Броски)")

        elif decision == "rejected":
            reason_comment = (candidate.get("comment") or "").lower()
            if "возраст=" in reason_comment:
                reason_txt = "у нас работают репетиторы 18+"
            elif "опыт=" in reason_comment:
                reason_txt = "нам важен опыт преподавания"
            elif "егэ=" in reason_comment:
                reason_txt = "нам важна уверенная база по предмету"
            else:
                reason_txt = "не всё сошлось по критериям отбора"
            msg = f"{name}, спасибо что уделили время. К сожалению, на данном этапе не подходим друг другу - {reason_txt}. Удачи вам!"
            if not is_test_user:
                await _simulate_typing(peer_id, len(msg))
            await client.send_message(peer, msg)
            add_message(user_id, "bot", msg)
            update_candidate(user_id, status="ОТКАЗ")
            _folders.trigger_sync(_folder_event)
            update_status(username, "ОТКАЗ")
            print(f"Отказ: {name}")

        elif decision == "transfer":
            msg = f"{name}, для обсуждения деталей вас свяжу с коллегой. Напишите ему, пожалуйста: @brosky_manage"
            if not is_test_user:
                await _simulate_typing(peer_id, len(msg))
            await client.send_message(peer, msg)
            add_message(user_id, "bot", msg)
            update_candidate(user_id, status="ПЕРЕДАН_МЕНЕДЖЕРУ")
            update_status(username, "ПЕРЕДАН_МЕНЕДЖЕРУ", "Передан @brosky_manage")
            print(f"Передан: {name} → @brosky_manage")

    except Exception as e:
        print(f"Decision send error for {name}: {e}")


DECISION_TIMEOUT_SEC = 150


async def decision_loop():
    while True:
        await asyncio.sleep(10)
        try:
            conn = sqlite3.connect(DB_PATH, timeout=10)
            conn.row_factory = sqlite3.Row
            conn.execute("""
                CREATE TABLE IF NOT EXISTS manager_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    candidate_user_id INTEGER,
                    decision TEXT,
                    created_at TEXT,
                    processed INTEGER DEFAULT 0
                )
            """)
            try:
                conn.execute("ALTER TABLE manager_decisions ADD COLUMN processed INTEGER DEFAULT 0")
            except:
                pass
            # Кандидатов conversation_bot='brosky' (холодный старт напрямую на Броски)
            # эта очередь не трогает вообще - у них своя собственная decision_loop
            # в brosky-bot's main.py, чтобы не слать сообщения с чужого аккаунта
            # и не перезатирать статус, который уже проставил manager_bot.py
            rows = conn.execute("""
                SELECT md.* FROM manager_decisions md
                LEFT JOIN candidates c ON c.user_id = md.candidate_user_id
                WHERE md.processed = 0 AND (c.conversation_bot IS NULL OR c.conversation_bot != 'brosky')
            """).fetchall()
            conn.close()

            for row in rows:
                d = dict(row)
                try:
                    await asyncio.wait_for(_process_one_decision(d), timeout=DECISION_TIMEOUT_SEC)
                except asyncio.TimeoutError:
                    print(f"Decision TIMEOUT id={d['id']} uid={d.get('candidate_user_id')} - применяю статус без сообщения, помечаю обработанным", flush=True)
                    candidate = get_candidate(d["candidate_user_id"])
                    if candidate:
                        _apply_decision_status(d["candidate_user_id"], candidate.get("username", ""), d["decision"], d.get("approved_by"))
                except Exception as e:
                    print(f"Decision processing error id={d['id']}: {e}", flush=True)

                conn2 = sqlite3.connect(DB_PATH, timeout=10)
                conn2.execute("UPDATE manager_decisions SET processed = 1 WHERE id = ?", (d["id"],))
                conn2.commit()
                conn2.close()

        except Exception as e:
            print(f"Decision loop error: {e}")


AUTO_QUALIFIED_STUCK_MINUTES = 5


async def auto_qualified_sweep_loop():
    """Страховка от того что LLM не закрыла тег >>> СТАТУС: ... <<< (обрыв без <<<
    ломает регулярку - статус не парсится, кандидат навсегда виснет на
    ТЕСТОВОЕ_ПОЛУЧЕНО, хотя должен был уйти дальше сам - одобрен или отказан
    по авто-критериям). Раз в 3 минуты принудительно проталкивает таких
    кандидатов, не дожидаясь корректного тега от модели.
    Авто-решение (approved/rejected) ставим только когда есть чёткий вердикт
    (auto_qualified=1, либо явная причина отказа в comment) - если анкету
    вообще не смогли разобрать, статус двигаем, но решение оставляем человеку."""
    while True:
        await asyncio.sleep(180)
        try:
            conn = sqlite3.connect(DB_PATH, timeout=10)
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT user_id, name, username, video_received_at, auto_qualified, comment FROM candidates
                WHERE status = 'ТЕСТОВОЕ_ПОЛУЧЕНО'
            """).fetchall()
            conn.close()

            now = datetime.now()
            for r in rows:
                va = r["video_received_at"]
                if not va:
                    continue
                try:
                    age_min = (now - datetime.fromisoformat(va)).total_seconds() / 60
                except ValueError:
                    continue
                if age_min < AUTO_QUALIFIED_STUCK_MINUTES:
                    continue

                user_id, name, username = r["user_id"], r["name"], r["username"]
                comment = r["comment"] or ""
                decision = None
                if r["auto_qualified"] == 1:
                    decision = "approved"
                elif "Не прошёл автоотбор" in comment:
                    decision = "rejected"

                update_candidate(user_id, status="ТЕСТОВОЕ_НА_ПРОВЕРКЕ")
                update_status(username, "ТЕСТОВОЕ_НА_ПРОВЕРКЕ")

                if decision:
                    conn2 = sqlite3.connect(DB_PATH, timeout=10)
                    conn2.execute(
                        "INSERT INTO manager_decisions (candidate_user_id, decision, created_at, approved_by) VALUES (?, ?, ?, ?)",
                        (user_id, decision, now.isoformat(), None)
                    )
                    conn2.commit()
                    conn2.close()
                    print(f"[sweep] Застрявший ({decision}): {name} ({username}) - проставлен статус и решение принудительно", flush=True)
                else:
                    print(f"[sweep] Застрявший (без вердикта, анкета не распознана): {name} ({username}) - статус проставлен, решение за человеком", flush=True)
        except Exception as e:
            print(f"Auto-qualified sweep error: {e}")


ACTIVE_STATUSES = {
    "НОВЫЙ", "ТЕСТОВОЕ_ОТПРАВЛЕНО", "ТЕСТОВОЕ_ПОЛУЧЕНО",
    "ТЕСТОВОЕ_НА_ПРОВЕРКЕ",
    "ЗАМОРОЗКА", "ИМПОРТ",
}

_patrol_processing = set()


async def patrol_loop():
    """Каждые 5 минут проверяет ВСЕ активные переписки.
    Если последнее сообщение от кандидата и мы не ответили — обрабатывает."""
    await asyncio.sleep(60)
    while True:
        try:
            candidates = get_all_candidates()
            active = [c for c in candidates if c.get("status") in ACTIVE_STATUSES]

            for c in active:
                user_id = c["user_id"]
                username = c.get("username", "").lstrip("@")
                name = c.get("name", "?")

                if user_id in _patrol_processing or user_id in _pending_messages or user_id in _active_responding:
                    continue

                # Резервируем user_id СРАЗУ после проверки, до первого await ниже -
                # раньше add() был в самом конце (после await client.get_messages и
                # всей синхронной обработки, местами с ещё несколькими await на пути
                # обработки кредов), что оставляло TOCTOU-окно. spawned контролирует,
                # снимаем ли мы бронь сами (все ранние continue) или это сделает
                # _patrol_respond в своём finally (единственный путь где реально
                # запустили обработку).
                _patrol_processing.add(user_id)
                spawned = False
                try:
                    try:
                        msgs = await client.get_messages(user_id, limit=5)
                    except Exception:
                        if username:
                            try:
                                msgs = await client.get_messages(username, limit=5)
                            except Exception:
                                continue
                        else:
                            continue

                    if not msgs:
                        continue

                    last_msg = msgs[0]
                    if last_msg.out:
                        continue

                    if last_msg.date and (datetime.now(last_msg.date.tzinfo) - last_msg.date).total_seconds() < 120:
                        continue

                    last_text = last_msg.text or ""
                    if not last_text.strip():
                        if last_msg.video or last_msg.video_note or last_msg.voice:
                            last_text = "[Отправлено медиа: видео/голосовое]"
                        elif last_msg.document:
                            last_text = "[Отправлен документ]"
                        elif last_msg.photo:
                            last_text = "[Отправлено фото]"
                        else:
                            continue

                    conv = get_conversation(user_id)
                    last_conv_texts = [(m.get("content") or m.get("text", "")) for m in conv[-5:] if m.get("role") == "candidate"]
                    if last_text in last_conv_texts:
                        continue

                    # Собираем все непрочитанные сообщения от кандидата подряд
                    new_texts = []
                    for m in msgs:
                        if m.out:
                            break
                        t = m.text or ""
                        if not t.strip():
                            if m.video or m.video_note or m.voice:
                                t = "[Отправлено медиа: видео/голосовое]"
                                if c.get("status") in ("НОВЫЙ", "ТЕСТОВОЕ_ОТПРАВЛЕНО", "ТЕСТОВОЕ_НА_ПРОВЕРКЕ", "ТЕСТОВОЕ_ПОЛУЧЕНО"):
                                    update_candidate(user_id, status="ТЕСТОВОЕ_ПОЛУЧЕНО")
                                    update_status(c.get("username", ""), "ТЕСТОВОЕ_ПОЛУЧЕНО")
                            elif m.document:
                                t = "[Отправлен документ]"
                            elif m.photo:
                                t = "[Отправлено фото]"
                            else:
                                continue
                        if t not in last_conv_texts:
                            new_texts.append(t)

                    if not new_texts:
                        continue

                    new_texts.reverse()
                    has_creds = False
                    for t in new_texts:
                        creds_match = CREDS_PATTERN.search(t)
                        if creds_match:
                            login, password = creds_match.group(1), creds_match.group(2)
                            creds_str = f"{login} / {password}"
                            add_message(user_id, "candidate", "[получены учётные данные аккаунта]")
                            update_candidate(user_id, status="АККАУНТ_ПОЛУЧЕН")
                            try:
                                sh = sheets_module._get_sheet()
                                ws = sh.sheet1
                                cell = ws.find(c.get("username", ""))
                                if cell:
                                    ws.update_cell(cell.row, 8, "АККАУНТ_ПОЛУЧЕН")
                            except Exception as e:
                                print(f"[patrol] Sheets creds error: {e}")
                            try:
                                confirm = f"Отлично! Данные получил, передам коллегам для настройки аккаунта."
                                await client.send_message(user_id, confirm)
                                add_message(user_id, "bot", confirm)
                            except Exception:
                                pass
                            try:
                                await client.send_message("mx_mish", f"🔑 Готов отдать аккаунт: {name} ({c.get('username','')})\nЛогин/пароль: {creds_str}")
                            except Exception as e:
                                print(f"[patrol] Notify mx_mish error: {e}")
                            print(f"[patrol] Кредсы от {name}: {login} / ***", flush=True)
                            has_creds = True
                        else:
                            add_message(user_id, "candidate", t)
                    update_candidate(user_id, reminder_count=0)

                    if has_creds:
                        continue

                    print(f"[patrol] Найдено {len(new_texts)} новых от {name} (@{username})", flush=True)

                    is_instant = username and username.lower() in INSTANT_USERS
                    delay = 3 if is_instant else random.randint(20, 60)
                    asyncio.create_task(_patrol_respond(user_id, username, name, delay))
                    spawned = True
                finally:
                    if not spawned:
                        _patrol_processing.discard(user_id)

        except Exception as e:
            print(f"Patrol error: {e}", flush=True)

        await asyncio.sleep(300)


async def _patrol_respond(user_id, username, name, delay):
    """Отвечает на пропущенное сообщение из patrol_loop."""
    try:
        await asyncio.sleep(delay)

        candidate = get_candidate(user_id)
        if not candidate or candidate["status"] in IGNORE_STATUSES:
            return
        if candidate.get("conversation_bot") == "brosky":
            return

        conversation = get_conversation(user_id)

        try:
            await client(SetTypingRequest(peer=user_id, action=SendMessageTypingAction()))
        except:
            pass

        response = await asyncio.to_thread(get_response, conversation, candidate)

        try:
            await client(SetTypingRequest(peer=user_id, action=SendMessageCancelAction()))
        except:
            pass

        if not response:
            return

        for marker in GARBAGE_MARKERS:
            if marker in response:
                print(f"[patrol] Filtered garbage for {name}: {marker}", flush=True)
                return

        clean = re.sub(r'>>>.*?<<<', '', response)
        ascii_ratio = sum(1 for c in clean if c.isascii() and c.isalpha()) / max(len(clean.strip()), 1)
        if ascii_ratio > 0.5:
            print(f"[patrol] Filtered English response for {name} (ascii_ratio={ascii_ratio:.2f})", flush=True)
            return

        signals = SIGNAL_PATTERN.findall(response)
        files = FILE_PATTERN.findall(response)
        anketas = ANKETA_PATTERN.findall(response)
        statuses = STATUS_PATTERN.findall(response)
        scores = SCORE_PATTERN.findall(response)

        clean_response = SIGNAL_PATTERN.sub("", response)
        clean_response = FILE_PATTERN.sub("", clean_response)
        clean_response = ANKETA_PATTERN.sub("", clean_response)
        clean_response = STATUS_PATTERN.sub("", clean_response)
        clean_response = SCORE_PATTERN.sub("", clean_response).strip()

        if clean_response and _recently_sent(user_id):
            print(f"[patrol][guard] Пропущена отправка {name} - уже отвечали за последние {DUPLICATE_GUARD_WINDOW_SEC} сек", flush=True)
            clean_response = ""

        if clean_response:
            clean_response = clean_response.replace("—", "-").replace("–", "-")
            is_instant = username and username.lower() in INSTANT_USERS
            if not is_instant:
                await _simulate_typing(user_id, len(clean_response))
            add_message(user_id, "bot", clean_response)
            await client.send_message(user_id, clean_response)
            print(f"[patrol] Ответил {name}: {clean_response[:80]}...", flush=True)

        for file_name in files:
            path = os.path.join(os.path.dirname(__file__) or ".", file_name.strip())
            if os.path.exists(path):
                await client.send_file(user_id, path, caption="Вот задания в картинке, ссылка что-то барахлит.")

        for anketa_raw in anketas:
            anketa = parse_anketa(anketa_raw)
            if anketa:
                qualified, reasons = evaluate_auto_criteria(anketa)
                comment = f"Обр: {anketa.get('образование', '')} | ЕГЭ: {anketa.get('егэ', '')} | Опыт: {anketa.get('опыт', '')} | Часы: {anketa.get('часы', '')}"
                if not qualified and reasons:
                    comment += f" | Не прошёл автоотбор: {reasons}"
                update_candidate(user_id,
                    subject=anketa.get("предмет", ""),
                    comment=comment,
                    auto_qualified=1 if qualified else 0,
                )
                uname_full = f"@{username}" if username else ""
                update_anketa(uname_full, anketa)
                print(f"[patrol] Анкета: {name} — {anketa} | Автоотбор: {'ДА' if qualified else 'НЕТ'} ({reasons})")

        if scores:
            score = min(int(scores[-1]), 10)
            update_candidate(user_id, score=score)
            uname_full = f"@{username}" if username else ""
            update_score(uname_full, score)

        for signal in signals:
            uname_full = f"@{username}" if username else ""
            signal_text = f"🔔 СИГНАЛ:\nКандидат: {name} ({uname_full})\n{signal.strip()}"
            await send_signal(signal_text)

        old_status = candidate["status"]
        if statuses:
            llm_status = statuses[-1].strip()
            if llm_status in VALID_STATUSES and llm_status != old_status and old_status != "ПЕРЕДАН_МЕНЕДЖЕРУ":
                update_candidate(user_id, status=llm_status)
                uname_full = f"@{username}" if username else ""
                update_status(uname_full, llm_status)
                print(f"[patrol] Статус: {name} {old_status} -> {llm_status}")

                if llm_status == "ТЕСТОВОЕ_НА_ПРОВЕРКЕ":
                    fresh = get_candidate(user_id)
                    if fresh:
                        comment = fresh.get("comment") or ""
                        decision = None
                        if fresh.get("auto_qualified") == 1:
                            decision = "approved"
                        elif "Не прошёл автоотбор" in comment:
                            decision = "rejected"
                        if decision:
                            conn_auto = sqlite3.connect(DB_PATH, timeout=10)
                            conn_auto.execute(
                                "INSERT INTO manager_decisions (candidate_user_id, decision, created_at, approved_by) VALUES (?, ?, ?, ?)",
                                (user_id, decision, datetime.now().isoformat(), None)
                            )
                            conn_auto.commit()
                            conn_auto.close()
                            if decision == "approved":
                                print(f"[patrol] Автоотбор: {name} прошёл по анкете, одобрен автоматически")
                            else:
                                print(f"[patrol] Автоотбор: {name} НЕ прошёл по анкете, авто-отказ ({comment})")

    except Exception as e:
        import traceback
        print(f"[patrol] Error responding to {name}: {e}", flush=True)
        traceback.print_exc()
    finally:
        _patrol_processing.discard(user_id)


async def sheets_sync_loop():
    """Синхронизирует статусы из БД в Google Sheets каждые 5 минут."""
    await asyncio.sleep(120)
    while True:
        try:
            all_candidates = get_all_candidates()
            sheet = None
            try:
                from sheets import _get_sheet
                sheet = _get_sheet()
            except Exception:
                pass

            if not sheet:
                await asyncio.sleep(300)
                continue

            ws = sheet.sheet1
            all_data = ws.get_all_values()
            if not all_data:
                await asyncio.sleep(300)
                continue

            db_map = {}
            for c in all_candidates:
                uname = c.get("username", "").lstrip("@").lower()
                if uname:
                    db_map[uname] = {"status": c.get("status", ""), "score": c.get("score", 0)}

            updates = []
            for row_idx, row in enumerate(all_data[1:], start=2):
                if len(row) < 8 or not row[2]:
                    continue
                uname = row[2].lstrip("@").lower()
                db = db_map.get(uname)
                if not db:
                    continue
                if row[7] != db["status"]:
                    updates.append({"range": f"H{row_idx}", "values": [[db["status"]]]})
                if len(row) > 10 and str(row[10]) != str(db["score"]):
                    updates.append({"range": f"K{row_idx}", "values": [[db["score"]]]})

            if updates:
                ws.batch_update(updates)
                print(f"[sheets] Synced {len(updates)} cells", flush=True)

            try:
                from sheets import sync_kanban, sync_dashboard
                sync_kanban(all_candidates)
                sync_dashboard(all_candidates)
            except Exception as e:
                print(f"[sheets] Kanban/Dashboard error: {e}", flush=True)

        except Exception as e:
            print(f"[sheets] Sync error: {e}", flush=True)

        await asyncio.sleep(300)


async def main():
    print("HR-бот v2 запущен. Слушаю входящие...")
    await client.start()
    try:
        dialogs = await client.get_dialogs(limit=300)
        print(f"Loaded {len(dialogs)} dialogs into entity cache", flush=True)
    except Exception as e:
        print(f"Failed to preload dialogs: {e}", flush=True)
    asyncio.create_task(reminder_loop())
    asyncio.create_task(decision_loop())
    asyncio.create_task(patrol_loop())
    asyncio.create_task(auto_qualified_sweep_loop())
    asyncio.create_task(sheets_sync_loop())
    asyncio.create_task(_folders.folder_sync_loop(client, _folder_event))
    await client.run_until_disconnected()


if __name__ == "__main__":
    init_db()
    with client:
        client.loop.run_until_complete(main())
