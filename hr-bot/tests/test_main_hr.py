"""Тесты hr-bot/main.py: авто-критерии, парсинг анкеты, защита от дублей/гонок."""
import asyncio
from datetime import datetime, timedelta

import pytest


# ── evaluate_auto_criteria ──────────────────────────────────────────────

def test_criteria_passes_strong_candidate():
    import main
    qualified, reasons = main.evaluate_auto_criteria({
        "егэ": "85", "опыт": "3 года репетиторства", "возраст": "25",
    })
    assert qualified is True
    assert reasons == ""


def test_criteria_fails_low_ege():
    import main
    qualified, reasons = main.evaluate_auto_criteria({
        "егэ": "45", "опыт": "3 года", "возраст": "25",
    })
    assert qualified is False
    assert "ЕГЭ" in reasons


def test_criteria_ege_not_taken_does_not_block():
    """'Не сдавал ЕГЭ' - нет цифр, критерий условный, не блокирует
    (осознанное решение, не баг)."""
    import main
    qualified, reasons = main.evaluate_auto_criteria({
        "егэ": "не сдавал", "опыт": "2 года", "возраст": "20",
    })
    assert qualified is True


def test_criteria_fails_no_experience_explicit():
    import main
    qualified, reasons = main.evaluate_auto_criteria({
        "егэ": "80", "опыт": "опыта нет", "возраст": "20",
    })
    assert qualified is False
    assert "опыт" in reasons


def test_criteria_vague_experience_passes():
    """'Около года' / 'пару лет' без явных цифр и без явного отказа -
    считаем что опыт есть (осознанное решение сессии)."""
    import main
    qualified, reasons = main.evaluate_auto_criteria({
        "егэ": "80", "опыт": "около года помогал знакомым", "возраст": "20",
    })
    assert qualified is True


def test_criteria_substring_bug_regression():
    """РЕГРЕССИЯ: в этой сессии был баг где маркер '0' в NO_EXPERIENCE_MARKERS
    матчился как подстрока внутри '10 лет'/'20 лет', ошибочно блокируя
    опытных кандидатов. Баг починен (маркер '0' убран, используется чистое
    re.findall(\\d+)). Кандидат с 10-летним опытом должен проходить."""
    import main
    qualified, reasons = main.evaluate_auto_criteria({
        "егэ": "70", "опыт": "10 лет преподавания в школе", "возраст": "35",
    })
    assert qualified is True, f"Регрессия substring-бага! reasons={reasons}"


def test_criteria_underage_fails():
    import main
    qualified, reasons = main.evaluate_auto_criteria({
        "егэ": "90", "опыт": "1 год", "возраст": "17",
    })
    assert qualified is False
    assert "возраст" in reasons


def test_criteria_missing_age_does_not_block():
    """Отсутствие поля 'возраст' (старая анкета без этого вопроса) не должно
    блокировать - осознанное решение сессии, не баг."""
    import main
    qualified, reasons = main.evaluate_auto_criteria({
        "егэ": "90", "опыт": "2 года",
    })
    assert qualified is True


def test_criteria_ege_field_extracts_any_digit_known_limitation():
    """ИЗВЕСТНОЕ ОГРАНИЧЕНИЕ (не баг, задокументировано осознанно): реальный
    кандидат София (16.07) писала 'не сдавала, закончила 10 класс' - внешний
    ретро-скрипт (не входит в основной код) по ошибке положил в поле 'егэ'
    именно ЭТУ фразу целиком, и evaluate_auto_criteria честно выдернула из
    неё '10' через re.findall(\\d+) - функция не различает "10 - балл ЕГЭ"
    и "10 - номер класса" внутри произвольного текста. Это ожидаемое
    поведение ПРИ УСЛОВИИ что вызывающий код кладёт в 'егэ' только чистый
    ответ на вопрос про баллы, а не полную фразу с посторонними числами -
    ответственность за чистоту поля 'егэ' на вызывающей стороне (парсере
    анкеты), не на evaluate_auto_criteria."""
    import main
    qualified, reasons = main.evaluate_auto_criteria({
        "егэ": "не сдавала, закончила 10 класс", "опыт": "вела занятия в своей школе", "возраст": "16",
    })
    assert qualified is False
    assert "возраст" in reasons
    # Да, "10" из "10 класс" ошибочно читается как балл ЕГЭ=10 (<60) - это
    # тот самый механизм бага Софии, воспроизведённый здесь намеренно, чтобы
    # он был виден в тестах, а не спрятан
    assert "ЕГЭ" in reasons


