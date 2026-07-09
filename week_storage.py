import json
import os

WEEK_FILE = "/tmp/week.json"
ALARM_GROUP_ID = int(os.getenv("ALARM_GROUP_ID", "0") or "0")


def ensure_week_data_shape(data):
    if not isinstance(data, dict):
        data = {}

    if "groups" not in data or not isinstance(data["groups"], dict):
        data["groups"] = {}

    if "users" not in data or not isinstance(data["users"], dict):
        data["users"] = {}

    return data


def download_weekly_from_telegram():
    """
    این تابع باید از تابع عمومی دانلود فایل از تلگرام استفاده کند.
    چون helper اصلی‌ات در main.py یا جای دیگری است، بعداً آن را import می‌کنیم.
    """
    from main import download_latest_file_from_telegram

    if not ALARM_GROUP_ID:
        return False

    return download_latest_file_from_telegram(
        chat_id=ALARM_GROUP_ID,
        filename="week.json",
        save_path=WEEK_FILE,
    )


def upload_weekly_to_telegram():
    """
    این تابع باید از helper عمومی آپلود فایل به تلگرام استفاده کند.
    """
    from main import upload_file_to_telegram

    if not ALARM_GROUP_ID:
        return False

    if not os.path.exists(WEEK_FILE):
        return False

    return upload_file_to_telegram(
        chat_id=ALARM_GROUP_ID,
        file_path=WEEK_FILE,
        caption="week.json",
    )


def load_week_data():
    if not os.path.exists(WEEK_FILE) or os.path.getsize(WEEK_FILE) == 0:
        print("⚠️ Local week.json not found or empty. Restoring from Telegram...")
        restored = download_weekly_from_telegram()

        if not restored:
            print("⚠️ No week.json backup found in Telegram. Creating new file.")
            data = {"groups": {}, "users": {}}
            save_week_data(data)
            return data

    try:
        with open(WEEK_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"❌ Failed to load week.json: {e}")
        data = {"groups": {}, "users": {}}
        save_week_data(data)
        return data

    return ensure_week_data_shape(data)


def save_week_data(data):
    data = ensure_week_data_shape(data)

    try:
        with open(WEEK_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print("💾 week.json saved locally")
    except Exception as e:
        print(f"❌ Failed to save week.json locally: {e}")
        return False

    if ALARM_GROUP_ID:
        try:
            upload_weekly_to_telegram()
        except Exception as e:
            print(f"⚠️ Failed to upload week.json to Telegram: {e}")

    return True
