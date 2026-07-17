"""Тесты storage.py - общий модуль для hr-bot и brosky-bot (симлинк)."""
import json


def test_add_message_roundtrip(make_candidate):
    import storage
    make_candidate(111, status="НОВЫЙ")
    storage.add_message(111, "candidate", "Привет")
    storage.add_message(111, "bot", "Привет! Заполните анкету")
    conv = storage.get_conversation(111)
    assert len(conv) == 2
    assert conv[0]["role"] == "candidate"
    assert conv[0]["text"] == "Привет"
    assert conv[1]["role"] == "bot"


def test_add_message_limit_is_300_not_30(make_candidate):
    """Регрессия: лимит хранения истории подняли с 30 до 300 (Задача 1,
    17.07) после того как реальные данные показали 4.45% диалогов теряли
    историю из-за старого лимита в 30. Проверяем что лимит реально 300,
    а не откатился обратно."""
    import storage
    make_candidate(112, status="НОВЫЙ")
    for i in range(305):
        storage.add_message(112, "candidate" if i % 2 == 0 else "bot", f"сообщение {i}")
    conv = storage.get_conversation(112)
    assert len(conv) == 300
    # Хранятся ПОСЛЕДНИЕ 300, а не первые
    assert conv[-1]["text"] == "сообщение 304"
    assert conv[0]["text"] == "сообщение 5"


def test_add_message_under_limit_keeps_everything(make_candidate):
    import storage
    make_candidate(113, status="НОВЫЙ")
    for i in range(10):
        storage.add_message(113, "candidate", f"msg{i}")
    conv = storage.get_conversation(113)
    assert len(conv) == 10


def test_get_conversation_empty_for_new_candidate(make_candidate):
    import storage
    make_candidate(114, status="НОВЫЙ")
    assert storage.get_conversation(114) == []


def test_create_candidate_is_idempotent(make_candidate):
    """INSERT OR IGNORE - повторный create_candidate не должен затирать
    уже накопленные данные существующего кандидата."""
    import storage
    make_candidate(115, status="ТЕСТОВОЕ_ОТПРАВЛЕНО", comment="важный комментарий")
    storage.create_candidate(115, "@test", "Тест")
    cand = storage.get_candidate(115)
    assert cand["status"] == "ТЕСТОВОЕ_ОТПРАВЛЕНО"
    assert cand["comment"] == "важный комментарий"
