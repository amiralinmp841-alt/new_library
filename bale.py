import os
import json
import uuid
import copy
import zipfile
import logging
import io as iolib
import asyncio
import requests
from datetime import datetime

from storage import (
    DB_FILE,
    load_db,
    save_db,
    load_userdata,
    save_userdata,
)

# ================= CONFIG =================

BALE_BOT_TOKEN = os.getenv("BALE_BOT_TOKEN")
BALE_BOT_USERNAME = os.getenv("BALE_BOT_USERNAME", "")
ADMIN_ACCESSIBILITY_NAME = os.getenv("ADMIN_ACCESSIBILITY_NAME")

BALE_ADMIN_IDS = []
if os.getenv("BALE_ADMIN_IDS"):
    BALE_ADMIN_IDS = list(map(int, os.getenv("BALE_ADMIN_IDS").split(",")))

BALE_API_URL = f"https://tapi.bale.ai/bot{BALE_BOT_TOKEN}"

MAX_HISTORY = 20

# session مخصوص کاربران بله
# ساختار:
# {
#   user_id: {
#       "current_node": "root",
#       "state": "CHOOSING",
#       ...
#   }
# }
BALE_SESSIONS = {}


# ================= STATES =================

CHOOSING = "CHOOSING"
WAITING_BUTTON_NAME = "WAITING_BUTTON_NAME"
WAITING_CONTENT = "WAITING_CONTENT"
WAITING_RENAME_BUTTON = "WAITING_RENAME_BUTTON"
WAITING_ADMIN_PASSWORD_EDIT = "WAITING_ADMIN_PASSWORD_EDIT"
WAITING_ADD_ADMIN = "WAITING_ADD_ADMIN"
WAITING_REMOVE_ADMIN = "WAITING_REMOVE_ADMIN"


# ================= BALE API HELPERS =================

async def bale_api(method, payload=None, files=None):
    """
    ارسال درخواست به API بله.
    requests سینک است، برای اینکه webhook قفل نشود داخل to_thread اجرا می‌شود.
    """
    if payload is None:
        payload = {}

    url = f"{BALE_API_URL}/{method}"

    def _send():
        try:
            if files:
                return requests.post(url, data=payload, files=files, timeout=30)
            return requests.post(url, json=payload, timeout=30)
        except Exception as e:
            logging.exception(f"Bale API error: {e}")
            return None

    return await asyncio.to_thread(_send)


async def send_message(chat_id, text, keyboard=None, parse_mode=None):
    payload = {
        "chat_id": chat_id,
        "text": text or "",
    }

    if keyboard:
        payload["reply_markup"] = keyboard

    if parse_mode:
        payload["parse_mode"] = parse_mode

    return await bale_api("sendMessage", payload)


async def send_document(chat_id, file_bytes, filename, caption=None):
    """
    ارسال فایل به بله.
    اگر API بله در پروژه‌ات اسم پارامتر متفاوتی داشت، فقط همین تابع باید اصلاح شود.
    """
    payload = {
        "chat_id": str(chat_id),
    }

    if caption:
        payload["caption"] = caption

    files = {
        "document": (filename, file_bytes)
    }

    return await bale_api("sendDocument", payload=payload, files=files)


# ================= SESSION HELPERS =================

def get_session(user_id):
    user_id = str(user_id)
    if user_id not in BALE_SESSIONS:
        BALE_SESSIONS[user_id] = {
            "current_node": "root",
            "state": CHOOSING,
            "admin_history": [],
            "admin_future": [],
        }
    return BALE_SESSIONS[user_id]


def clear_session(user_id):
    user_id = str(user_id)
    BALE_SESSIONS[user_id] = {
        "current_node": "root",
        "state": CHOOSING,
        "admin_history": [],
        "admin_future": [],
    }
    return BALE_SESSIONS[user_id]


def is_admin(user_id):
    userdata = load_userdata()
    sub_admins = userdata.get("sub_admins", [])
    sub_admins = [int(x) for x in sub_admins]

    return int(user_id) in BALE_ADMIN_IDS or int(user_id) in sub_admins


def push_admin_history(session, db):
    history = session.setdefault("admin_history", [])
    future = session.setdefault("admin_future", [])

    history.append(copy.deepcopy(db))

    if len(history) > MAX_HISTORY:
        history.pop(0)

    future.clear()


def delete_node_recursive(db, node_id):
    if node_id not in db:
        return

    children = db[node_id].get("children", [])
    for child_id in children:
        delete_node_recursive(db, child_id)

    del db[node_id]


