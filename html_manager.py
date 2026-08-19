# html_manager.py
# مدیریت جزوه‌های HTML چندفایلی + هاست روی همان سرور ربات
#
# وابستگی به main.py فقط در زمان اجرا انجام می‌شود تا circular import ایجاد نشود.
# main.py باید تابع‌های زیر را داشته باشد:
#   run_telethon
#   telethon_client
#   load_userdata
#   ADMIN_IDS
#   ApplicationHandlerStop
#
# ENV:
#   HTML_BASE_URL=https://YOUR-APP.onrender.com/html
#   HTML_BACKUP_CHAT_ID=-100xxxxxxxxxx

import os
import io
import json
import zipfile
import shutil
import html
from pathlib import Path

from aiohttp import web
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import ContextTypes, ApplicationHandlerStop


HTML_DB_FILE = "/tmp/html_database.json"
HTML_ROOT = "/tmp/html_pages"
HTML_BACKUP_FILE = "/tmp/html_backup.zip"

WEBHOOK_URL = os.getenv("WEBHOOK_URL")
HTML_BASE_URL = f"{WEBHOOK_URL}/html"
HTML_BACKUP_CHAT_ID = int(os.getenv("HTML_BACKUP_CHAT_ID", "0"))

PAGE_SIZE = 8

os.makedirs(HTML_ROOT, exist_ok=True)

# =========================================================
# HTML Conversation States
# =========================================================

HTML_WAITING_ZIP = 1001
HTML_WAITING_NAME = 1002
HTML_WAITING_BACKUP = 1003

# =========================================================
# اتصال تنبل به main.py
# =========================================================

def _main():
    import main
    return main


def _is_admin(user_id):
    main = _main()
    userdata = main.load_userdata()
    sub_admins = userdata.get("sub_admins", [])
    return (
        user_id in main.ADMIN_IDS
        or user_id in sub_admins
    )


def _run_telethon(coro):
    return _main().run_telethon(coro)


def _telethon_client():
    return _main().telethon_client


# =========================================================
# DATABASE
# =========================================================

def _empty_db():
    return {
        "version": 1,
        "next_id": 1,
        "items": {}
    }


