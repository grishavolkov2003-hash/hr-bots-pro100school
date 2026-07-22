import anthropic
import json
import re
import logging
from config import ANTHROPIC_API_KEY
from prompt import SYSTEM_PROMPT
import os

BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")

client = anthropic.Anthropic(
    api_key=ANTHROPIC_API_KEY,
    base_url=BASE_URL,
)


GARBAGE_PREFIXES = [
    "ПРЕДПОЛЁТНАЯ ПРОВЕРКА", "ПРЕДПОЛЕТНАЯ ПРОВЕРКА",
    "Thinking Process", "thinking process",
    "]<]minimax", "pre-flight check",
    "Скажи, что он", "I'm going to answer",
    "Based on the conversation",
]

def _strip_thinking(text):
    if not text:
        return text
    text = re.sub(r'(?i)<thinking>.*?</thinking>', '', text, flags=re.DOTALL)
    stripped = text.strip()
    for prefix in GARBAGE_PREFIXES:
        if stripped.startswith(prefix):
            lines = stripped.split('\n')
            clean_lines = []
            skip = True
            for line in lines:
                if skip:
                    if any(line.strip().startswith(p) for p in GARBAGE_PREFIXES) or not line.strip():
                        continue
                    if re.search(r'[а-яёА-ЯЁ]', line) and not re.match(r'^\d+\.\s', line):
                        skip = False
                        clean_lines.append(line)
                else:
                    clean_lines.append(line)
            result = '\n'.join(clean_lines).strip()
            return result if result else None
    if 'Thinking Process' not in text and 'thinking process' not in text:
        return text.strip()
    lines = text.split('\n')
    result_lines = []
    in_thinking = False
    for line in lines:
        if re.match(r'(?i)^\s*thinking process', line):
            in_thinking = True
            continue
        if in_thinking:
            stripped = line.strip()
            if not stripped or re.match(r'^\d+\.', stripped) or stripped.startswith('*') or stripped.startswith('-') or stripped.startswith('**'):
                continue
            has_cyrillic = bool(re.search(r'[а-яёА-ЯЁ]', stripped))
            has_numbering = bool(re.match(r'^\d+\.?\s', stripped))
            if has_cyrillic and not has_numbering:
                in_thinking = False
                result_lines.append(line)
        else:
            result_lines.append(line)
    return '\n'.join(result_lines).strip()


# Было 16 - по логам p50=8, p90=23, p95=29 сообщений на диалог, то есть
# больше 16 модель не видела почти пятую часть всех диалогов. 30 покрывает
# p95 полностью, дальше уже разумный компромисс с ростом токенов.
MAX_HISTORY_MESSAGES = 30

# Статус - объективный факт из БД, а не то что LLM должна вычислить по
# сырому тексту истории (история к тому же обрезается по MAX_HISTORY_MESSAGES
# и физически удаляется в storage.py после 300 сообщений). Даём модели
# готовую сводку "что уже пройдено" вместо того чтобы полагаться на
# самостоятельную интерпретацию - не отменяет нужды в самой истории,
# но снижает шанс что бот "забудет" про уже пройденные этапы воронки.
STATUS_PROGRESS_SUMMARY = {
    "НОВЫЙ": "",
    "ТЕСТОВОЕ_ОТПРАВЛЕНО": "анкета собрана, видеовизитка запрошена и ещё не получена",
    "ТЕСТОВОЕ_ПОЛУЧЕНО": "анкета собрана, видеовизитка получена, передаётся на проверку",
    "ТЕСТОВОЕ_НА_ПРОВЕРКЕ": "анкета и видеовизитка получены, на проверке у менеджера",
    "ГОТОВ_К_СОЗВОНУ": "видео одобрено менеджером, идёт прогрев к созвону",
    "ПЕРЕДАН_МЕНЕДЖЕРУ": "видео одобрено, кандидат передан коллеге для созвона/договора",
    "СОЗВОН_НАЗНАЧЕН": "кандидат одобрен, созвон назначен",
    "ДОГОВОР_ОТПРАВЛЕН": "кандидат одобрен, договор и материалы отправлены, идут вопросы по ним",
    "ДОГОВОР_ПОДПИСАН": "договор подписан, запрошено фото/материалы для карточки профиля",
    "АККАУНТ_ПОЛУЧЕН": "договор подписан, логин/пароль от аккаунта получены",
    "ОТКРЫТ": "аккаунт полностью оформлен и открыт",
    "ОТКАЗ": "кандидату отказано",
    "ЗАМОРОЗКА": "диалог долго неактивен",
}