def is_valid_node_id(text, db):
    return text in db and isinstance(db[text], dict)


def ensure_numeric_id(text: str):
    text = str(text).strip()
    if not text.isdigit():
        return None
    return int(text)


# ================= KEYBOARDS =================

def make_keyboard(rows):
    """
    فرمت کیبورد بله تقریباً مشابه تلگرام است.
    اگر در رباتت کیبوردهای بله شکل دیگری می‌خواهند، فقط این تابع را تغییر بده.
    """
    keyboard = []

    for row in rows:
        new_row = []
        for btn in row:
            if isinstance(btn, dict):
                new_row.append(btn)
            else:
                new_row.append({"text": str(btn)})
        keyboard.append(new_row)

    return {
        "keyboard": keyboard,
        "resize_keyboard": True
    }


def get_bale_keyboard(node_id, admin=False):
    db = load_db()
    node = db.get(node_id)

    if not node:
        return make_keyboard([["/start"]])

    rows = []

    children_ids = node.get("children", [])
    row = []

    for child_id in children_ids:
        child_node = db.get(child_id)
        if child_node:
            row.append(child_node.get("name", "بدون نام"))
            if len(row) == 2:
                rows.append(row)
                row = []

    if row:
        rows.append(row)

    if admin:
        rows.append(["➕ افزودن دکمه", "➕ افزودن محتوا"])
        rows.append(["🗑 حذف دکمه", "🧹 حذف محتوای صفحه"])
        rows.append(["✏️ ویرایش نام دکمه", "🔑 دریافت هش و لینک دکمه", "🔀 جابه‌جایی چیدمان"])
        rows.append(["📥 دریافت بکاپ", "📤 وارد کردن بکاپ"])
        rows.append(["↩️", "↪️"])

    nav_row = []
    if node.get("parent"):
        nav_row.append("🔙 بازگشت")

    nav_row.append("🏠 صفحه اصلی")
    rows.append(nav_row)

    return make_keyboard(rows)


def admin_access_keyboard():
    return make_keyboard([
        ["👑 مدیریت ادمین‌ها"],
        ["📤 دریافت userdata"],
        ["📥 وارد کردن userdata"],
        ["🔙 بازگشت"]
    ])


def admin_mgmt_keyboard():
    return make_keyboard([
        ["🔑 تنظیم رمز ادمینی"],
        ["➕ افزودن ادمین", "➖ حذف ادمین"],
        ["📋 لیست ادمین‌ها"],
        ["🔙 بازگشت"]
    ])


def cancel_keyboard():
    return make_keyboard([["❌ لغو"]])


# ================= CONTENT SENDER =================

async def send_node_contents(chat_id, node_id):
    db = load_db()

    if node_id not in db:
        return

    contents = db[node_id].get("contents", [])

    if not contents:
        return

    for item in contents:
        try:
            msg_type = item.get("type")

            if msg_type == "text":
                await send_message(
                    chat_id,
                    item.get("text", ""),
                    parse_mode="HTML"
                )
            else:
                # مهم:
                # file_id ذخیره‌شده در دیتابیس برای تلگرام است، نه بله.
                # پس فعلاً فقط کپشن/هشدار می‌فرستیم.
                caption = item.get("caption", "")
                await send_message(
                    chat_id,
                    "📎 این محتوا از نوع فایل است، اما فایل‌های ذخیره‌شده‌ی تلگرام "
                    "مستقیماً در بله قابل ارسال نیستند.\n\n"
                    f"نوع فایل: {msg_type}\n"
                    f"{caption or ''}"
                )

        except Exception as e:
            logging.exception(f"Error sending Bale content: {e}")


# ================= START =================

async def bale_start(chat_id, user_id, args=None):
    session = clear_session(user_id)
    admin = is_admin(user_id)
    db = load_db()

    if args:
        target_id = args[0]
        if target_id in db:
            session["current_node"] = target_id
            session["state"] = CHOOSING

            await send_message(
                chat_id,
                f"📂 {db[target_id].get('name', 'بدون نام')}",
                keyboard=get_bale_keyboard(target_id, admin)
            )

            await send_node_contents(chat_id, target_id)
            return

    session["current_node"] = "root"
    session["state"] = CHOOSING

    await send_message(
        chat_id,
        "🕊 به ربات دانشگاه خوش آمدید. (نسخه بله)v_1_1_0",
        keyboard=get_bale_keyboard("root", admin)
    )


# ================= ADMIN LIST =================

