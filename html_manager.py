# -*- coding: utf-8 -*-
"""
HTML ZIP Manager for the Telegram bot.

- /html -> receive ZIP -> receive booklet name -> publish at /html/<numeric-id>
- Admin panel: HTML management
- HTML ZIPs are stored under /tmp/html_zips and described by html_database.json
- Automatic backup is one archive: html_backup.zip
- Backup archive contains html_database.json + all ZIP files.
- Backup is uploaded to the configured Telethon backup group after every mutation.
- On startup the newest html_backup.zip is restored if local files are missing.

This module intentionally does NOT import main.py.  main.py injects the few
functions/resources that already exist there, avoiding circular imports.
"""

import io
import json
import logging
import os
import re
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
import mimetypes
from urllib.parse import unquote
from pathlib import PurePosixPath

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from aiohttp import web

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

HTML_WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")
HTML_BACKUP_CHAT_ID = int(os.getenv("HTML_BACKUP_CHAT_ID", "0") or "0")
HTML_DB_FILE = os.getenv("HTML_DB_FILE", "/tmp/html_database.json")
HTML_ROOT = Path(os.getenv("HTML_ROOT", "/tmp/html_zips"))
HTML_BACKUP_FILE = os.getenv("HTML_BACKUP_FILE", "/tmp/html_backup.zip")
HTML_MAX_ZIP_BYTES = int(os.getenv("HTML_MAX_ZIP_BYTES", str(50 * 1024 * 1024)))
HTML_PAGE_SIZE = 8
HTML_LOG_MAX = 3000

# PTB conversation states are local to this ConversationHandler.
HTML_WAIT_ZIP, HTML_WAIT_NAME = range(2)

# Injected by main.py.
ADMIN_IDS = set()
_get_userdata = None
_upload_file_to_telegram = None
_download_latest_file_from_telegram = None
_run_telethon = None
_telethon_client = None


def configure_html_manager(
    *,
    admin_ids,
    get_userdata,
    upload_file_to_telegram,
    download_latest_file_from_telegram,
    run_telethon=None,
    telethon_client=None,
):
    """Inject main.py dependencies without importing main.py."""
    global ADMIN_IDS, _get_userdata, _upload_file_to_telegram
    global _download_latest_file_from_telegram, _run_telethon, _telethon_client

    ADMIN_IDS = {int(x) for x in (admin_ids or [])}
    _get_userdata = get_userdata
    _upload_file_to_telegram = upload_file_to_telegram
    _download_latest_file_from_telegram = download_latest_file_from_telegram
    _run_telethon = run_telethon
    _telethon_client = telethon_client


# ---------------------------------------------------------------------------
# Local DB / filesystem
# ---------------------------------------------------------------------------


def _default_db():
    return {"version": 1, "next_id": 1, "zips": {}}


def _ensure_dirs():
    HTML_ROOT.mkdir(parents=True, exist_ok=True)
    Path(HTML_DB_FILE).parent.mkdir(parents=True, exist_ok=True)


def _load_db():
    _ensure_dirs()
    if not os.path.exists(HTML_DB_FILE):
        return _default_db()
    try:
        with open(HTML_DB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return _default_db()
        data.setdefault("version", 1)
        data.setdefault("next_id", 1)
        data.setdefault("zips", {})
        return data
    except Exception:
        log.exception("Failed to load HTML DB")
        return _default_db()


def _save_db(db):
    _ensure_dirs()
    tmp = HTML_DB_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, HTML_DB_FILE)


def _zip_path(zip_id):
    return HTML_ROOT / f"{int(zip_id)}.zip"


def _safe_filename(name):
    name = os.path.basename(name or "")
    name = re.sub(r"[\x00-\x1f\x7f]", "", name)
    return name[:180]


