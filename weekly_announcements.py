import json
import os
import re
import uuid
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

WEEK_FILE = "/tmp/week.json"

WEEK_ROOT = "week_root"
WEEK_WAITING_GROUP_NAME = "week_waiting_group_name"
WEEK_WAITING_ADD_TIME = "week_waiting_add_time"
WEEK_WAITING_DELETE_TIME = "week_waiting_delete_time"
WEEK_WAITING_DELETE_GROUP = "week_waiting_delete_group"

PERSIAN_DAY_ALIASES = {
    "شنبه": "شنبه",
    "یکشنبه": "یک شنبه",
    "یک‌شنبه": "یک شنبه",
    "یک شنبه": "یک شنبه",
    "دوشنبه": "دوشنبه",
    "دو شنبه": "دوشنبه",
    "سهشنبه": "سه شنبه",
    "سه‌شنبه": "سه شنبه",
    "سه شنبه": "سه شنبه",
    "چهارشنبه": "چهارشنبه",
    "چهار شنبه": "چهارشنبه",
    "پنجشنبه": "پنج شنبه",
    "پنج‌شنبه": "پنج شنبه",
    "پنج شنبه": "پنج شنبه",
    "جمعه": "جمعه",
}

ALL_DAYS = [
    "شنبه",
    "یک شنبه",
    "دوشنبه",
    "سه شنبه",
    "چهارشنبه",
    "پنج شنبه",
    "جمعه",
]