async def list_admins_bale(chat_id):
    userdata = load_userdata()
    sub_admins = userdata.get("sub_admins", [])
    buttons_count = userdata.get("sub_admins_buttons", {})

    main_admins = [int(x) for x in BALE_ADMIN_IDS]
    sub_admins = [int(x) for x in sub_admins]

    msg = "👑 ادمین‌های اصلی:\n\n"

    sorted_main_admins = sorted(
        main_admins,
        key=lambda x: buttons_count.get(str(x), 0),
        reverse=True
    )

    for aid in sorted_main_admins:
        count = buttons_count.get(str(aid), 0)
        msg += f"🆔 {aid} | تعداد دکمه: {count}\n"

    msg += "\n👤 ادمین‌های فرعی:\n\n"

    sorted_sub_admins = sorted(
        sub_admins,
        key=lambda x: buttons_count.get(str(x), 0),
        reverse=True
    )

    for aid in sorted_sub_admins:
        count = buttons_count.get(str(aid), 0)
        msg += f"🆔 {aid} | تعداد دکمه: {count}\n"

    await send_message(
        chat_id,
        msg,
        keyboard=admin_mgmt_keyboard()
    )


# ================= REORDER =================

async def show_reorder_keyboard(chat_id, session, db):
    remaining = session.get("reorder_remaining", [])

    rows = []
    for cid in remaining:
        if cid in db:
            rows.append([f"🔀 {db[cid].get('name', 'بدون نام')}"])

    rows.append(["❌ لغو"])

    await send_message(
        chat_id,
        f"ترتیب جدید را انتخاب کنید ({len(remaining)} دکمه باقی مانده):",
        keyboard=make_keyboard(rows)
    )


# ================= STATE HANDLERS =================

async def handle_waiting_button_name(chat_id, user_id, text, session):
    admin = is_admin(user_id)

    if text == "❌ لغو":
        current = session.get("current_node", "root")
        session["state"] = CHOOSING
        await send_message(chat_id, "لغو شد.", keyboard=get_bale_keyboard(current, admin))
        return

    db = load_db()
    current_node_id = session.get("current_node", "root")

    if current_node_id not in db:
        current_node_id = "root"
        session["current_node"] = "root"

    # اگر متن، هش معتبر بود، کل نود را کپی کن
    if is_valid_node_id(text, db):
        source_id = text

        def clone_node(old_id, new_parent):
            new_id = str(uuid.uuid4())
            old = db[old_id]

            db[new_id] = {
                "name": old.get("name", "بدون نام"),
                "parent": new_parent,
                "children": [],
                "contents": old.get("contents", []).copy()
            }

            for child in old.get("children", []):
                child_new_id = clone_node(child, new_id)
                db[new_id]["children"].append(child_new_id)

            return new_id

        push_admin_history(session, db)
        new_root_id = clone_node(source_id, current_node_id)
        db[current_node_id].setdefault("children", []).append(new_root_id)
        save_db(db)

        session["state"] = CHOOSING

        await send_message(
            chat_id,
            "✅ دکمه با تمام زیرمجموعه‌ها کپی شد.",
            keyboard=get_bale_keyboard(current_node_id, True)
        )
        return

    # ساخت دکمه جدید
    new_id = str(uuid.uuid4())

    db[new_id] = {
        "name": text,
        "parent": current_node_id,
        "children": [],
        "contents": []
    }

    push_admin_history(session, db)
    db[current_node_id].setdefault("children", []).append(new_id)
    save_db(db)

    # افزایش شمارنده دکمه‌های ادمین
    userdata = load_userdata()
    userdata.setdefault("sub_admins_buttons", {})
    current_count = userdata["sub_admins_buttons"].get(str(user_id), 0)
    userdata["sub_admins_buttons"][str(user_id)] = current_count + 1
    save_userdata(userdata)

    session["state"] = CHOOSING

    await send_message(
        chat_id,
        f"✅ دکمه '{text}' ساخته شد.",
        keyboard=get_bale_keyboard(current_node_id, True)
    )