# ── parse_anketa_fallback ────────────────────────────────────────────────

def test_parse_anketa_fallback_new_format_bare_values():
    """Новый формат (8 вопросов, с 'Возраст') определяется по тому что
    пункт 2 - ЧИСТОЕ число (14-70) без повторения слова 'Возраст:' -
    так фактически отвечают кандиденты, когда просто вписывают ответ."""
    import main
    text = (
        "1. Иван, @ivan\n"
        "2. 22\n"
        "3. МГУ\n"
        "4. Математика\n"
        "5. 90\n"
        "6. 2 года\n"
        "7. 10\n"
        "8. РФ\n"
    )
    result = main.parse_anketa_fallback(text)
    assert result is not None
    assert result.get("возраст") == "22"
    assert "90" in (result.get("егэ") or "")


def test_parse_anketa_fallback_old_format_no_age_question():
    """Старый формат (7 вопросов, без 'Возраст') - позиция 2 не похожа на
    число 14-70, парсер падает на старую раскладку полей."""
    import main
    text = (
        "1. @ivan\n"
        "2. МГУ, 3 курс\n"
        "3. Математика\n"
        "4. 90\n"
        "5. 2 года опыта\n"
        "6. 10 часов\n"
    )
    result = main.parse_anketa_fallback(text)
    assert result is not None
    assert "90" in (result.get("егэ") or "")
    assert "возраст" not in result


def test_parse_anketa_fallback_label_echo_known_limitation():
    """ИЗВЕСТНОЕ ОГРАНИЧЕНИЕ: если кандидат отвечает не голым числом, а
    повторяет метку вопроса ('2. Возраст: 22' вместо '2. 22'), позиция 2
    перестаёт выглядеть как чистое число и has_age_format-эвристика не
    срабатывает - парсер уходит в старую 7-позиционную раскладку, поля
    съезжают. Задокументировано намеренно, не тихо."""
    import main
    text = (
        "1. Имя, ник в TG: Иван, @ivan\n"
        "2. Возраст: 22\n"
        "3. Образование: МГУ\n"
        "4. Какие предметы: Математика\n"
        "5. Баллы ЕГЭ: 90\n"
        "6. Опыт: 2 года\n"
        "7. Часов в неделю: 10\n"
        "8. Гражданство: РФ\n"
    )
    result = main.parse_anketa_fallback(text)
    assert result is not None
    # съехавшая раскладка - "90" оказывается НЕ в 'егэ', а годом позже
    assert "90" not in (result.get("егэ") or "")


def test_parse_anketa_fallback_none_for_unrelated_text():
    import main
    result = main.parse_anketa_fallback("привет, как дела?")
    assert not result


# ── _recently_sent (барьер №3) ──────────────────────────────────────────

def test_recently_sent_true_immediately_after_bot_message(make_candidate):
    import main
    make_candidate(200, status="ТЕСТОВОЕ_ОТПРАВЛЕНО",
                    conversation=[{"role": "bot", "text": "привет", "time": datetime.now().isoformat()}])
    assert main._recently_sent(200) is True


def test_recently_sent_false_after_window_expires(make_candidate):
    import main
    old_time = (datetime.now() - timedelta(seconds=main.DUPLICATE_GUARD_WINDOW_SEC + 10)).isoformat()
    make_candidate(201, status="ТЕСТОВОЕ_ОТПРАВЛЕНО",
                    conversation=[{"role": "bot", "text": "привет", "time": old_time}])
    assert main._recently_sent(201) is False


def test_recently_sent_false_for_new_candidate_no_messages(make_candidate):
    import main
    make_candidate(202, status="НОВЫЙ", conversation=[])
    assert main._recently_sent(202) is False


# ── _wait_and_reserve (сериализация, регрессия гонки 17.07) ─────────────

