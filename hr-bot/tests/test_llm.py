"""Тесты llm.py - общий модуль (build_messages, история, сводка по статусу)."""


def test_max_history_messages_is_30():
    """Регрессия: подняли с 16 до 30 по замеру p95 реальных диалогов
    (Задача 1, 17.07) - если кто-то откатит константу, тест упадёт."""
    import llm
    assert llm.MAX_HISTORY_MESSAGES == 30


def test_status_progress_summary_has_all_valid_statuses():
    """STATUS_PROGRESS_SUMMARY должен покрывать каждый статус из VALID_STATUSES
    обоих ботов - иначе кандидат в непокрытом статусе получит пустую сводку
    и мы вернёмся к исходной проблеме "бот не понимает на каком он этапе"."""
    import llm
    import main as main_hr

    for status in main_hr.VALID_STATUSES:
        assert status in llm.STATUS_PROGRESS_SUMMARY, f"Статус {status} не описан в сводке"


def test_build_messages_includes_status_and_progress():
    from llm import build_messages
    candidate_info = {
        "name": "Иван", "username": "@ivan", "subject": "Математика",
        "status": "ДОГОВОР_ОТПРАВЛЕН", "comment": "",
    }
    messages = build_messages([], candidate_info)
    context = messages[0]["content"]
    assert "ДОГОВОР_ОТПРАВЛЕН" in context
    assert "договор" in context.lower()  # сводка про уже пройденные шаги


def test_build_messages_new_candidate_has_no_progress_claim():
    from llm import build_messages
    candidate_info = {"name": "Новый", "username": "@n", "subject": "-", "status": "НОВЫЙ", "comment": ""}
    messages = build_messages([], candidate_info)
    assert "ничего, самое начало" in messages[0]["content"]


def test_build_messages_trims_history_to_max():
    from llm import build_messages, MAX_HISTORY_MESSAGES
    conversation = [
        {"role": "candidate" if i % 2 == 0 else "bot", "text": f"msg{i}"}
        for i in range(50)
    ]
    candidate_info = {"name": "Т", "username": "@t", "subject": "-", "status": "НОВЫЙ", "comment": ""}
    messages = build_messages(conversation, candidate_info)
    # 2 системных + не больше MAX_HISTORY_MESSAGES реальных (могут слиться подряд идущие одной роли)
    real_messages = messages[2:]
    assert len(real_messages) <= MAX_HISTORY_MESSAGES
    # последнее сообщение диалога должно попасть в контекст
    joined = " ".join(m["content"] for m in real_messages)
    assert "msg49" in joined
    # a сообщение из начала (за пределами окна) - не должно
    assert "msg0" not in joined


def test_build_messages_merges_consecutive_same_role():
    from llm import build_messages
    conversation = [
        {"role": "candidate", "text": "первая часть"},
        {"role": "candidate", "text": "вторая часть"},
    ]
    candidate_info = {"name": "Т", "username": "@t", "subject": "-", "status": "НОВЫЙ", "comment": ""}
    messages = build_messages(conversation, candidate_info)
    real_messages = messages[2:]
    assert len(real_messages) == 1
    assert "первая часть" in real_messages[0]["content"]
    assert "вторая часть" in real_messages[0]["content"]