async def handle_waiting_content(chat_id, user_id, text, session, message):
    admin = is_admin(user_id)

    if text == "❌ لغو":
        current = session.get("current_node", "root")
        session.pop("temp_content", None)
        session["state"] = CHOOSING

        await send_message(
            chat_id,
            "عملیات لغو شد.",
            keyboard=get_bale_keyboard(current, admin)
        )
        return

    if text == "✅ ثبت نهایی":
        temp_content = session.get("temp_content", [])
        current_node_id = session.get("current_node", "root")

        if temp_content:
            db = load_db()

            if current_node_id not in db:
                current_node_id = "root"
                session["current_node"] = "root"

            push_admin_history(session, db)

            db[current_node_id].setdefault("contents", [])
            db[current_node_id]["contents"].extend(temp_content)
            save_db(db)

            await send_message(
                chat_id,
                f"✅ {len(temp_content)} مورد ذخیره شد.",
                keyboard=get_bale_keyboard(current_node_id, True)
            )
        else:
            await send_message(
                chat_id,
                "موردی برای ذخیره وجود نداشت.",
                keyboard=get_bale_keyboard(current_node_id, True)
            )

        session.pop("temp_content", None)
        session["state"] = CHOOSING
        return

    # در فاز اول، محتواهای متنی بله را ذخیره می‌کنیم
    # فایل‌های بله باید جداگانه هندل شوند چون ساختار file_id متفاوت است.
    if text and not text.startswith("/"):
        session.setdefault("temp_content", []).append({
            "type": "text",
            "text": text,
            "format": "HTML"
        })

        await send_message(chat_id, "👍 دریافت شد. ادامه بدهید یا ✅ ثبت نهایی را بزنید.")
        return

    await send_message(chat_id, "فعلاً فقط متن در بله ذخیره می‌شود.")


async def handle_waiting_rename_button(chat_id, user_id, text, session):
    if text == "❌ لغو":
        current = session.get("current_node", "root")
        session.pop("rename_target", None)
        session["state"] = CHOOSING

        await send_message(
            chat_id,
            "لغو شد.",
            keyboard=get_bale_keyboard(current, True)
        )
        return

    target_id = session.get("rename_target")
    db = load_db()

    if target_id in db:
        push_admin_history(session, db)
        db[target_id]["name"] = text
        save_db(db)

    current = session.get("current_node", "root")
    session.pop("rename_target", None)
    session["state"] = CHOOSING

    await send_message(
        chat_id,
        "✅ نام دکمه ویرایش شد.",
        keyboard=get_bale_keyboard(current, True)
    )


async def handle_waiting_admin_password(chat_id, user_id, text, session):
    if text in ["🔙 بازگشت", "❌ لغو"]:
        session["state"] = CHOOSING
        await send_message(
            chat_id,
            "لغو شد.",
            keyboard=admin_access_keyboard()
        )
        return

    if len(text.strip()) < 4:
        await send_message(chat_id, "❌ رمز خیلی کوتاه است.")
        return

    userdata = load_userdata()
    userdata["admin_password"] = text.strip()
    save_userdata(userdata)

    session["state"] = CHOOSING

    await send_message(
        chat_id,
        "✅ رمز ادمینی با موفقیت تغییر کرد.",
        keyboard=admin_access_keyboard()
    )


async def handle_waiting_add_admin(chat_id, user_id, text, session):
    if text == "❌ لغو":
        session["state"] = CHOOSING
        await send_message(chat_id, "❌ عملیات لغو شد.", keyboard=admin_mgmt_keyboard())
        return

    new_admin = ensure_numeric_id(text)

    if new_admin is None:
        await send_message(chat_id, "❌ فقط آیدی عددی معتبر است. دوباره وارد کنید:")
        return

    userdata = load_userdata()
    sub_admins = userdata.get("sub_admins", [])
    sub_admins = [int(x) for x in sub_admins]

    if new_admin in BALE_ADMIN_IDS:
        await send_message(chat_id, "❌ این فرد قبلاً ادمین اصلی است.")
        return

    if new_admin not in sub_admins:
        sub_admins.append(new_admin)
        userdata["sub_admins"] = sub_admins

        userdata.setdefault("sub_admins_buttons", {})
        userdata["sub_admins_buttons"][str(new_admin)] = 0

        save_userdata(userdata)

        session["state"] = CHOOSING

        await send_message(
            chat_id,
            f"✅ ادمین {new_admin} با موفقیت اضافه شد.",
            keyboard=admin_mgmt_keyboard()
        )

        # اطلاع به خود ادمین جدید در بله
        try:
            await send_message(
                new_admin,
                "🎉 شما به عنوان ادمین فرعی ربات منصوب شدید."
            )
        except Exception as e:
            logging.warning(f"Failed to notify new Bale admin: {e}")

        return

    await send_message(chat_id, "❌ این فرد قبلاً ادمین فرعی است.")