def load_html_db():
    os.makedirs(HTML_ROOT, exist_ok=True)

    if not os.path.exists(HTML_DB_FILE):
        data = _empty_db()
        save_html_db(data)
        return data

    try:
        with open(HTML_DB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            raise ValueError("HTML database is not a dictionary")

        data.setdefault("version", 1)
        data.setdefault("next_id", 1)
        data.setdefault("items", {})

        if not isinstance(data["items"], dict):
            data["items"] = {}

        return data

    except Exception as e:
        print("❌ HTML DB read error:", repr(e))
        return _empty_db()


def save_html_db(data):
    tmp = HTML_DB_FILE + ".tmp"

    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    os.replace(tmp, HTML_DB_FILE)


# =========================================================
# ZIP SECURITY / EXTRACTION
# =========================================================

def _safe_zip_member(name):
    name = name.replace("\\", "/")

    if not name or name.startswith("/"):
        return False

    parts = Path(name).parts

    if ".." in parts:
        return False

    return True


def _find_index_name(zf):
    names = [
        n.replace("\\", "/").lstrip("./")
        for n in zf.namelist()
        if not n.endswith("/")
    ]

    # اولویت با index.html در ریشه
    for n in names:
        if n.lower() == "index.html":
            return n

    # اگر zip یک پوشه اصلی داشته باشد:
    # folder/index.html
    candidates = [
        n for n in names
        if n.lower().endswith("/index.html")
    ]

    if candidates:
        candidates.sort(key=lambda x: x.count("/"))
        return candidates[0]

    return None


def _extract_zip_bytes(zip_bytes, target_dir):
    if os.path.exists(target_dir):
        shutil.rmtree(target_dir)

    os.makedirs(target_dir, exist_ok=True)

    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:

        bad = [
            name for name in zf.namelist()
            if not _safe_zip_member(name)
        ]

        if bad:
            raise ValueError(
                "ZIP شامل مسیر غیرمجاز است."
            )

        index_name = _find_index_name(zf)

        if not index_name:
            raise ValueError(
                "داخل ZIP فایل index.html پیدا نشد."
            )

        # اگر index داخل یک پوشه است، همان پوشه را به عنوان root
        # سایت در نظر می‌گیریم.
        prefix = ""
        normalized_index = index_name.replace("\\", "/")

        if normalized_index.lower() != "index.html":
            prefix = normalized_index[
                :normalized_index.lower().rfind("index.html")
            ]

        for member in zf.namelist():

            member = member.replace("\\", "/")

            if prefix and member.startswith(prefix):
                relative = member[len(prefix):]
            else:
                relative = member

            relative = relative.lstrip("/")

            if not relative:
                continue

            if not _safe_zip_member(relative):
                raise ValueError("مسیر غیرمجاز داخل ZIP.")

            destination = os.path.abspath(
                os.path.join(target_dir, relative)
            )

            root = os.path.abspath(target_dir)

            if not (
                destination == root
                or destination.startswith(root + os.sep)
            ):
                raise ValueError("ZIP path traversal detected.")

            if member.endswith("/"):
                os.makedirs(destination, exist_ok=True)
                continue

            os.makedirs(
                os.path.dirname(destination),
                exist_ok=True
            )

            with zf.open(member) as src, open(
                destination, "wb"
            ) as dst:
                shutil.copyfileobj(src, dst)

    final_index = os.path.join(target_dir, "index.html")

    if not os.path.isfile(final_index):
        raise ValueError(
            "بعد از استخراج، index.html در ریشه سایت پیدا نشد."
        )


# =========================================================
# BACKUP
# =========================================================

def _build_backup_zip():
    """
    html_backup.zip شامل:
      html_database.json
      pages/<id>.zip
    """
    db = load_html_db()

    buffer = io.BytesIO()

    with zipfile.ZipFile(
        buffer,
        "w",
        zipfile.ZIP_DEFLATED
    ) as zf:

        zf.writestr(
            "html_database.json",
            json.dumps(
                db,
                ensure_ascii=False,
                indent=2
            ).encode("utf-8")
        )

        for item_id in db.get("items", {}):
            zip_path = os.path.join(
                HTML_ROOT,
                f"{item_id}.zip"
            )

            if os.path.isfile(zip_path):
                zf.write(
                    zip_path,
                    arcname=f"pages/{item_id}.zip"
                )

    buffer.seek(0)

    with open(HTML_BACKUP_FILE, "wb") as f:
        f.write(buffer.getvalue())

    return buffer.getvalue()


def _split_text(text, max_len=3500):
    chunks = []

    while text:
        chunks.append(text[:max_len])
        text = text[max_len:]

    return chunks or [""]


def _admin_log(admin, reason):
    name = html.escape(
        getattr(admin, "full_name", None)
        or "بدون نام"
    )
    username = getattr(admin, "username", None)
    user_id = getattr(admin, "id", "نامشخص")

    username_text = (
        f"@{html.escape(username)}"
        if username
        else "ندارد"
    )

    return (
        "👤 <b>ادمین:</b> "
        f"{name}\n"
        f"🆔 <code>{user_id}</code>\n"
        f"🔗 {username_text}\n\n"
        f"📝 <b>دلیل:</b>\n{reason}"
    )


def backup_html_database(admin, reason):
    """
    بعد از هر تغییر، html_backup.zip را به گروه HTML_BACKUP می‌فرستد
    و گزارش تغییر را به صورت reply روی همان فایل می‌فرستد.
    """
    if not HTML_BACKUP_CHAT_ID:
        print("⚠️ HTML_BACKUP_CHAT_ID تنظیم نشده.")
        return False

    try:
        _build_backup_zip()

        caption = (
            "📦 <b>HTML BACKUP</b>\n"
            "آخرین نسخه بکاپ جزوه‌های HTML"
        )

        async def upload():
            return await _telethon_client().send_file(
                HTML_BACKUP_CHAT_ID,
                HTML_BACKUP_FILE,
                caption=caption,
                parse_mode="HTML"
            )

        message = _run_telethon(upload())

        if not message:
            print("❌ HTML backup upload failed.")
            return False

        msg_id = getattr(message, "id", None)

        if msg_id:
            log_text = _admin_log(admin, reason)

            async def send_logs():
                for chunk in _split_text(log_text):
                    await _telethon_client().send_message(
                        HTML_BACKUP_CHAT_ID,
                        chunk,
                        parse_mode="HTML",
                        link_preview=False,
                        reply_to=msg_id
                    )

            _run_telethon(send_logs())

        return True

    except Exception as e:
        print("❌ HTML backup error:", repr(e))
        return False


async def _download_latest_html_backup():
    if not HTML_BACKUP_CHAT_ID:
        return False

    try:
        client = _telethon_client()

        async def find_and_download():
            async for message in client.iter_messages(
                HTML_BACKUP_CHAT_ID,
                limit=300
            ):
                if not message.file:
                    continue

                filename = (
                    message.file.name
                    if message.file.name
                    else ""
                )

                caption = message.message or ""

                if (
                    filename == "html_backup.zip"
                    or "HTML BACKUP" in caption
                ):
                    await message.download_media(
                        file=HTML_BACKUP_FILE
                    )
                    return True

            return False

        return bool(_run_telethon(find_and_download()))

    except Exception as e:
        print("❌ HTML backup download error:", repr(e))
        return False


def restore_html_database():
    """
    آخرین html_backup.zip را از گروه می‌گیرد و
    دیتابیس + zipهای صفحات را جایگزین می‌کند.
    """
    if not os.path.exists(HTML_BACKUP_FILE):
        ok = _download_latest_html_backup()
        if not ok:
            print("ℹ️ HTML backup پیدا نشد؛ دیتابیس جدید ساخته می‌شود.")
            save_html_db(_empty_db())
            return False

    try:
        with zipfile.ZipFile(
            HTML_BACKUP_FILE,
            "r"
        ) as zf:

            names = set(zf.namelist())

            if "html_database.json" not in names:
                raise ValueError(
                    "html_backup.zip فاقد html_database.json است."
                )

            raw_db = zf.read("html_database.json")
            data = json.loads(raw_db.decode("utf-8"))

            if not isinstance(data, dict):
                raise ValueError("HTML DB نامعتبر است.")

            data.setdefault("version", 1)
            data.setdefault("next_id", 1)
            data.setdefault("items", {})

            # پاک کردن صفحات فعلی
            if os.path.exists(HTML_ROOT):
                shutil.rmtree(HTML_ROOT)

            os.makedirs(HTML_ROOT, exist_ok=True)

            save_html_db(data)

            # استخراج zip هر جزوه
            for item_id in data.get("items", {}):
                member = f"pages/{item_id}.zip"

                if member not in names:
                    print(
                        f"⚠️ ZIP برای HTML {item_id} در backup نیست."
                    )
                    continue

                zip_bytes = zf.read(member)

                zip_path = os.path.join(
                    HTML_ROOT,
                    f"{item_id}.zip"
                )

                with open(zip_path, "wb") as f:
                    f.write(zip_bytes)

                target_dir = os.path.join(
                    HTML_ROOT,
                    str(item_id)
                )

                _extract_zip_bytes(
                    zip_bytes,
                    target_dir
                )

        print("✅ HTML database restored.")
        return True

    except Exception as e:
        print("❌ HTML restore error:", repr(e))
        return False


# =========================================================
# UPLOAD NEW HTML ZIP
# =========================================================

async def html_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return

    context.user_data["html_waiting"] = "zip"

    await update.message.reply_text(
        "📦 ZIP جزوه HTML را بفرستید.\n\n"
        "ZIP باید شامل <code>index.html</code> و تمام "
        "فایل‌های موردنیاز مثل CSS، JS و تصاویر باشد.\n\n"
        "برای لغو: /cancel",
        parse_mode="HTML"
    )


async def html_receive_zip(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if context.user_data.get("html_waiting") != "zip":
        return

    if not _is_admin(update.effective_user.id):
        return

    document = update.message.document

    if not document:
        return

    filename = (document.file_name or "").lower()

    if not filename.endswith(".zip"):
        await update.message.reply_text(
            "❌ فقط فایل ZIP بفرستید.\n"
            "برای لغو: /cancel"
        )
        raise ApplicationHandlerStop

    try:
        tg_file = await document.get_file()
        data = bytes(
            await tg_file.download_as_bytearray()
        )

        # تست و استخراج در یک فولدر موقت
        temp_id = "__temp__"
        temp_dir = os.path.join(
            HTML_ROOT,
            temp_id
        )

        _extract_zip_bytes(data, temp_dir)

        shutil.rmtree(temp_dir, ignore_errors=True)

        context.user_data["html_zip_bytes"] = data
        context.user_data["html_original_filename"] = document.file_name
        context.user_data["html_waiting"] = "name"

        await update.message.reply_text(
            "✅ ZIP دریافت شد.\n\n"
            "📚 حالا اسم جزوه را بفرستید.\n"
            "برای لغو: /cancel"
        )

    except zipfile.BadZipFile:
        await update.message.reply_text(
            "❌ فایل ZIP معتبر نیست.\n"
            "دوباره ZIP را بفرستید یا /cancel."
        )

    except Exception as e:
        print("❌ HTML ZIP validation error:", repr(e))
        await update.message.reply_text(
            f"❌ ZIP قابل استفاده نیست:\n{e}"
        )

    raise ApplicationHandlerStop


async def html_receive_name(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if context.user_data.get("html_waiting") != "name":
        return

    if not _is_admin(update.effective_user.id):
        return

    name = (update.message.text or "").strip()

    if not name:
        await update.message.reply_text(
            "❌ اسم جزوه نمی‌تواند خالی باشد."
        )
        raise ApplicationHandlerStop

    zip_bytes = context.user_data.get("html_zip_bytes")

    if not zip_bytes:
        context.user_data.pop("html_waiting", None)
        await update.message.reply_text(
            "❌ فایل ZIP موقت پیدا نشد. دوباره /html را بزنید."
        )
        raise ApplicationHandlerStop

    try:
        db = load_html_db()

        item_id = int(db.get("next_id", 1))

        while str(item_id) in db.get("items", {}):
            item_id += 1

        db["next_id"] = item_id + 1

        zip_path = os.path.join(
            HTML_ROOT,
            f"{item_id}.zip"
        )

        page_dir = os.path.join(
            HTML_ROOT,
            str(item_id)
        )

        with open(zip_path, "wb") as f:
            f.write(zip_bytes)

        _extract_zip_bytes(
            zip_bytes,
            page_dir
        )

        db["items"][str(item_id)] = {
            "id": item_id,
            "name": name,
            "zip_filename": f"{item_id}.zip",
            "url": f"{HTML_BASE_URL}/{item_id}/",
        }

        save_html_db(db)

        link = f"{HTML_BASE_URL}/{item_id}/"

        reason = (
            "➕ <b>افزودن جزوه HTML</b>\n"
            f"📚 نام: {html.escape(name)}\n"
            f"🔢 ID: <code>{item_id}</code>\n"
            f"🔗 لینک: {html.escape(link)}"
        )

        backup_html_database(
            update.effective_user,
            reason
        )

        await update.message.reply_text(
            "✅ جزوه HTML با موفقیت ثبت شد.\n\n"
            f"📚 <b>{html.escape(name)}</b>\n"
            f"🔗 {html.escape(link)}",
            parse_mode="HTML"
        )

    except Exception as e:
        print("❌ HTML create error:", repr(e))
        await update.message.reply_text(
            f"❌ خطا در ثبت جزوه:\n{e}"
        )

    finally:
        for key in (
            "html_waiting",
            "html_zip_bytes",
            "html_original_filename"
        ):
            context.user_data.pop(key, None)

    raise ApplicationHandlerStop


async def html_cancel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    waiting = context.user_data.get("html_waiting")

    if not waiting:
        return

    for key in (
        "html_waiting",
        "html_zip_bytes",
        "html_original_filename"
    ):
        context.user_data.pop(key, None)

    await update.message.reply_text(
        "❌ عملیات HTML لغو شد."
    )

    raise ApplicationHandlerStop


# =========================================================
# ADMIN PANEL KEYBOARDS
# =========================================================

def html_admin_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📦 زیپ‌های موجود",
                callback_data="admin_html_list"
            )
        ],
        [
            InlineKeyboardButton(
                "➕ وارد کردن زیپ جدید",
                callback_data="admin_html_import"
            )
        ],
        [
            InlineKeyboardButton(
                "🗑 حذف زیپ",
                callback_data="admin_html_delete"
            )
        ],
        [
            InlineKeyboardButton(
                "🔥 حذف همه زیپ‌ها",
                callback_data="admin_html_delete_all"
            )
        ],
        [
            InlineKeyboardButton(
                "📤 دریافت بکاپ",
                callback_data="admin_html_get_backup"
            ),
            InlineKeyboardButton(
                "📥 وارد کردن بکاپ",
                callback_data="admin_html_import_backup"
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 بازگشت",
                callback_data="admin_back_access"
            )
        ]
    ])


