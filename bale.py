# bale.py
import os
from balepy import Bot # یا هر کتابخانه بله که استفاده می‌کنید
from storage import load_db, download_by_message_id, DB_BACKUP_CHAT_ID

bot = Bot(token=os.getenv("BALE_BOT_TOKEN"))

# نمایش محتوای نودها (مشابه تلگرام)
async def send_contents(message, node_id):
    db = load_db()
    contents = db[node_id].get("contents", [])
    for item in contents:
        if item['type'] == 'text':
            await message.reply(item['text'])
        else:
            # دانلود از تلگرام و ارسال در بله
            file_path = f"/tmp/{item['file_id']}"
            download_by_message_id(DB_BACKUP_CHAT_ID, item['telegram_message_id'], file_path)
            await message.reply_document(document=file_path)

@bot.on_command("start")
async def start(message):
    await message.reply("سلام! ربات دانشگاه بله فعال شد.")

@bot.on_message()
async def navigation(message):
    db = load_db()
    text = message.text
    # اینجا منطق حرکت در دکمه‌ها (مشابه main.py) را پیاده کنید
    # برای فایل‌ها از download_by_message_id استفاده کنید
