"""Тесты manager_bot.py: контроль доступа (ALLOWED_IDS) и callback-роутинг.

До этой задачи (T7 плана "полный проход по 10 аспектам") у manager_bot.py
не было ни одного теста, хотя это отдельный сервис (hr-manager-bot.service)
с доступом к БД кандидатов и кнопками, влияющими на решения (одобрить/
отказать/передать). Особый риск - если проверка ALLOWED_IDS пропущена в
каком-то из хендлеров, посторонний Telegram-пользователь получит доступ
к данным кандидатов или сможет менять статусы.
"""
import pytest


class FakeUser:
    def __init__(self, id):
        self.id = id


class FakeMessage:
    def __init__(self, text=""):
        self.replies = []
        self.text = text

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)


class FakeUpdate:
    def __init__(self, user_id, text=""):
        self.effective_user = FakeUser(user_id)
        self.message = FakeMessage(text=text)


# Хендлеры-кнопки, защищённые единой проверкой update.effective_user.id not
# in ALLOWED_IDS и всегда отвечающие хоть чем-то авторизованному пользователю
# (даже на пустую БД - "нет кандидатов"/сводка из нулей). handle_text - роутер
# по тексту кнопки, тестируется отдельно ниже (на пустой/несовпавший текст он
# МОЛЧА ничего не делает - это штатное поведение, не баг).
GUARDED_HANDLERS = [
    "start", "review", "pipeline", "top", "summary", "waiting",
    "calls", "transferred", "scheduled", "signed",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("handler_name", GUARDED_HANDLERS)
async def test_handler_silently_blocks_unauthorized_user(handler_name):
    """Посторонний Telegram-id (не менеджер, не Броски) не должен получить
    вообще никакого ответа - ни данных о кандидатах, ни любой другой
    информации. Молчание - единственно правильное поведение для чужого id."""
    import manager_bot

    handler = getattr(manager_bot, handler_name)
    update = FakeUpdate(user_id=999999999)  # заведомо не в ALLOWED_IDS

    await handler(update, context=None)

    assert update.message.replies == [], (
        f"{handler_name} ответил постороннему id - утечка доступа к данным кандидатов"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("handler_name", GUARDED_HANDLERS)
async def test_handler_responds_for_authorized_manager(handler_name):
    """Для реального менеджера (MANAGER_ID) хендлер должен отработать и
    прислать хотя бы один ответ - проверка ALLOWED_IDS не должна случайно
    заблокировать легитимного пользователя (пустая тестовая БД - хендлеры
    штатно отвечают "нет кандидатов"/сводкой из нулей, не падают)."""
    import manager_bot

    handler = getattr(manager_bot, handler_name)
    update = FakeUpdate(user_id=manager_bot.MANAGER_ID)

    await handler(update, context=None)

    assert len(update.message.replies) >= 1, (
        f"{handler_name} не ответил авторизованному менеджеру"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("handler_name", GUARDED_HANDLERS)
async def test_handler_responds_for_authorized_brosky(handler_name):
    """Тот же контроль для второго легитимного id - Броски (BROSKY_ID)."""
    import manager_bot

    handler = getattr(manager_bot, handler_name)
    update = FakeUpdate(user_id=manager_bot.BROSKY_ID)

    await handler(update, context=None)

    assert len(update.message.replies) >= 1, (
        f"{handler_name} не ответил авторизованному Броски"
    )


# ── handle_text: роутер по тексту кнопки, тестируется отдельно от GUARDED_HANDLERS ──

@pytest.mark.asyncio
async def test_handle_text_blocks_unauthorized_user():
    import manager_bot

    update = FakeUpdate(user_id=999999999, text="🎬 На проверку")
    await manager_bot.handle_text(update, context=None)

    assert update.message.replies == [], "handle_text ответил постороннему id"


@pytest.mark.asyncio
async def test_handle_text_routes_known_button_to_handler():
    """Известный текст кнопки должен реально дойти до целевого хендлера
    (review()) и получить ответ - проверяет сам факт роутинга, не только
    guard доступа."""
    import manager_bot

    update = FakeUpdate(user_id=manager_bot.MANAGER_ID, text="🎬 На проверку")
    await manager_bot.handle_text(update, context=None)

    assert len(update.message.replies) >= 1, "handle_text не доставил до review() по известной кнопке"


@pytest.mark.asyncio
async def test_handle_text_unmatched_text_does_nothing():
    """Незнакомый текст (не кнопка меню) - штатно молчит, не падает и не
    отвечает наугад каким-то хендлером."""
    import manager_bot

    update = FakeUpdate(user_id=manager_bot.MANAGER_ID, text="случайный текст не кнопка")
    await manager_bot.handle_text(update, context=None)

    assert update.message.replies == []


# ── button_callback: отдельная проверка доступа через query.from_user.id ──

class FakeCallbackQuery:
    def __init__(self, user_id, data):
        self.from_user = FakeUser(user_id)
        self.data = data
        self.answered = []
        self.edited = []

    async def answer(self, *a, **kw):
        self.answered.append((a, kw))

    async def edit_message_text(self, *a, **kw):
        self.edited.append((a, kw))

    async def edit_message_reply_markup(self, *a, **kw):
        self.edited.append((a, kw))


class FakeCallbackUpdate:
    def __init__(self, user_id, data):
        self.callback_query = FakeCallbackQuery(user_id, data)


@pytest.mark.asyncio
async def test_button_callback_blocks_unauthorized_user():
    """button_callback проверяет доступ отдельно (query.from_user.id, не
    update.effective_user.id, т.к. это callback от нажатия кнопки) - лёгкое
    место разъехаться с остальными хендлерами и забыть проверку."""
    import manager_bot

    update = FakeCallbackUpdate(user_id=999999999, data="approve_123")
    await manager_bot.button_callback(update, context=None)

    assert update.callback_query.answered == [], "Посторонний получил ответ на callback"
    assert update.callback_query.edited == [], "Посторонний смог вызвать эффект callback-кнопки"