def _paged_buttons(items, action, page=0):
    total = len(items)
    start = page * PAGE_SIZE
    end = start + PAGE_SIZE

    keyboard = []

    for item in items[start:end]:
        item_id = item["id"]
        name = str(item["name"])[:35]

        keyboard.append([
            InlineKeyboardButton(
                f"📚 {name}",
                callback_data=f"admin_html_{action}_{item_id}"
            )
        ])

    total_pages = max(
        1,
        (total + PAGE_SIZE - 1) // PAGE_SIZE
    )

    nav = []

    if page > 0:
        nav.append(
            InlineKeyboardButton(
                "⬅️ صفحه قبل",
                callback_data=(
                    f"admin_html_{action}_page_{page - 1}"
                )
            )
        )

    if end < total:
        nav.append(
            InlineKeyboardButton(
                "➡️ صفحه بعد",
                callback_data=(
                    f"admin_html_{action}_page_{page + 1}"
                )
            )
        )

    if nav:
        keyboard.append(nav)

    keyboard.append([
        InlineKeyboardButton(
            "🔙 بازگشت",
            callback_data="admin_html_panel"
        )
    ])

    return InlineKeyboardMarkup(keyboard), total_pages


async def _show_html_list(query, action, page=0):
    db = load_html_db()

    items = list(db.get("items", {}).values())
    items.sort(
        key=lambda x: int(x.get("id", 0))
    )

    if not items:
        await query.message.edit_text(
            "📭 هنوز هیچ جزوه HTML ثبت نشده است.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 بازگشت",
                        callback_data="admin_html_panel"
                    )
                ]
            ])
        )
        return

    keyboard, total_pages = _paged_buttons(
        items,
        action,
        page
    )

    title = (
        "📦 زیپ‌های موجود"
        if action == "open"
        else "🗑 انتخاب زیپ برای حذف"
    )

    await query.message.edit_text(
        f"{title}\n\n"
        f"📄 صفحه {page + 1} از {total_pages}",
        reply_markup=keyboard
    )


