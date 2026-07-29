import sqlite3
import json
import re
import logging
from datetime import datetime
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton, BotCommand,
)
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from config import DB_PATH

import os
from dotenv import load_dotenv
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
MANAGER_ID = 8281593540
BROSKY_ID = 8009920862
ALLOWED_IDS = {MANAGER_ID, BROSKY_ID}

# StreamHandler, не файл - процесс уже запущен под systemd, journald и так
# перехватывает stdout/stderr со своей ротацией (journalctl -u hr-manager-bot).
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

MAIN_MENU = ReplyKeyboardMarkup(
    [
        [KeyboardButton("🎬 На проверку"), KeyboardButton("📋 Воронка")],
        [KeyboardButton("🏆 Топ"), KeyboardButton("📊 Сводка")],
        [KeyboardButton("🔍 Ждут ответа"), KeyboardButton("📅 Созвоны")],
        [KeyboardButton("✅ Созвон назначен"), KeyboardButton("👨‍💼 Переданные")],
        [KeyboardButton("📝 Договор"), KeyboardButton("🔑 Аккаунты")],
    ],
    resize_keyboard=True,
)


def _msg_text(m):
    return (m.get("content") or m.get("text", ""))[:100]


# ── DB helpers ──

def get_candidates_by_status(status):
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM candidates WHERE status = ?", (status,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_candidates_by_statuses(statuses):
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    placeholders = ",".join("?" for _ in statuses)
    rows = conn.execute(
        f"SELECT * FROM candidates WHERE status IN ({placeholders})", tuple(statuses)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_candidate_by_id(user_id):
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM candidates WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_candidates():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM candidates ORDER BY updated_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_candidate_status(user_id, status):
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("UPDATE candidates SET status = ?, updated_at = ? WHERE user_id = ?",
                 (status, datetime.now().isoformat(), user_id))
    conn.commit()
    conn.close()


def save_manager_decision(user_id, decision, approved_by=None):
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS manager_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_user_id INTEGER,
            decision TEXT,
            created_at TEXT
        )
    """)
    try:
        conn.execute("ALTER TABLE manager_decisions ADD COLUMN approved_by INTEGER")
    except:
        pass
    conn.execute(
        "INSERT INTO manager_decisions (candidate_user_id, decision, created_at, approved_by) VALUES (?, ?, ?, ?)",
        (user_id, decision, datetime.now().isoformat(), approved_by)
    )
    conn.commit()
    conn.close()


MAILBOX_LOCAL_PART_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,62}[a-z0-9]$")


def mailbox_local_part_for(candidate):
    """Ник кандидата в Telegram годится как есть (латиница/цифры/подчёркивания
    по правилам самого Telegram) - используем его как local-part адреса. Если
    ника нет или он не проходит валидацию provision_mailbox.py на сервере -
    падаем на 'tutor<user_id>', гарантированно валидный и уникальный."""
    username = (candidate.get("username") or "").lstrip("@").lower()
    if MAILBOX_LOCAL_PART_RE.match(username):
        return username
    return f"tutor{candidate['user_id']}"


def queue_mailbox_provision(user_id, local_part):
    """Заявка на создание почтового ящика - саму отправку делает отдельный
    mail_provision_loop() в hr-bot/main.py через sudo к provision_mailbox.py
    на mail-сервере. Отделено от смены статуса намеренно: сбой почтовой
    подсистемы не должен уметь задержать или сломать то, что менеджер только
    что успешно отметил в этом боте."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mail_outbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_user_id INTEGER NOT NULL,
            local_part TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            processed_at TEXT,
            error TEXT
        )
    """)
    conn.execute(
        "INSERT INTO mail_outbox (candidate_user_id, local_part, status, created_at) VALUES (?, ?, 'pending', ?)",
        (user_id, local_part, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


# ── Command handlers ──

async def start(update: Update, context):
    if update.effective_user.id not in ALLOWED_IDS:
        return
    await update.message.reply_text(
        "👋 HR Manager Panel\n\n"
        "Используй кнопки внизу:\n\n"
        "🎬 На проверку - видео кандидатов\n"
        "📋 Воронка - статусы по этапам\n"
        "🏆 Топ - лучшие кандидаты\n"
        "📊 Сводка - общая статистика\n"
        "🔍 Ждут ответа - кто ждёт реакции\n"
        "📅 Созвоны - назначенные и ожидающие",
        reply_markup=MAIN_MENU,
    )


async def review(update: Update, context):
    if update.effective_user.id not in ALLOWED_IDS:
        return

    candidates = get_candidates_by_status("ТЕСТОВОЕ_ПОЛУЧЕНО") + get_candidates_by_status("ТЕСТОВОЕ_НА_ПРОВЕРКЕ")
    candidates = [c for c in candidates if c.get("auto_qualified") != 1]
    if not candidates:
        await update.message.reply_text("✅ Нет кандидатов на проверку.", reply_markup=MAIN_MENU)
        return

    await update.message.reply_text(f"🎬 На проверку: {len(candidates)} чел.", reply_markup=MAIN_MENU)

    for c in candidates:
        name = c.get("name", "?")
        username = c.get("username", "?")
        subject = c.get("subject", "?")
        score = c.get("score", 0)
        comment = c.get("comment", "")

        conv = json.loads(c.get("conversation", "[]"))
        last_msgs = conv[-5:]
        msgs_text = "\n".join([f"{'👤' if m['role']=='candidate' else '🤖'} {_msg_text(m)}" for m in last_msgs])

        text = (
            f"👤 {name} ({username})\n"
            f"📚 {subject} | Скор: {score}/10\n"
            f"💬 {comment}\n\n"
            f"Последние сообщения:\n{msgs_text}"
        )

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Одобрить", callback_data=f"approve_{c['user_id']}"),
                InlineKeyboardButton("❌ Отказать", callback_data=f"reject_{c['user_id']}"),
            ]
        ])

        await update.message.reply_text(text, reply_markup=keyboard)


async def pipeline(update: Update, context):
    if update.effective_user.id not in ALLOWED_IDS:
        return

    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT status, COUNT(*) as cnt FROM candidates GROUP BY status ORDER BY cnt DESC").fetchall()
    conn.close()

    text = "📋 Воронка:\n\n"
    total = sum(r["cnt"] for r in rows)
    for r in rows:
        pct = round(r["cnt"] / total * 100) if total else 0
        bar = "█" * max(1, pct // 5)
        text += f"  {r['status']}: {r['cnt']} ({pct}%) {bar}\n"
    text += f"\n📌 Всего: {total}"

    await update.message.reply_text(text, reply_markup=MAIN_MENU)


async def top(update: Update, context):
    if update.effective_user.id not in ALLOWED_IDS:
        return

    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM candidates WHERE score > 0 AND status NOT IN ('ОТКАЗ', 'ЗАМОРОЗКА') ORDER BY score DESC LIMIT 15"
    ).fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("Пока нет кандидатов с оценками.", reply_markup=MAIN_MENU)
        return

    text = "🏆 Топ кандидаты:\n\n"
    for i, r in enumerate(rows, 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        text += f"{medal} {r['name']} ({r['username']}) - {r['score']}/10 | {r['subject']} | {r['status']}\n"

    await update.message.reply_text(text, reply_markup=MAIN_MENU)


async def summary(update: Update, context):
    if update.effective_user.id not in ALLOWED_IDS:
        return

    all_cands = get_all_candidates()
    total = len(all_cands)
    today = datetime.now().strftime("%Y-%m-%d")
    new_today = sum(1 for c in all_cands if (c.get("created_at") or "")[:10] == today)
    active = sum(1 for c in all_cands if c.get("status") not in ("ОТКАЗ", "ЗАМОРОЗКА"))
    on_review = sum(1 for c in all_cands if c.get("status") in ("ТЕСТОВОЕ_ПОЛУЧЕНО", "ТЕСТОВОЕ_НА_ПРОВЕРКЕ"))
    ready_call = sum(1 for c in all_cands if c.get("status") == "ГОТОВ_К_СОЗВОНУ")
    scheduled = sum(1 for c in all_cands if c.get("status") == "СОЗВОН_НАЗНАЧЕН")
    refused = sum(1 for c in all_cands if c.get("status") == "ОТКАЗ")
    frozen = sum(1 for c in all_cands if c.get("status") == "ЗАМОРОЗКА")

    avg_score = 0
    scored = [c for c in all_cands if c.get("score", 0) > 0]
    if scored:
        avg_score = round(sum(c["score"] for c in scored) / len(scored), 1)

    text = (
        f"📊 Сводка за {today}\n\n"
        f"👥 Всего: {total}\n"
        f"🆕 Сегодня: {new_today}\n"
        f"✅ Активных: {active}\n\n"
        f"🎬 На проверке: {on_review}\n"
        f"📞 Ждут созвон: {ready_call}\n"
        f"📅 Назначен: {scheduled}\n"
        f"❌ Отказ: {refused}\n"
        f"❄️ Заморозка: {frozen}\n\n"
        f"⭐ Средний скор: {avg_score}/10 ({len(scored)} оценок)"
    )

    await update.message.reply_text(text, reply_markup=MAIN_MENU)


async def waiting(update: Update, context):
    if update.effective_user.id not in ALLOWED_IDS:
        return

    all_cands = get_all_candidates()
    waiting_list = []

    for c in all_cands:
        if c.get("status") in ("ОТКАЗ", "ЗАМОРОЗКА"):
            continue
        conv = json.loads(c.get("conversation", "[]"))
        if not conv:
            continue
        if conv[-1].get("role") == "candidate":
            waiting_list.append(c)

    if not waiting_list:
        await update.message.reply_text("✅ Никто не ждёт ответа.", reply_markup=MAIN_MENU)
        return

    text = f"🔍 Ждут ответа: {len(waiting_list)} чел.\n\n"
    for c in waiting_list[:20]:
        conv = json.loads(c.get("conversation", "[]"))
        last_msg = _msg_text(conv[-1]) if conv else ""
        text += f"• {c.get('name', '?')} ({c.get('username', '?')}) | {c.get('status', '?')}\n  └ {last_msg}\n\n"

    await update.message.reply_text(text, reply_markup=MAIN_MENU)


async def calls(update: Update, context):
    if update.effective_user.id not in ALLOWED_IDS:
        return

    ready = get_candidates_by_status("ГОТОВ_К_СОЗВОНУ")

    if not ready:
        await update.message.reply_text("📅 Нет кандидатов, ожидающих созвон.", reply_markup=MAIN_MENU)
        return

    await update.message.reply_text(
        f"📞 Ждут назначения созвона: {len(ready)}",
        reply_markup=MAIN_MENU,
    )

    for c in ready:
        uid = c["user_id"]
        name = c.get("name", "?")
        username = c.get("username", "?")
        subject = c.get("subject", "?")
        score = c.get("score", 0)

        text = (
            f"📞 {name} ({username})\n"
            f"📚 {subject} | Скор: {score}/10\n"
        )

        buttons = [
            [InlineKeyboardButton("👨‍💼 Передать @brosky", callback_data=f"transfer_{uid}")],
            [InlineKeyboardButton("🔑 Акк взят", callback_data=f"account_{uid}")],
        ]

        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))


async def transferred(update: Update, context):
    """Переданные менеджеру — brosky назначает созвон."""
    if update.effective_user.id not in ALLOWED_IDS:
        return

    candidates = get_candidates_by_status("ПЕРЕДАН_МЕНЕДЖЕРУ")
    if not candidates:
        await update.message.reply_text("👨‍💼 Нет переданных кандидатов.", reply_markup=MAIN_MENU)
        return

    await update.message.reply_text(f"👨‍💼 Переданные: {len(candidates)} чел.", reply_markup=MAIN_MENU)

    for c in candidates:
        uid = c["user_id"]
        name = c.get("name", "?")
        username = c.get("username", "?")
        subject = c.get("subject", "?")
        score = c.get("score", 0)

        text = (
            f"👨‍💼 {name} ({username})\n"
            f"📚 {subject} | Скор: {score}/10\n"
        )

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Созвон назначен", callback_data=f"scheduled_{uid}")],
            [
                InlineKeyboardButton("🔑 Акк взят", callback_data=f"account_{uid}"),
                InlineKeyboardButton("❌ Отказался от аккаунта", callback_data=f"refused_account_{uid}"),
            ],
        ])

        await update.message.reply_text(text, reply_markup=keyboard)


async def scheduled(update: Update, context):
    """Созвон назначен — отмечаем акк взят."""
    if update.effective_user.id not in ALLOWED_IDS:
        return

    candidates = get_candidates_by_status("СОЗВОН_НАЗНАЧЕН")
    if not candidates:
        await update.message.reply_text("✅ Нет назначенных созвонов.", reply_markup=MAIN_MENU)
        return

    await update.message.reply_text(f"✅ Созвон назначен: {len(candidates)} чел.", reply_markup=MAIN_MENU)

    for c in candidates:
        uid = c["user_id"]
        name = c.get("name", "?")
        username = c.get("username", "?")
        subject = c.get("subject", "?")
        score = c.get("score", 0)

        text = (
            f"📅 {name} ({username})\n"
            f"📚 {subject} | Скор: {score}/10\n"
        )

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 Договор отправлен", callback_data=f"dogovor_{uid}")],
            [InlineKeyboardButton("🔑 Акк взят", callback_data=f"account_{uid}")],
            [InlineKeyboardButton("❌ Отказался от аккаунта", callback_data=f"refused_account_{uid}")]
        ])

        await update.message.reply_text(text, reply_markup=keyboard)


async def signed(update: Update, context):
    """Договор отправлен и/или подписан — ждём выдачи аккаунта.
    Показывает оба статуса: ДОГОВОР_ОТПРАВЛЕН (ещё не подписан, бот
    отвечает в QA-режиме) и ДОГОВОР_ПОДПИСАН (бот уже молчит)."""
    if update.effective_user.id not in ALLOWED_IDS:
        return

    candidates = get_candidates_by_statuses(["ДОГОВОР_ОТПРАВЛЕН", "ДОГОВОР_ПОДПИСАН"])
    if not candidates:
        await update.message.reply_text("✅ Нет ожидающих подписания/выдачи аккаунта.", reply_markup=MAIN_MENU)
        return

    await update.message.reply_text(f"📝 Договор отправлен/подписан: {len(candidates)} чел.", reply_markup=MAIN_MENU)

    for c in candidates:
        uid = c["user_id"]
        name = c.get("name", "?")
        username = c.get("username", "?")
        subject = c.get("subject", "?")
        score = c.get("score", 0)
        status = c.get("status")
        is_signed = status == "ДОГОВОР_ПОДПИСАН"

        text = (
            f"{'✅' if is_signed else '📝'} {name} ({username})\n"
            f"📚 {subject} | Скор: {score}/10\n"
            f"{'✅ Подписан, бот молчит' if is_signed else '📝 Отправлен, ждём подписания'}\n"
        )

        buttons = []
        if not is_signed:
            buttons.append([InlineKeyboardButton("✅ Подписан", callback_data=f"contractsigned_{uid}")])
        buttons.append([InlineKeyboardButton("🔑 Акк взят", callback_data=f"account_{uid}")])
        buttons.append([InlineKeyboardButton("❌ Отказался от аккаунта", callback_data=f"refused_account_{uid}")])

        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))


async def accounts_received(update: Update, context):
    """Логин/пароль получены, идёт техническая настройка на Профи.ру - ждём
    отметки что аккаунт реально открыт и работает. До этой функции статус
    ОТКРЫТ был в VALID_STATUSES/счётчике сводки, но ни одна кнопка или
    автоматика нигде в коде его не выставляла - кандидаты застревали в
    АККАУНТ_ПОЛУЧЕН без возможности закрыть цепочку (найдено 2026-07-29:
    21 чел. в очереди, некоторые больше месяца, "Открыт" - 1 за всё время,
    судя по всему выставлен вручную правкой базы в прошлом)."""
    if update.effective_user.id not in ALLOWED_IDS:
        return

    candidates = get_candidates_by_status("АККАУНТ_ПОЛУЧЕН")
    if not candidates:
        await update.message.reply_text("✅ Нет аккаунтов в настройке.", reply_markup=MAIN_MENU)
        return

    await update.message.reply_text(f"🔑 Аккаунт получен, в настройке: {len(candidates)} чел.", reply_markup=MAIN_MENU)

    for c in candidates:
        uid = c["user_id"]
        name = c.get("name", "?")
        username = c.get("username", "?")
        subject = c.get("subject", "?")

        text = (
            f"🔑 {name} ({username})\n"
            f"📚 {subject}\n"
        )

        buttons = [
            [InlineKeyboardButton("✅ Аккаунт открыт", callback_data=f"opened_{uid}")],
            [InlineKeyboardButton("❌ Отказался от аккаунта", callback_data=f"refused_account_{uid}")],
        ]

        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))


async def handle_text(update: Update, context):
    if update.effective_user.id not in ALLOWED_IDS:
        return
    text = update.message.text or ""
    if text == "🎬 На проверку":
        return await review(update, context)
    elif text == "📋 Воронка":
        return await pipeline(update, context)
    elif text == "🏆 Топ":
        return await top(update, context)
    elif text == "📊 Сводка":
        return await summary(update, context)
    elif text == "🔍 Ждут ответа":
        return await waiting(update, context)
    elif text == "📅 Созвоны":
        return await calls(update, context)
    elif text == "✅ Созвон назначен":
        return await scheduled(update, context)
    elif text == "👨‍💼 Переданные":
        return await transferred(update, context)
    elif text == "📝 Договор":
        return await signed(update, context)
    elif text == "🔑 Аккаунты":
        return await accounts_received(update, context)


# ── Callbacks ──

async def button_callback(update: Update, context):
    query = update.callback_query
    if query.from_user.id not in ALLOWED_IDS:
        return

    data = query.data

    # ── Scheduled: mark call as scheduled ──
    if data.startswith("scheduled_"):
        user_id = int(data.replace("scheduled_", ""))
        candidate = get_candidate_by_id(user_id)
        if not candidate:
            await query.answer("Кандидат не найден.")
            return

        if candidate.get("status") == "СОЗВОН_НАЗНАЧЕН":
            await query.answer("Уже назначен!")
            await query.edit_message_text(f"⚠️ {candidate['name']} — созвон уже был назначен ранее")
            return

        update_candidate_status(user_id, "СОЗВОН_НАЗНАЧЕН")

        await query.answer("Созвон назначен!")
        await query.edit_message_text(
            f"✅ {candidate['name']} — созвон назначен"
        )
        return

    # ── Договор отправлен ──
    if data.startswith("dogovor_"):
        user_id = int(data.replace("dogovor_", ""))
        candidate = get_candidate_by_id(user_id)
        if not candidate:
            await query.answer("Кандидат не найден.")
            return

        if candidate.get("status") in ("ДОГОВОР_ОТПРАВЛЕН", "ДОГОВОР_ПОДПИСАН", "АККАУНТ_ПОЛУЧЕН"):
            await query.answer("Уже отмечен!")
            await query.edit_message_text(f"⚠️ {candidate['name']} — уже в статусе {candidate['status']}")
            return

        update_candidate_status(user_id, "ДОГОВОР_ОТПРАВЛЕН")

        await query.answer("Отмечено!")
        await query.edit_message_text(
            f"📝 {candidate['name']} ({candidate.get('username', '?')}) — договор отправлен"
        )
        return

    # ── Договор подписан (бот больше не пишет кандидату) ──
    if data.startswith("contractsigned_"):
        user_id = int(data.replace("contractsigned_", ""))
        candidate = get_candidate_by_id(user_id)
        if not candidate:
            await query.answer("Кандидат не найден.")
            return

        if candidate.get("status") in ("ДОГОВОР_ПОДПИСАН", "АККАУНТ_ПОЛУЧЕН"):
            await query.answer("Уже отмечен!")
            await query.edit_message_text(f"⚠️ {candidate['name']} — уже в статусе {candidate['status']}")
            return

        who = query.from_user.id
        update_candidate_status(user_id, "ДОГОВОР_ПОДПИСАН")
        save_manager_decision(user_id, "contract_signed", approved_by=who)
        try:
            queue_mailbox_provision(user_id, mailbox_local_part_for(candidate))
        except Exception as e:
            logging.error(f"Не удалось поставить в очередь создание почты для {user_id}: {e}")

        await query.answer("Отмечено! Бот пришлёт запрос на фото/диплом.")
        await query.edit_message_text(
            f"✅ {candidate['name']} ({candidate.get('username', '?')}) — договор подписан, бот пришлёт запрос на фото/диплом"
        )
        return

    # ── Transfer to @brosky_manage ──
    if data.startswith("transfer_"):
        user_id = int(data.replace("transfer_", ""))
        candidate = get_candidate_by_id(user_id)
        if not candidate:
            await query.answer("Кандидат не найден.")
            return

        if candidate.get("status") in ("ПЕРЕДАН_МЕНЕДЖЕРУ", "СОЗВОН_НАЗНАЧЕН", "АККАУНТ_ПОЛУЧЕН"):
            await query.answer("Уже передан!")
            await query.edit_message_text(f"⚠️ {candidate['name']} — уже в статусе {candidate['status']}")
            return

        who = query.from_user.id
        update_candidate_status(user_id, "ПЕРЕДАН_МЕНЕДЖЕРУ")
        save_manager_decision(user_id, "transfer", approved_by=who)

        await query.answer("Передано!")
        await query.edit_message_text(
            f"👨‍💼 {candidate['name']} — передаётся @brosky_manage\n"
            f"Бот напишет кандидату через несколько секунд."
        )
        return

    # ── Refused to give account ──
    if data.startswith("refused_account_"):
        user_id = int(data.replace("refused_account_", ""))
        candidate = get_candidate_by_id(user_id)
        if not candidate:
            await query.answer("Кандидат не найден.")
            return
        update_candidate_status(user_id, "ОТКАЗ")
        save_manager_decision(user_id, "rejected")
        await query.answer("Отмечено!")
        await query.edit_message_text(
            f"❌ {candidate['name']} ({candidate.get('username', '?')}) — отказался от аккаунта. Статус: ОТКАЗ"
        )
        return

    # ── Account taken ──
    if data.startswith("account_"):
        user_id = int(data.replace("account_", ""))
        candidate = get_candidate_by_id(user_id)
        if not candidate:
            await query.answer("Кандидат не найден.")
            return

        if candidate.get("status") == "АККАУНТ_ПОЛУЧЕН":
            await query.answer("Уже отмечен!")
            await query.edit_message_text(f"⚠️ {candidate['name']} — акк уже получен")
            return

        update_candidate_status(user_id, "АККАУНТ_ПОЛУЧЕН")

        await query.answer("Отмечено!")
        await query.edit_message_text(
            f"🔑 {candidate['name']} ({candidate.get('username', '?')}) — акк получен!"
        )
        return

    # ── Account opened (техническая настройка на Профи.ру завершена) ──
    if data.startswith("opened_"):
        user_id = int(data.replace("opened_", ""))
        candidate = get_candidate_by_id(user_id)
        if not candidate:
            await query.answer("Кандидат не найден.")
            return

        if candidate.get("status") == "ОТКРЫТ":
            await query.answer("Уже отмечен!")
            await query.edit_message_text(f"⚠️ {candidate['name']} — аккаунт уже открыт")
            return

        update_candidate_status(user_id, "ОТКРЫТ")

        await query.answer("Отмечено!")
        await query.edit_message_text(
            f"✅ {candidate['name']} ({candidate.get('username', '?')}) — аккаунт открыт и работает!"
        )
        return

    # ── Approve/Reject ──
    await query.answer()

    if data.startswith("approve_"):
        user_id = int(data.replace("approve_", ""))
        candidate = get_candidate_by_id(user_id)
        if not candidate:
            await query.edit_message_text("Кандидат не найден.")
            return

        who = query.from_user.id
        is_brosky_candidate = candidate.get("conversation_bot") == "brosky"
        if is_brosky_candidate:
            # Кандидат уже у Броски в чате - передавать некуда, просто готов к созвону
            update_candidate_status(user_id, "ГОТОВ_К_СОЗВОНУ")
        else:
            # hr-bot кандидат - всегда автоматически передаётся Броски
            update_candidate_status(user_id, "ПЕРЕДАН_МЕНЕДЖЕРУ")
        save_manager_decision(user_id, "approved", approved_by=who)

        suffix = ""
        if not is_brosky_candidate:
            suffix = "\n👨‍💼 Автоматически передан @brosky_manage."
        await query.edit_message_text(
            f"✅ {candidate['name']} одобрен!\n\n"
            f"HR-бот отправит предложение через несколько секунд."
            + suffix
        )

    elif data.startswith("reject_"):
        user_id = int(data.replace("reject_", ""))
        candidate = get_candidate_by_id(user_id)
        if not candidate:
            await query.edit_message_text("Кандидат не найден.")
            return

        update_candidate_status(user_id, "ОТКАЗ")
        save_manager_decision(user_id, "rejected")

        await query.edit_message_text(
            f"❌ {candidate['name']} отклонён.\n\n"
            f"HR-бот отправит вежливый отказ."
        )


# ── Background jobs ──

AUTO_REVIEW_DELAY_MIN = 10


async def notify_new_videos(context):
    candidates = get_candidates_by_status("ТЕСТОВОЕ_ПОЛУЧЕНО") + get_candidates_by_status("ТЕСТОВОЕ_НА_ПРОВЕРКЕ")
    now = datetime.now()
    for c in candidates:
        # Авто-прошедшие по анкете обрабатываются кодом бота напрямую - сюда не попадают
        if c.get("auto_qualified") == 1:
            continue

        # Не авто-прошедшие ждут 10 минут после получения видео, потом уходят к Броски
        received_raw = c.get("video_received_at")
        if received_raw:
            try:
                received = datetime.fromisoformat(received_raw)
                if (now - received).total_seconds() < AUTO_REVIEW_DELAY_MIN * 60:
                    continue
            except ValueError:
                pass

        marker_key = f"notified_{c['user_id']}"
        last_notified = context.bot_data.get(marker_key, "")
        current_updated = c.get("updated_at", "")
        if last_notified == current_updated:
            continue

        name = c.get("name", "?")
        username = c.get("username", "?")
        subject = c.get("subject", "?")
        score = c.get("score", 0)
        comment = c.get("comment", "")

        conv = json.loads(c.get("conversation", "[]"))
        last_msgs = conv[-5:]
        msgs_text = "\n".join([f"{'👤' if m['role']=='candidate' else '🤖'} {_msg_text(m)}" for m in last_msgs])

        text = (
            f"🎬 НОВОЕ ВИДЕО (не прошёл автоотбор)!\n\n"
            f"👤 {name} ({username})\n"
            f"📚 {subject} | Скор: {score}/10\n"
            f"💬 {comment}\n\n"
            f"Последние сообщения:\n{msgs_text}"
        )

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Одобрить", callback_data=f"approve_{c['user_id']}"),
                InlineKeyboardButton("❌ Отказать", callback_data=f"reject_{c['user_id']}"),
            ]
        ])

        try:
            await context.bot.send_message(BROSKY_ID, text, reply_markup=keyboard)
            context.bot_data[marker_key] = current_updated
            logging.info(f"Уведомление Броски: {name}")
        except Exception as e:
            logging.error(f"Notify error: {e}")


async def post_init(app: Application):
    await app.bot.set_my_commands([
        BotCommand("start", "Главное меню"),
        BotCommand("review", "Кандидаты на проверку"),
        BotCommand("pipeline", "Воронка по статусам"),
        BotCommand("top", "Топ по скору"),
    ])


HEARTBEAT_PATH = "/opt/hr-bot/heartbeat_manager.txt"
ALERT_GROUP_ID = -5553995946  # "HR воронка важные сообщения" - сюда же алерты watchdog.sh


async def heartbeat(context):
    """Безусловная метка времени - watchdog.sh проверяет её свежесть.
    В отличие от notify_new_videos, который молчит если нечего слать,
    это единственный гарантированный признак что job_queue жив
    (именно job_queue завис в инциденте с простоем, а не сам процесс)."""
    try:
        with open(HEARTBEAT_PATH, "w") as f:
            f.write(datetime.now().isoformat())
    except Exception as e:
        logging.error(f"Heartbeat write error: {e}")


DAILY_STATS_MARKER = "/opt/hr-bot/last_daily_stats.txt"


async def daily_stats_job(context):
    """Раз в день (в 21:00 по времени сервера) шлёт сводку в ALERT_GROUP_ID.
    Проверка идёт раз в 10 минут - без завязки на часовой пояс job_queue,
    просто сравниваем текущий час с локальным временем сервера.
    Флаг "уже отправлено сегодня" - в файле на диске, не в памяти процесса:
    иначе рестарт бота в течение 21-го часа (например от watchdog) приводит
    к повторной отправке, т.к. in-memory переменная обнуляется при рестарте."""
    now = datetime.now()
    if now.hour != 21:
        return
    today_str = now.strftime("%Y-%m-%d")
    try:
        with open(DAILY_STATS_MARKER) as f:
            if f.read().strip() == today_str:
                return
    except FileNotFoundError:
        pass
    with open(DAILY_STATS_MARKER, "w") as f:
        f.write(today_str)

    all_cands = get_all_candidates()
    total = len(all_cands)
    new_today = sum(1 for c in all_cands if (c.get("created_at") or "")[:10] == today_str)
    on_review = sum(1 for c in all_cands if c.get("status") in ("ТЕСТОВОЕ_ПОЛУЧЕНО", "ТЕСТОВОЕ_НА_ПРОВЕРКЕ"))
    transferred = sum(1 for c in all_cands if c.get("status") == "ПЕРЕДАН_МЕНЕДЖЕРУ")
    ready_call = sum(1 for c in all_cands if c.get("status") == "ГОТОВ_К_СОЗВОНУ")
    scheduled = sum(1 for c in all_cands if c.get("status") == "СОЗВОН_НАЗНАЧЕН")
    dogovor = sum(1 for c in all_cands if c.get("status") == "ДОГОВОР_ОТПРАВЛЕН")
    dogovor_signed = sum(1 for c in all_cands if c.get("status") == "ДОГОВОР_ПОДПИСАН")
    account = sum(1 for c in all_cands if c.get("status") == "АККАУНТ_ПОЛУЧЕН")
    opened = sum(1 for c in all_cands if c.get("status") == "ОТКРЫТ")
    refused = sum(1 for c in all_cands if c.get("status") == "ОТКАЗ")
    frozen = sum(1 for c in all_cands if c.get("status") == "ЗАМОРОЗКА")

    scored = [c for c in all_cands if c.get("score", 0) > 0]
    avg_score = round(sum(c["score"] for c in scored) / len(scored), 1) if scored else 0

    # Авто-отказы за сегодня - раньше слались поштучно в группу (шумно), теперь
    # одним списком в сводке, чтобы можно было проверить и переиграть ошибки
    # парсинга (см. случай Софии - "10 класс" ошибочно прочитан как балл ЕГЭ)
    auto_rejected_today = [
        c for c in all_cands
        if c.get("status") == "ОТКАЗ"
        and "Не прошёл автоотбор" in (c.get("comment") or "")
        and (c.get("updated_at") or "")[:10] == today_str
    ]

    text = (
        f"📊 Итоги дня {today_str}\n\n"
        f"👥 Всего в базе: {total} (+{new_today} сегодня)\n"
        f"🎬 На проверке видео: {on_review}\n"
        f"👨‍💼 У Броски: {transferred}\n"
        f"📞 Ждут созвон: {ready_call}\n"
        f"📅 Созвон назначен: {scheduled}\n"
        f"📝 Договор отправлен: {dogovor}\n"
        f"✅ Договор подписан: {dogovor_signed}\n"
        f"🔑 Аккаунт получен: {account}\n"
        f"✅ Открыт: {opened}\n"
        f"❌ Отказ: {refused}\n"
        f"❄️ Заморозка: {frozen}\n\n"
        f"⭐ Средний скор: {avg_score}/10 ({len(scored)} оценок)"
    )

    if auto_rejected_today:
        names = "\n".join(f"- {c.get('name', '?')} ({c.get('username', '?')})" for c in auto_rejected_today)
        text += f"\n\n🤖 Авто-отказ за сегодня ({len(auto_rejected_today)}), проверить если что не так:\n{names}"

    try:
        await context.bot.send_message(ALERT_GROUP_ID, text)
    except Exception as e:
        logging.error(f"Daily stats send error: {e}")


def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("review", review))
    app.add_handler(CommandHandler("pipeline", pipeline))
    app.add_handler(CommandHandler("top", top))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    app.job_queue.run_repeating(notify_new_videos, interval=15, first=5)
    app.job_queue.run_repeating(heartbeat, interval=120, first=5)
    app.job_queue.run_repeating(daily_stats_job, interval=600, first=30)

    logging.info("Manager bot запущен...")
    app.run_polling()


if __name__ == "__main__":
    main()