def _safe_extract_zip(zip_path: Path, destination: Path):
    """Extract safely; reject path traversal and suspicious symlinks."""
    if not zipfile.is_zipfile(zip_path):
        raise ValueError("فایل ZIP معتبر نیست.")

    with zipfile.ZipFile(zip_path) as zf:
        members = zf.infolist()
        if not members:
            raise ValueError("ZIP خالی است.")

        total_uncompressed = 0
        for info in members:
            total_uncompressed += max(0, int(info.file_size))
            normalized = os.path.normpath(info.filename.replace("\\", "/"))
            if normalized.startswith("../") or normalized == ".." or normalized.startswith("/"):
                raise ValueError("ZIP شامل مسیر غیرمجاز است.")
            # Unix symlink bit.
            mode = (info.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                raise ValueError("ZIP شامل symlink است و قابل قبول نیست.")

        # Keep an explicit decompression ceiling too.
        if total_uncompressed > 250 * 1024 * 1024:
            raise ValueError("حجم استخراج‌شده ZIP بیش از حد مجاز است.")

        destination.mkdir(parents=True, exist_ok=True)
        zf.extractall(destination)


def _find_index_file(root: Path):
    candidates = []
    for p in root.rglob("*"):
        if p.is_file() and p.name.lower() in {"index.html", "index.htm"}:
            candidates.append(p)
    if not candidates:
        raise ValueError("داخل ZIP فایل index.html یا index.htm پیدا نشد.")
    # Prefer the shallowest index.
    return sorted(candidates, key=lambda p: (len(p.relative_to(root).parts), str(p)))[0]


def _validate_and_prepare_zip(source_zip: Path, zip_id: int):
    """Validate ZIP and make sure its HTML root is renderable."""
    work = Path(tempfile.mkdtemp(prefix=f"html_validate_{zip_id}_"))
    try:
        _safe_extract_zip(source_zip, work)
        index = _find_index_file(work)
        # Return the relative directory containing index.html.  We serve that directory.
        return index.parent.relative_to(work).as_posix()
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _extract_for_serving(zip_id: int):
    """Materialize a ZIP into /tmp/html_zips/rendered/<id>."""
    zp = _zip_path(zip_id)
    if not zp.exists():
        raise FileNotFoundError(f"ZIP {zip_id} not found")

    render_root = HTML_ROOT / "rendered" / str(zip_id)
    if render_root.exists():
        shutil.rmtree(render_root, ignore_errors=True)
    render_root.mkdir(parents=True, exist_ok=True)
    _safe_extract_zip(zp, render_root)
    index = _find_index_file(render_root)
    return render_root, index


def _rebuild_rendered():
    db = _load_db()
    rendered_root = HTML_ROOT / "rendered"
    rendered_root.mkdir(parents=True, exist_ok=True)
    for item in rendered_root.iterdir():
        if item.is_dir():
            shutil.rmtree(item, ignore_errors=True)
        else:
            item.unlink(missing_ok=True)

    for key in list(db.get("zips", {})):
        try:
            _extract_for_serving(int(key))
        except Exception:
            log.exception("Could not rebuild HTML ZIP %s", key)


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------


def _make_backup_archive():
    """Create a complete self-contained backup archive."""
    _ensure_dirs()
    db = _load_db()
    _save_db(db)

    tmp = HTML_BACKUP_FILE + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as out:
        out.write(HTML_DB_FILE, arcname="html_database.json")
        for key in sorted(db.get("zips", {}), key=lambda x: int(x)):
            zp = _zip_path(int(key))
            if zp.exists():
                out.write(zp, arcname=f"zips/{int(key)}.zip")
    os.replace(tmp, HTML_BACKUP_FILE)
    return HTML_BACKUP_FILE


def _restore_backup_archive(archive_path: str):
    """Replace local HTML state from a complete backup archive."""
    archive = Path(archive_path)
    if not archive.exists() or not zipfile.is_zipfile(archive):
        return False

    temp = Path(tempfile.mkdtemp(prefix="html_restore_"))
    try:
        with zipfile.ZipFile(archive) as zf:
            names = zf.namelist()
            if "html_database.json" not in names:
                raise ValueError("فایل html_database.json در بکاپ وجود ندارد.")
            for name in names:
                normalized = os.path.normpath(name.replace("\\", "/"))
                if normalized.startswith("../") or normalized == ".." or normalized.startswith("/"):
                    raise ValueError("بکاپ شامل مسیر غیرمجاز است.")
            zf.extractall(temp)

        with open(temp / "html_database.json", "r", encoding="utf-8") as f:
            db = json.load(f)
        if not isinstance(db, dict) or not isinstance(db.get("zips", {}), dict):
            raise ValueError("ساختار دیتابیس HTML نامعتبر است.")

        _ensure_dirs()
        # Replace DB and ZIPs atomically-ish: only mutate after validation.
        new_root = Path(tempfile.mkdtemp(prefix="html_state_"))
        try:
            (new_root / "zips").mkdir(parents=True, exist_ok=True)
            shutil.copy2(temp / "html_database.json", new_root / "html_database.json")
            for key in db.get("zips", {}):
                src = temp / "zips" / f"{int(key)}.zip"
                if src.exists():
                    shutil.copy2(src, new_root / "zips" / f"{int(key)}.zip")

            # Move into place.
            for old in HTML_ROOT.glob("*.zip"):
                old.unlink(missing_ok=True)
            for src in (new_root / "zips").glob("*.zip"):
                shutil.copy2(src, HTML_ROOT / src.name)
            shutil.copy2(new_root / "html_database.json", HTML_DB_FILE)
        finally:
            shutil.rmtree(new_root, ignore_errors=True)

        _rebuild_rendered()
        shutil.copy2(archive, HTML_BACKUP_FILE)
        return True
    finally:
        shutil.rmtree(temp, ignore_errors=True)


def restore_latest_html_backup():
    """Called from main during startup."""
    _ensure_dirs()
    if not HTML_BACKUP_CHAT_ID or _download_latest_file_from_telegram is None:
        return False
    try:
        ok = _download_latest_file_from_telegram(
            chat_id=HTML_BACKUP_CHAT_ID,
            filename="html_backup.zip",
            save_path=HTML_BACKUP_FILE,
        )
        if ok:
            return _restore_backup_archive(HTML_BACKUP_FILE)
    except Exception:
        log.exception("Failed to restore HTML backup from Telegram")
    return False


def _split_text(text, max_len=HTML_LOG_MAX):
    text = str(text or "")
    if len(text) <= max_len:
        return [text]
    chunks, current = [], []
    size = 0
    for line in text.splitlines(True):
        if size + len(line) > max_len and current:
            chunks.append("".join(current))
            current, size = [], 0
        # hard split an individual oversized line
        while len(line) > max_len:
            chunks.append(line[:max_len])
            line = line[max_len:]
        if line:
            current.append(line)
            size += len(line)
    if current:
        chunks.append("".join(current))
    return chunks or [""]


def _admin_html_name(user):
    if not user:
        return "ادمین نامشخص"
    name = user.full_name or "بدون نام"
    return f'<a href="tg://user?id={user.id}">{name}</a>'


def _backup_caption(user, reason):
    return f"<b>HTML BACKUP</b>\n👤 ادمین: {_admin_html_name(user)}\n📝 دلیل: {reason}"


def _backup_and_log(user, reason):
    """Synchronous because main's Telethon bridge is synchronous."""
    if not HTML_BACKUP_CHAT_ID or _upload_file_to_telegram is None:
        log.warning("HTML backup chat/helper is not configured")
        return False

    try:
        backup_path = _make_backup_archive()
        backup_msg = _upload_file_to_telegram(
            HTML_BACKUP_CHAT_ID,
            backup_path,
            caption="📦 html_backup.zip",
            parse_mode="HTML",
        )
        if not backup_msg:
            return False
        msg_id = getattr(backup_msg, "id", None)
        if msg_id and _run_telethon and _telethon_client:
            for chunk in _split_text(_backup_caption(user, reason)):
                try:
                    _run_telethon(
                        _telethon_client.send_message(
                            entity=HTML_BACKUP_CHAT_ID,
                            message=chunk,
                            parse_mode="HTML",
                            link_preview=False,
                            reply_to=msg_id,
                        )
                    )
                except Exception:
                    log.exception("Failed to send HTML backup log")
        return True
    except Exception:
        log.exception("HTML backup failed")
        return False


# ---------------------------------------------------------------------------
# Admin helpers / keyboards
# ---------------------------------------------------------------------------


def _is_admin(user_id):
    if int(user_id) in ADMIN_IDS:
        return True
    if _get_userdata is not None:
        try:
            userdata = _get_userdata()
            return int(user_id) in {int(x) for x in userdata.get("sub_admins", [])}
        except Exception:
            pass
    return False


def _html_base_url():
    return HTML_WEBHOOK_URL + "/html"


def _public_url(zip_id):
    return f"{_html_base_url()}/{int(zip_id)}/"


def _sorted_items():
    db = _load_db()
    items = []
    for key, item in db.get("zips", {}).items():
        try:
            zid = int(key)
        except Exception:
            continue
        item = dict(item)
        item["id"] = zid
        items.append(item)
    items.sort(key=lambda x: x["id"])
    return items


def _manage_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 زیپ‌های موجود", callback_data="html_list_0")],
        [InlineKeyboardButton("➕ وارد کردن زیپ جدید", callback_data="html_import")],
        [InlineKeyboardButton("🗑 حذف زیپ", callback_data="html_delete_0")],
        [InlineKeyboardButton("🧹 حذف همه زیپ‌ها", callback_data="html_delete_all_confirm")],
        [InlineKeyboardButton("📤 دریافت بکاپ", callback_data="html_get_backup")],
        [InlineKeyboardButton("📥 وارد کردن بکاپ", callback_data="html_import_backup")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="html_back_admin")],
    ])


