import os
import asyncio
from balepy import Bot
from storage import load_db, download_by_message_id, DB_BACKUP_CHAT_ID

bot = Bot(token=os.getenv("BALE_BOT_TOKEN"))
BALE_ADMINS = os.getenv("BALE_ADMIN_IDS", "").split(",") # ادمین‌های بله

# برای ذخیره اینکه هر کاربر الان کجاست (جایگزین ConversationHandler)
user_states = {} 

def is_admin(user_id):
    return str(user_id) in BALE_ADMINS

async def send_contents(message, node_id):
    db = load_db()
    node_data = db.get(node_id, {})
    contents = node_data.get("contents", [])
    
    if not contents:
        await message.reply("این بخش خالی است.")
        return

    for item in contents:
        if item['type'] == 'text':
            await message.reply(item.get('text', ''))
        else:
            # 👈 نکته مهم: حتماً باید await شود چون تلگرام Async است
            file_path = f"/tmp/{item['telegram_message_id']}.tmp"
            
            # دانلود از تلگرام
            await download_by_message_id(DB_BACKUP_CHAT_ID, item['telegram_message_id'], file_path)
            
            # ارسال در بله
            await message.reply_document(document=file_path)
            # بعد از ارسال فایل را پاک کنید تا حافظه پر نشود
            if os.path.exists(file_path):
                os.remove(file_path)

@bot.on_command("start")
async def start(message):
    user_states[message.author.id] = "root" # ریست کردن وضعیت
    await message.reply("سلام! به ربات دانشگاه خوش آمدید.")
    # اینجا دکمه‌های اصلی را نشان بدهید (مانند main.py)

@bot.on_message()
async def navigation(message):
    user_id = message.author.id
    current_node = user_states.get(user_id, "root")
    text = message.text
    
    # 1. بررسی دسترسی ادمین
    if is_admin(user_id):
        # اینجا منطق ویرایش دکمه‌ها و... را اضافه کنید
        pass
    
    # 2. منطق حرکت در منوها
    db = load_db()
    if text in db: # اگر کاربر روی یک دکمه کلیک کرد
        user_states[user_id] = text
        await send_contents(message, text)
    elif text == "بازگشت":
        # منطق بازگشت به نود والد (نیاز به ذخیره parent در دیتابیس دارید)
        pass
