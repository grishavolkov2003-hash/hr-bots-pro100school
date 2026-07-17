import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession
from dotenv import load_dotenv
import os, sqlite3, json
from datetime import datetime

load_dotenv()

client = TelegramClient(
    StringSession(os.getenv("TELEGRAM_SESSION_STRING")),
    int(os.getenv("TELEGRAM_API_ID")),
    os.getenv("TELEGRAM_API_HASH"),
)

IGNORE = {"tutor_zelimhan", "brosky_manage", "nemok1rra", "kfanenshtil", "andruy28",
          "pro100school_manager", "groupanonymousbot", "channel_bot", "telegram",
          "pro100hrbot", "igorkopylov1"}

# Internal contacts (not candidates) - skip these
INTERNAL = {
    "managman121", "duh_poligona", "iliya_999999", "hobyaka", "wh3teee",
    "chateaulafite_e", "iveze", "el_sstell", "wenatt", "arcosinus",
    "amirhansh", "mkoshkina", "osipovvvns", "crranberry24", "ss_s_r",
    "diasshhha17", "marynik13", "melbezi", "hadllee", "floiru",
    "jmih_pojil", "alinss06", "sonia_popova", "wildmaxxxx",
    "alchemistalehandro", "aashanfr", "saybesk", "dianatokmakova",
    "eyesonjewelry", "slaskalsls", "evuyan", "la_si_enne", "darkext",
    "x9micexd",
}

VACANCY_KEYWORDS = [
    "вакансии", "вакансию", "репетитор", "математик", "hh.ru", "hh", "сотрудничест",
    "откликал", "откликнул", "приглашение", "работ", "преподав", "анкет",
    "копылов", "задание", "визитк", "резюме", "собеседовани",
]

async def main():
    await client.start()
    dialogs = await client.get_dialogs(limit=300)

    conn = sqlite3.connect("candidates.db")
    conn.row_factory = sqlite3.Row
    db_uids = set(r[0] for r in conn.execute("SELECT user_id FROM candidates").fetchall())

    added = 0
    skipped_internal = 0
    skipped_no_match = 0

    for d in dialogs:
        if not d.is_user or d.entity.bot:
            continue
        uname = (d.entity.username or "").lower()
        if uname in IGNORE or uname in INTERNAL:
            skipped_internal += 1
            continue
        uid = d.entity.id
        if uid in db_uids or uid == 777000:
            continue

        name = (d.entity.first_name or "") + (" " + (d.entity.last_name or "")).rstrip()
        msgs = await client.get_messages(d.entity, limit=15)

        all_text = " ".join([(m.text or "") for m in msgs]).lower()
        is_candidate = any(kw in all_text for kw in VACANCY_KEYWORDS)

        if not is_candidate:
            skipped_no_match += 1
            continue

        # Determine status from conversation
        out_msgs = [m for m in msgs if m.out and m.text]
        in_msgs = [m for m in msgs if not m.out and m.text]

        status = "НОВЫЙ"
        has_conditions = any("75%" in (m.text or "") for m in out_msgs)
        has_call = any("созвон" in (m.text or "").lower() for m in out_msgs)
        has_video = any(m.video or m.video_note for m in msgs if not m.out)
        has_anketa_response = any("получил" in (m.text or "").lower() and "записал" in (m.text or "").lower() for m in out_msgs)
        has_scheduled = any("записал" in (m.text or "").lower() and ("мск" in (m.text or "").lower() or "завтра" in (m.text or "").lower()) for m in out_msgs)

        if has_scheduled and has_call:
            status = "СОЗВОН_НАЗНАЧЕН"
        elif has_conditions:
            status = "ГОТОВ_К_СОЗВОНУ"
        elif has_anketa_response or has_video:
            status = "ТЕСТОВОЕ_ПОЛУЧЕНО"
        elif any("анкет" in (m.text or "").lower() or "задани" in (m.text or "").lower() for m in out_msgs):
            status = "ТЕСТОВОЕ_ОТПРАВЛЕНО"

        # Build conversation
        conv = []
        for m in reversed(msgs):
            t = m.text or ""
            if not t.strip():
                if m.video or m.video_note or m.voice:
                    t = "[Отправлено медиа: видео/голосовое]"
                elif m.photo:
                    t = "[Отправлено фото]"
                elif m.document:
                    t = "[Отправлен документ]"
                else:
                    continue
            role = "bot" if m.out else "candidate"
            conv.append({"role": role, "content": t})

        # Extract subject from text
        subject = ""
        for kw in ["математик", "физик", "информатик", "русск"]:
            if kw in all_text:
                if "математик" in all_text:
                    subject = "математика"
                if "физик" in all_text:
                    subject = (subject + ", физика").lstrip(", ")
                if "информатик" in all_text:
                    subject = (subject + ", информатика").lstrip(", ")
                if "русск" in all_text:
                    subject = (subject + ", русский язык").lstrip(", ")
                break

        conn.execute("""
            INSERT OR IGNORE INTO candidates (user_id, username, name, status, subject, conversation, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (uid, f"@{uname}" if uname else "", name, status, subject,
              json.dumps(conv, ensure_ascii=False),
              datetime.now().isoformat(), datetime.now().isoformat()))

        added += 1
        print(f"  + @{uname} ({name}) -> {status} | {subject} | {len(conv)} msgs")

    conn.commit()
    conn.close()
    await client.disconnect()

    print(f"\nДобавлено: {added}")
    print(f"Пропущено внутренних: {skipped_internal}")
    print(f"Пропущено не-кандидатов: {skipped_no_match}")

asyncio.run(main())