def _paged_zip_keyboard(action, page):
    items = _sorted_items()
    start = page * HTML_PAGE_SIZE
    page_items = items[start:start + HTML_PAGE_SIZE]
    keyboard = []
    for item in page_items:
        label = f"#{item['id']} — {item.get('name', 'بدون نام')}"
        if action == "list":
            cb = f"html_show_{item['id']}_{page}"
        else:
            cb = f"html_delete_pick_{item['id']}_{page}"
        keyboard.append([InlineKeyboardButton(label[:60], callback_data=cb)])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"html_{action}_{page - 1}"))
    if start + HTML_PAGE_SIZE < len(items):
        nav.append(InlineKeyboardButton("بعدی ➡️", callback_data=f"html_{action}_{page + 1}"))
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="html_manage")])
    return InlineKeyboardMarkup(keyboard)


def _backup_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 بازگشت", callback_data="html_manage")],
        [InlineKeyboardButton("❌ لغو عملیات", callback_data="html_cancel")],
    ])


# ---------------------------------------------------------------------------
# /html upload flow
# ---------------------------------------------------------------------------


async def html_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return ConversationHandler.END
    context.user_data.pop("html_pending_zip", None)
    await update.message.reply_text(
        "📦 زیپ HTML را بفرستید.\n\nبرای لغو، /cancel را بزنید.",
        reply_markup=ReplyKeyboardMarkup([["❌ لغو عملیات"]], resize_keyboard=True),
    )
    return HTML_WAIT_ZIP


async def html_receive_zip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return ConversationHandler.END

    if update.message.text and update.message.text.strip().lower() in {"/cancel", "❌ لغو عملیات"}:
        return await html_cancel(update, context)

    document = update.message.document
    if not document:
        await update.message.reply_text("❌ لطفاً فایل ZIP را به‌صورت فایل (Document) ارسال کنید.")
        return HTML_WAIT_ZIP

    file_name = (document.file_name or "").lower()
    if not file_name.endswith(".zip"):
        await update.message.reply_text("❌ فقط فایل ZIP قابل قبول است. دوباره ارسال کنید.")
        return HTML_WAIT_ZIP
    if document.file_size and document.file_size > HTML_MAX_ZIP_BYTES:
        await update.message.reply_text("❌ حجم ZIP بیشتر از حد مجاز است.")
        return HTML_WAIT_ZIP

    tmp_dir = Path(tempfile.mkdtemp(prefix="html_upload_"))
    tmp_zip = tmp_dir / _safe_filename(document.file_name or "upload.zip")
    try:
        tg_file = await document.get_file()
        await tg_file.download_to_drive(custom_path=str(tmp_zip))
        # Validate before asking for the name.
        _validate_and_prepare_zip(tmp_zip, 0)
        context.user_data["html_pending_zip"] = str(tmp_zip)
        context.user_data["html_pending_zip_tmp"] = str(tmp_dir)
        await update.message.reply_text(
            "✅ زیپ دریافت و بررسی شد.\n\n📚 اسم جزوه را بفرستید.\nبرای لغو، /cancel را بزنید."
        )
        return HTML_WAIT_NAME
    except Exception as e:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        await update.message.reply_text(f"❌ زیپ قابل استفاده نیست:\n{e}")
        return HTML_WAIT_ZIP


