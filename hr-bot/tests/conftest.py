import os
import sys
import tempfile

# КРИТИЧНО: должно выполниться ДО того как что-либо (даже другие conftest'ы
# или тестовые модули) импортирует config.py/storage.py/main.py - иначе
# DB_PATH зафиксируется на реальный /opt/hr-bot/candidates.db через .env
# (config.py делает load_dotenv(), который НЕ перезаписывает уже
# установленную переменную окружения - на этом и держится изоляция).
_TEST_DB = os.path.join(tempfile.gettempdir(), "test_candidates_hrbot.db")
os.environ["DB_PATH"] = _TEST_DB

_BOT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BOT_ROOT not in sys.path:
    sys.path.insert(0, _BOT_ROOT)

import sqlite3
import pytest


@pytest.fixture(autouse=True)
def clean_db():
    """Каждый тест получает чистую изолированную БД - никогда не трогает
    реальный /opt/hr-bot/candidates.db с данными живых кандидатов."""
    if os.path.exists(_TEST_DB):
        os.remove(_TEST_DB)
    import storage
    storage.init_db()
    # manager_decisions создаётся лениво внутри decision_loop() (не в
    # storage.init_db()) - тесты, вызывающие _process_one_decision напрямую
    # (в обход самого decision_loop), должны создать её сами.
    conn = sqlite3.connect(_TEST_DB, timeout=10)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS manager_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_user_id INTEGER,
            decision TEXT,
            created_at TEXT,
            processed INTEGER DEFAULT 0,
            approved_by INTEGER
        )
    """)
    conn.commit()
    conn.close()
    yield
    if os.path.exists(_TEST_DB):
        os.remove(_TEST_DB)


@pytest.fixture
def make_candidate():
    """Фабрика тестовых кандидатов - идёт через реальные storage.create_candidate/
    update_candidate (не сырой SQL), чтобы тест не разъезжался со схемой."""
    import storage
    import json

    def _make(user_id, status="НОВЫЙ", username="@test", name="Тест",
              conversation=None, conversation_bot=None, comment="", auto_qualified=0):
        storage.create_candidate(user_id, username, name)
        kwargs = {"status": status, "comment": comment, "auto_qualified": auto_qualified}
        if conversation is not None:
            kwargs["conversation"] = json.dumps(conversation, ensure_ascii=False)
        if conversation_bot is not None:
            kwargs["conversation_bot"] = conversation_bot
        storage.update_candidate(user_id, **kwargs)
        return storage.get_candidate(user_id)
    return _make