async def html_admin_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    data = query.data

    if not _is_admin(query.from_user.id):
        await query.answer(
            "⛔️ دسترسی ندارید.",
            show_alert=True
        )
        return

    await query.answer()

    # ---------------- پنل ----------------
    if data == "admin_html_panel":
        await query.message.edit_text(
            "🌐 <b>مدیریت HTML</b>\n\n"
            "از گزینه موردنظر استفاده کنید:",
            parse_mode="HTML",
            reply_markup=html_admin_keyboard()
        )
        return

    # ---------------- لیست ----------------
    if data == "admin_html_list":
        await _show_html_list(query, "open", 0)
        return

    if data.startswith("admin_html_open_page_"):
        page = int(data.rsplit("_", 1)[-1])
        await _show_html_list(query, "open", page)
        return

    # ---------------- باز کردن لینک ----------------
    if data.startswith("admin_html_open_"):
        item_id = int(data.rsplit("_", 1)[-1])
        db = load_html_db()
        item = db.get("items", {}).get(str(item_id))

        if not item:
            await query.answer(
                "❌ جزوه پیدا نشد.",
                show_alert=True
            )
            return

        await query.message.reply_text(
            "🔗 لینک جزوه:\n"
            f"{item['url']}\n\n"
            f"📚 {html.escape(item['name'])}",
            parse_mode="HTML"
        )
        return

    # ---------------- وارد کردن از پنل ----------------
    if data == "admin_html_import":
        context.user_data["html_waiting"] = "zip"

        await query.message.reply_text(
            "📦 ZIP جزوه HTML را بفرستید.\n"
            "برای لغو: /cancel"
        )
        return

    # ---------------- حذف ----------------
    if data == "admin_html_delete":
        await _show_html_list(query, "delete", 0)
        return

    if data.startswith("admin_html_delete_page_"):
        page = int(data.rsplit("_", 1)[-1])
        await _show_html_list(query, "delete", page)
        return

    if data.startswith("admin_html_delete_"):
        item_id = int(data.rsplit("_", 1)[-1])

        db = load_html_db()
        item = db.get("items", {}).get(str(item_id))

        if not item:
            await query.answer(
                "❌ جزوه پیدا نشد.",
                show_alert=True
            )
            return

        context.user_data["html_delete_confirm"] = item_id

        await query.message.edit_text(
            "⚠️ <b>تأیید حذف</b>\n\n"
            f"📚 {html.escape(item['name'])}\n"
            f"🔗 {html.escape(item['url'])}\n\n"
            "آیا مطمئن هستید؟",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "✅ بله، حذف کن",
                        callback_data=(
                            f"admin_html_confirm_delete_{item_id}"
                        )
                    ),
                    InlineKeyboardButton(
                        "❌ لغو",
                        callback_data="admin_html_delete"
                    )
                ]
            ])
        )
        return

    if data.startswith("admin_html_confirm_delete_"):
        item_id = int(data.rsplit("_", 1)[-1])

        db = load_html_db()
        item = db.get("items", {}).pop(str(item_id), None)

        if not item:
            await query.message.edit_text(
                "❌ جزوه پیدا نشد.",
                reply_markup=html_admin_keyboard()
            )
            return

        shutil.rmtree(
            os.path.join(HTML_ROOT, str(item_id)),
            ignore_errors=True
        )

        try:
            os.remove(
                os.path.join(
                    HTML_ROOT,
                    f"{item_id}.zip"
                )
            )
        except FileNotFoundError:
            pass

        save_html_db(db)

        reason = (
            "🗑 <b>حذف جزوه HTML</b>\n"
            f"📚 نام: {html.escape(item['name'])}\n"
            f"🔢 ID: <code>{item_id}</code>\n"
            f"🔗 لینک قبلی: {html.escape(item['url'])}"
        )

        backup_html_database(
            query.from_user,
            reason
        )

        await query.message.edit_text(
            "✅ جزوه حذف شد.\n\n"
            f"📚 {html.escape(item['name'])}",
            parse_mode="HTML",
            reply_markup=html_admin_keyboard()
        )
        return

    # ---------------- حذف همه ----------------
    if data == "admin_html_delete_all":
        db = load_html_db()
        items = list(db.get("items", {}).values())

        if not items:
            await query.answer(
                "📭 چیزی برای حذف وجود ندارد.",
                show_alert=True
            )
            return

        await query.message.edit_text(
            f"⚠️ <b>حذف همه جزوه‌های HTML</b>\n\n"
            f"تعداد: {len(items)}\n"
            "این عملیات قابل بازگشت نیست.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔥 بله، همه را حذف کن",
                        callback_data="admin_html_confirm_delete_all"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "❌ لغو",
                        callback_data="admin_html_panel"
                    )
                ]
            ])
        )
        return

    if data == "admin_html_confirm_delete_all":
        db = load_html_db()
        items = list(db.get("items", {}).values())

        if not items:
            await query.message.edit_text(
                "📭 چیزی برای حذف وجود ندارد.",
                reply_markup=html_admin_keyboard()
            )
            return

        names = [
            f"• {item.get('name', 'بدون نام')} "
            f"(ID: {item.get('id')})"
            for item in items
        ]

        db["items"] = {}
        save_html_db(db)

        for item in items:
            item_id = item.get("id")
            shutil.rmtree(
                os.path.join(HTML_ROOT, str(item_id)),
                ignore_errors=True
            )

            try:
                os.remove(
                    os.path.join(
                        HTML_ROOT,
                        f"{item_id}.zip"
                    )
                )
            except FileNotFoundError:
                pass

        reason = (
            "🔥 <b>حذف همه جزوه‌های HTML</b>\n\n"
            + "\n".join(names)
        )

        backup_html_database(
            query.from_user,
            reason
        )

        await query.message.edit_text(
            "✅ همه جزوه‌های HTML حذف شدند.",
            reply_markup=html_admin_keyboard()
        )
        return

    # ---------------- دریافت بکاپ ----------------
    if data == "admin_html_get_backup":
        try:
            _build_backup_zip()

            with open(
                HTML_BACKUP_FILE,
                "rb"
            ) as f:
                data_bytes = f.read()

            await query.message.reply_document(
                document=io.BytesIO(data_bytes),
                filename="html_backup.zip",
                caption="📦 بکاپ کامل جزوه‌های HTML"
            )

        except Exception as e:
            await query.message.reply_text(
                f"❌ خطا در ساخت بکاپ:\n{e}"
            )
        return

    # ---------------- وارد کردن بکاپ ----------------
    if data == "admin_html_import_backup":
        context.user_data["html_waiting"] = "backup"

        await query.message.reply_text(
            "📥 فایل <code>html_backup.zip</code> را بفرستید.\n"
            "برای لغو: /cancel",
            parse_mode="HTML"
        )
        return