async def html_receive_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return ConversationHandler.END
    name = (update.message.text or "").strip()
    if name.lower() == "/cancel" or name == "❌ لغو عملیات":
        return await html_cancel(update, context)
    if not name:
        await update.message.reply_text("❌ اسم جزوه نمی‌تواند خالی باشد.")
        return HTML_WAIT_NAME
    if len(name) > 120:
        await update.message.reply_text("❌ اسم جزوه حداکثر ۱۲۰ کاراکتر باشد.")
        return HTML_WAIT_NAME

    pending = context.user_data.get("html_pending_zip")
    tmp_dir = context.user_data.get("html_pending_zip_tmp")
    if not pending or not os.path.exists(pending):
        await update.message.reply_text("❌ فایل موقت پیدا نشد. دوباره /html را اجرا کنید.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    db = _load_db()
    zip_id = int(db.get("next_id", 1))
    while str(zip_id) in db.get("zips", {}):
        zip_id += 1
    final_zip = _zip_path(zip_id)

    try:
        # Copy first, validate the final file again, then save DB.
        shutil.copy2(pending, final_zip)
        index_dir = _validate_and_prepare_zip(final_zip, zip_id)
        db.setdefault("zips", {})[str(zip_id)] = {
            "id": zip_id,
            "name": name,
            "filename": _safe_filename(os.path.basename(pending)),
            "index_dir": index_dir,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        db["next_id"] = zip_id + 1
        _save_db(db)
        _extract_for_serving(zip_id)

        reason = f"افزودن زیپ جدید: <b>{_escape(name)}</b>\n🔗 لینک: {_public_url(zip_id)}"
        backup_ok = _backup_and_log(update.effective_user, reason)

        await update.message.reply_text(
            "✅ جزوه با موفقیت ثبت شد.\n\n"
            f"📚 نام: <b>{_escape(name)}</b>\n"
            f"🔢 شناسه: <code>{zip_id}</code>\n"
            f"🔗 لینک: {_public_url(zip_id)}\n\n"
            + ("☁️ بکاپ هم به‌روزرسانی شد." if backup_ok else "⚠️ بکاپ در تلگرام ارسال نشد؛ تنظیمات HTML_BACKUP_CHAT_ID را بررسی کنید."),
            parse_mode="HTML",
            disable_web_page_preview=False,
            reply_markup=ReplyKeyboardRemove(),
        )
    except Exception as e:
        final_zip.unlink(missing_ok=True)
        await update.message.reply_text(f"❌ ثبت جزوه انجام نشد:\n{e}", reply_markup=ReplyKeyboardRemove())
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        context.user_data.pop("html_pending_zip", None)
        context.user_data.pop("html_pending_zip_tmp", None)

    return ConversationHandler.END


async def html_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tmp_dir = context.user_data.pop("html_pending_zip_tmp", None)
    context.user_data.pop("html_pending_zip", None)
    if tmp_dir:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    await update.message.reply_text("❌ عملیات لغو شد.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Admin panel callbacks
# ---------------------------------------------------------------------------


def _escape(text):
    import html
    return html.escape(str(text), quote=True)


async def html_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not _is_admin(query.from_user.id):
        await query.answer("⛔️ دسترسی ادمین ندارید.", show_alert=True)
        return

    data = query.data or ""
    try:
        if data == "html_manage":
            context.user_data["admin_panel"] = "html"
            await query.message.edit_text("🧩 مدیریت HTML:", reply_markup=_manage_keyboard())
            return

        if data == "html_back_admin":
            context.user_data["admin_panel"] = "access"
            # main's admin panel can be reopened with admin_access.
            await query.message.edit_text("🔐 برای برگشت به پنل اصلی، دوباره پنل مدیریت را باز کنید.", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 پنل مدیریت", callback_data="admin_access")]
            ]))
            return

        if data == "html_cancel":
            context.user_data.pop("html_pending_zip", None)
            context.user_data.pop("html_pending_zip_tmp", None)
            await query.message.edit_text("❌ عملیات لغو شد.", reply_markup=_manage_keyboard())
            return

        if data == "html_import":
            await query.message.reply_text("📦 برای افزودن زیپ جدید /html را بزنید.")
            return

        if data.startswith("html_list_"):
            page = int(data.rsplit("_", 1)[1])
            items = _sorted_items()
            if not items:
                await query.message.edit_text("📦 هنوز هیچ زیپی ثبت نشده است.", reply_markup=_manage_keyboard())
                return
            await query.message.edit_text(f"📦 زیپ‌های موجود — صفحه {page + 1}", reply_markup=_paged_zip_keyboard("list", page))
            return

        if data.startswith("html_show_"):
            parts = data.split("_")
            zip_id, page = int(parts[2]), int(parts[3])
            item = _load_db().get("zips", {}).get(str(zip_id))
            if not item:
                await query.answer("این زیپ دیگر وجود ندارد.", show_alert=True)
                return
            text = (
                f"📦 <b>{_escape(item.get('name', 'بدون نام'))}</b>\n"
                f"🔢 شناسه: <code>{zip_id}</code>\n"
                f"🔗 {_public_url(zip_id)}\n"
                f"🕒 {item.get('created_at', '-') }"
            )
            await query.message.edit_text(text, parse_mode="HTML", disable_web_page_preview=True, reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔗 ارسال لینک", callback_data=f"html_send_{zip_id}")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data=f"html_list_{page}")],
            ]))
            return

        if data.startswith("html_send_"):
            zip_id = int(data.rsplit("_", 1)[1])
            item = _load_db().get("zips", {}).get(str(zip_id))
            if not item:
                await query.answer("زیپ پیدا نشد.", show_alert=True)
                return
            await query.message.reply_text(
                f"📚 <b>{_escape(item.get('name', 'بدون نام'))}</b>\n🔗 {_public_url(zip_id)}",
                parse_mode="HTML",
                disable_web_page_preview=False,
            )
            return

        if data.startswith("html_delete_") and data != "html_delete_all_confirm":
            if data.startswith("html_delete_0"):
                page = int(data.rsplit("_", 1)[1])
                items = _sorted_items()
                if not items:
                    await query.message.edit_text("🗑 زیپی برای حذف وجود ندارد.", reply_markup=_manage_keyboard())
                    return
                await query.message.edit_text(f"🗑 حذف زیپ — صفحه {page + 1}", reply_markup=_paged_zip_keyboard("delete", page))
                return

        if data.startswith("html_delete_pick_"):
            parts = data.split("_")
            zip_id, page = int(parts[3]), int(parts[4])
            item = _load_db().get("zips", {}).get(str(zip_id))
            if not item:
                await query.answer("زیپ پیدا نشد.", show_alert=True)
                return
            await query.message.edit_text(
                f"⚠️ حذف شود؟\n\n📚 <b>{_escape(item.get('name', 'بدون نام'))}</b>\n🔗 {_public_url(zip_id)}",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ بله، حذف کن", callback_data=f"html_delete_yes_{zip_id}_{page}")],
                    [InlineKeyboardButton("❌ لغو", callback_data=f"html_delete_{page}")],
                ]),
            )
            return

        if data.startswith("html_delete_yes_"):
            parts = data.split("_")
            zip_id, page = int(parts[3]), int(parts[4])
            db = _load_db()
            item = db.get("zips", {}).get(str(zip_id))
            if not item:
                await query.answer("زیپ قبلاً حذف شده است.", show_alert=True)
                return
            name = item.get("name", "بدون نام")
            del db["zips"][str(zip_id)]
            _save_db(db)
            _zip_path(zip_id).unlink(missing_ok=True)
            rendered = HTML_ROOT / "rendered" / str(zip_id)
            shutil.rmtree(rendered, ignore_errors=True)
            backup_ok = _backup_and_log(query.from_user, f"حذف زیپ: <b>{_escape(name)}</b>\n🔗 لینک قبلی: {_public_url(zip_id)}")
            await query.message.edit_text(
                f"✅ زیپ «{_escape(name)}» حذف شد.\n" + ("☁️ بکاپ به‌روزرسانی شد." if backup_ok else "⚠️ بکاپ ارسال نشد."),
                parse_mode="HTML",
                reply_markup=_paged_zip_keyboard("delete", page) if _sorted_items() else _manage_keyboard(),
            )
            return

        if data == "html_delete_all_confirm":
            items = _sorted_items()
            if not items:
                await query.message.edit_text("🧹 هیچ زیپی وجود ندارد.", reply_markup=_manage_keyboard())
                return
            await query.message.edit_text(
                f"⚠️ این عملیات همه {len(items)} زیپ را حذف می‌کند. مطمئن هستید؟",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🧹 بله، همه را حذف کن", callback_data="html_delete_all_yes")],
                    [InlineKeyboardButton("❌ لغو", callback_data="html_manage")],
                ]),
            )
            return

        if data == "html_delete_all_yes":
            items = _sorted_items()
            names = [str(x.get("name", "بدون نام")) for x in items]
            db = _default_db()
            _save_db(db)
            for p in HTML_ROOT.glob("*.zip"):
                p.unlink(missing_ok=True)
            shutil.rmtree(HTML_ROOT / "rendered", ignore_errors=True)
            reason = "حذف همه زیپ‌ها:\n" + "\n".join(f"• {_escape(n)}" for n in names)
            backup_ok = _backup_and_log(query.from_user, reason)
            await query.message.edit_text(
                f"✅ همه {len(items)} زیپ حذف شدند.\n" + ("☁️ بکاپ به‌روزرسانی شد." if backup_ok else "⚠️ بکاپ ارسال نشد."),
                parse_mode="HTML",
                reply_markup=_manage_keyboard(),
            )
            return

        if data == "html_get_backup":
            if not HTML_BACKUP_CHAT_ID:
                await query.answer("HTML_BACKUP_CHAT_ID تنظیم نشده است.", show_alert=True)
                return
            _make_backup_archive()
            await query.message.reply_document(
                document=HTML_BACKUP_FILE,
                filename="html_backup.zip",
                caption="📦 بکاپ کامل HTML",
            )
            return

        if data == "html_import_backup":
            context.user_data["html_waiting_backup"] = True
            await query.message.reply_text(
                "📥 فایل html_backup.zip را ارسال کنید.\nبرای لغو /cancel را بزنید.",
                reply_markup=ReplyKeyboardMarkup([["❌ لغو عملیات"]], resize_keyboard=True),
            )
            return

        if data.startswith("html_list_") or data.startswith("html_delete_"):
            return
    except Exception:
        log.exception("HTML admin callback failed: %s", data)
        await query.message.reply_text("❌ اجرای عملیات HTML با خطا مواجه شد.")


