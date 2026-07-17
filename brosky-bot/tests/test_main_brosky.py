"""Тесты brosky-bot/main.py: авто-критерии, дедуп/гонки, QA-дебаунс, каскад decision_loop.

evaluate_auto_criteria/_recently_sent/_wait_and_reserve продублированы в
main.py каждого бота независимо (не общий модуль) - тесты здесь и в
hr-bot/tests специально не переиспользуют друг друга, чтобы ловить будущее
расхождение копий (кто-то поправит одну и забудет другую)."""
import asyncio
from datetime import datetime, timedelta

import pytest


# ── evaluate_auto_criteria (своя копия, drift-check) ────────────────────

def test_criteria_passes_strong_candidate():
    import main
    qualified, reasons = main.evaluate_auto_criteria({
        "егэ": "85", "опыт": "3 года репетиторства", "возраст": "25",
    })
    assert qualified is True


def test_criteria_substring_bug_regression():
    """Та же регрессия что и в hr-bot/tests - копия должна вести себя
    идентично, иначе критерии разъехались между ботами."""
    import main
    qualified, reasons = main.evaluate_auto_criteria({
        "егэ": "70", "опыт": "10 лет преподавания", "возраст": "35",
    })
    assert qualified is True, f"Регрессия substring-бага в brosky-bot! reasons={reasons}"


def test_criteria_underage_fails():
    import main
    qualified, reasons = main.evaluate_auto_criteria({
        "егэ": "90", "опыт": "1 год", "возраст": "17",
    })
    assert qualified is False
    assert "возраст" in reasons


# ── _recently_sent / _wait_and_reserve (своя копия) ─────────────────────

def test_recently_sent_true_immediately_after(make_candidate):
    import main
    make_candidate(500, status="ДОГОВОР_ОТПРАВЛЕН",
                    conversation=[{"role": "bot", "text": "привет", "time": datetime.now().isoformat()}])
    assert main._recently_sent(500) is True


def test_recently_sent_false_after_window(make_candidate):
    import main
    old = (datetime.now() - timedelta(seconds=main.DUPLICATE_GUARD_WINDOW_SEC + 10)).isoformat()
    make_candidate(501, status="ДОГОВОР_ОТПРАВЛЕН",
                    conversation=[{"role": "bot", "text": "привет", "time": old}])
    assert main._recently_sent(501) is False


@pytest.mark.asyncio
async def test_wait_and_reserve_serializes():
    import main
    main._active_responding.clear()
    user_id = 600601
    results = await asyncio.gather(
        main._wait_and_reserve(user_id, max_wait_sec=2),
        main._wait_and_reserve(user_id, max_wait_sec=2),
    )
    assert results.count(True) == 1
    main._active_responding.discard(user_id)


# ── QA-режим: дебаунс не теряет сообщения (регрессия/формализация Теста 2, 17.07) ──

@pytest.mark.asyncio
async def test_qa_debounce_no_content_loss(make_candidate, monkeypatch):
    """Два быстрых РАЗНЫХ сообщения кандидата в QA-режиме должны привести
    к ОДНОМУ вызову обработки, который видит ОБА сообщения - не к двум
    параллельным ответам и не к потере второго сообщения."""
    import main

    make_candidate(700, status="ДОГОВОР_ОТПРАВЛЕН",
                    conversation=[{"role": "bot", "text": "Договор отправлен", "time": datetime.now().isoformat()}])

    call_log = []

    async def fake_qa_message(user_id, username, name, chat_id):
        conv = main.get_conversation(user_id)
        texts = [c.get("text", "") for c in conv if c.get("role") == "candidate"]
        call_log.append(texts)

    monkeypatch.setattr(main, "_process_qa_message", fake_qa_message)

    main.add_message(700, "candidate", "Первый вопрос про комиссию")
    task1 = asyncio.create_task(main._process_qa_after_delay(700, "test", "Т", 700, delay=1))
    await asyncio.sleep(0.2)
    main.add_message(700, "candidate", "Второй вопрос про сроки")
    task1.cancel()
    task2 = asyncio.create_task(main._process_qa_after_delay(700, "test", "Т", 700, delay=1))
    await asyncio.sleep(2)

    assert len(call_log) == 1, f"Ожидали ровно 1 вызов обработки, получили {len(call_log)}"
    assert call_log[0] == ["Первый вопрос про комиссию", "Второй вопрос про сроки"]


