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
    
    for attempt in range(5):
        qr_login = await client.qr_login()
        
        qr = qrcode.QRCode(version=1, box_size=1, border=1)
        qr.add_data(qr_login.url)
        qr.make(fit=True)
        
        f = io.StringIO()
        qr.print_ascii(out=f, invert=True)
        print(f.getvalue())
        print(f"[Попытка {attempt+1}/5] Сканируй QR! 120 сек...")
        print("Telegram -> Настройки -> Устройства -> Подключить устройство")
        print()
        
        try:
            await qr_login.wait(timeout=120)
            session_string = client.session.save()
            print(f"\nSESSION_STRING={session_string}")
            await client.disconnect()
            return
        except Exception:
            print("Истёк, генерю новый QR...\n")
    
    print("Не удалось за 5 попыток")
    await client.disconnect()

asyncio.run(main())