async def html_receive_backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("html_waiting_backup"):
        return
    if not _is_admin(update.effective_user.id):
        return
    if update.message.text and update.message.text.strip().lower() in {"/cancel", "❌ لغو عملیات"}:
        context.user_data.pop("html_waiting_backup", None)
        await update.message.reply_text("❌ عملیات لغو شد.", reply_markup=ReplyKeyboardRemove())
        return

    doc = update.message.document
    if not doc:
        await update.message.reply_text("❌ لطفاً فایل html_backup.zip را ارسال کنید.")
        return
    if not (doc.file_name or "").lower().endswith(".zip"):
        await update.message.reply_text("❌ فقط ZIP قابل قبول است.")
        return

    temp_dir = Path(tempfile.mkdtemp(prefix="html_backup_upload_"))
    uploaded = temp_dir / "html_backup.zip"
    try:
        tg_file = await doc.get_file()
        await tg_file.download_to_drive(custom_path=str(uploaded))
        if not _restore_backup_archive(str(uploaded)):
            raise ValueError("ساختار بکاپ معتبر نیست.")
        # Keep exact latest imported backup as local backup source.
        shutil.copy2(uploaded, HTML_BACKUP_FILE)
        context.user_data.pop("html_waiting_backup", None)
        backup_ok = _backup_and_log(update.effective_user, "جایگزینی فایل HTML BACKUP")
        await update.message.reply_text(
            "✅ بکاپ HTML با موفقیت جایگزین شد.\n" + ("☁️ نسخه جدید در گروه بکاپ هم ثبت شد." if backup_ok else "⚠️ ارسال نسخه جدید به گروه بکاپ ناموفق بود."),
            reply_markup=ReplyKeyboardRemove(),
        )
    except Exception as e:
        await update.message.reply_text(f"❌ وارد کردن بکاپ ناموفق بود:\n{e}")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