async def handle_waiting_remove_admin(chat_id, user_id, text, session):
    if text == "❌ لغو":
        session["state"] = CHOOSING
        await send_message(chat_id, "❌ عملیات لغو شد.", keyboard=admin_mgmt_keyboard())
        return

    admin_id = ensure_numeric_id(text)

    if admin_id is None:
        await send_message(chat_id, "❌ فقط آیدی عددی معتبر است. دوباره ارسال کنید:")
        return

    userdata = load_userdata()
    sub_admins = userdata.get("sub_admins", [])
    sub_admins = [int(x) for x in sub_admins]

    if admin_id in BALE_ADMIN_IDS:
        await send_message(chat_id, "❌ نمی‌توان ادمین اصلی را حذف کرد.")
        return

    if admin_id in sub_admins:
        sub_admins.remove(admin_id)
        userdata["sub_admins"] = sub_admins

        if "sub_admins_buttons" in userdata:
            userdata["sub_admins_buttons"].pop(str(admin_id), None)

        save_userdata(userdata)

        session["state"] = CHOOSING

        await send_message(
            chat_id,
            f"✅ ادمین {admin_id} حذف شد.",
            keyboard=admin_mgmt_keyboard()
        )

        try:
            await send_message(
                admin_id,
                "⚠️ شما از لیست ادمین‌های ربات حذف شدید."
            )
        except Exception as e:
            logging.warning(f"Failed to notify removed Bale admin: {e}")

        return

    await send_message(chat_id, "❌ این فرد ادمین نیست.")


# ================= MAIN NAVIGATION =================