def load_week_data():
    if not os.path.exists(WEEK_FILE):
        initial_data = {"groups": {}}
        save_week_data(initial_data)
        return initial_data

    try:
        with open(WEEK_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        data = {"groups": {}}
        save_week_data(data)
        return data


def save_week_data(data):
    with open(WEEK_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def normalize_schedule_text(text: str) -> str:
    text = text.replace("ي", "ی").replace("ك", "ک")
    text = text.replace("…", "...")
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def normalize_day_name(day_text: str):
    day_text = normalize_schedule_text(day_text)
    return PERSIAN_DAY_ALIASES.get(day_text)


def parse_days_part(days_text: str):
    days_text = normalize_schedule_text(days_text)
    days_text = days_text.replace("/", " و ")
    parts = [p.strip() for p in re.split(r"\s+و\s+", days_text) if p.strip()]

    result = []
    for part in parts:
        normalized = normalize_day_name(part)
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def parse_week_part(week_text: str):
    week_text = normalize_schedule_text(week_text)

    if week_text == "این هفته":
        return {
            "mode": "single",
            "week_offset": 0,
            "label": "این هفته"
        }

    if week_text == "این هفته و هفته های بعد" or week_text == "این هفته و هفته‌های بعد":
        return {
            "mode": "recurring",
            "week_offset": 0,
            "label": "این هفته و هفته های بعد"
        }

    match = re.fullmatch(r"(\d+)\s+هفته\s+بعد", week_text)
    if match:
        offset = int(match.group(1))
        return {
            "mode": "single",
            "week_offset": offset,
            "label": f"{offset} هفته بعد"
        }

    return None


def parse_time_part(time_text: str):
    time_text = normalize_schedule_text(time_text)
    match = re.search(r"ساعت\s+(\d{1,2}:\d{2})\s+تا\s+(\d{1,2}:\d{2})", time_text)
    if not match:
        return None

    start_time = match.group(1)
    end_time = match.group(2)

    return {
        "start_time": start_time,
        "end_time": end_time
    }


def parse_schedule_line(line: str):
    raw_line = normalize_schedule_text(line)
    if not raw_line:
        return None

    if "ساعت" not in raw_line:
        return None

    before_time, time_part = raw_line.rsplit("ساعت", 1)
    time_info = parse_time_part("ساعت " + time_part)
    if not time_info:
        return None

    if "..." in before_time:
        week_part_text, days_part_text = before_time.split("...", 1)
    else:
        return None

    week_part_text = normalize_schedule_text(week_part_text)
    days_part_text = normalize_schedule_text(days_part_text)

    week_info = parse_week_part(week_part_text)
    if not week_info:
        return None

    days = parse_days_part(days_part_text)
    if not days:
        return None

    return {
        "id": str(uuid.uuid4()),
        "raw": raw_line,
        "mode": week_info["mode"],
        "week_offset": week_info["week_offset"],
        "week_label": week_info["label"],
        "days": days,
        "start_time": time_info["start_time"],
        "end_time": time_info["end_time"],
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }


def parse_week_schedule_text(text: str):
    lines = [normalize_schedule_text(line) for line in text.splitlines()]
    lines = [line for line in lines if line]

    parsed_items = []
    invalid_lines = []

    for line in lines:
        parsed = parse_schedule_line(line)
        if parsed:
            parsed_items.append(parsed)
        else:
            invalid_lines.append(line)

    return parsed_items, invalid_lines


def build_week_root_keyboard(data):
    keyboard = [
        [
            InlineKeyboardButton("➕ افزودن گروه", callback_data="week_add_group"),
            InlineKeyboardButton("➖ حذف گروه", callback_data="week_delete_group_menu"),
        ]
    ]

    for group_id, group_data in data.get("groups", {}).items():
        keyboard.append([
            InlineKeyboardButton(
                f"📁 {group_data.get('title', 'بدون نام')}",
                callback_data=f"week_open_group:{group_id}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton("❌ بستن", callback_data="week_close")
    ])

    return InlineKeyboardMarkup(keyboard)


def build_group_keyboard(group_id):
    keyboard = [
        [
            InlineKeyboardButton("➕ افزودن گروه", callback_data="week_add_group"),
            InlineKeyboardButton("➖ حذف گروه", callback_data=f"week_delete_group:{group_id}"),
        ],
        [
            InlineKeyboardButton("⏰ تعیین تایم", callback_data=f"week_time_menu:{group_id}")
        ],
        [
            InlineKeyboardButton("🔙 بازگشت", callback_data="week_back_root")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def build_time_menu_keyboard(group_id):
    keyboard = [
        [
            InlineKeyboardButton("➕ افزودن تایم جدید", callback_data=f"week_add_time:{group_id}"),
            InlineKeyboardButton("➖ حذف تایم", callback_data=f"week_delete_time_menu:{group_id}"),
        ],
        [
            InlineKeyboardButton("🔙 بازگشت", callback_data=f"week_open_group:{group_id}")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def format_schedule_item(item):
    return item["raw"]


def format_group_schedules(group_data):
    schedules = group_data.get("schedules", [])
    if not schedules:
        return "هنوز هیچ تایمی برای این گروه ثبت نشده."

    lines = []
    for idx, item in enumerate(schedules, start=1):
        lines.append(f"{idx}. {format_schedule_item(item)}")
    return "\n".join(lines)


async def set_week_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_week_data()
    text = "📅 پنل اعلان هفتگی\n\nیکی از گزینه‌ها را انتخاب کنید."
    await update.message.reply_text(
        text,
        reply_markup=build_week_root_keyboard(data)
    )
    context.user_data["week_state"] = WEEK_ROOT
    return WEEK_ROOT


async def week_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = load_week_data()
    callback = query.data or ""

    if callback == "week_close":
        await query.edit_message_text("✅ پنل اعلان هفتگی بسته شد.")
        context.user_data.pop("week_state", None)
        context.user_data.pop("week_target_group", None)
        return ConversationHandler.END

    if callback == "week_back_root":
        await query.edit_message_text(
            "📅 پنل اعلان هفتگی\n\nیکی از گزینه‌ها را انتخاب کنید.",
            reply_markup=build_week_root_keyboard(data)
        )
        context.user_data["week_state"] = WEEK_ROOT
        context.user_data.pop("week_target_group", None)
        return WEEK_ROOT

    if callback == "week_add_group":
        context.user_data["week_state"] = WEEK_WAITING_GROUP_NAME
        await query.message.reply_text("نام گروه جدید را ارسال کنید.")
        return WEEK_WAITING_GROUP_NAME

    if callback == "week_delete_group_menu":
        groups = data.get("groups", {})
        if not groups:
            await query.answer("هیچ گروهی وجود ندارد.", show_alert=True)
            return WEEK_ROOT

        keyboard = []
        for group_id, group_data in groups.items():
            keyboard.append([
                InlineKeyboardButton(
                    f"🗑 {group_data.get('title', 'بدون نام')}",
                    callback_data=f"week_delete_group:{group_id}"
                )
            ])
        keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="week_back_root")])

        await query.edit_message_text(
            "گروهی را برای حذف انتخاب کنید:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return WEEK_ROOT

    if callback.startswith("week_open_group:"):
        group_id = callback.split(":", 1)[1]
        group_data = data.get("groups", {}).get(group_id)

        if not group_data:
            await query.answer("گروه پیدا نشد.", show_alert=True)
            return WEEK_ROOT

        await query.edit_message_text(
            f"📁 گروه: {group_data.get('title', 'بدون نام')}\n\nیکی از گزینه‌ها را انتخاب کنید.",
            reply_markup=build_group_keyboard(group_id)
        )
        context.user_data["week_target_group"] = group_id
        context.user_data["week_state"] = WEEK_ROOT
        return WEEK_ROOT

    if callback.startswith("week_delete_group:"):
        group_id = callback.split(":", 1)[1]
        groups = data.get("groups", {})
        group_data = groups.get(group_id)

        if not group_data:
            await query.answer("گروه پیدا نشد.", show_alert=True)
            return WEEK_ROOT

        group_title = group_data.get("title", "بدون نام")
        groups.pop(group_id, None)
        save_week_data(data)

        await query.edit_message_text(
            f"✅ گروه «{group_title}» حذف شد.\n\n📅 پنل اعلان هفتگی",
            reply_markup=build_week_root_keyboard(data)
        )
        context.user_data["week_state"] = WEEK_ROOT
        context.user_data.pop("week_target_group", None)
        return WEEK_ROOT

    if callback.startswith("week_time_menu:"):
        group_id = callback.split(":", 1)[1]
        group_data = data.get("groups", {}).get(group_id)

        if not group_data:
            await query.answer("گروه پیدا نشد.", show_alert=True)
            return WEEK_ROOT

        schedules_text = format_group_schedules(group_data)

        await query.edit_message_text(
            f"⏰ تایم‌های گروه «{group_data.get('title', 'بدون نام')}»:\n\n{schedules_text}",
            reply_markup=build_time_menu_keyboard(group_id)
        )
        context.user_data["week_target_group"] = group_id
        return WEEK_ROOT

    if callback.startswith("week_add_time:"):
        group_id = callback.split(":", 1)[1]
        group_data = data.get("groups", {}).get(group_id)

        if not group_data:
            await query.answer("گروه پیدا نشد.", show_alert=True)
            return WEEK_ROOT

        context.user_data["week_target_group"] = group_id
        context.user_data["week_state"] = WEEK_WAITING_ADD_TIME

        await query.message.reply_text(
            "تایم را با فرمت زیر ارسال کنید:\n\n"
            "این هفته ... شنبه ... ساعت 18:00 تا 20:00\n"
            "1 هفته بعد ... یک شنبه ... ساعت 16:00 تا 20:00\n"
            "این هفته و هفته های بعد ... شنبه و یک شنبه و سه شنبه ... ساعت 18:00 تا 20:00\n\n"
            "می‌توانید چند خط هم بفرستید."
        )
        return WEEK_WAITING_ADD_TIME

    if callback.startswith("week_delete_time_menu:"):
        group_id = callback.split(":", 1)[1]
        group_data = data.get("groups", {}).get(group_id)

        if not group_data:
            await query.answer("گروه پیدا نشد.", show_alert=True)
            return WEEK_ROOT

        schedules_text = format_group_schedules(group_data)

        context.user_data["week_target_group"] = group_id
        context.user_data["week_state"] = WEEK_WAITING_DELETE_TIME

        await query.message.reply_text(
            "برنامه‌های فعلی این گروه:\n\n"
            f"{schedules_text}\n\n"
            "برای حذف، یکی از این فرمت‌ها را بفرستید:\n"
            "- متن کامل همان سطر\n"
            "- این هفته\n"
            "- 1 هفته بعد\n"
            "- 2 هفته بعد\n"
            "- شنبه این هفته\n"
            "- همه هفته ها شنبه\n"
            "- همه هفته‌ها شنبه"
        )
        return WEEK_WAITING_DELETE_TIME

    return WEEK_ROOT


async def receive_week_group_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_name = (update.message.text or "").strip()
    if not group_name:
        await update.message.reply_text("❌ نام گروه نمی‌تواند خالی باشد.")
        return WEEK_WAITING_GROUP_NAME

    data = load_week_data()
    group_id = str(uuid.uuid4())

    data.setdefault("groups", {})[group_id] = {
        "title": group_name,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "schedules": []
    }
    save_week_data(data)

    await update.message.reply_text(
        f"✅ گروه «{group_name}» ساخته شد.",
        reply_markup=build_week_root_keyboard(data)
    )
    context.user_data["week_state"] = WEEK_ROOT
    return WEEK_ROOT


async def receive_week_time_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = context.user_data.get("week_target_group")
    if not group_id:
        await update.message.reply_text("❌ گروه مقصد مشخص نیست. دوباره /set_week را بزنید.")
        return ConversationHandler.END

    text = update.message.text or ""
    data = load_week_data()
    group_data = data.get("groups", {}).get(group_id)

    if not group_data:
        await update.message.reply_text("❌ گروه پیدا نشد. دوباره /set_week را بزنید.")
        return ConversationHandler.END

    parsed_items, invalid_lines = parse_week_schedule_text(text)

    if not parsed_items:
        await update.message.reply_text(
            "❌ هیچ خط معتبری تشخیص داده نشد.\n"
            "نمونه صحیح:\n"
            "این هفته ... شنبه ... ساعت 18:00 تا 20:00"
        )
        return WEEK_WAITING_ADD_TIME

    group_data.setdefault("schedules", []).extend(parsed_items)
    save_week_data(data)

    msg = [f"✅ {len(parsed_items)} تایم جدید برای گروه «{group_data.get('title', 'بدون نام')}» ثبت شد."]

    if invalid_lines:
        msg.append("\n⚠️ این خط‌ها نامعتبر بودند و ذخیره نشدند:")
        msg.extend([f"- {line}" for line in invalid_lines])

    msg.append("\nبرنامه‌های فعلی:")
    msg.append(format_group_schedules(group_data))

    await update.message.reply_text("\n".join(msg))
    context.user_data["week_state"] = WEEK_ROOT
    return WEEK_ROOT


def _matches_delete_request(item, line):
    normalized = normalize_schedule_text(line)

    if normalized == normalize_schedule_text(item.get("raw", "")):
        return True

    if normalized in ["این هفته", "1 هفته بعد", "2 هفته بعد", "3 هفته بعد", "4 هفته بعد"]:
        return normalized == item.get("week_label")

    match = re.fullmatch(r"(شنبه|یکشنبه|یک‌شنبه|یک شنبه|دوشنبه|دو شنبه|سهشنبه|سه‌شنبه|سه شنبه|چهارشنبه|چهار شنبه|پنجشنبه|پنج‌شنبه|پنج شنبه|جمعه)\s+(این هفته|\d+\s+هفته\s+بعد)", normalized)
    if match:
        day = normalize_day_name(match.group(1))
        week_label = normalize_schedule_text(match.group(2))
        return day in item.get("days", []) and item.get("week_label") == week_label

    match_all = re.fullmatch(r"(همه هفته ها|همه هفته‌ها)\s+(شنبه|یکشنبه|یک‌شنبه|یک شنبه|دوشنبه|دو شنبه|سهشنبه|سه‌شنبه|سه شنبه|چهارشنبه|چهار شنبه|پنجشنبه|پنج‌شنبه|پنج شنبه|جمعه)", normalized)
    if match_all:
        day = normalize_day_name(match_all.group(2))
        return item.get("mode") == "recurring" and day in item.get("days", [])

    return False


async def receive_week_delete_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = context.user_data.get("week_target_group")
    if not group_id:
        await update.message.reply_text("❌ گروه مقصد مشخص نیست. دوباره /set_week را بزنید.")
        return ConversationHandler.END

    data = load_week_data()
    group_data = data.get("groups", {}).get(group_id)

    if not group_data:
        await update.message.reply_text("❌ گروه پیدا نشد. دوباره /set_week را بزنید.")
        return ConversationHandler.END

    text = update.message.text or ""
    delete_lines = [normalize_schedule_text(line) for line in text.splitlines() if normalize_schedule_text(line)]

    if not delete_lines:
        await update.message.reply_text("❌ چیزی برای حذف ارسال نشده.")
        return WEEK_WAITING_DELETE_TIME

    old_schedules = group_data.get("schedules", [])
    kept = []
    removed = []

    for item in old_schedules:
        should_remove = any(_matches_delete_request(item, line) for line in delete_lines)
        if should_remove:
            removed.append(item)
        else:
            kept.append(item)

    if not removed:
        await update.message.reply_text("❌ هیچ موردی برای حذف پیدا نشد.")
        return WEEK_WAITING_DELETE_TIME

    group_data["schedules"] = kept
    save_week_data(data)

    removed_lines = "\n".join([f"- {item['raw']}" for item in removed])

    await update.message.reply_text(
        f"✅ {len(removed)} مورد حذف شد:\n\n{removed_lines}\n\n"
        f"برنامه‌های باقی‌مانده:\n{format_group_schedules(group_data)}"
    )
    context.user_data["week_state"] = WEEK_ROOT
    return WEEK_ROOT


async def week_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ عملیات اعلان هفتگی لغو شد.")
    context.user_data.pop("week_state", None)
    context.user_data.pop("week_target_group", None)
    return ConversationHandler.END