# ---------------------------------------------------------------------------
# Smart asset resolver / HTML-CSS URL repair
# ---------------------------------------------------------------------------

ASSET_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".ico", ".avif",
    ".css", ".js", ".mjs", ".json",
    ".woff", ".woff2", ".ttf", ".otf",
    ".mp3", ".wav", ".ogg", ".mp4", ".webm",
    ".pdf", ".txt",
}


def _is_inside(child: Path, parent: Path) -> bool:
    """
    بررسی می‌کند child واقعاً داخل parent باشد.
    برای جلوگیری از path traversal استفاده می‌شود.
    """
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _clean_requested_path(value: str) -> str:
    """
    مسیر URL را تمیز می‌کند اما ../ را حذف نمی‌کند؛
    چون ممکن است فایل HTML واقعاً از ../images/a.png استفاده کرده باشد.

    مثال:
      images\\a.jpg -> images/a.jpg
      ./images/a.jpg -> images/a.jpg
      /images/a.jpg -> images/a.jpg
    """
    value = unquote(str(value or ""))
    value = value.replace("\\", "/").strip()

    # مواردی که اصلاً فایل محلی نیستند
    if (
        value.startswith("http://")
        or value.startswith("https://")
        or value.startswith("data:")
        or value.startswith("blob:")
        or value.startswith("file:")
        or value.startswith("mailto:")
        or value.startswith("tel:")
        or value.startswith("#")
    ):
        return ""

    value = value.split("?", 1)[0].split("#", 1)[0]
    value = value.lstrip("/")

    while value.startswith("./"):
        value = value[2:]

    return value


def _case_insensitive_path(root: Path, relative_path: str):
    """
    فایل را با نادیده‌گرفتن تفاوت حروف بزرگ و کوچک پیدا می‌کند.

    مثلاً اگر HTML نوشته باشد:
        images/Test.JPG

    ولی فایل واقعی باشد:
        Images/test.jpg

    باز هم آن را پیدا می‌کند.
    """
    relative_path = _clean_requested_path(relative_path)

    if not relative_path:
        return None

    current = root

    # PurePosixPath برای ZIP و URL مناسب‌تر از Path ویندوز است.
    for part in PurePosixPath(relative_path).parts:
        if part in ("", "."):
            continue

        if part == "..":
            current = current.parent
            if not _is_inside(current, root):
                return None
            continue

        if not current.exists() or not current.is_dir():
            return None

        # اول تطابق دقیق
        exact = current / part
        if exact.exists():
            current = exact
            continue

        # سپس تطابق بدون حساسیت به حروف
        part_lower = part.casefold()
        matched = None

        try:
            for child in current.iterdir():
                if child.name.casefold() == part_lower:
                    matched = child
                    break
        except OSError:
            return None

        if matched is None:
            return None

        current = matched

    if current.exists() and current.is_file() and _is_inside(current, root):
        return current

    return None


def _find_asset_by_filename(render_root: Path, requested: str):
    """
    آخرین fallback:

    اگر HTML فقط نوشته باشد:
        <img src="photo.jpg">

    ولی فایل واقعی در این مسیر باشد:
        assets/images/photo.jpg

    این تابع براساس نام فایل جست‌وجو می‌کند.

    نکته:
    اگر چند فایل هم‌نام وجود داشته باشند، هیچ‌کدام را انتخاب نمی‌کنیم
    تا تصویر اشتباه نمایش داده نشود.
    """
    requested = _clean_requested_path(requested)

    if not requested:
        return None

    filename = PurePosixPath(requested).name
    if not filename:
        return None

    target = filename.casefold()
    matches = []

    try:
        for candidate in render_root.rglob("*"):
            if (
                candidate.is_file()
                and candidate.name.casefold() == target
                and _is_inside(candidate, render_root)
            ):
                matches.append(candidate)

                # اگر بیش از یک فایل هم‌نام باشد، fallback خطرناک است.
                if len(matches) > 1:
                    return None
    except OSError:
        return None

    return matches[0] if len(matches) == 1 else None


def _resolve_asset_file(render_root: Path, html_root: Path, requested: str):
    """
    Resolver مقاوم برای فایل‌های HTML/CSS/JS/تصویر.

    ترتیب تلاش:
    1) مسیر نسبی نسبت به محل index.html
    2) مسیر نسبی نسبت به ریشه ZIP
    3) مسیر بدون حساسیت به uppercase/lowercase
    4) جست‌وجوی یکتا براساس نام فایل در کل ZIP
    """
    requested = _clean_requested_path(requested)

    if not requested:
        return None

    candidates = []

    # حالت اصلی:
    # index.html کنار images/ باشد.
    candidates.append(html_root / requested)

    # اگر ZIP ساختار نامنظم دارد و asset از ریشه ZIP صدا زده شده باشد.
    candidates.append(render_root / requested)

    # اگر درخواست با ../ باشد، حالت اصلی اهمیت بیشتری دارد.
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue

        if _is_inside(resolved, render_root) and resolved.exists() and resolved.is_file():
            return resolved

    # حالت case-insensitive نسبت به index directory
    found = _case_insensitive_path(html_root, requested)
    if found:
        return found

    # حالت case-insensitive نسبت به ریشه ZIP
    found = _case_insensitive_path(render_root, requested)
    if found:
        return found

    # آخرین تلاش: فقط اگر نام فایل در کل ZIP یکتا باشد.
    return _find_asset_by_filename(render_root, requested)