async def handle_bale_navigation(chat_id, user_id, text, message):
    session = get_session(user_id)
    state = session.get("state", CHOOSING)

    # اول stateهای موقت
    if state == WAITING_BUTTON_NAME:
        return await handle_waiting_button_name(chat_id, user_id, text, session)

    if state == WAITING_CONTENT:
        return await handle_waiting_content(chat_id, user_id, text, session, message)

    if state == WAITING_RENAME_BUTTON:
        return await handle_waiting_rename_button(chat_id, user_id, text, session)

    if state == WAITING_ADMIN_PASSWORD_EDIT:
        return await handle_waiting_admin_password(chat_id, user_id, text, session)

    if state == WAITING_ADD_ADMIN:
        return await handle_waiting_add_admin(chat_id, user_id, text, session)

    if state == WAITING_REMOVE_ADMIN:
        return await handle_waiting_remove_admin(chat_id, user_id, text, session)

    userdata = load_userdata()
    sub_admins = userdata.get("sub_admins", [])
    sub_admins = [int(x) for x in sub_admins]

    admin = is_admin(user_id)

    # ورود با رمز ادمینی
    admin_pass = userdata.get("admin_password")
    if admin_pass and text == admin_pass:
        if int(user_id) not in BALE_ADMIN_IDS and int(user_id) not in sub_admins:
            userdata.setdefault("sub_admins", []).append(int(user_id))
            save_userdata(userdata)

            await send_message(
                chat_id,
                "✅ رمز تایید شد.\nشما اکنون ادمین هستید 😎",
                keyboard=get_bale_keyboard(session.get("current_node", "root"), True)
            )

            for aid in BALE_ADMIN_IDS:
                if int(aid) != int(user_id):
                    await send_message(
                        aid,
                        f"🚨 ادمین جدید در بله اضافه شد!\n\n"
                        f"🆔 {user_id}"
                    )

        return

    current_node_id = session.get("current_node", "root")
    db = load_db()

    if current_node_id not in db:
        current_node_id = "root"
        session["current_node"] = "root"

    # لغو عمومی
    if text == "❌ لغو":
        session["state"] = CHOOSING
        session.pop("reorder_mode", None)
        session.pop("reorder_remaining", None)
        session.pop("reorder_result", None)

        await send_message(
            chat_id,
            "لغو شد.",
            keyboard=get_bale_keyboard(current_node_id, admin)
        )
        return

    # برگشت در پنل ادمین
    if text == "🔙 بازگشت" and session.get("admin_panel"):
        panel = session.get("admin_panel")

        if panel == "admin_mgmt":
            session["admin_panel"] = "access"
            await send_message(
                chat_id,
                "🔐 پنل مدیریت:",
                keyboard=admin_access_keyboard()
            )
            return

        if panel == "access":
            session.pop("admin_panel", None)
            session["current_node"] = "root"
            await send_message(
                chat_id,
                "بازگشت به صفحه اصلی",
                keyboard=get_bale_keyboard("root", admin)
            )
            return

    # صفحه اصلی
    if text == "🏠 صفحه اصلی":
        session["current_node"] = "root"
        await send_message(
            chat_id,
            "به صفحه اصلی بازگشتید.",
            keyboard=get_bale_keyboard("root", admin)
        )
        return

    # بازگشت
    if text == "🔙 بازگشت":
        parent = db[current_node_id].get("parent")
        if parent:
            session["current_node"] = parent
            await send_message(
                chat_id,
                "بازگشت به عقب.",
                keyboard=get_bale_keyboard(parent, admin)
            )
        else:
            session["current_node"] = "root"
            await send_message(
                chat_id,
                "شما در صفحه اصلی هستید.",
                keyboard=get_bale_keyboard("root", admin)
            )
        return

    # پنل مخفی مدیریت
    if admin and ADMIN_ACCESSIBILITY_NAME and text == ADMIN_ACCESSIBILITY_NAME:
        session["admin_panel"] = "access"
        await send_message(
            chat_id,
            "🔐 پنل مدیریت:",
            keyboard=admin_access_keyboard()
        )
        return

    # مدیریت ادمین‌ها
    if admin and text == "👑 مدیریت ادمین‌ها":
        session["admin_panel"] = "admin_mgmt"
        await send_message(
            chat_id,
            "👑 مدیریت ادمین‌ها:",
            keyboard=admin_mgmt_keyboard()
        )
        return

    if admin and text == "🔑 تنظیم رمز ادمینی":
        admin_pass = userdata.get("admin_password", "تعریف نشده")
        await send_message(
            chat_id,
            f"🔐 رمز ادمینی فعلی:\n\n{admin_pass}",
            keyboard=make_keyboard([
                ["✏️ ویرایش رمز"],
                ["🔙 بازگشت"]
            ])
        )
        return

    if admin and text == "✏️ ویرایش رمز":
        session["state"] = WAITING_ADMIN_PASSWORD_EDIT
        await send_message(
            chat_id,
            "✏️ رمز جدید ادمینی را ارسال کنید:",
            keyboard=cancel_keyboard()
        )
        return

    if admin and text == "➕ افزودن ادمین":
        session["state"] = WAITING_ADD_ADMIN
        await send_message(
            chat_id,
            "📝 آیدی عددی فرد مورد نظر را ارسال کنید:",
            keyboard=cancel_keyboard()
        )
        return

    if admin and text == "➖ حذف ادمین":
        session["state"] = WAITING_REMOVE_ADMIN
        await send_message(
            chat_id,
            "📝 آیدی عددی ادمینی که می‌خواهید حذف کنید را ارسال کنید:",
            keyboard=cancel_keyboard()
        )
        return

    if admin and text == "📋 لیست ادمین‌ها":
        await list_admins_bale(chat_id)
        return

    # دریافت userdata
    if admin and text == "📤 دریافت userdata":
        userdata = load_userdata()
        json_bytes = json.dumps(userdata, ensure_ascii=False, indent=2).encode("utf-8")

        zip_buffer = iolib.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
            zipf.writestr("userdata.json", json_bytes)

        zip_buffer.seek(0)

        await send_document(
            chat_id,
            zip_buffer.getvalue(),
            ".userdata.zip",
            caption="📦 بکاپ userdata"
        )
        return

    if admin and text == "📥 وارد کردن userdata":
        await send_message(
            chat_id,
            "⚠️ ورود userdata از داخل بله در این نسخه هنوز فعال نشده است.\n"
            "فعلاً از تلگرام برای وارد کردن userdata استفاده کنید.",
            keyboard=admin_access_keyboard()
        )
        return

    # ================= ADMIN NODE ACTIONS =================

    if admin and text == "➕ افزودن دکمه":
        session["state"] = WAITING_BUTTON_NAME
        await send_message(
            chat_id,
            "نام دکمه جدید را بنویسید:",
            keyboard=cancel_keyboard()
        )
        return

    if admin and text == "➕ افزودن محتوا":
        session["state"] = WAITING_CONTENT
        session["temp_content"] = []

        await send_message(
            chat_id,
            "متن‌هایی که می‌خواهید ذخیره شوند را ارسال کنید.\n"
            "در پایان دکمه «✅ ثبت نهایی» را بزنید.\n\n"
            "فعلاً ذخیره فایل در بله جداگانه باید فعال شود.",
            keyboard=make_keyboard([["✅ ثبت نهایی", "❌ لغو"]])
        )
        return

    if admin and text == "🗑 حذف دکمه":
        children = db[current_node_id].get("children", [])

        if not children:
            await send_message(chat_id, "دکمه‌ای برای حذف وجود ندارد.")
            return

        rows = []
        for child_id in children:
            if child_id in db:
                rows.append([f"❌ حذف {db[child_id].get('name', 'بدون نام')}"])

        rows.append(["❌ لغو"])

        await send_message(
            chat_id,
            "روی دکمه‌ای که می‌خواهید حذف شود بزنید:",
            keyboard=make_keyboard(rows)
        )
        return

    if admin and text.startswith("❌ حذف "):
        target_name = text.replace("❌ حذف ", "")
        children = db[current_node_id].get("children", [])

        target_id = None
        for child_id in children:
            if child_id in db and db[child_id].get("name") == target_name:
                target_id = child_id
                break

        if target_id:
            push_admin_history(session, db)
            db[current_node_id]["children"].remove(target_id)
            delete_node_recursive(db, target_id)
            save_db(db)

            await send_message(
                chat_id,
                f"دکمه '{target_name}' و تمام زیرمجموعه‌هایش حذف شد.",
                keyboard=get_bale_keyboard(current_node_id, True)
            )
        else:
            await send_message(
                chat_id,
                "دکمه یافت نشد.",
                keyboard=get_bale_keyboard(current_node_id, True)
            )

        return

    if admin and text == "🧹 حذف محتوای صفحه":
        push_admin_history(session, db)
        db[current_node_id]["contents"] = []
        save_db(db)

        await send_message(
            chat_id,
            "🧹 محتوای این صفحه حذف شد.",
            keyboard=get_bale_keyboard(current_node_id, True)
        )
        return

    if admin and text == "✏️ ویرایش نام دکمه":
        children = db[current_node_id].get("children", [])

        if not children:
            await send_message(chat_id, "دکمه‌ای برای ویرایش وجود ندارد.")
            return

        rows = []
        for cid in children:
            if cid in db:
                rows.append([f"✏️ {db[cid].get('name', 'بدون نام')}"])

        rows.append(["❌ لغو"])

        await send_message(
            chat_id,
            "دکمه‌ای که می‌خواهید ویرایش شود را انتخاب کنید:",
            keyboard=make_keyboard(rows)
        )
        return

    if admin and text.startswith("✏️ "):
        target_name = text.replace("✏️ ", "")

        for cid in db[current_node_id].get("children", []):
            if cid in db and db[cid].get("name") == target_name:
                session["rename_target"] = cid
                session["state"] = WAITING_RENAME_BUTTON

                await send_message(
                    chat_id,
                    "نام جدید دکمه را وارد کنید:",
                    keyboard=cancel_keyboard()
                )
                return

    if admin and text == "🔑 دریافت هش و لینک دکمه":
        children = db[current_node_id].get("children", [])

        if not children:
            await send_message(chat_id, "دکمه‌ای وجود ندارد.")
            return

        rows = []
        for cid in children:
            if cid in db:
                rows.append([f"🔑 {db[cid].get('name', 'بدون نام')}"])

        rows.append(["❌ لغو"])

        await send_message(
            chat_id,
            "دکمه‌ای که می‌خواهید هش و لینک آن را بگیرید، انتخاب کنید:",
            keyboard=make_keyboard(rows)
        )
        return

    if admin and text.startswith("🔑 "):
        target_name = text.replace("🔑 ", "")

        for cid in db[current_node_id].get("children", []):
            if cid in db and db[cid].get("name") == target_name:
                msg = f"🔑 هش این دکمه:\n\n{cid}"

                if BALE_BOT_USERNAME:
                    msg += f"\n\n🔗 لینک مستقیم بله:\nhttps://ble.ir/{BALE_BOT_USERNAME}?start={cid}"

                await send_message(chat_id, msg)
                return

    if admin and text == "🔀 جابه‌جایی چیدمان":
        children = db[current_node_id].get("children", [])

        if len(children) < 2:
            await send_message(chat_id, "برای جابه‌جایی حداقل دو دکمه لازم است.")
            return

        session["reorder_remaining"] = children.copy()
        session["reorder_result"] = []
        session["reorder_mode"] = True

        await show_reorder_keyboard(chat_id, session, db)
        return

    if admin and session.get("reorder_mode") and session.get("reorder_remaining"):
        remaining = session["reorder_remaining"]
        result = session["reorder_result"]

        selected_id = None

        for cid in remaining:
            if cid in db and text == f"🔀 {db[cid].get('name', 'بدون نام')}":
                selected_id = cid
                break

        if selected_id:
            remaining.remove(selected_id)
            result.append(selected_id)

            if remaining:
                await show_reorder_keyboard(chat_id, session, db)
                return

            push_admin_history(session, db)
            db[current_node_id]["children"] = result
            save_db(db)

            session.pop("reorder_remaining", None)
            session.pop("reorder_result", None)
            session.pop("reorder_mode", None)

            await send_message(
                chat_id,
                "✅ چیدمان جدید ذخیره شد.",
                keyboard=get_bale_keyboard(current_node_id, True)
            )
            return

    if admin and text == "↩️":
        history = session.get("admin_history", [])
        future = session.get("admin_future", [])

        if not history:
            await send_message(chat_id, "⛔️ چیزی برای بازگشت وجود ندارد.")
            return

        future.append(copy.deepcopy(load_db()))

        last_db = history.pop()
        save_db(last_db)

        session["current_node"] = "root"

        await send_message(
            chat_id,
            "↩️ آخرین تغییر بازگردانده شد.",
            keyboard=get_bale_keyboard("root", True)
        )
        return

    if admin and text == "↪️":
        history = session.get("admin_history", [])
        future = session.get("admin_future", [])

        if not future:
            await send_message(chat_id, "⛔️ چیزی برای جلو رفتن نیست.")
            return

        history.append(copy.deepcopy(load_db()))

        next_db = future.pop()
        save_db(next_db)

        session["current_node"] = "root"

        await send_message(
            chat_id,
            "↪️ تغییر دوباره اعمال شد.",
            keyboard=get_bale_keyboard("root", True)
        )
        return

    if admin and text == "📥 دریافت بکاپ":
        mem_zip = iolib.BytesIO()

        with zipfile.ZipFile(mem_zip, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(DB_FILE, arcname="database.json")

        mem_zip.seek(0)

        await send_document(
            chat_id,
            mem_zip.getvalue(),
            f"backup_{datetime.now().strftime('%Y%m%d')}.zip",
            caption="این فایل حاوی تمام ساختار دکمه‌ها و لینک فایل‌هاست."
        )
        return

    if admin and text == "📤 وارد کردن بکاپ":
        await send_message(
            chat_id,
            "⚠️ ورود بکاپ از داخل بله در این نسخه هنوز فعال نشده است.\n"
            "فعلاً از تلگرام برای وارد کردن بکاپ استفاده کنید.",
            keyboard=get_bale_keyboard(current_node_id, True)
        )
        return

    # ================= NORMAL NAVIGATION =================

    children = db[current_node_id].get("children", [])

    for child_id in children:
        child_node = db.get(child_id)

        if child_node and child_node.get("name") == text:

            # کاربر عادی + دکمه بدون فرزند
            if not admin and not child_node.get("children"):
                await send_node_contents(chat_id, child_id)
                return

            # ادمین یا دکمه دارای فرزند
            session["current_node"] = child_id

            await send_message(
                chat_id,
                f"📂 {child_node.get('name', 'بدون نام')}",
                keyboard=get_bale_keyboard(child_id, admin)
            )

            await send_node_contents(chat_id, child_id)
            return

    # اگر هیچ‌چیز match نشد
    if "current_node" not in session:
        await send_message(
            chat_id,
            "♻️ ربات بروزرسانی شده است.\nبرای ادامه لطفاً /start را بزنید."
        )


# ================= UPDATE ENTRYPOINT =================

async def handle_bale_update(update: dict):
    """
    این تابع از main.py صدا زده می‌شود:
    await handle_bale_update(data)
    """

    message = update.get("message") or update.get("edited_message") or {}

    if not message:
        return

    chat = message.get("chat") or {}
    sender = message.get("from") or {}

    chat_id = chat.get("id")
    user_id = sender.get("id") or chat_id

    if not chat_id or not user_id:
        return

    text = message.get("text") or ""

    # اگر متن نبود، فعلاً فقط پیام راهنما بده
    # بعداً فایل‌های بله را اینجا هندل می‌کنیم.
    if not text:
        session = get_session(user_id)
        if session.get("state") == WAITING_CONTENT:
            await send_message(
                chat_id,
                "📎 فایل دریافت شد، اما ذخیره فایل در بله هنوز فعال نشده است.\n"
                "فعلاً متن ارسال کنید یا ✅ ثبت نهایی را بزنید."
            )
        return

    text = text.strip()

    # /start یا /start payload
    if text.startswith("/start"):
        parts = text.split(maxsplit=1)

        args = []
        if len(parts) > 1:
            args = [parts[1].strip()]

        await bale_start(chat_id, user_id, args=args)
        return

    # اگر کاربر هنوز start نزده
    session = get_session(user_id)
    if "current_node" not in session:
        await send_message(
            chat_id,
            "♻️ ربات بروزرسانی شده است.\nبرای ادامه لطفاً /start را بزنید."
        )
        return

    await handle_bale_navigation(chat_id, user_id, text, message)
