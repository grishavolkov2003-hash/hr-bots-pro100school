import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID = 36669184
API_HASH = "3976ae2af478e360569ecfc0cb728bfe"
SESSION = "1ApWapzMBu38pWjr3P1t0-MOqv9vTTuJj7yrdnVdoPm-PqPQbJH5l7ArGapXG9FBZxIjui1snWoMEEN-B3bO6DvRtFAQFWB-GI1wxfTNJ4KcO_PK3mGyyvWT_JywO_z2HLvksZuI33RMtK57ZSlO0TQuiBTlwtPS2M4bcYbq3GjRgqluHsnz_U0sGWtH1I8I842rbGMqo24B_ITLaSj9Xd26AaPMi7NfCfNXDrnuFo95Z6nDogDVWRTw7ZQ8Xt05avotB7_ZppRXLMjxW4mWMzhBB9H3UqMBZpUBNCyXxt9EvztZzQKe-fJyTvxBP-EMPLwbKCrslrjyRBSCAQKFqCs56jNY-WLs="

client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)

MESSAGES = [
    ("@Villora517", "Привет! Это Гриша (@tutor_zelimhan). Напоминаю про отзывы на Профи на аккаунт Роман 🙏 Когда получится попросить?"),
    ("@vadim65060", "Привет! Это Гриша (@tutor_zelimhan). Напоминаю про отзыв на Профи на аккаунт Роман 🙏 Когда получится попросить?"),
    ("@duh_poligona", "Привет! Это Гриша (@tutor_zelimhan). Напоминаю про отзывы на Профи на аккаунт Роман 🙏 Когда получится попросить?"),
    ("@g00db7e", "Привет! Это Гриша (@tutor_zelimhan). Напоминаю про отзыв на Профи на аккаунт Роман 🙏 Когда получится попросить?"),
    ("@gfch3k", "Привет! Это Гриша (@tutor_zelimhan). Напоминаю про отзывы на Профи на аккаунт Роман + Литие 🙏 Когда получится попросить?"),
    ("@saviorofgothamO_O", "Привет! Это Гриша (@tutor_zelimhan). Напоминаю про отзывы на Профи на аккаунт Роман + Литие 🙏 Когда получится попросить?"),
    ("@traxodron_24", "Привет! Это Гриша (@tutor_zelimhan). Напоминаю про отзыв на Профи на аккаунт Роман 🙏 Когда получится попросить?"),
    ("@eyesonjewelry", "Привет! Это Гриша (@tutor_zelimhan). Напоминаю про отзыв на Профи на аккаунт Алина 🙏 Когда получится попросить?"),
    ("@samokamillica", "Привет! Это Гриша (@tutor_zelimhan). Напоминаю про отзыв на Профи на аккаунт Алина 🙏 Когда получится попросить?"),
    ("@iveze", "Привет! Это Гриша (@tutor_zelimhan). Напоминаю про отзыв на Профи на аккаунт Амир 🙏 Когда получится попросить?"),
    ("@melnivan", "Привет! Это Гриша (@tutor_zelimhan). Напоминаю про отзывы на Профи на аккаунт Литие + Амир 🙏 Когда получится попросить?"),
    ("@shmitk", "Привет! Это Гриша (@tutor_zelimhan). Напоминаю про отзыв на Профи на аккаунт Амир 🙏 Когда получится попросить?"),
    ("@Sy_rai", "Привет! Это Гриша (@tutor_zelimhan). Напоминаю про отзыв на Профи на аккаунт Литие 🙏 Когда получится попросить?"),
    ("@chergintsev", "Привет! Это Гриша (@tutor_zelimhan). Напоминаю про отзыв на Профи на аккаунт Литие 🙏 Когда получится попросить?"),
    ("@recruiter_tg", "Привет! Это Гриша (@tutor_zelimhan). Напоминаю про отзыв на Профи на аккаунт Литие 🙏 Когда получится попросить?"),
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