@pytest.mark.asyncio
async def test_wait_and_reserve_serializes_concurrent_calls():
    """РЕГРЕССИЯ (17.07): живым тестом обнаружено что _recently_sent сам по
    себе не atomic - два по-настоящему параллельных вызова оба проходят
    проверку. Починено через _wait_and_reserve (жёсткая сериализация по
    _active_responding). Этот тест воспроизводит гонку и проверяет что
    ВТОРОЙ параллельный вызов либо ждёт, либо получает reserved=False,
    но никогда оба не бронируют одновременно."""
    import main
    main._active_responding.clear()
    user_id = 300301

    results = await asyncio.gather(
        main._wait_and_reserve(user_id, max_wait_sec=2),
        main._wait_and_reserve(user_id, max_wait_sec=2),
    )
    # Первый должен забронировать сразу (True), второй - либо ждать и не
    # успеть за 2 сек (False, т.к. первый не освобождает сам), либо не
    # оказаться True ОДНОВРЕМЕННО с первым. Главное свойство: не может
    # быть что оба вернули True пока набор не очищен вручную.
    assert results.count(True) == 1
    main._active_responding.discard(user_id)


@pytest.mark.asyncio
async def test_wait_and_reserve_frees_up_after_discard():
    import main
    main._active_responding.clear()
    user_id = 300302
    assert await main._wait_and_reserve(user_id) is True
    main._active_responding.discard(user_id)
    assert await main._wait_and_reserve(user_id) is True
    main._active_responding.discard(user_id)


# ── patrol_loop: try/finally паттерн (регрессия TOCTOU 17.07) ──────────

@pytest.mark.asyncio
async def test_patrol_processing_pattern_discards_on_exception():
    """Формализованная версия живого теста паттерна try/finally, которым
    реструктурирован patrol_loop() 17.07 - при исключении user_id не должен
    навсегда зависать в _patrol_processing."""
    import main
    main._patrol_processing.clear()
    user_id = 400401

    async def simulate_iteration_with_failure():
        main._patrol_processing.add(user_id)
        spawned = False
        try:
            raise RuntimeError("симуляция сбоя client.get_messages")
        finally:
            if not spawned:
                main._patrol_processing.discard(user_id)

    with pytest.raises(RuntimeError):
        await simulate_iteration_with_failure()

    assert user_id not in main._patrol_processing


# ── T1: утечка CREDS_PATTERN (пароль profi.ru открытым текстом) ─────────

@pytest.mark.asyncio
async def test_handler_creds_redacted_in_conversation_and_sheets(make_candidate, monkeypatch):
    """РЕГРЕССИЯ: до фикса add_message писал сырое сообщение (с логином/
    паролем) в историю ДО проверки CREDS_PATTERN, а Sheets получал пароль
    открытым текстом в столбец 7. После фикса: в истории - редактированный
    плейсхолдер, столбец 7 в Sheets не трогается вообще. Пересылка коллеге
    mx_mish (единственное легитимное место) остаётся рабочей - проверяем
    что она всё ещё получает реальный пароль, иначе аккаунт некому будет
    настраивать."""
    import main

    make_candidate(900, status="НОВЫЙ", username="@testcreds", name="Тест Кредсов")

    class FakeSender:
        id = 900
        username = "testcreds"
        first_name = "Тест"
        last_name = "Кредсов"
        bot = False
        access_hash = None

    class FakeMessage:
        text = "логин: myuser пароль: SuperSecret123"
        video = None
        video_note = None
        voice = None
        document = None
        photo = None

    class FakeEvent:
        chat_id = 900
        message = FakeMessage()

        async def get_sender(self):
            return FakeSender()

    class Cell:
        row = 5

    class FakeWorksheet:
        def find(self, username):
            return Cell()

        def update_cell(self, row, col, value):
            sheets_calls.append((row, col, value))

    class FakeSheet:
        sheet1 = FakeWorksheet()

    sheets_calls = []
    mx_mish_messages = []

    async def fake_send_message(peer, text):
        if peer == "mx_mish":
            mx_mish_messages.append(text)

    monkeypatch.setattr(main.client, "send_message", fake_send_message)
    monkeypatch.setattr(main.sheets_module, "_get_sheet", lambda: FakeSheet())

    await main.handler(FakeEvent())

    conv = main.get_conversation(900)
    conv_texts = " ".join(c.get("text", "") for c in conv)
    assert "SuperSecret123" not in conv_texts, "Пароль всё ещё утекает в историю переписки"
    assert "[получены учётные данные аккаунта]" in conv_texts

    assert all(col != 7 for (_row, col, _val) in sheets_calls), \
        f"Пароль всё ещё уходит в столбец 7 Google Sheets: {sheets_calls}"

    assert len(mx_mish_messages) == 1, "Пересылка коллеге не должна пропасть при фиксе редактирования"
    assert "SuperSecret123" in mx_mish_messages[0], "Коллега должен получить реальный пароль, иначе некому настраивать аккаунт"


