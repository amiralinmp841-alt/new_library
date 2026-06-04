import os
import json
import asyncio
import threading

from telethon import TelegramClient
from telethon.sessions import StringSession


# ============ TELEGRAM USER API BACKUP CONFIG ============

DB_FILE = "/tmp/database.json"
USERDATA_FILE = "/tmp/userdata.json"

TG_API_ID = int(os.getenv("TG_API_ID", "0"))
TG_API_HASH = os.getenv("TG_API_HASH")
TG_SESSION_STRING = os.getenv("TG_SESSION_STRING")

DB_BACKUP_CHAT_ID = int(os.getenv("DB_BACKUP_CHAT_ID", "0"))
USERDATA_BACKUP_CHAT_ID = int(os.getenv("USERDATA_BACKUP_CHAT_ID", "0"))


# ============ TELETHON SEPARATE EVENT LOOP ============

telethon_loop = asyncio.new_event_loop()
telethon_client = None
telethon_ready = threading.Event()


def start_telethon_loop():
    """
    Telethon client runs in a separate thread and separate event loop.
    This prevents conflicts with bot async loop.
    """
    global telethon_client

    asyncio.set_event_loop(telethon_loop)

    telethon_client = TelegramClient(
        StringSession(TG_SESSION_STRING),
        TG_API_ID,
        TG_API_HASH,
        loop=telethon_loop
    )

    async def init_client():
        await telethon_client.start()
        print("✅ Telethon User API client started")
        telethon_ready.set()

    telethon_loop.run_until_complete(init_client())
    telethon_loop.run_forever()


telethon_thread = threading.Thread(target=start_telethon_loop, daemon=True)
telethon_thread.start()


def run_telethon(coro):
    """
    Run async Telethon functions from normal sync code.
    """
    telethon_ready.wait(timeout=30)

    if not telethon_ready.is_set():
        print("❌ Telethon client not ready")
        return None

    future = asyncio.run_coroutine_threadsafe(coro, telethon_loop)
    return future.result(timeout=120)


# ============ TELEGRAM FILE BACKUP HELPERS ============

async def _upload_file_to_telegram(chat_id, file_path, caption=None):
    try:
        if not os.path.exists(file_path):
            print(f"❌ File not found for upload: {file_path}")
            return None

        msg = await telethon_client.send_file(
            entity=chat_id,
            file=file_path,
            caption=caption or f"backup: {os.path.basename(file_path)}"
        )

        print(f"⬆️ Uploaded to Telegram group: {file_path}")

        # مهم:
        # برای بکاپ دیتابیس فقط True بودن مهم است،
        # ولی برای فایل‌های محتوا message_id لازم داریم.
        return msg.id

    except Exception as e:
        print(f"❌ Failed to upload file to Telegram: {e}")
        return None


async def _download_latest_file_from_telegram(chat_id, filename, save_path):
    try:
        print(f"🔍 Searching latest {filename} in Telegram group {chat_id}...")

        async for message in telethon_client.iter_messages(chat_id, limit=200):
            if not message.file:
                continue

            original_name = message.file.name if message.file.name else None
            caption = message.message or ""

            if original_name == filename or filename in caption:
                await message.download_media(file=save_path)
                print(f"⬇️ Downloaded latest {filename} from Telegram group")
                return True

        print(f"⚠️ No file named {filename} found in Telegram group")
        return False

    except Exception as e:
        print(f"❌ Failed to download file from Telegram: {e}")
        return False


async def _download_by_message_id(chat_id, message_id, save_path):
    """
    دانلود فایل مشخص از گروه تلگرام با message_id.
    این برای ربات بله خیلی مهم است.
    """
    try:
        message = await telethon_client.get_messages(
            entity=chat_id,
            ids=int(message_id)
        )

        if not message:
            print(f"⚠️ Message not found: {message_id}")
            return False

        if not message.media:
            print(f"⚠️ Message has no media: {message_id}")
            return False

        await message.download_media(file=save_path)
        print(f"⬇️ Downloaded media by message_id: {message_id}")
        return True

    except Exception as e:
        print(f"❌ Failed to download by message_id: {e}")
        return False


def upload_file_to_telegram(chat_id, file_path, caption=None):
    """
    خروجی:
    - message_id اگر آپلود موفق باشد
    - None اگر شکست بخورد
    """
    return run_telethon(
        _upload_file_to_telegram(chat_id, file_path, caption)
    )


def download_latest_file_from_telegram(chat_id, filename, save_path):
    return run_telethon(
        _download_latest_file_from_telegram(chat_id, filename, save_path)
    )


def download_by_message_id(chat_id, message_id, save_path):
    return run_telethon(
        _download_by_message_id(chat_id, message_id, save_path)
    )


# ============ DATABASE BACKUP WITH TELEGRAM ============

def download_db_from_telegram():
    return download_latest_file_from_telegram(
        chat_id=DB_BACKUP_CHAT_ID,
        filename="database.json",
        save_path=DB_FILE
    )


def upload_db_to_telegram():
    message_id = upload_file_to_telegram(
        chat_id=DB_BACKUP_CHAT_ID,
        file_path=DB_FILE,
        caption="database.json"
    )

    return message_id is not None


def load_db():
    if not os.path.exists(DB_FILE):
        print("⚠️ Local DB not found. Restoring from Telegram group...")

        if not download_db_from_telegram():
            print("⚠️ Telegram DB backup not found, creating new DB")

            initial_db = {
                "root": {
                    "name": "خانه",
                    "parent": None,
                    "children": [],
                    "contents": []
                }
            }

            save_db(initial_db)
            return initial_db

    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    except Exception as e:
        print("❌ Failed to load local DB:", e)
        return {}


def save_db(data):
    try:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        print("💾 DB saved locally")

    except Exception as e:
        print("❌ Failed to save DB locally:", e)
        return False

    return upload_db_to_telegram()


# ============ USERDATA BACKUP WITH TELEGRAM ============

def download_userdata_from_telegram():
    return download_latest_file_from_telegram(
        chat_id=USERDATA_BACKUP_CHAT_ID,
        filename="userdata.json",
        save_path=USERDATA_FILE
    )


def upload_userdata_to_telegram():
    message_id = upload_file_to_telegram(
        chat_id=USERDATA_BACKUP_CHAT_ID,
        file_path=USERDATA_FILE,
        caption="userdata.json"
    )

    return message_id is not None


def load_userdata():
    if not os.path.exists(USERDATA_FILE):
        print("⚠️ Local userdata not found. Restoring from Telegram group...")

        if not download_userdata_from_telegram():
            print("⚠️ No userdata backup in Telegram. Creating new userdata.")

            save_userdata({})
            return {}

    try:
        with open(USERDATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    except Exception as e:
        print("❌ Failed to load userdata:", e)
        return {}


def save_userdata(data):
    try:
        with open(USERDATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        print("💾 Userdata saved locally")

    except Exception as e:
        print("❌ Failed to save userdata locally:", e)
        return False

    return upload_userdata_to_telegram()


BACKUP_FILE = "/tmp/backup_database.zip"