# ── Барьер №3 vs настоящая гонка (регрессия/формализация Теста 4, 17.07) ──

@pytest.mark.asyncio
async def test_qa_barrier_blocks_concurrent_duplicate_send(make_candidate, monkeypatch):
    """РЕГРЕССИЯ: живым тестом 17.07 обнаружено что при ДВУХ по-настоящему
    одновременных вызовах _process_qa_after_delay для одного user_id барьер
    _recently_sent сам по себе пропускал оба (гонка между чтением и записью).
    Починено через _wait_and_reserve. Этот тест - формализованная версия
    того самого живого теста, который нашёл баг."""
    import main

    make_candidate(701, status="ДОГОВОР_ОТПРАВЛЕН",
                    conversation=[
                        {"role": "bot", "text": "Договор отправлен", "time": (datetime.now() - timedelta(seconds=200)).isoformat()},
                        {"role": "candidate", "text": "Вопрос про комиссию", "time": datetime.now().isoformat()},
                    ])

    send_calls = []

    async def fake_send_message(chat_id, text):
        send_calls.append(text)

    async def fake_simulate_typing(*a, **kw):
        pass

    def fake_get_qa_response(conversation, candidate, prompt):
        return "Комиссия 25%, всё как в договоре."

    monkeypatch.setattr(main.client, "send_message", fake_send_message)
    monkeypatch.setattr(main, "_simulate_typing", fake_simulate_typing)
    monkeypatch.setattr(main, "get_qa_response", fake_get_qa_response)

    await asyncio.gather(
        main._process_qa_after_delay(701, "test", "Т", 701, delay=0),
        main._process_qa_after_delay(701, "test", "Т", 701, delay=0),
    )

    assert len(send_calls) == 1, f"Ожидали ровно 1 реальную отправку, получили {len(send_calls)}: {send_calls}"


# ── decision_loop: каскад не блокируется барьером (регрессия/формализация Теста 5, 17.07) ──

@pytest.mark.asyncio
async def test_decision_loop_cascade_not_blocked_by_barrier(make_candidate, monkeypatch):
    """Барьер №3 и сериализация по _active_responding не должны мешать
    легитимному многошаговому каскаду decision_loop (комплимент → условия →
    2 авто-текста → аудио → PDF, ~6 сообщений за секунды). Барьер применяется
    ТОЛЬКО в _do_process/_patrol_respond/_process_qa_message, НЕ в
    decision_loop - это осознанное архитектурное решение, тест его закрепляет."""
    import main

    make_candidate(702, status="ГОТОВ_К_СОЗВОНУ", conversation_bot="brosky")

    send_msg_calls = []
    send_file_calls = []

    class FakePeer:
        id = 702

    async def fake_get_entity(x):
        return FakePeer()

    async def fake_send_message(peer, text):
        send_msg_calls.append(text[:40])

    async def fake_send_file(peer, path, **kwargs):
        send_file_calls.append(path)

    async def fake_simulate_typing(*a, **kw):
        pass

    monkeypatch.setattr(main.client, "get_entity", fake_get_entity)
    monkeypatch.setattr(main.client, "send_message", fake_send_message)
    monkeypatch.setattr(main.client, "send_file", fake_send_file)
    monkeypatch.setattr(main, "_simulate_typing", fake_simulate_typing)

    decision = {"id": 1, "candidate_user_id": 702, "decision": "approved", "approved_by": None}
    await main._process_one_decision(decision)

    assert len(send_msg_calls) == 4, f"Ожидали 4 текстовых сообщения каскада, получили {len(send_msg_calls)}"
    assert len(send_file_calls) == 2, f"Ожидали 2 файла (аудио+PDF), получили {len(send_file_calls)}"

    cand = main.get_candidate(702)
    assert cand["status"] == "ДОГОВОР_ОТПРАВЛЕН"


# ── T1: утечка CREDS_PATTERN (пароль profi.ru открытым текстом) ─────────

@pytest.mark.asyncio
async def test_handler_creds_redacted_in_conversation_and_sheets(make_candidate, monkeypatch):
    """РЕГРЕССИЯ: та же утечка что и в hr-bot (копия логики в этом файле) -
    сырой текст с логином/паролем писался в историю ДО проверки
    CREDS_PATTERN, а Sheets получал пароль открытым текстом в столбец 7.
    После фикса - в истории редактированный плейсхолдер, столбец 7 не
    трогается, пересылка коллеге mx_mish (единственное легитимное место)
    по-прежнему работает."""
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