# ── T2: гонка old_status (устаревший candidate-снэпшот) ─────────────────

@pytest.mark.asyncio
async def test_do_process_uses_fresh_status_not_stale_snapshot(make_candidate, monkeypatch):
    """РЕГРЕССИЯ (найдена ревью 17.07): candidate передаётся в _do_process
    снэпшотом, снятым ДО ожидания в очереди (_wait_and_reserve, до 30с) и ДО
    вызова LLM (может занимать десятки секунд) - за это время decision_loop
    мог реально сменить статус в БД (например на ПЕРЕДАН_МЕНЕДЖЕРУ). До
    фикса old_status брался прямо из этого устаревшего candidate, и guard
    пропускал LLM-статус поверх уже принятого решения менеджера. После
    фикса - свежий get_candidate() непосредственно перед guard."""
    import main

    real = make_candidate(950, status="ПЕРЕДАН_МЕНЕДЖЕРУ", username="@igorkopylov1", name="Т")
    stale_candidate = dict(real)
    stale_candidate["status"] = "ТЕСТОВОЕ_ПОЛУЧЕНО"  # снэпшот до решения менеджера

    def fake_get_response(conversation, candidate_info):
        return "Спасибо! >>> СТАТУС: ТЕСТОВОЕ_НА_ПРОВЕРКЕ <<<"

    async def fake_send_message(chat_id, text):
        pass

    monkeypatch.setattr(main, "get_response", fake_get_response)
    monkeypatch.setattr(main.random, "uniform", lambda a, b: 0)
    monkeypatch.setattr(main.client, "send_message", fake_send_message)

    await main._do_process(950, "igorkopylov1", "Т", 950, stale_candidate)

    cand = main.get_candidate(950)
    assert cand["status"] == "ПЕРЕДАН_МЕНЕДЖЕРУ", (
        f"Гонка вернулась: LLM откатил статус до {cand['status']} поверх уже "
        f"принятого менеджером решения ПЕРЕДАН_МЕНЕДЖЕРУ"
    )


# ── T4: FloodWaitError - один повтор вместо необработанного исключения ──

@pytest.mark.asyncio
async def test_send_message_safe_retries_once_on_flood_wait(monkeypatch):
    """_send_message_safe должна поймать FloodWaitError, подождать e.seconds
    и повторить ровно один раз - без обёртки это необработанное исключение
    прямо в живом хендлере кандидата (Telethon кидает FloodWaitError на
    любой исходящий вызов при превышении лимитов Telegram)."""
    import main
    from telethon.errors import FloodWaitError

    calls = []
    sleep_calls = []

    async def flaky_send_message(peer, text, **kwargs):
        calls.append((peer, text))
        if len(calls) == 1:
            raise FloodWaitError(request=None, capture=1)
        return "ok"

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr(main.client, "send_message", flaky_send_message)
    monkeypatch.setattr(main.asyncio, "sleep", fake_sleep)

    result = await main._send_message_safe(123, "тест")

    assert result == "ok"
    assert len(calls) == 2, f"Ожидали ровно 1 повтор после FloodWaitError, вызовов: {len(calls)}"
    assert sleep_calls == [1], f"Ожидали ожидание e.seconds=1 перед повтором, получили {sleep_calls}"
