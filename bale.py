import os
from balepy import Bot, Keyboard, ReplyMarkup
from storage import load_db, download_by_message_id, DB_BACKUP_CHAT_ID

bot = Bot(token=os.getenv("BALE_BOT_TOKEN"))
BALE_ADMINS = [int(x) for x in os.getenv("BALE_ADMIN_IDS", "").split(",") if x]

# ذخیره وضعیت کاربران
user_states = {}

def get_bale_keyboard(node_id):
    db = load_db()
    node = db.get(node_id)
    if not node: return None

    buttons = []
    # دکمه‌های فرزند (پوشه‌ها)
    for child_id in node.get("children", []):
        child_node = db.get(child_id)
        if child_node:
            buttons.append([child_node["name"]])
    
    # دکمه‌های بازگشت
    nav_row = []
    if node.get("parent"):
        nav_row.append("🔙 بازگشت")
    nav_row.append("🏠 صفحه اصلی")
    buttons.append(nav_row)
    
    return ReplyMarkup(buttons)

async def send_contents(message, node_id):
    db = load_db()
    contents = db.get(node_id, {}).get("contents", [])
    
    if not contents:
        await message.reply("این بخش خالی است.")
        return

    for item in contents:
        try:
            # دانلود از تلگرام (بکاپ)
            # فرض بر این است که download_by_message_id در storage.py خروجی درست می‌دهد
            file_path = f"/tmp/{item.get('telegram_message_id', 'temp_file')}"
            await download_by_message_id(DB_BACKUP_CHAT_ID, item.get('telegram_message_id'), file_path)

            msg_type = item.get('type')
            caption = item.get('caption', '')

            if msg_type == 'text':
                await message.reply(item.get('text', ''))
            elif msg_type == 'photo':
                await message.reply_photo(photo=file_path, caption=caption)
            elif msg_type == 'video':
                await message.reply_video(video=file_path, caption=caption)
            elif msg_type == 'document':
                await message.reply_document(document=file_path, caption=caption)
            elif msg_type == 'audio':
                await message.reply_audio(audio=file_path, caption=caption)
            elif msg_type == 'voice':
                await message.reply_voice(voice=file_path, caption=caption)
            
            # پاک کردن فایل موقت
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception as e:
            print(f"Error sending file: {e}")

@bot.on_command("start")
async def start(message):
    user_states[message.author.id] = "root"
    await message.reply("سلام! به ربات خوش آمدید.", reply_markup=get_bale_keyboard("root"))

@bot.on_message()
async def navigation(message):
    user_id = message.author.id
    text = message.text
    db = load_db()
    current_node = user_states.get(user_id, "root")
    
    # 1. منطق بازگشت
    if text == "🏠 صفحه اصلی":
        user_states[user_id] = "root"
        await message.reply("به صفحه اصلی برگشتید.", reply_markup=get_bale_keyboard("root"))
        return

    if text == "🔙 بازگشت":
        parent = db.get(current_node, {}).get("parent")
        if parent:
            user_states[user_id] = parent
            await message.reply("بازگشت...", reply_markup=get_bale_keyboard(parent))
            await send_contents(message, parent)
        return

    # 2. بررسی کلیک روی دکمه‌های فرزند
    node = db.get(current_node, {})
    children = node.get("children", [])
    
    for child_id in children:
        child_node = db.get(child_id)
        if child_node and child_node["name"] == text:
            user_states[user_id] = child_id
            await message.reply(f"📂 {text}", reply_markup=get_bale_keyboard(child_id))
            await send_contents(message, child_id)
            return

    await message.reply("دستور نامعتبر.")

bot.run()