def _make_public_asset_url(zip_id: int, url_value: str) -> str:
    """
    مسیرهای absolute اشتباه را به مسیر صحیح جزوه تبدیل می‌کند.

    /images/a.jpg
    -> /html/1/images/a.jpg

    images/a.jpg
    -> بدون تغییر؛ چون relative است و مرورگر خودش درست resolve می‌کند.
    """
    value = str(url_value or "").strip()

    if not value:
        return value

    lower = value.lower()

    # URL خارجی یا data URI را دست‌کاری نکن.
    if lower.startswith((
        "http://", "https://", "//",
        "data:", "blob:", "mailto:", "tel:", "#"
    )):
        return value

    # فقط مسیر absolute دامنه مشکل‌ساز است.
    if value.startswith("/"):
        return f"/html/{int(zip_id)}/{value.lstrip('/')}"

    return value


def _rewrite_html_for_zip(html_text: str, zip_id: int) -> str:
    """
    HTML را هنگام ارسال اصلاح می‌کند تا:
    - <base href="/"> خراب‌کاری نکند.
    - مسیرهای absolute مانند /images/a.jpg به /html/<id>/images/a.jpg تبدیل شوند.
    - مسیرهای src, href, poster, data-src و srcset تا حد ممکن درست شوند.
    """

    public_base = f"/html/{int(zip_id)}/"

    # هر base موجود را حذف می‌کنیم؛ چون اغلب باعث خراب شدن assetها می‌شود.
    html_text = re.sub(
        r"<base\b[^>]*>",
        "",
        html_text,
        flags=re.IGNORECASE,
    )

    # base صحیح را بعد از <head> تزریق می‌کنیم.
    base_tag = f'<base href="{public_base}">'
    if re.search(r"<head\b[^>]*>", html_text, flags=re.IGNORECASE):
        html_text = re.sub(
            r"(<head\b[^>]*>)",
            r"\1" + base_tag,
            html_text,
            count=1,
            flags=re.IGNORECASE,
        )
    else:
        html_text = base_tag + html_text

    # src / href / poster / data-src / data-background
    attribute_pattern = re.compile(
        r'(?P<prefix>\b(?:src|href|poster|data-src|data-background)\s*=\s*)(?P<quote>["\'])(?P<url>.*?)(?P=quote)',
        flags=re.IGNORECASE,
    )

    def replace_attribute(match):
        fixed = _make_public_asset_url(zip_id, match.group("url"))
        return f'{match.group("prefix")}{match.group("quote")}{fixed}{match.group("quote")}'

    html_text = attribute_pattern.sub(replace_attribute, html_text)

    # srcset نمونه:
    # srcset="/images/a.jpg 1x, /images/b.jpg 2x"
    srcset_pattern = re.compile(
        r'(?P<prefix>\bsrcset\s*=\s*)(?P<quote>["\'])(?P<value>.*?)(?P=quote)',
        flags=re.IGNORECASE,
    )

    def replace_srcset(match):
        pieces = []
        for item in match.group("value").split(","):
            item = item.strip()
            if not item:
                continue

            parts = item.split()
            url = parts[0]
            descriptor = " ".join(parts[1:])

            fixed_url = _make_public_asset_url(zip_id, url)
            pieces.append(f"{fixed_url} {descriptor}".strip())

        return f'{match.group("prefix")}{match.group("quote")}{", ".join(pieces)}{match.group("quote")}'

    html_text = srcset_pattern.sub(replace_srcset, html_text)

    # CSS inline:
    # style="background-image:url('/images/bg.jpg')"
    html_text = _rewrite_css_urls(html_text, zip_id)

    return html_text


def _rewrite_css_urls(css_text: str, zip_id: int) -> str:
    """
    مسیرهای absolute داخل CSS را اصلاح می‌کند.

    url('/images/bg.png')
    -> url('/html/1/images/bg.png')
    """
    pattern = re.compile(
        r'url\(\s*(?P<quote>["\']?)(?P<url>.*?)(?P=quote)\s*\)',
        flags=re.IGNORECASE,
    )

    def replace_url(match):
        raw_url = match.group("url").strip()
        fixed_url = _make_public_asset_url(zip_id, raw_url)
        quote = match.group("quote") or ""
        return f"url({quote}{fixed_url}{quote})"

    return pattern.sub(replace_url, css_text)


def _content_type_for_file(path: Path) -> str:
    """
    MIME type مناسب؛ مخصوصاً برای عکس، فونت، CSS و JS.
    """
    suffix = path.suffix.lower()

    mime_types = {
        ".html": "text/html; charset=utf-8",
        ".htm": "text/html; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
        ".mjs": "application/javascript; charset=utf-8",
        ".json": "application/json; charset=utf-8",

        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
        ".ico": "image/x-icon",
        ".avif": "image/avif",

        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".ogg": "audio/ogg",
        ".mp4": "video/mp4",
        ".webm": "video/webm",

        ".woff": "font/woff",
        ".woff2": "font/woff2",
        ".ttf": "font/ttf",
        ".otf": "font/otf",
        ".pdf": "application/pdf",
    }

    content_type = mime_types.get(suffix)
    if content_type:
        return content_type

    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"

