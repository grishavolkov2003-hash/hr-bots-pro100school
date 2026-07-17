import asyncio
import qrcode
from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID = 36669184
API_HASH = "3976ae2af478e360569ecfc0cb728bfe"

async def main():
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    await client.connect()
    
    qr_login = await client.qr_login()
    
    img = qrcode.make(qr_login.url)
    img.save("/opt/brosky-bot/qr_code.png")
    print("QR saved to /opt/brosky-bot/qr_code.png")
    print("URL: " + qr_login.url)
    
    print("Жду сканирования... 120 сек")
    try:
        await qr_login.wait(timeout=120)
        session_string = client.session.save()
        print(f"SESSION_STRING={session_string}")
    except Exception as e:
        print(f"Timeout: {e}")
    
    await client.disconnect()

asyncio.run(main())
