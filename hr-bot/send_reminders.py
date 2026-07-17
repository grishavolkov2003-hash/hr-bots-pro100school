import asyncio
import os
from telethon import TelegramClient
from telethon.sessions import StringSession
from dotenv import load_dotenv

load_dotenv("/opt/hr-bot/.env")

API_ID = int(os.getenv("TELEGRAM_API_ID"))
API_HASH = os.getenv("TELEGRAM_API_HASH")
SESSION = os.getenv("TELEGRAM_SESSION_STRING")

client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)

MESSAGES = [
    ("@Villora517", "Привет! Напоминаю про отзывы на Профи на аккаунт Роман 🙏 Когда получится попросить?"),
    ("@vadim65060", "Привет! Напоминаю про отзыв на Профи на аккаунт Роман 🙏 Когда получится попросить?"),
    ("@duh_poligona", "Привет! Напоминаю про отзывы на Профи на аккаунт Роман 🙏 Когда получится попросить?"),
    ("@g00db7e", "Привет! Напоминаю про отзыв на Профи на аккаунт Роман 🙏 Когда получится попросить?"),
    ("@gfch3k", "Привет! Напоминаю про отзывы на Профи на аккаунт Роман + Литие 🙏 Когда получится попросить?"),
    ("@saviorofgothamO_O", "Привет! Напоминаю про отзывы на Профи на аккаунт Роман + Литие 🙏 Когда получится попросить?"),
    ("@traxodron_24", "Привет! Напоминаю про отзыв на Профи на аккаунт Роман 🙏 Когда получится попросить?"),
    ("@vaanyaasleep", "Привет! Напоминаю про отзывы на Профи на аккаунт Роман + Амир 🙏 Когда получится попросить?"),
    ("@eyesonjewelry", "Привет! Напоминаю про отзыв на Профи на аккаунт Алина 🙏 Когда получится попросить?"),
    ("@samokamillica", "Привет! Напоминаю про отзыв на Профи на аккаунт Алина 🙏 Когда получится попросить?"),
    ("@iveze", "Привет! Напоминаю про отзыв на Профи на аккаунт Амир 🙏 Когда получится попросить?"),
    ("@melnivan", "Привет! Напоминаю про отзывы на Профи на аккаунт Литие + Амир 🙏 Когда получится попросить?"),
    ("@shmitk", "Привет! Напоминаю про отзыв на Профи на аккаунт Амир 🙏 Когда получится попросить?"),
    ("@elenash464", "Привет! Напоминаю про отзывы на Профи на аккаунт Вита 🙏 Когда получится попросить?"),
    ("@Sy_rai", "Привет! Напоминаю про отзыв на Профи на аккаунт Литие 🙏 Когда получится попросить?"),
    ("@chergintsev", "Привет! Напоминаю про отзыв на Профи на аккаунт Литие 🙏 Когда получится попросить?"),
    ("@recruiter_tg", "Привет! Напоминаю про отзыв на Профи на аккаунт Литие 🙏 Когда получится попросить?"),
    ("@nemok1rra", "Привет! Напоминаю про отзыв на Профи на аккаунт Литие 🙏 Когда получится попросить?"),
]


async def main():
    await client.start()
    ok = 0
    fail = 0
    for username, text in MESSAGES:
        try:
            entity = await client.get_entity(username)
            await client.send_message(entity, text)
            print(f"OK: {username}")
            ok += 1
        except Exception as e:
            print(f"FAIL: {username} — {e}")
            fail += 1
        await asyncio.sleep(10)
    print(f"\nИтого: {ok} отправлено, {fail} ошибок")
    await client.disconnect()


with client:
    client.loop.run_until_complete(main())
