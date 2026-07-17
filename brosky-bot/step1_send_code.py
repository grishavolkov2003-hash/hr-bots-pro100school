import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID = 36669184
API_HASH = "3976ae2af478e360569ecfc0cb728bfe"
PHONE = "+79915878932"

async def main():
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    await client.connect()
    try:
        result = await client.send_code_request(PHONE, force_sms=True)
        phone_code_hash = result.phone_code_hash
        session_str = client.session.save()
        print(f"PHONE_CODE_HASH={phone_code_hash}")
        print(f"SESSION={session_str}")
        print(f"type={result.type}")
    except Exception as e:
        print(f"ERROR: {e}")
    await client.disconnect()

asyncio.run(main())
