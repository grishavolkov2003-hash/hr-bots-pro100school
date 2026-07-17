import asyncio
import qrcode
import io
from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID = 36669184
API_HASH = "3976ae2af478e360569ecfc0cb728bfe"

async def main():
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    await client.connect()
    
    qr_login = await client.qr_login()
    
    qr = qrcode.QRCode(version=1, box_size=1, border=1)
    qr.add_data(qr_login.url)
    qr.make(fit=True)
    
    f = io.StringIO()
    qr.print_ascii(out=f, invert=True)
    print(f.getvalue())
    print("Отсканируй QR в Telegram:")
    print("Настройки → Устройства → Подключить устройство")
    print("Жду подтверждения...")
    
    try:
        await qr_login.wait(timeout=60)
        session_string = client.session.save()
        print(f"\n=== SESSION STRING ===")
        print(session_string)
        print(f"=== END ===")
    except Exception as e:
        print(f"Ошибка: {e}")
    
    await client.disconnect()

asyncio.run(main())