async def html_receive_backup(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if context.user_data.get("html_waiting") != "backup":
        return

    if not _is_admin(update.effective_user.id):
        return

    document = update.message.document

    if not document:
        return

    if not (document.file_name or "").lower().endswith(".zip"):
        await update.message.reply_text(
            "❌ فقط html_backup.zip را بفرستید."
        )
        raise ApplicationHandlerStop

    try:
        tg_file = await document.get_file()
        data = bytes(
            await tg_file.download_as_bytearray()
        )

        with zipfile.ZipFile(
            io.BytesIO(data),
            "r"
        ) as zf:

            if "html_database.json" not in zf.namelist():
                raise ValueError(
                    "html_database.json داخل بکاپ نیست."
                )

        with open(HTML_BACKUP_FILE, "wb") as f:
            f.write(data)

        if not restore_html_database():
            raise ValueError(
                "بازیابی بکاپ انجام نشد."
            )

        reason = (
            "♻️ <b>جایگزینی HTML BACKUP</b>\n"
            "ادمین یک بکاپ جدید را وارد و جایگزین کرد."
        )

        backup_html_database(
            update.effective_user,
            reason
        )

        await update.message.reply_text(
            "✅ بکاپ HTML با موفقیت جایگزین شد."
        )

    except Exception as e:
        print("❌ HTML backup import error:", repr(e))
        await update.message.reply_text(
            f"❌ خطا در وارد کردن بکاپ:\n{e}"
        )

    finally:
        context.user_data.pop("html_waiting", None)

    raise ApplicationHandlerStop


# =========================================================
# WEB ROUTE
# =========================================================

async def html_page_handler(request):
    item_id = request.match_info.get("item_id", "")
    relative = request.match_info.get("path", "") or "index.html"

    if not item_id.isdigit():
        return web.Response(status=404, text="Not found")

    db = load_html_db()

    item = db.get("items", {}).get(str(int(item_id)))

    if not item:
        return web.Response(
            status=404,
            text="جزوه پیدا نشد."
        )

    root = os.path.abspath(
        os.path.join(HTML_ROOT, str(int(item_id)))
    )

    relative = relative.replace("\\", "/").lstrip("/")

    if ".." in Path(relative).parts:
        return web.Response(status=403, text="Forbidden")

    file_path = os.path.abspath(
        os.path.join(root, relative)
    )

    if not (
        file_path == root
        or file_path.startswith(root + os.sep)
    ):
        return web.Response(status=403, text="Forbidden")

    if os.path.isdir(file_path):
        file_path = os.path.join(file_path, "index.html")

    if not os.path.isfile(file_path):
        # برای SPAها می‌توان اینجا fallback کرد؛ فعلاً 404 امن‌تر است.
        return web.Response(
            status=404,
            text="فایل موردنظر پیدا نشد."
        )

    return web.FileResponse(file_path)


def register_html_routes(webapp):
    # /html/12/  و /html/12/assets/app.js
    webapp.router.add_get(
        "/html/{item_id}/{path:.*}",
        html_page_handler
    )


# =========================================================
# STARTUP RESTORE
# =========================================================

def restore_html_on_startup():
    """
    اگر فایل محلی HTML DB وجود ندارد، آخرین backup را از Telegram می‌گیرد.
    اگر وجود دارد، آن را دست نمی‌زند.
    """
    if os.path.exists(HTML_DB_FILE):
        try:
            db = load_html_db()
            if db.get("items"):
                print(
                    f"✅ Local HTML DB loaded: "
                    f"{len(db['items'])} items"
                )
                return True
        except Exception:
            pass

    print("🔄 Restoring HTML database from Telegram...")
    return restore_html_database()