# ---------------------------------------------------------------------------
# HTTP serving: /html/<id> and /html/<id>/...
# ---------------------------------------------------------------------------

async def html_http_handler(request: web.Request):
    """
    سرو کردن HTML و assetهای آن با resolver مقاوم.

    پشتیبانی از:
    - مسیرهای صحیح relative
    - مسیرهای اشتباه نسبت به root ZIP
    - uppercase/lowercase متفاوت
    - فایل در پوشه‌ای متفاوت ولی با نام یکتا
    - مسیرهای absolute داخل HTML / CSS
    """

    try:
        zip_id = int(request.match_info["zip_id"])
    except (TypeError, ValueError):
        raise web.HTTPNotFound(text="Not found")

    requested = request.match_info.get("path", "") or ""

    # مهم:
    # /html/1 باید به /html/1/ برود تا لینک‌های relative صحیح محاسبه شوند.
    if not requested and not request.path.endswith("/"):
        raise web.HTTPFound(location=f"/html/{zip_id}/")

    db = _load_db()
    item = db.get("zips", {}).get(str(zip_id))

    if not item:
        raise web.HTTPNotFound(text="HTML not found")

    try:
        render_root = HTML_ROOT / "rendered" / str(zip_id)

        # بعد از restart Render، در صورت نبود فایل extracted، دوباره extract می‌کنیم.
        if not render_root.exists():
            _extract_for_serving(zip_id)

        if not render_root.exists():
            raise web.HTTPNotFound(text="HTML files not found")

        render_root = render_root.resolve()

        # پوشه‌ای که index.html در آن قرار دارد.
        index_dir = (item.get("index_dir", "") or "").replace("\\", "/").strip("/")

        if index_dir in ("", "."):
            html_root = render_root
        else:
            html_root = (render_root / index_dir).resolve()

        if not _is_inside(html_root, render_root) and html_root != render_root:
            raise web.HTTPForbidden(text="Forbidden")

        # ---------------------------------------------------------
        # صفحه اصلی
        # ---------------------------------------------------------
        if not requested:
            index_file = html_root / "index.html"

            if not index_file.exists():
                index_file = html_root / "index.htm"

            if not index_file.exists():
                # اگر index_dir در DB قدیمی/غلط باشد، دوباره پیدا کن.
                index_file = _find_index_file(render_root)
                html_root = index_file.parent.resolve()

            # HTML را به response عادی تبدیل می‌کنیم تا بتوانیم base و URLها را اصلاح کنیم.
            html_text = index_file.read_text(encoding="utf-8", errors="replace")
            html_text = _rewrite_html_for_zip(html_text, zip_id)

            return web.Response(
                text=html_text,
                content_type="text/html",
                charset="utf-8",
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                },
            )

        # ---------------------------------------------------------
        # فایل‌های دیگر: image, css, js, font, video, pdf, ...
        # ---------------------------------------------------------
        file_path = _resolve_asset_file(
            render_root=render_root,
            html_root=html_root,
            requested=requested,
        )

        if file_path is None:
            log.warning(
                "HTML asset not found | zip_id=%s | requested=%r | html_root=%s",
                zip_id,
                requested,
                html_root,
            )
            raise web.HTTPNotFound(text="File not found")

        suffix = file_path.suffix.lower()

        # CSS را هم rewrite می‌کنیم تا url('/images/a.jpg') درست شود.
        if suffix == ".css":
            css_text = file_path.read_text(encoding="utf-8", errors="replace")
            css_text = _rewrite_css_urls(css_text, zip_id)

            return web.Response(
                text=css_text,
                content_type="text/css",
                charset="utf-8",
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                },
            )

        # اگر HTML دیگری، iframe، یا صفحه داخلی وجود داشت، آن را نیز اصلاح کن.
        if suffix in {".html", ".htm"}:
            html_text = file_path.read_text(encoding="utf-8", errors="replace")
            html_text = _rewrite_html_for_zip(html_text, zip_id)

            return web.Response(
                text=html_text,
                content_type="text/html",
                charset="utf-8",
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                },
            )

        # تصویر، فونت، ویدئو، فایل‌های صوتی و ...
        return web.FileResponse(
            path=file_path,
            headers={
                "Content-Type": _content_type_for_file(file_path),
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )

    except web.HTTPException:
        raise

    except Exception:
        log.exception("HTML render failed for zip_id=%s", zip_id)
        raise web.HTTPInternalServerError(text="HTML render error")


# ---------------------------------------------------------------------------
# Integration helpers
# ---------------------------------------------------------------------------


def get_html_admin_keyboard():
    """Keyboard button to add to main's admin access panel."""
    return InlineKeyboardButton("🧩 مدیریت HTML", callback_data="html_manage")


def build_html_conversation_handler():
    return ConversationHandler(
        entry_points=[CommandHandler("html", html_command)],
        states={
            HTML_WAIT_ZIP: [
                CommandHandler("cancel", html_cancel),
                MessageHandler(filters.Document.ALL, html_receive_zip),
                MessageHandler(filters.TEXT & ~filters.COMMAND, html_receive_zip),
            ],
            HTML_WAIT_NAME: [
                CommandHandler("cancel", html_cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, html_receive_name),
            ],
        },
        fallbacks=[CommandHandler("cancel", html_cancel)],
        allow_reentry=True,
        name="html_upload_conversation",
        persistent=False,
    )


def build_html_callback_handler():
    return CallbackQueryHandler(html_admin_callback, pattern=r"^html_")


def build_html_backup_message_handler():
    return MessageHandler(
        (filters.Document.ALL | (filters.TEXT & ~filters.COMMAND)),
        html_receive_backup,
    )


def html_state_exists():
    db = _load_db()
    return bool(db.get("zips"))