def build_messages(conversation, candidate_info):
    status = candidate_info.get('status', 'НОВЫЙ')
    progress = STATUS_PROGRESS_SUMMARY.get(status, "")
    # Имя до заполнения анкеты (comment пуст) - это сырой профиль Telegram
    # (first_name), а не подтверждённое имя человека: может быть буквой,
    # ником, эмодзи, чем угодно. Явно предупреждаем модель, иначе она
    # обращается по нему как по настоящему имени в первых же сообщениях.
    name_note = "" if candidate_info.get("comment") else " (это НЕ подтверждённое имя, а ник/имя из Telegram-профиля - кандидат ещё не представился и не заполнил анкету; не используй это как обращение по имени, общайся нейтрально пока анкета не даст настоящее имя)"
    context = f"""Информация о кандидате:
- Имя: {candidate_info.get('name', 'неизвестно')}{name_note}
- Username: {candidate_info.get('username', 'нет')}
- Предмет: {candidate_info.get('subject', 'не указан')}
- Статус: {status}
- Уже пройдено (факт, не нужно перепроверять по истории): {progress or 'ничего, самое начало'}
- Комментарий: {candidate_info.get('comment', '')}
"""
    messages = [
        {"role": "user", "content": context},
        {"role": "assistant", "content": "Понял, работаю с этим кандидатом."},
    ]
    trimmed = conversation[-MAX_HISTORY_MESSAGES:] if len(conversation) > MAX_HISTORY_MESSAGES else conversation
    for msg in trimmed:
        role = "user" if msg["role"] == "candidate" else "assistant"
        text = msg.get("content") or msg.get("text", "")
        if not text.strip():
            continue
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"] += "\n" + text
        else:
            messages.append({"role": role, "content": text})
    return messages


def get_response(conversation, candidate_info):
    messages = build_messages(conversation, candidate_info)
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=2048,
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            messages=messages,
        )
        if response.stop_reason in ("max_tokens", "length"):
            # Ответ обрублен на середине (не хватило токенов на видимый текст,
            # например из-за длинного скрытого reasoning) - лучше не слать
            # кандидату обрывок фразы, чем отправить битое сообщение.
            logging.info(f"LLM truncated (max_tokens hit), пропускаем ответ")
            return None
        return _strip_thinking(response.content[0].text)
    except Exception as e:
        logging.error(f"LLM error: {e}")
        return None


def get_qa_response(conversation, candidate_info, qa_system_prompt):
    messages = build_messages(conversation, candidate_info)
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=2048,
            system=[{"type": "text", "text": qa_system_prompt, "cache_control": {"type": "ephemeral"}}],
            messages=messages,
        )
        if response.stop_reason in ("max_tokens", "length"):
            logging.info(f"QA LLM truncated (max_tokens hit), пропускаем ответ")
            return None
        return _strip_thinking(response.content[0].text)
    except Exception as e:
        logging.error(f"QA LLM error: {e}")
        return None


MANAGER_SYSTEM = """Ты — ассистент менеджера онлайн-школы по найму репетиторов. Менеджер пишет тебе в Telegram, ты отвечаешь коротко и по делу.

У тебя есть полная база кандидатов с их статусами и историей переписок. Ты можешь:
- Дать сводку по набору (сколько кандидатов, на каком этапе)
- Рассказать про конкретного кандидата (найти по имени/username)
- Ответить на вопросы по ситуации
- Дать рекомендации кого одобрить/отклонить
- Показать скоринг кандидатов

Отвечай коротко, структурированно. Если спрашивают сводку — дай таблицу. Если про конкретного человека — дай всю инфу включая скор.

Статусы воронки:
- НОВЫЙ — только написал
- ТЕСТОВОЕ_ОТПРАВЛЕНО — получил анкету и задание
- ТЕСТОВОЕ_ПОЛУЧЕНО — прислал видео, на проверке
- ТЕСТОВОЕ_НА_ПРОВЕРКЕ — видео передано на проверку
- ГОТОВ_К_СОЗВОНУ — одобрен, ждёт созвон
- СОЗВОН_НАЗНАЧЕН — дата/время согласованы
- ДОГОВОР_ОТПРАВЛЕН — договор на подписи
- АККАУНТ_ПОЛУЧЕН — логин/пароль получены
- ОТКРЫТ — всё оформлено, работает
- ОТКАЗ — отказался
- ЗАМОРОЗКА — не отвечает
"""


def get_manager_response(question, all_candidates):
    candidates_summary = []
    for c in all_candidates:
        conv = json.loads(c.get("conversation", "[]"))
        last_msgs = conv[-3:] if conv else []
        last_text = " | ".join([f"{'👤' if m['role']=='candidate' else '🤖'} {(m.get('content') or m.get('text', ''))[:80]}" for m in last_msgs])
        candidates_summary.append(
            f"- {c.get('name', '?')} ({c.get('username', '?')}) | Предмет: {c.get('subject', '?')} | "
            f"Статус: {c.get('status', '?')} | Скор: {c.get('score', 0)}/10 | "
            f"Комментарий: {c.get('comment', '')} | "
            f"Последние сообщения: {last_text}"
        )

    context = f"База кандидатов ({len(all_candidates)} чел.):\n" + "\n".join(candidates_summary)

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=2048,
            system=[{"type": "text", "text": MANAGER_SYSTEM, "cache_control": {"type": "ephemeral"}}],
            messages=[
                {"role": "user", "content": context + "\n\n---\n\nВопрос менеджера: " + question},
            ],
        )
        return _strip_thinking(response.content[0].text)
    except Exception as e:
        logging.error(f"Manager LLM error: {e}")
        return None
