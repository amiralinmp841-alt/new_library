import json
import os
import re
import uuid
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
from week_storage import load_week_data, save_week_data, upload_weekly_to_telegram
import jdatetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

WEEK_FILE = "/tmp/week.json"

WEEK_ROOT = "week_root"
WEEK_WAITING_GROUP_NAME = "week_waiting_group_name"
WEEK_WAITING_ADD_TIME = "week_waiting_add_time"
WEEK_WAITING_DELETE_TIME = "week_waiting_delete_time"
TEHRAN_TZ = ZoneInfo("Asia/Tehran")

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
PERSIAN_MONTHS = {
    "فروردین": 1,
    "اردیبهشت": 2,
    "خرداد": 3,
    "تیر": 4,
    "مرداد": 5,
    "شهریور": 6,
    "مهر": 7,
    "آبان": 8,
    "آذر": 9,
    "دی": 10,
    "بهمن": 11,
    "اسفند": 12,
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


def normalize_day_name(day_text: str):
    day_text = normalize_schedule_text(day_text)
    return PERSIAN_DAY_ALIASES.get(day_text)


def parse_days_part(days_text: str):
    days_text = normalize_schedule_text(days_text)

    # جداکننده‌های مختلف
    days_text = days_text.replace("/", " ")
    days_text = days_text.replace(",", " ")
    days_text = days_text.replace("،", " ")

    # حذف کلمات اضافی
    days_text = re.sub(r"\bروز(?:های)?\b", " ", days_text)

    result = []

    # مستقیم تمام نام روزها را داخل متن پیدا می‌کنیم
    aliases = sorted(
        PERSIAN_DAY_ALIASES.keys(),
        key=len,
        reverse=True
    )

    remaining = days_text

    for alias in aliases:
        pattern = re.escape(alias)

        if re.search(pattern, remaining):
            normalized = PERSIAN_DAY_ALIASES[alias]

            if normalized not in result:
                result.append(normalized)

            remaining = re.sub(pattern, " ", remaining)

    return result
def parse_specific_dates_part(text: str):
    text = normalize_schedule_text(text)

    # مثال:
    # 9 فروردین
    # 9 و 10 فروردین
    # 9، 10 و 12 فروردین
    # 9 و 10 فروردین 1405

    month_pattern = "|".join(
        re.escape(month)
        for month in PERSIAN_MONTHS.keys()
    )

    pattern = rf"""
        ((?:\d{{1,2}}\s*(?:و|،|,)?\s*)+)
        ({month_pattern})
        (?:\s*(\d{{4}}))?
    """

    match = re.search(pattern, text, flags=re.VERBOSE)

    if not match:
        return None

    days_text = match.group(1)
    month_name = match.group(2)
    year_text = match.group(3)

    month = PERSIAN_MONTHS[month_name]

    # استخراج روزها
    day_numbers = [
        int(x)
        for x in re.findall(r"\d{1,2}", days_text)
    ]

    if not day_numbers:
        return None

    # اگر سال گفته نشده، سال فعلی شمسی را در نظر می‌گیریم
    now_jalali = jdatetime.datetime.now()
    if year_text:
        year = int(year_text)
    else:
        year = now_jalali.year

        # تاریخ بدون سال است.
        # اگر تاریخ امسال گذشته باشد، سال بعد را انتخاب کن.
        try:
            candidate = jdatetime.date(year, month, min(day_numbers))
            today = jdatetime.date(
                now_jalali.year,
                now_jalali.month,
                now_jalali.day
            )

            if candidate < today:
                year += 1

        except ValueError:
            return None

    # اعتبارسنجی
    result = []

    for day in day_numbers:
        try:
            jdate = jdatetime.date(year, month, day)

            result.append(
                f"{jdate.year:04d}-{jdate.month:02d}-{jdate.day:02d}"
            )

        except ValueError:
            return None

    return {
        "dates": result,
        "year": year,
        "month": month,
        "month_name": month_name,
        "days": day_numbers,
    }

def canonical_week_label(mode: str, week_offset: int):
    if mode == "recurring":
        return "این هفته و هفته های بعد"
    if week_offset == 0:
        return "این هفته"
    return f"{week_offset} هفته بعد"


def parse_week_part(week_text: str):
    week_text = normalize_schedule_text(week_text)

    recurring_forms = {
        "این هفته و هفته های بعد",
        "این هفته و هفته‌های بعد",
        "از این هفته به بعد",
        "از این هفته و هفته های بعد",
        "از این هفته و هفته‌های بعد",
        "هر هفته",
        "همه هفته ها",
        "همه هفته‌ها",
    }

    if week_text in recurring_forms:
        return {
            "mode": "recurring",
            "week_offset": 0,
            "label": "این هفته و هفته های بعد",
        }

    if week_text in {
        "این هفته",
        "هفته جاری",
    }:
        return {
            "mode": "single",
            "week_offset": 0,
            "label": "این هفته",
        }

    match = re.fullmatch(
        r"(\d+)\s*هفته\s*بعد",
        week_text
    )

    if match:
        offset = int(match.group(1))

        return {
            "mode": "single",
            "week_offset": offset,
            "label": f"{offset} هفته بعد",
        }

    if week_text == "هفته بعد":
        return {
            "mode": "single",
            "week_offset": 1,
            "label": "1 هفته بعد",
        }

    return None

PERSIAN_TO_ENGLISH_DIGITS = str.maketrans({
    "۰": "0",
    "۱": "1",
    "۲": "2",
    "۳": "3",
    "۴": "4",
    "۵": "5",
    "۶": "6",
    "۷": "7",
    "۸": "8",
    "۹": "9",

    "٠": "0",
    "١": "1",
    "٢": "2",
    "٣": "3",
    "٤": "4",
    "٥": "5",
    "٦": "6",
    "٧": "7",
    "٨": "8",
    "٩": "9",
})


def normalize_digits(text: str) -> str:
    return (text or "").translate(PERSIAN_TO_ENGLISH_DIGITS)


def normalize_schedule_text(text: str) -> str:
    text = normalize_digits(text)

    text = (text or "").strip()

    # حروف عربی به فارسی
    text = text.replace("ي", "ی").replace("ك", "ک")

    # نیم‌فاصله
    text = text.replace("‌", " ")

    # سه‌نقطه
    text = text.replace("…", "...")

    # انواع خط تیره
    text = text.replace("–", "-")
    text = text.replace("—", "-")

    # فاصله‌های استاندارد
    text = re.sub(r"\s+", " ", text)

    return text.strip()

def normalize_time_value(value: str):
    value = normalize_digits(value).strip()

    if ":" in value:
        parts = value.split(":")

        if len(parts) != 2:
            return None

        try:
            hour = int(parts[0])
            minute = int(parts[1])
        except ValueError:
            return None

    else:
        try:
            hour = int(value)
            minute = 0
        except ValueError:
            return None

    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None

    return f"{hour:02d}:{minute:02d}"

def parse_time_part(time_text: str):
    time_text = normalize_schedule_text(time_text)

    # --------------------------------
    # حالت بازه:
    # 8 تا 10
    # 8:30 تا 10:45
    # 08:30-10:45
    # --------------------------------
    range_pattern = (
        r"(?:از\s*)?"
        r"(?:ساعت\s*)?"
        r"(\d{1,2}(?::\d{1,2})?)"
        r"\s*(?:تا|الی|-)\s*"
        r"(\d{1,2}(?::\d{1,2})?)"
    )

    match = re.search(range_pattern, time_text)

    if match:
        start_time = normalize_time_value(match.group(1))
        end_time = normalize_time_value(match.group(2))

        if start_time and end_time:
            return {
                "start_time": start_time,
                "end_time": end_time,
            }

    # --------------------------------
    # حالت تک‌ساعت:
    #
    # 8
    # ساعت 8
    # از ساعت 8
    # 8:30
    # --------------------------------
    single_pattern = (
        r"(?:از\s*)?"
        r"(?:ساعت\s*)?"
        r"(\d{1,2}(?::\d{1,2})?)"
        r"(?!\s*(?:تا|الی|-))"
    )

    match = re.search(single_pattern, time_text)

    if match:
        start_time = normalize_time_value(match.group(1))

        if start_time:
            return {
                "start_time": start_time,
                "end_time": None,
            }

    return None

def parse_schedule_line(line: str):
    raw_line = normalize_schedule_text(line)

    if not raw_line:
        return None

    # -----------------------------
    # 1) تشخیص زمان
    # -----------------------------
    time_info = parse_time_part(raw_line)

    if not time_info:
        return None

    # حذف بازه زمانی از متن
    line_without_time = raw_line

    time_pattern = (
        r"(?:از\s*)?"
        r"(?:ساعت\s*)?"
        r"\d{1,2}(?::\d{1,2})?"
        r"(?:\s*(?:تا|الی|-)\s*\d{1,2}(?::\d{1,2})?)?"
    )

    line_without_time = re.sub(
        time_pattern,
        " ",
        line_without_time,
        flags=re.IGNORECASE,
    )

    # حذف کلمات اضافی مربوط به زمان
    line_without_time = re.sub(
        r"\b(?:ساعت|صبح|عصر|شب)\b",
        " ",
        line_without_time,
    )

    line_without_time = normalize_schedule_text(line_without_time)

    # -----------------------------
    # 2) تشخیص تاریخ مشخص
    # -----------------------------
    specific_date_info = parse_specific_dates_part(raw_line)

    if specific_date_info:

        if time_info["end_time"]:
            time_text = (
                f"ساعت {time_info['start_time']} "
                f"تا {time_info['end_time']}"
            )
        else:
            time_text = f"ساعت {time_info['start_time']}"

        dates_text = " و ".join(
            f"{day} {specific_date_info['month_name']}"
            for day in specific_date_info["days"]
        )

        canonical_raw = (
            f"{dates_text} ... {time_text}"
        )

        return {
            "id": str(uuid.uuid4()),
            "raw": raw_line,
            "canonical_raw": canonical_raw,

            "mode": "specific_date",

            "week_offset": 0,
            "week_label": None,

            "days": [],
            "dates": specific_date_info["dates"],

            "start_time": time_info["start_time"],
            "end_time": time_info["end_time"],

            "created_at": get_now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    # -----------------------------
    # 2) تشخیص هفته
    # -----------------------------
    week_info = None
    found_week_text = None

    candidate_week_patterns = [
        r"این هفته و هفته های بعد",
        r"این هفته و هفته‌های بعد",
        r"از این هفته به بعد",
        r"از این هفته و هفته های بعد",
        r"از این هفته و هفته‌های بعد",
        r"هر هفته",
        r"همه هفته ها",
        r"همه هفته‌ها",
        r"هفته جاری",
        r"\d+\s*هفته\s*بعد",
        r"هفته بعد",
        r"این هفته",
    ]

    for pattern in candidate_week_patterns:
        match = re.search(pattern, line_without_time)

        if match:
            found_week_text = match.group(0)

            week_info = parse_week_part(found_week_text)

            if week_info:
                break

    if not week_info:
        return None

    # -----------------------------
    # 3) حذف بخش هفته
    # -----------------------------
    remaining_text = line_without_time

    if found_week_text:
        remaining_text = remaining_text.replace(
            found_week_text,
            " "
        )

    remaining_text = normalize_schedule_text(remaining_text)

    # -----------------------------
    # 4) تشخیص روزها
    # -----------------------------
    days = parse_days_part(remaining_text)

    if not days:
        return None

    # -----------------------------
    # 5) ساخت متن استاندارد
    # -----------------------------
    if time_info["end_time"]:
        time_text = (
            f"ساعت {time_info['start_time']} "
            f"تا {time_info['end_time']}"
        )
    else:
        time_text = f"ساعت {time_info['start_time']}"
    
    canonical_raw = (
        f"{canonical_week_label(week_info['mode'], week_info['week_offset'])}"
        f" ... {' و '.join(days)} ... "
        f"{time_text}"
    )

    return {
        "id": str(uuid.uuid4()),
        "raw": raw_line,
        "canonical_raw": canonical_raw,

        "mode": week_info["mode"],
        "week_offset": week_info["week_offset"],
        "week_label": week_info["label"],

        "days": days,

        "start_time": time_info["start_time"],
        "end_time": time_info["end_time"],

        "created_at": get_now().strftime("%Y-%m-%d %H:%M:%S"),
    }

def format_schedule_time(schedule):
    start_time = schedule.get("start_time")

    if not start_time:
        return "--:--"

    end_time = schedule.get("end_time")

    if end_time:
        return f"{start_time} تا {end_time}"

    return start_time

def is_duplicate_schedule(existing_items, new_item):
    for item in existing_items:

        if item.get("mode") != new_item.get("mode"):
            continue

        if item.get("mode") == "specific_date":
            if (
                item.get("dates", []) == new_item.get("dates", [])
                and item.get("start_time") == new_item.get("start_time")
                and item.get("end_time") == new_item.get("end_time")
            ):
                return True

        else:
            if (
                int(item.get("week_offset", 0))
                == int(new_item.get("week_offset", 0))
                and item.get("days", []) == new_item.get("days", [])
                and item.get("start_time") == new_item.get("start_time")
                and item.get("end_time") == new_item.get("end_time")
            ):
                return True

    return False


def parse_week_schedule_text(text: str):
    lines = [normalize_schedule_text(line) for line in (text or "").splitlines()]
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


def get_root_groups(data):
    result = []
    for group_id, group_data in data.get("groups", {}).items():
        if group_data.get("parent_id") is None:
            result.append((group_id, group_data))
    result.sort(key=lambda x: x[1].get("title", ""))
    return result


def get_group_children(data, group_id):
    children_ids = data.get("groups", {}).get(group_id, {}).get("children", [])
    result = []
    for child_id in children_ids:
        child = data.get("groups", {}).get(child_id)
        if child:
            result.append((child_id, child))
    return result


def ensure_group_shape(group_data):
    group_data.setdefault("title", "بدون نام")
    group_data.setdefault("created_at", get_now().strftime("%Y-%m-%d %H:%M:%S"))
    group_data.setdefault("schedules", [])
    group_data.setdefault("children", [])
    group_data.setdefault("parent_id", None)
    return group_data


def build_week_root_keyboard(data):
    keyboard = [
        [
            InlineKeyboardButton("➕ افزودن گروه", callback_data="week_add_group_root"),
            InlineKeyboardButton("➖ حذف گروه", callback_data="week_delete_group_menu_root"),
        ],
        [
            InlineKeyboardButton("📥 دریافت بکاپ", callback_data="week_backup_get"),
            InlineKeyboardButton("📤 وارد کردن بکاپ", callback_data="week_backup_upload_prompt"),
        ]
    ]

    for group_id, group_data in get_root_groups(data):
        keyboard.append([
            InlineKeyboardButton(
                f"📁 {group_data.get('title', 'بدون نام')}",
                callback_data=f"week_open_group:{group_id}"
            )
        ])

    keyboard.append([InlineKeyboardButton("❌ بستن", callback_data="week_close")])
    return InlineKeyboardMarkup(keyboard)


def build_group_keyboard(data, group_id):
    group_data = data["groups"][group_id]
    children = get_group_children(data, group_id)

    keyboard = [
        [
            InlineKeyboardButton("➕ افزودن زیرگروه", callback_data=f"week_add_group_child:{group_id}"),
            InlineKeyboardButton("➖ حذف همین گروه", callback_data=f"week_delete_group:{group_id}"),
        ],
        [
            InlineKeyboardButton("⏰ تعیین تایم", callback_data=f"week_time_menu:{group_id}")
        ],
    ]

    for child_id, child_data in children:
        keyboard.append([
            InlineKeyboardButton(
                f"📁 {child_data.get('title', 'بدون نام')}",
                callback_data=f"week_open_group:{child_id}"
            )
        ])

    parent_id = group_data.get("parent_id")
    if parent_id:
        keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data=f"week_open_group:{parent_id}")])
    else:
        keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="week_back_root")])

    return InlineKeyboardMarkup(keyboard)


def build_delete_group_menu(data, parent_id=None):
    keyboard = []

    if parent_id is None:
        items = get_root_groups(data)
        back_callback = "week_back_root"
    else:
        items = get_group_children(data, parent_id)
        back_callback = f"week_open_group:{parent_id}"

    for group_id, group_data in items:
        keyboard.append([
            InlineKeyboardButton(
                f"🗑 {group_data.get('title', 'بدون نام')}",
                callback_data=f"week_delete_group:{group_id}"
            )
        ])

    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data=back_callback)])
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
    return item.get("canonical_raw") or item.get("raw", "")


def format_group_schedules(group_data):
    schedules = group_data.get("schedules", [])
    if not schedules:
        return "هنوز هیچ تایمی برای این گروه ثبت نشده."

    lines = []
    for idx, item in enumerate(schedules, start=1):
        lines.append(f"{idx}. {format_schedule_item(item)}")
    return "\n".join(lines)


def delete_group_recursive(data, group_id):
    group = data["groups"].get(group_id)
    if not group:
        return

    for child_id in list(group.get("children", [])):
        delete_group_recursive(data, child_id)

    parent_id = group.get("parent_id")
    if parent_id and parent_id in data["groups"]:
        parent_children = data["groups"][parent_id].get("children", [])
        data["groups"][parent_id]["children"] = [x for x in parent_children if x != group_id]

    data["groups"].pop(group_id, None)


async def set_week_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_week_data()
    await update.message.reply_text(
        "📅 پنل اعلان هفتگی\n\nیکی از گزینه‌ها را انتخاب کنید.",
        reply_markup=build_week_root_keyboard(data),
    )
    context.user_data["week_state"] = WEEK_ROOT
    context.user_data.pop("week_target_group", None)
    context.user_data.pop("week_parent_for_new_group", None)
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
        context.user_data.pop("week_parent_for_new_group", None)
        return ConversationHandler.END

    if callback == "week_back_root":
        await query.edit_message_text(
            "📅 پنل اعلان هفتگی\n\nیکی از گزینه‌ها را انتخاب کنید.",
            reply_markup=build_week_root_keyboard(data),
        )
        context.user_data["week_state"] = WEEK_ROOT
        context.user_data.pop("week_target_group", None)
        context.user_data.pop("week_parent_for_new_group", None)
        return WEEK_ROOT

    if callback == "week_add_group_root":
        context.user_data["week_parent_for_new_group"] = None
        context.user_data["week_state"] = WEEK_WAITING_GROUP_NAME
        await query.message.reply_text("نام گروه جدید را ارسال کنید.")
        return WEEK_WAITING_GROUP_NAME

    if callback.startswith("week_add_group_child:"):
        parent_id = callback.split(":", 1)[1]
        if parent_id not in data["groups"]:
            await query.answer("گروه پیدا نشد.", show_alert=True)
            return WEEK_ROOT

        context.user_data["week_parent_for_new_group"] = parent_id
        context.user_data["week_state"] = WEEK_WAITING_GROUP_NAME
        await query.message.reply_text("نام زیرگروه جدید را ارسال کنید.")
        return WEEK_WAITING_GROUP_NAME

    if callback == "week_delete_group_menu_root":
        if not get_root_groups(data):
            await query.answer("هیچ گروهی وجود ندارد.", show_alert=True)
            return WEEK_ROOT

        await query.edit_message_text(
            "گروه ریشه‌ای که می‌خواهید حذف شود را انتخاب کنید:",
            reply_markup=build_delete_group_menu(data, parent_id=None),
        )
        return WEEK_ROOT

    if callback.startswith("week_delete_group_menu_child:"):
        parent_id = callback.split(":", 1)[1]
        if parent_id not in data["groups"]:
            await query.answer("گروه پیدا نشد.", show_alert=True)
            return WEEK_ROOT

        await query.edit_message_text(
            "زیرگروهی که می‌خواهید حذف شود را انتخاب کنید:",
            reply_markup=build_delete_group_menu(data, parent_id=parent_id),
        )
        return WEEK_ROOT

    if callback.startswith("week_open_group:"):
        group_id = callback.split(":", 1)[1]
        group_data = data.get("groups", {}).get(group_id)

        if not group_data:
            await query.answer("گروه پیدا نشد.", show_alert=True)
            return WEEK_ROOT

        ensure_group_shape(group_data)

        schedules_count = len(group_data.get("schedules", []))
        children_count = len(group_data.get("children", []))

        text = (
            f"📁 گروه: {group_data.get('title', 'بدون نام')}\n"
            f"⏰ تعداد تایم‌ها: {schedules_count}\n"
            f"🗂 تعداد زیرگروه‌ها: {children_count}\n\n"
            f"یکی از گزینه‌ها را انتخاب کنید."
        )

        await query.edit_message_text(
            text,
            reply_markup=build_group_keyboard(data, group_id),
        )
        context.user_data["week_target_group"] = group_id
        context.user_data["week_state"] = WEEK_ROOT
        return WEEK_ROOT

    if callback.startswith("week_delete_group:"):
        group_id = callback.split(":", 1)[1]
        group = data.get("groups", {}).get(group_id)

        if not group:
            await query.answer("گروه پیدا نشد.", show_alert=True)
            return WEEK_ROOT

        group_title = group.get("title", "بدون نام")
        parent_id = group.get("parent_id")

        affected_group_ids = collect_group_and_children_ids(data, group_id)

        removed_map = {}
        
        for gid in affected_group_ids:
            group_item = data.get("groups", {}).get(gid)
        
            if group_item:
                removed_map[gid] = list(
                    group_item.get("schedules", [])
                )
        
        for removed_group_id, removed_schedules in removed_map.items():
            if removed_schedules:
                await dispatch_cancel_for_removed_schedules(
                    context.bot,
                    data,
                    removed_group_id,
                    removed_schedules,
                )

        delete_group_recursive(data, group_id)
        save_week_data(data)

        if parent_id and parent_id in data["groups"]:
            await query.edit_message_text(
                f"✅ گروه «{group_title}» و زیرگروه‌هایش حذف شد.",
                reply_markup=build_group_keyboard(data, parent_id),
            )
        else:
            await query.edit_message_text(
                f"✅ گروه «{group_title}» و زیرگروه‌هایش حذف شد.\n\n📅 پنل اعلان هفتگی",
                reply_markup=build_week_root_keyboard(data),
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
            reply_markup=build_time_menu_keyboard(group_id),
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
            "⏰ تایم جدید را با هر ترتیب راحتی وارد کن.\n\n"
        
            "می‌توانی به دو شکل برنامه ثبت کنی:\n\n"
        
            "📅 برنامه هفتگی:\n"
            "• هفته\n"
            "• روز یا روزها\n"
            "• ساعت\n\n"
        
            "📆 تاریخ مشخص:\n"
            "• روز و ماه\n"
            "• ساعت\n\n"
        
            "مثال‌های هفتگی:\n"
            "شنبه این هفته 18 تا 20\n"
            "این هفته شنبه ساعت 18:00-20:00\n"
            "هر هفته شنبه و دوشنبه 8 تا 10\n"
            "۲ هفته بعد جمعه 10:30 تا 12\n\n"
        
            "مثال‌های تاریخ مشخص:\n"
            "9 فروردین ساعت 8\n"
            "9 و 10 فروردین ساعت 8\n"
            "9، 10 و 12 فروردین ساعت 08:30\n"
            "9 و 10 فروردین ساعت 8 تا 10\n"
            "15 اردیبهشت ساعت 14\n"
            "9 فروردین 1406 ساعت 10\n\n"
        
            "می‌توانی چند برنامه را هم در چند خط بفرستی.\n"
            "برای لغو: /cancel"
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
            "فرمت‌های حذف:\n"
            "- متن کامل همان برنامه\n"
            "- این هفته\n"
            "- هفته بعد\n"
            "- 2 هفته بعد\n"
            "- شنبه این هفته\n"
            "- شنبه هفته بعد\n"
            "- همه هفته ها شنبه\n"
            "- هر هفته شنبه\n"
            "- 18:00 تا 20:00\n"
            "- شنبه 18:00 تا 20:00\n\n"
            "می‌توانید چند خط هم بفرستید.\n"
            "برای لغو: /cancel"
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
    parent_id = context.user_data.get("week_parent_for_new_group")

    data.setdefault("groups", {})[group_id] = ensure_group_shape({
        "title": group_name,
        "created_at": get_now().strftime("%Y-%m-%d %H:%M:%S"),
        "schedules": [],
        "children": [],
        "parent_id": parent_id,
    })

    if parent_id:
        parent_group = data["groups"].get(parent_id)
        if not parent_group:
            await update.message.reply_text("❌ گروه والد پیدا نشد. دوباره /set_alarm را بزنید.")
            return ConversationHandler.END
        parent_group.setdefault("children", []).append(group_id)

    save_week_data(data)

    if parent_id:
        await update.message.reply_text(
            f"✅ زیرگروه «{group_name}» ساخته شد.",
            reply_markup=build_group_keyboard(data, parent_id),
        )
    else:
        await update.message.reply_text(
            f"✅ گروه «{group_name}» ساخته شد.",
            reply_markup=build_week_root_keyboard(data),
        )

    context.user_data["week_state"] = WEEK_ROOT
    context.user_data["week_target_group"] = parent_id
    context.user_data.pop("week_parent_for_new_group", None)
    return WEEK_ROOT


async def receive_week_time_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = context.user_data.get("week_target_group")
    if not group_id:
        await update.message.reply_text("❌ گروه مقصد مشخص نیست. دوباره /set_alarm را بزنید.")
        return ConversationHandler.END

    text = update.message.text or ""
    data = load_week_data()
    group_data = data.get("groups", {}).get(group_id)

    if not group_data:
        await update.message.reply_text("❌ گروه پیدا نشد. دوباره /set_alarm را بزنید.")
        return ConversationHandler.END

    parsed_items, invalid_lines = parse_week_schedule_text(text)

    if not parsed_items:
        await update.message.reply_text(
            "❌ هیچ خط معتبری تشخیص داده نشد.\n\n"
            "نمونه‌ها:\n"
            "این هفته ... شنبه ... ساعت 18:00 تا 20:00\n"
            "هفته بعد ... دوشنبه ... 08:00 تا 10:00\n"
            "هر هفته ... شنبه و یک شنبه ... 18:00-20:00"
        )
        return WEEK_WAITING_ADD_TIME

    schedules = group_data.setdefault("schedules", [])
    added = []
    duplicates = []

    for item in parsed_items:
        if is_duplicate_schedule(schedules, item):
            duplicates.append(item)
        else:
            schedules.append(item)
            added.append(item)

    save_week_data(data)

    if added:
        await dispatch_immediate_alarms_for_new_schedules(
            context.bot,
            data,
            group_id,
            added,
        )

    msg = []
    if added:
        msg.append(f"✅ {len(added)} تایم جدید برای گروه «{group_data.get('title', 'بدون نام')}» ثبت شد.")
    if duplicates:
        msg.append(f"⚠️ {len(duplicates)} مورد تکراری بود و دوباره ذخیره نشد.")

    if invalid_lines:
        msg.append("\n⚠️ این خط‌ها نامعتبر بودند و ذخیره نشدند:")
        msg.extend([f"- {line}" for line in invalid_lines])

    msg.append("\nبرنامه‌های فعلی:")
    msg.append(format_group_schedules(group_data))

    await update.message.reply_text("\n".join(msg))
    context.user_data["week_state"] = WEEK_ROOT
    return WEEK_ROOT


def _parse_delete_line(line: str):
    normalized = normalize_schedule_text(line)

    parsed_schedule = parse_schedule_line(normalized)
    if parsed_schedule:
        return {"type": "exact_schedule", "value": parsed_schedule}

    week_info = parse_week_part(normalized)
    if week_info:
        return {"type": "week_only", "value": week_info}

    time_info = parse_time_part(normalized)
    if time_info:
        remaining = normalized
        remaining = re.sub(
            r"(?:ساعت\s*)?\d{1,2}(?::\d{1,2})?\s*(?:تا|الی|-)\s*\d{1,2}(?::\d{1,2})?",
            "",
            remaining,
        )
        remaining = re.sub(r"از\s*\d{1,2}(?::\d{1,2})?\s*(?:تا|الی|-)\s*\d{1,2}(?::\d{1,2})?", "", remaining)
        remaining = normalize_schedule_text(remaining)

        week_info_inside = None
        found_week = None
        for pattern in [
            r"این هفته و هفته های بعد",
            r"این هفته و هفته‌های بعد",
            r"هر هفته",
            r"همه هفته ها",
            r"همه هفته‌ها",
            r"این هفته",
            r"هفته جاری",
            r"\d+\s+هفته\s+بعد",
            r"هفته بعد",
        ]:
            match = re.search(pattern, remaining)
            if match:
                found_week = normalize_schedule_text(match.group(0))
                week_info_inside = parse_week_part(found_week)
                if week_info_inside:
                    break

        if found_week:
            remaining = normalize_schedule_text(remaining.replace(found_week, " "))

        days = parse_days_part(remaining) if remaining else []

        return {
            "type": "filter",
            "week": week_info_inside,
            "days": days,
            "time": time_info,
        }

    match = re.fullmatch(
        r"(شنبه|یکشنبه|یک‌شنبه|یک شنبه|دوشنبه|دو شنبه|سهشنبه|سه‌شنبه|سه شنبه|چهارشنبه|چهار شنبه|پنجشنبه|پنج‌شنبه|پنج شنبه|جمعه)\s+(این هفته|\d+\s+هفته\s+بعد|هفته بعد)",
        normalized
    )
    if match:
        day = normalize_day_name(match.group(1))
        week_info = parse_week_part(match.group(2))
        return {"type": "day_week", "day": day, "week": week_info}

    match = re.fullmatch(
        r"(همه هفته ها|همه هفته‌ها|هر هفته)\s+(شنبه|یکشنبه|یک‌شنبه|یک شنبه|دوشنبه|دو شنبه|سهشنبه|سه‌شنبه|سه شنبه|چهارشنبه|چهار شنبه|پنجشنبه|پنج‌شنبه|پنج شنبه|جمعه)",
        normalized
    )
    if match:
        day = normalize_day_name(match.group(2))
        return {"type": "recurring_day", "day": day}

    day_only = normalize_day_name(normalized)
    if day_only:
        return {"type": "day_only", "day": day_only}

    return {"type": "raw", "value": normalized}


def _matches_delete_request(item, line):
    parsed = _parse_delete_line(line)

    if parsed["type"] == "exact_schedule":
        value = parsed["value"]
        return (
            item.get("mode") == value.get("mode")
            and int(item.get("week_offset", 0)) == int(value.get("week_offset", 0))
            and item.get("days", []) == value.get("days", [])
            and item.get("start_time") == value.get("start_time")
            and item.get("end_time") == value.get("end_time")
        )

    if parsed["type"] == "week_only":
        week = parsed["value"]
        return (
            item.get("mode") == week.get("mode")
            and int(item.get("week_offset", 0)) == int(week.get("week_offset", 0))
        )

    if parsed["type"] == "day_week":
        return (
            parsed["day"] in item.get("days", [])
            and item.get("mode") == parsed["week"].get("mode")
            and int(item.get("week_offset", 0)) == int(parsed["week"].get("week_offset", 0))
        )

    if parsed["type"] == "recurring_day":
        return item.get("mode") == "recurring" and parsed["day"] in item.get("days", [])

    if parsed["type"] == "day_only":
        return parsed["day"] in item.get("days", [])

    if parsed["type"] == "filter":
        if parsed["week"]:
            if item.get("mode") != parsed["week"].get("mode"):
                return False
            if int(item.get("week_offset", 0)) != int(parsed["week"].get("week_offset", 0)):
                return False

        if parsed["days"]:
            if not any(day in item.get("days", []) for day in parsed["days"]):
                return False

        if parsed["time"]:
            if item.get("start_time") != parsed["time"].get("start_time"):
                return False
            if item.get("end_time") != parsed["time"].get("end_time"):
                return False

        return True

    if parsed["type"] == "raw":
        normalized_item_raw = normalize_schedule_text(item.get("raw", ""))
        normalized_canonical = normalize_schedule_text(item.get("canonical_raw", ""))
        return parsed["value"] in {normalized_item_raw, normalized_canonical}

    return False


async def receive_week_delete_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = context.user_data.get("week_target_group")
    if not group_id:
        await update.message.reply_text("❌ گروه مقصد مشخص نیست. دوباره /set_alarm را بزنید.")
        return ConversationHandler.END

    data = load_week_data()
    group_data = data.get("groups", {}).get(group_id)

    if not group_data:
        await update.message.reply_text("❌ گروه پیدا نشد. دوباره /set_alarm را بزنید.")
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
        await update.message.reply_text(
            "❌ هیچ موردی برای حذف پیدا نشد.\n"
            "مثال‌های معتبر:\n"
            "- این هفته\n"
            "- هفته بعد\n"
            "- شنبه این هفته\n"
            "- همه هفته ها شنبه\n"
            "- 18:00 تا 20:00\n"
            "- شنبه 18:00 تا 20:00"
        )
        return WEEK_WAITING_DELETE_TIME

    group_data["schedules"] = kept
    save_week_data(data)

    await dispatch_cancel_for_removed_schedules(
        context.bot,
        data,
        group_id,
        removed,
    )

    removed_lines = "\n".join([f"- {format_schedule_item(item)}" for item in removed])

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
    context.user_data.pop("week_parent_for_new_group", None)
    return ConversationHandler.END



WEEK_USER_ROOT = "week_user_root"


def ensure_week_users_shape(data):
    data.setdefault("users", {})
    return data


def get_week_user_id(update_or_query):
    user = update_or_query.effective_user
    return str(user.id)


def ensure_user_week_data(data, user_id):
    ensure_week_users_shape(data)
    data["users"].setdefault(user_id, {"courses": []})
    data["users"][user_id].setdefault("courses", [])
    ensure_user_alarm_defaults(data["users"][user_id])
    return data["users"][user_id]


WEEK_WAITING_ALARM_DAYS = "week_waiting_alarm_days"
WEEK_WAITING_ALARM_TIME = "week_waiting_alarm_time"


def ensure_user_alarm_defaults(user_data):
    user_data.setdefault("alarm_enabled", True)
    user_data.setdefault("alarm_all", {
        "days_before": 1,
        "time": "06:00",
    })
    user_data.setdefault("course_alarms", {})
    user_data.setdefault("alarm_sent", {})
    user_data.setdefault("alarm_cancel_sent", {})
    return user_data


def build_alarm_root_keyboard():
    keyboard = [
        [InlineKeyboardButton("🔔 الارم برای همه درس‌ها", callback_data="uweek_alarm_all")],
        [InlineKeyboardButton("📚 الارم برای درس خاص", callback_data="uweek_alarm_course_menu")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="uweek_back_root")],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_alarm_course_picker_keyboard(data, user_data):
    courses = clean_user_courses(data, user_data)
    keyboard = []

    for group_id in courses:
        keyboard.append([
            InlineKeyboardButton(
                f"🔔 {get_group_title_path(data, group_id)}",
                callback_data=f"uweek_alarm_course:{group_id}"
            )
        ])

    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="uweek_alarm_menu")])
    return InlineKeyboardMarkup(keyboard)


def format_alarm_summary(data, user_data):
    ensure_user_alarm_defaults(user_data)

    lines = [
        "🔔 تنظیمات الارم:",
        f"وضعیت کلی: {'روشن' if user_data.get('alarm_enabled', True) else 'خاموش'}",
    ]

    alarm_all = user_data.get("alarm_all", {})
    lines.append(
        f"برای همه درس‌ها: {alarm_all.get('days_before', 1)} روز قبل، ساعت {alarm_all.get('time', '06:00')}"
    )

    course_alarms = user_data.get("course_alarms", {})
    if course_alarms:
        lines.append("\nالارم درس‌های خاص:")
        for group_id, alarm in course_alarms.items():
            if group_id in data.get("groups", {}):
                lines.append(
                    f"- {get_group_title_path(data, group_id)}: "
                    f"{alarm.get('days_before', 1)} روز قبل، ساعت {alarm.get('time', '06:00')}"
                )

    return "\n".join(lines)


def parse_alarm_days_before(text: str):
    text = normalize_schedule_text(text)
    match = re.search(r"(\d+)", text)
    if not match:
        return None

    value = int(match.group(1))
    if value < 0 or value > 30:
        return None
    return value


def group_has_children(data, group_id):
    group = data.get("groups", {}).get(group_id, {})
    return bool(group.get("children", []))


def get_group_title_path(data, group_id):
    groups = data.get("groups", {})
    titles = []
    current_id = group_id
    visited = set()

    while current_id and current_id in groups and current_id not in visited:
        visited.add(current_id)
        group = groups[current_id]
        titles.append(group.get("title", "بدون نام"))
        current_id = group.get("parent_id")

    return " ".join(reversed(titles))


def clean_user_courses(data, user_data):
    groups = data.get("groups", {})
    old_courses = user_data.get("courses", [])
    user_data["courses"] = [group_id for group_id in old_courses if group_id in groups]
    return user_data["courses"]


def build_user_week_root_keyboard():
    keyboard = [
        [InlineKeyboardButton("📚 درس‌های من", callback_data="uweek_my_courses")],
        [InlineKeyboardButton("📅 برنامه کل هفتگی من", callback_data="uweek_full_schedule")],
        [InlineKeyboardButton("🔔 تعیین الارم", callback_data="uweek_alarm_menu")],
        [InlineKeyboardButton("❌ بستن", callback_data="uweek_close")],
    ]
    return InlineKeyboardMarkup(keyboard)


def format_my_courses_text(data, user_data):
    courses = clean_user_courses(data, user_data)

    if not courses:
        return "هنوز هیچ درسی اضافه نکردی."

    lines = ["📚 درس‌های من:"]
    for index, group_id in enumerate(courses, start=1):
        lines.append(f"{index}. {get_group_title_path(data, group_id)}")

    return "\n".join(lines)


def build_my_courses_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("➕ افزودن درس", callback_data="uweek_add_course_menu"),
            InlineKeyboardButton("➖ حذف درس", callback_data="uweek_delete_course_menu"),
        ],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="uweek_back_root")],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_user_group_browser_keyboard(data, parent_id=None):
    keyboard = []

    if parent_id is None:
        items = get_root_groups(data)
        back_callback = "uweek_my_courses"
    else:
        items = get_group_children(data, parent_id)
        parent_group = data.get("groups", {}).get(parent_id, {})
        grand_parent_id = parent_group.get("parent_id")
        back_callback = f"uweek_browse:{grand_parent_id}" if grand_parent_id else "uweek_add_course_menu"

    for group_id, group_data in items:
        title = group_data.get("title", "بدون نام")

        if group_has_children(data, group_id):
            button_text = f"🔵 {title}"
            callback_data = f"uweek_browse:{group_id}"
        else:
            button_text = f"🟢 {title}"
            callback_data = f"uweek_add_course:{group_id}"

        keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])

    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data=back_callback)])
    return InlineKeyboardMarkup(keyboard)


def build_delete_my_course_keyboard(data, user_data):
    courses = clean_user_courses(data, user_data)
    keyboard = []

    for group_id in courses:
        keyboard.append([
            InlineKeyboardButton(
                f"🗑 {get_group_title_path(data, group_id)}",
                callback_data=f"uweek_delete_course:{group_id}"
            )
        ])

    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="uweek_my_courses")])
    return InlineKeyboardMarkup(keyboard)


def get_day_sort_index(item):
    days = item.get("days", [])
    if not days:
        return 99

    first_day = days[0]
    try:
        return ALL_DAYS.index(first_day)
    except ValueError:
        return 99

        
def format_user_full_schedule(data, user_data):
    courses = clean_user_courses(data, user_data)

    if not courses:
        return (
            "هنوز هیچ درسی اضافه نکردی.\n\n"
            "از بخش «درس‌های من» اول درس‌هایت را اضافه کن."
        )

    schedule_rows = []

    for group_id in courses:
        group = data.get("groups", {}).get(group_id)

        if not group:
            continue

        course_title = get_group_title_path(data, group_id)

        for schedule in group.get("schedules", []):
            schedule_rows.append({
                "course_title": course_title,
                "schedule": schedule,
                "group_id": group_id,
            })

    if not schedule_rows:
        return "برای درس‌های انتخابی تو هنوز هیچ برنامه‌ای ثبت نشده."

    # -----------------------------------------
    # تاریخ و زمان فعلی
    # -----------------------------------------

    now = get_now()

    # شروع هفته جاری = شنبه
    start_of_week = get_start_of_current_week(now)

    # -----------------------------------------
    # تبدیل تاریخ میلادی به شمسی
    # -----------------------------------------

    def format_jalali_date(target_date):
        dt = datetime(
            target_date.year,
            target_date.month,
            target_date.day,
            tzinfo=TEHRAN_TZ
        )

        jalali = jdatetime.datetime.fromgregorian(datetime=dt)

        return (
            f"{to_persian_digits(jalali.day)} "
            f"{PERSIAN_MONTH_NAMES[jalali.month]} "
            f"{to_persian_digits(jalali.year)}"
        )

    # -----------------------------------------
    # تبدیل تاریخ شمسی ذخیره‌شده
    # مثل:
    # 1405-05-07
    # -----------------------------------------

    def parse_stored_jalali_date(date_text):
        if not date_text:
            return None

        try:
            date_text = normalize_digits(str(date_text)).strip()

            parts = date_text.split("-")

            if len(parts) != 3:
                return None

            year = int(parts[0])
            month = int(parts[1])
            day = int(parts[2])

            jdate = jdatetime.date(
                year,
                month,
                day
            )

            gregorian = jdate.togregorian()

            return datetime(
                gregorian.year,
                gregorian.month,
                gregorian.day,
                tzinfo=TEHRAN_TZ
            ).date()

        except (ValueError, TypeError):
            return None

    # -----------------------------------------
    # نام روز + تاریخ
    # -----------------------------------------

    def format_day_with_date(target_date, day_name=None):
        if target_date is None:
            return day_name or ""

        if day_name:
            return (
                f"{day_name} "
                f"{format_jalali_date(target_date)}"
            )

        # اگر specific_date است،
        # خود روز هفته را از تاریخ محاسبه کن
        weekday_map = {
            5: "شنبه",
            6: "یک شنبه",
            0: "دوشنبه",
            1: "سه شنبه",
            2: "چهارشنبه",
            3: "پنج شنبه",
            4: "جمعه",
        }

        day_name = weekday_map.get(target_date.weekday(), "")

        return (
            f"{day_name} "
            f"{format_jalali_date(target_date)}"
        )

    # -----------------------------------------
    # برچسب هفته
    # -----------------------------------------

    def week_label_from_offset(offset):
        if offset == 0:
            return "این هفته"
        elif offset == 1:
            return "هفته بعد"
        elif offset == 2:
            return "۲ هفته بعد"
        else:
            return f"{to_persian_digits(offset)} هفته بعد"

    # -----------------------------------------
    # ساخت ردیف‌ها
    # -----------------------------------------

    expanded_rows = []

    for row in schedule_rows:

        schedule = row["schedule"]

        mode = schedule.get("mode", "single")

        # =====================================================
        # ⭐ تاریخ مشخص
        # =====================================================

        if mode == "specific_date":

            stored_dates = schedule.get("dates", []) or []

            for stored_date in stored_dates:

                target_date = parse_stored_jalali_date(
                    stored_date
                )

                if target_date is None:
                    continue

                expanded_rows.append({
                    "course_title": row["course_title"],
                    "schedule": schedule,
                    "day": None,
                    "date": target_date,
                    "week_offset": 0,
                    "week_label": "تاریخ‌های مشخص",
                })

            continue

        # =====================================================
        # برنامه‌های هفتگی
        # =====================================================

        try:
            offset = int(
                schedule.get("week_offset", 0)
            )
        except (TypeError, ValueError):
            offset = 0

        days = schedule.get("days", []) or []

        if not days:
            continue

        start_time = schedule.get("start_time")

        if not start_time:
            continue

        # -------------------------------------
        # حالت تکرارشونده
        # -------------------------------------

        if mode == "recurring":
            week_offsets = [0, 1, 2]

        # -------------------------------------
        # حالت یک‌بار مصرف
        # -------------------------------------

        else:
            week_offsets = [offset]

        # -------------------------------------
        # ساخت تاریخ واقعی هر جلسه
        # -------------------------------------

        for week_offset in week_offsets:

            for day_name in days:

                day_idx = get_day_index(day_name)

                if day_idx is None:
                    continue

                target_date = (
                    start_of_week
                    + timedelta(
                        days=(week_offset * 7 + day_idx)
                    )
                )

                expanded_rows.append({
                    "course_title": row["course_title"],
                    "schedule": schedule,
                    "day": day_name,
                    "date": target_date,
                    "week_offset": week_offset,
                    "week_label": week_label_from_offset(
                        week_offset
                    ),
                })

        # -------------------------------------
        # برای recurring
        # -------------------------------------

        if mode == "recurring":

            for day_name in days:

                day_idx = get_day_index(day_name)

                if day_idx is None:
                    continue

                expanded_rows.append({
                    "course_title": row["course_title"],
                    "schedule": schedule,
                    "day": day_name,
                    "date": None,
                    "week_offset": 999,
                    "week_label": "هفته‌های بعد",
                })

    # -----------------------------------------
    # مرتب‌سازی
    # -----------------------------------------

    expanded_rows.sort(
        key=lambda row: (
            row["date"].toordinal()
            if row["date"] is not None
            else 999999999,
            row["schedule"].get(
                "start_time",
                "99:99"
            ),
            row["course_title"],
        )
    )

    # -----------------------------------------
    # خروجی
    # -----------------------------------------

    current_datetime_text = get_current_persian_datetime_text()

    lines = [
        "📅 برنامه کل هفتگی من:",
        "",
        current_datetime_text,
        "",
        "━━━━━━━━━━━━━━━━━━",
    ]

    current_date = None
    current_week = None

    for row in expanded_rows:

        schedule = row["schedule"]

        target_date = row["date"]

        # -----------------------------------------
        # مشخص کردن هفته
        # -----------------------------------------

        if schedule.get("mode") == "specific_date":

            # برای تاریخ مشخص، هفته واقعی تقویمی را مشخص می‌کنیم
            week_start = target_date - timedelta(
                days=(target_date.weekday() + 2) % 7
            )

            if week_start != current_week:

                current_week = week_start
                current_date = None

                lines.append("")

                # اگر تاریخ در همین هفته است
                if (
                    week_start == start_of_week.date()
                ):
                    week_title = "این هفته"
                elif (
                    week_start
                    == (start_of_week + timedelta(days=7)).date()
                ):
                    week_title = "هفته بعد"
                else:
                    week_title = format_jalali_date(
                        week_start
                    )

                lines.append(
                    f"📌 {week_title}"
                )

        else:

            week_label = row["week_label"]

            if week_label != current_week:

                current_week = week_label
                current_date = None

                lines.append("")
                lines.append(
                    f"📌 {week_label}"
                )

        # -----------------------------------------
        # عنوان روز
        # -----------------------------------------

        day_text = format_day_with_date(
            target_date,
            row.get("day")
        )

        # -----------------------------------------
        # فقط وقتی روز تغییر کرده چاپ کن
        # -----------------------------------------

        if day_text != current_date:

            current_date = day_text

            lines.append(
                f"🔹 {day_text}"
            )

        # -----------------------------------------
        # ساعت
        # -----------------------------------------

        class_time = format_schedule_time(
            schedule
        )

        lines.append(
            f"• {row['course_title']} | ساعت {class_time}"
        )

    # -----------------------------------------
    # اگر به هر دلیلی هیچ ردیفی ساخته نشد
    # -----------------------------------------

    if not expanded_rows:
        return "برای درس‌های انتخابی تو هنوز هیچ برنامه‌ای ثبت نشده."

    return "\n".join(lines)

async def get_week_alarm_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_week_data()
    ensure_week_users_shape(data)

    user_id = get_week_user_id(update)
    ensure_user_week_data(data, user_id)

    save_week_data(data)

    await update.message.reply_text(
        get_week_panel_root_text(),
        reply_markup=build_user_week_root_keyboard(),
    )

    return WEEK_USER_ROOT


async def user_week_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = load_week_data()
    ensure_week_users_shape(data)

    user_id = get_week_user_id(update)
    user_data = ensure_user_week_data(data, user_id)

    callback = query.data or ""

    if callback == "uweek_close":
        save_week_data(data)
        await query.edit_message_text("✅ پنل برنامه هفتگی بسته شد.")
        return ConversationHandler.END

    if callback == "uweek_back_root":
        #save_week_data(data)
        await query.edit_message_text(
            get_week_panel_root_text(),
            reply_markup=build_user_week_root_keyboard(),
        )
        return WEEK_USER_ROOT

    if callback == "uweek_my_courses":
        text = format_my_courses_text(data, user_data)
        #save_week_data(data)

        await query.edit_message_text(
            text,
            reply_markup=build_my_courses_keyboard(),
        )
        return WEEK_USER_ROOT

    if callback == "uweek_add_course_menu":
        if not get_root_groups(data):
            await query.answer("هنوز هیچ گروهی توسط ادمین ساخته نشده.", show_alert=True)
            return WEEK_USER_ROOT

        await query.edit_message_text(
            "➕ افزودن درس\n\n"
            "راهنما:\n"
            "🔵 یعنی این مورد زیرمجموعه دارد.\n"
            "🟢 یعنی درس نهایی است و با کلیک اضافه می‌شود.",
            reply_markup=build_user_group_browser_keyboard(data, parent_id=None),
        )
        return WEEK_USER_ROOT

    if callback.startswith("uweek_browse:"):
        group_id = callback.split(":", 1)[1]

        if group_id in {"None", "", "null"}:
            await query.edit_message_text(
                "➕ افزودن درس\n\n"
                "🔵 زیرمجموعه دارد.\n"
                "🟢 درس نهایی است.",
                reply_markup=build_user_group_browser_keyboard(data, parent_id=None),
            )
            return WEEK_USER_ROOT

        group = data.get("groups", {}).get(group_id)
        if not group:
            await query.answer("این گروه پیدا نشد.", show_alert=True)
            return WEEK_USER_ROOT

        await query.edit_message_text(
            f"📁 {get_group_title_path(data, group_id)}\n\nزیرمجموعه را انتخاب کن:",
            reply_markup=build_user_group_browser_keyboard(data, parent_id=group_id),
        )
        return WEEK_USER_ROOT

    if callback.startswith("uweek_add_course:"):
        group_id = callback.split(":", 1)[1]

        group = data.get("groups", {}).get(group_id)
        if not group:
            await query.answer("این درس پیدا نشد.", show_alert=True)
            return WEEK_USER_ROOT

        if group_has_children(data, group_id):
            await query.edit_message_text(
                f"📁 {get_group_title_path(data, group_id)}\n\nاین مورد زیرمجموعه دارد؛ یکی را انتخاب کن:",
                reply_markup=build_user_group_browser_keyboard(data, parent_id=group_id),
            )
            return WEEK_USER_ROOT

        courses = user_data.setdefault("courses", [])
        course_title = get_group_title_path(data, group_id)

        if group_id in courses:
            await query.answer("این درس قبلاً اضافه شده.", show_alert=True)
        else:
            courses.append(group_id)
            await query.answer("درس اضافه شد.", show_alert=True)

        save_week_data(data)

        await query.edit_message_text(
            f"✅ درس اضافه شد:\n{course_title}\n\n"
            f"{format_my_courses_text(data, user_data)}",
            reply_markup=build_my_courses_keyboard(),
        )
        return WEEK_USER_ROOT

    if callback == "uweek_delete_course_menu":
        changed = clean_user_courses(data, user_data)
        courses = clean_user_courses(data, user_data)

        if not courses:
            if changed:
                save_week_data(data)
            await query.answer("هیچ درسی برای حذف نداری.", show_alert=True)
            await query.edit_message_text(
                format_my_courses_text(data, user_data),
                reply_markup=build_my_courses_keyboard(),
            )
            return WEEK_USER_ROOT
        if changed:
            save_week_data(data)

        await query.edit_message_text(
            "➖ حذف درس\n\nروی درسی که می‌خواهی حذف شود بزن:",
            reply_markup=build_delete_my_course_keyboard(data, user_data),
        )
        return WEEK_USER_ROOT

    if callback.startswith("uweek_delete_course:"):
        group_id = callback.split(":", 1)[1]
        course_title = get_group_title_path(data, group_id)

        old_courses = user_data.get("courses", [])
        user_data["courses"] = [item for item in old_courses if item != group_id]

        save_week_data(data)

        await query.edit_message_text(
            f"✅ درس حذف شد:\n{course_title}\n\n"
            f"{format_my_courses_text(data, user_data)}",
            reply_markup=build_my_courses_keyboard(),
        )
        return WEEK_USER_ROOT

    if callback == "uweek_full_schedule":
        text = format_user_full_schedule(data, user_data)
        #save_week_data(data)

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📚 درس‌های من", callback_data="uweek_my_courses")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="uweek_back_root")],
            ]),
        )
        return WEEK_USER_ROOT
    
    if callback == "uweek_alarm_menu":
        ensure_user_alarm_defaults(user_data)
        save_week_data(data)
    
        await query.edit_message_text(
            format_alarm_summary(data, user_data),
            reply_markup=build_alarm_root_keyboard(),
        )
        return WEEK_USER_ROOT
    
    if callback == "uweek_alarm_all":
        context.user_data["week_alarm_target"] = {"type": "all"}
        context.user_data["week_state"] = WEEK_WAITING_ALARM_DAYS
        await query.message.reply_text(
            "برای همه درس‌ها، چند روز قبل الارم داده شود؟\n"
            "مثال: 1 روز / 2 روز / 0"
        )
        return WEEK_WAITING_ALARM_DAYS

    if callback == "uweek_alarm_course_menu":
        courses = clean_user_courses(data, user_data)
        if not courses:
            await query.answer("اول باید حداقل یک درس اضافه کنی.", show_alert=True)
            return WEEK_USER_ROOT

        await query.edit_message_text(
            "درس موردنظر برای الارم اختصاصی را انتخاب کن:",
            reply_markup=build_alarm_course_picker_keyboard(data, user_data),
        )
        return WEEK_USER_ROOT

    if callback.startswith("uweek_alarm_course:"):
        group_id = callback.split(":", 1)[1]
        if group_id not in data.get("groups", {}):
            await query.answer("درس پیدا نشد.", show_alert=True)
            return WEEK_USER_ROOT

        context.user_data["week_alarm_target"] = {"type": "course", "group_id": group_id}
        context.user_data["week_state"] = WEEK_WAITING_ALARM_DAYS

        await query.message.reply_text(
            f"برای درس «{get_group_title_path(data, group_id)}» چند روز قبل الارم داده شود؟\n"
            "مثال: 1 روز / 2 روز / 0"
        )
        return WEEK_WAITING_ALARM_DAYS


    return WEEK_USER_ROOT

async def receive_week_alarm_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    value = parse_alarm_days_before(update.message.text or "")
    if value is None:
        await update.message.reply_text("❌ عدد معتبر وارد کن. مثال: 1 روز / 2 روز / 0")
        return WEEK_WAITING_ALARM_DAYS

    context.user_data["week_alarm_days_before"] = value
    context.user_data["week_state"] = WEEK_WAITING_ALARM_TIME

    await update.message.reply_text(
        "ساعت الارم را وارد کن.\n"
        "مثال: 06:00 یا 18:30"
    )
    return WEEK_WAITING_ALARM_TIME

def reset_alarm_sent_for_target(data, user_id, target):
    """
    وقتی کاربر زمان/روز الارم را تغییر می‌دهد،
    وضعیت ارسال الارم occurrenceهای مربوط به همان هدف را ریست می‌کند.
    """
    user_data = ensure_user_week_data(data, user_id)

    sent_map = user_data.setdefault("alarm_sent", {})

    if target["type"] == "all":
        # تغییر تنظیم کلی:
        # برای همه درس‌های کاربر وضعیت alarm_sent ریست شود.
        group_ids = clean_user_courses(data, user_data)

    else:
        # فقط همان درس
        group_id = target.get("group_id")
        group_ids = [group_id] if group_id else []

    changed = False

    for key in list(sent_map.keys()):
        for group_id in group_ids:
            prefix = f"{group_id}__"

            if key.startswith(prefix):
                sent_map.pop(key, None)
                changed = True
                break

    return changed
    
async def receive_week_alarm_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    time_value = normalize_time_value((update.message.text or "").strip())

    if not time_value:
        await update.message.reply_text(
            "❌ ساعت معتبر نیست. مثال درست: 06:00"
        )
        return WEEK_WAITING_ALARM_TIME

    data = load_week_data()
    ensure_week_users_shape(data)

    user_id = get_week_user_id(update)
    user_data = ensure_user_week_data(data, user_id)

    target = context.user_data.get("week_alarm_target")
    days_before = context.user_data.get("week_alarm_days_before", 1)

    if not target:
        await update.message.reply_text(
            "❌ مقصد الارم مشخص نیست. دوباره /get_alarm را بزن."
        )
        return ConversationHandler.END

    change = False

    # =========================
    # الارم همه درس‌ها
    # =========================

    if target["type"] == "all":

        new_alarm = {
            "days_before": days_before,
            "time": time_value,
        }

        old_alarm = user_data.get(
            "alarm_all",
            {
                "days_before": 1,
                "time": "06:00",
            }
        )

        if (
            old_alarm.get("days_before") != days_before
            or old_alarm.get("time") != time_value
        ):
            change = True

        user_data["alarm_all"] = new_alarm

        message = (
            f"✅ الارم همه درس‌ها تنظیم شد:\n"
            f"{days_before} روز قبل، ساعت {time_value}"
        )

    # =========================
    # الارم یک درس خاص
    # =========================

    else:

        group_id = target.get("group_id")

        if group_id not in data.get("groups", {}):
            await update.message.reply_text(
                "❌ درس پیدا نشد. دوباره تلاش کن."
            )
            return ConversationHandler.END

        new_alarm = {
            "days_before": days_before,
            "time": time_value,
        }

        old_alarm = user_data.setdefault(
            "course_alarms",
            {}
        ).get(group_id)

        if old_alarm is None:
            change = True

        elif (
            old_alarm.get("days_before") != days_before
            or old_alarm.get("time") != time_value
        ):
            change = True

        user_data.setdefault(
            "course_alarms",
            {}
        )[group_id] = new_alarm

        message = (
            f"✅ الارم درس "
            f"«{get_group_title_path(data, group_id)}» "
            f"تنظیم شد:\n"
            f"{days_before} روز قبل، ساعت {time_value}"
        )

    # ==========================================
    # اگر تنظیم تغییر کرده، وضعیت ارسال ریست شود
    # ==========================================

    if change:
        reset_alarm_sent_for_target(
            data,
            user_id,
            target,
        )

    # ==========================================
    # بررسی الارم فوری
    # ==========================================

    immediate_sent = await dispatch_immediate_alarm_after_user_setting(
        context.bot,
        data,
        user_id,
        target,
    )

    save_week_data(data)

    context.user_data["week_state"] = WEEK_USER_ROOT
    context.user_data.pop("week_alarm_target", None)
    context.user_data.pop("week_alarm_days_before", None)

    if immediate_sent:
        message += (
            "\n\n🔔 برای بعضی کلاس‌های نزدیک، "
            "یادآوری همین الان ارسال شد."
        )

    await update.message.reply_text(message)

    await update.message.reply_text(
        format_alarm_summary(data, user_data),
        reply_markup=build_alarm_root_keyboard(),
    )

    return WEEK_USER_ROOT

async def dispatch_immediate_alarm_after_user_setting(bot, data, user_id, target):
    now = get_now()
    user_data = ensure_user_week_data(data, user_id)
    ensure_user_alarm_defaults(user_data)

    if not user_data.get("alarm_enabled", True):
        return False

    if target["type"] == "all":
        group_ids = clean_user_courses(data, user_data)
    else:
        group_id = target.get("group_id")
        group_ids = [group_id] if group_id else []

    changed = False

    for group_id in group_ids:
        group = data.get("groups", {}).get(group_id)
        if not group:
            continue

        alarm_config = get_user_alarm_config_for_group(user_data, group_id)

        for schedule in group.get("schedules", []):
            occurrences = get_schedule_occurrences(schedule, horizon_weeks=8, now=now)

            for occurrence in occurrences:
                class_dt = occurrence["class_datetime"]
                alarm_dt = compute_alarm_datetime(class_dt, alarm_config)

                if alarm_dt <= now < class_dt:
                    sent = await send_alarm_for_occurrence(
                        bot,
                        data,
                        user_id,
                        group_id,
                        schedule,
                        occurrence,
                    )
                    if sent:
                        changed = True

    return changed


async def toggle_week_alarm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_week_data()
    ensure_week_users_shape(data)

    user_id = get_week_user_id(update)
    user_data = ensure_user_week_data(data, user_id)

    current = user_data.get("alarm_enabled", True)
    user_data["alarm_enabled"] = not current
    save_week_data(data)

    if user_data["alarm_enabled"]:
        await update.message.reply_text(
            "🔔 الارم‌ها روشن شدند.\n"
            "دیفالت فعلی: برای همه درس‌ها، 1 روز قبل، ساعت 06:00"
        )
    else:
        await update.message.reply_text("🔕 الارم‌ها خاموش شدند.")


# ==================الارم واقعی =====================

def get_now():
    return datetime.now(TEHRAN_TZ)
    
PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

def to_persian_digits(value):
    return str(value).translate(PERSIAN_DIGITS)


PERSIAN_MONTH_NAMES = {
    1: "فروردین",
    2: "اردیبهشت",
    3: "خرداد",
    4: "تیر",
    5: "مرداد",
    6: "شهریور",
    7: "مهر",
    8: "آبان",
    9: "آذر",
    10: "دی",
    11: "بهمن",
    12: "اسفند",
}
def get_current_persian_datetime_text():
    now = get_now()

    jalali = jdatetime.datetime.fromgregorian(datetime=now)

    weekdays = {
        0: "دوشنبه",
        1: "سه شنبه",
        2: "چهارشنبه",
        3: "پنج شنبه",
        4: "جمعه",
        5: "شنبه",
        6: "یک شنبه",
    }

    day_name = weekdays.get(now.weekday(), "")

    return (
        f"📆 امروز: {day_name} "
        f"{to_persian_digits(jalali.day)} "
        f"{PERSIAN_MONTH_NAMES[jalali.month]} "
        f"{to_persian_digits(jalali.year)}\n"
        f"🕐 ساعت الان: "
        f"{to_persian_digits(now.strftime('%H:%M:%S'))}"
    )
def get_week_panel_root_text():
    current_datetime_text = get_current_persian_datetime_text()

    return (
        "⏰ پنل برنامه هفتگی\n\n"
        f"{current_datetime_text}\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "یکی از گزینه‌ها را انتخاب کن:"
    )
    
def get_day_index(day_name: str):
    try:
        return ALL_DAYS.index(day_name)
    except ValueError:
        return None


def get_start_of_current_week(now=None):
    now = now or get_now()

    # Python weekday: Monday=0 ... Sunday=6
    # ما می‌خواهیم شنبه=0 ... جمعه=6
    day_map = {
        5: 0,  # Saturday
        6: 1,  # Sunday
        0: 2,  # Monday
        1: 3,  # Tuesday
        2: 4,  # Wednesday
        3: 5,  # Thursday
        4: 6,  # Friday
    }

    current_idx = day_map[now.weekday()]
    start_date = (now - timedelta(days=current_idx)).date()
    return start_date


def combine_date_and_hhmm(target_date, hhmm: str):
    hour, minute = [int(x) for x in hhmm.split(":")]
    return datetime(
        target_date.year, target_date.month, target_date.day,
        hour, minute, tzinfo=TEHRAN_TZ
    )


def get_schedule_occurrences(schedule, horizon_weeks=8, now=None):
    now = now or get_now()
    start_of_week = get_start_of_current_week(now)

    days = schedule.get("days", []) or []

    occurrences = []

    mode = schedule.get("mode", "single")
    week_offset = int(schedule.get("week_offset", 0))
    start_time = schedule.get("start_time")

    if not start_time:
        return occurrences

    for day_name in days:

        day_idx = get_day_index(day_name)

        if day_idx is None:
            continue

        if mode == "single":

            target_date = start_of_week + timedelta(
                days=(week_offset * 7 + day_idx)
            )

            class_dt = combine_date_and_hhmm(
                target_date,
                start_time
            )

            jalali = jdatetime.date.fromgregorian(
                date=target_date
            )

            occurrences.append({
                "class_datetime": class_dt,
                "day_name": day_name,
                "week_offset": week_offset,
                "mode": mode,

                # تاریخ شمسی واقعی
                "jalali_year": jalali.year,
                "jalali_month": jalali.month,
                "jalali_day": jalali.day,
            })

        else:

            for offset in range(horizon_weeks):

                target_date = start_of_week + timedelta(
                    days=(offset * 7 + day_idx)
                )

                class_dt = combine_date_and_hhmm(
                    target_date,
                    start_time
                )

                jalali = jdatetime.date.fromgregorian(
                    date=target_date
                )

                occurrences.append({
                    "class_datetime": class_dt,
                    "day_name": day_name,
                    "week_offset": offset,
                    "mode": mode,

                    # تاریخ شمسی واقعی
                    "jalali_year": jalali.year,
                    "jalali_month": jalali.month,
                    "jalali_day": jalali.day,
                })

    occurrences.sort(
        key=lambda x: x["class_datetime"]
    )

    return occurrences

def format_occurrence_jalali_date(occurrence):
    month = PERSIAN_MONTH_NAMES.get(
        occurrence.get("jalali_month"),
        ""
    )

    return (
        f"{to_persian_digits(occurrence.get('jalali_day'))} "
        f"{month} "
        f"{to_persian_digits(occurrence.get('jalali_year'))}"
    )

def build_occurrence_key(group_id, schedule, occurrence):
    schedule_id = schedule.get("id", "noid")
    class_dt = occurrence["class_datetime"].strftime("%Y-%m-%d %H:%M")
    return f"{group_id}__{schedule_id}__{class_dt}"


def get_user_alarm_config_for_group(user_data, group_id):
    ensure_user_alarm_defaults(user_data)
    course_alarm = user_data.get("course_alarms", {}).get(group_id)
    if course_alarm:
        return course_alarm
    return user_data.get("alarm_all", {"days_before": 1, "time": "06:00"})


def compute_alarm_datetime(class_dt, alarm_config):
    days_before = int(alarm_config.get("days_before", 1))
    alarm_time = alarm_config.get("time", "06:00")
    alarm_date = (class_dt - timedelta(days=days_before)).date()
    return combine_date_and_hhmm(alarm_date, alarm_time)


def canonical_week_label_for_offset(offset):
    if offset == 0:
        return "این هفته"
    if offset == 1:
        return "هفته بعد"
    return f"{offset} هفته بعد"


def format_alarm_fire_message(course_title, occurrence, schedule):
    week_label = canonical_week_label_for_offset(
        occurrence["week_offset"]
    )

    class_time = format_schedule_time(schedule)

    jalali_date = format_occurrence_jalali_date(occurrence)
    
    return (
        "🔔 یادآوری کلاس\n\n"
        f"درس: {course_title}\n"
        f"📅 تاریخ: {jalali_date}\n"
        f"📆 روز: {occurrence['day_name']}\n"
        f"📌 هفته: {week_label}\n"
        f"🕐 ساعت کلاس: {class_time}\n\n"
        "کلاس شما در این زمان برگزار می‌شود."
    )


def format_alarm_cancel_message(course_title, occurrence, schedule):
    week_label = canonical_week_label_for_offset(
        occurrence["week_offset"]
    )

    class_time = format_schedule_time(schedule)

    return (
        "🚫 اعلان کلاس لغو شد\n\n"
        f"درس: {course_title}\n"
        f"روز: {occurrence['day_name']}\n"
        f"هفته: {week_label}\n"
        f"ساعت کلاس: {class_time}\n\n"
        "این برنامه حذف یا کنسل شده است."
    )

def get_interested_user_ids_for_group(data, group_id):
    result = []
    users = data.get("users", {})
    for user_id, user_data in users.items():
        ensure_user_alarm_defaults(user_data)
        courses = clean_user_courses(data, user_data)
        if group_id in courses and user_data.get("alarm_enabled", True):
            result.append(user_id)
    return result


async def send_alarm_for_occurrence(bot, data, user_id, group_id, schedule, occurrence):
    user_data = ensure_user_week_data(data, user_id)
    sent_map = user_data.setdefault("alarm_sent", {})
    cancel_map = user_data.setdefault("alarm_cancel_sent", {})

    occurrence_key = build_occurrence_key(group_id, schedule, occurrence)
    if sent_map.get(occurrence_key):
        return False

    course_title = get_group_title_path(data, group_id)
    text = format_alarm_fire_message(course_title, occurrence, schedule)

    try:
        await bot.send_message(chat_id=int(user_id), text=text)
    except Exception:
        return False

    sent_map[occurrence_key] = get_now().strftime("%Y-%m-%d %H:%M:%S")
    cancel_map.pop(occurrence_key, None)
    return True


async def send_cancel_for_occurrence(bot, data, user_id, group_id, schedule, occurrence):
    user_data = ensure_user_week_data(data, user_id)
    sent_map = user_data.setdefault("alarm_sent", {})
    cancel_map = user_data.setdefault("alarm_cancel_sent", {})

    occurrence_key = build_occurrence_key(group_id, schedule, occurrence)

    if not sent_map.get(occurrence_key):
        return False

    if cancel_map.get(occurrence_key):
        return False

    course_title = get_group_title_path(data, group_id)
    text = format_alarm_cancel_message(course_title, occurrence, schedule)

    try:
        await bot.send_message(chat_id=int(user_id), text=text)
    except Exception:
        return False

    cancel_map[occurrence_key] = get_now().strftime("%Y-%m-%d %H:%M:%S")
    return True

async def process_weekly_alarm_queue(context: ContextTypes.DEFAULT_TYPE):
    try:
        data = load_week_data()
        ensure_week_users_shape(data)

        now = get_now()

        print("\n========== WEEKLY ALARM CHECK ==========")
        print("NOW:", now)

        changed = False

        for user_id, user_data in data.get("users", {}).items():

            print("\nUSER:", user_id)

            ensure_user_alarm_defaults(user_data)

            print("ALARM ENABLED:", user_data.get("alarm_enabled", True))

            if not user_data.get("alarm_enabled", True):
                print("⛔ Alarm disabled")
                continue

            courses = clean_user_courses(data, user_data)

            print("COURSES:", courses)

            for group_id in courses:

                group = data.get("groups", {}).get(group_id)

                if not group:
                    print("❌ GROUP NOT FOUND:", group_id)
                    continue

                alarm_config = get_user_alarm_config_for_group(
                    user_data,
                    group_id
                )

                print("\nGROUP:", group_id)
                print("ALARM CONFIG:", alarm_config)

                for schedule in group.get("schedules", []):

                    occurrences = get_schedule_occurrences(
                        schedule,
                        horizon_weeks=8,
                        now=now
                    )

                    print("SCHEDULE:", schedule)
                    print("OCCURRENCES:", len(occurrences))

                    for occurrence in occurrences:

                        class_dt = occurrence["class_datetime"]

                        alarm_dt = compute_alarm_datetime(
                            class_dt,
                            alarm_config
                        )

                        print("-------------------------")
                        print("CLASS:", class_dt)
                        print("ALARM:", alarm_dt)
                        print("NOW:", now)

                        if alarm_dt <= now < class_dt:

                            print("🔔 ALARM SHOULD SEND!")

                            sent = await send_alarm_for_occurrence(
                                context.bot,
                                data,
                                user_id,
                                group_id,
                                schedule,
                                occurrence,
                            )

                            print("SEND RESULT:", sent)

                            if sent:
                                changed = True

        if changed:
            save_week_data(data)

        print("========== CHECK FINISHED ==========\n")

    except Exception as e:
        print("❌ WEEKLY ALARM ERROR:", repr(e))
        import traceback
        traceback.print_exc()

async def dispatch_immediate_alarms_for_new_schedules(bot, data, group_id, schedules):
    now = get_now()
    changed = False
    user_ids = get_interested_user_ids_for_group(data, group_id)

    for user_id in user_ids:
        user_data = ensure_user_week_data(data, user_id)
        alarm_config = get_user_alarm_config_for_group(user_data, group_id)

        for schedule in schedules:
            occurrences = get_schedule_occurrences(schedule, horizon_weeks=8, now=now)

            for occurrence in occurrences:
                class_dt = occurrence["class_datetime"]
                alarm_dt = compute_alarm_datetime(class_dt, alarm_config)

                if alarm_dt <= now < class_dt:
                    sent = await send_alarm_for_occurrence(
                        bot,
                        data,
                        user_id,
                        group_id,
                        schedule,
                        occurrence,
                    )
                    if sent:
                        changed = True

    if changed:
        save_week_data(data)

async def dispatch_cancel_for_removed_schedules(bot, data, group_id, removed_schedules):
    now = get_now()
    changed = False
    user_ids = get_interested_user_ids_for_group(data, group_id)

    for user_id in user_ids:
        for schedule in removed_schedules:
            occurrences = get_schedule_occurrences(schedule, horizon_weeks=8, now=now)

            for occurrence in occurrences:
                class_dt = occurrence["class_datetime"]
                if class_dt < now:
                    continue

                sent = await send_cancel_for_occurrence(
                    bot,
                    data,
                    user_id,
                    group_id,
                    schedule,
                    occurrence,
                )
                if sent:
                    changed = True

    if changed:
        save_week_data(data)

def collect_group_and_children_ids(data, group_id):
    result = [group_id]
    group = data.get("groups", {}).get(group_id, {})
    for child_id in group.get("children", []):
        result.extend(collect_group_and_children_ids(data, child_id))
    return result

# ========== بکاپ دستی ===============
# وضعیت برای ConversationHandler جدید
WEEK_WAITING_BACKUP_FILE = 99

async def handle_week_backup_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "week_backup_get":
        if not os.path.exists(WEEK_FILE):
            await query.message.reply_text("❌ فایل بکاپ `week.json` پیدا نشد.")
            return WEEK_ROOT

        try:
            with open(WEEK_FILE, "rb") as backup_file:
                await query.message.reply_document(
                    document=backup_file,
                    filename="week.json",
                    caption="📥 این هم فایل بکاپ فعلی الارم‌ها."
                )
        except Exception as e:
            await query.message.reply_text(f"❌ خطا در ارسال بکاپ:\n`{e}`")

        return WEEK_ROOT

    if query.data == "week_backup_upload_prompt":
        cancel_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ لغو", callback_data="week_backup_cancel")]
        ])

        await query.edit_message_text(
            "📤 لطفاً فایل `week.json` جدید را به صورت Document بفرستید.",
            reply_markup=cancel_keyboard,
            parse_mode="Markdown"
        )
        return WEEK_WAITING_BACKUP_FILE

    if query.data == "week_backup_cancel":
        await query.edit_message_text(
            "❌ عملیات وارد کردن بکاپ لغو شد.",
            reply_markup=build_week_root_keyboard(load_week_data())
        )
        return WEEK_ROOT

    return WEEK_ROOT


async def receive_week_backup_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.document:
        await update.message.reply_text("❌ لطفاً فایل را به صورت Document بفرستید (نه عکس یا متن).")
        return WEEK_WAITING_BACKUP_FILE

    # دانلود فایل جدید
    new_file = await update.message.document.get_file()
    temp_path = "/tmp/new_week.json"
    await new_file.download_to_drive(temp_path)

    # تست سلامت فایل JSON
    try:
        with open(temp_path, "r", encoding="utf-8") as f:
            new_data = json.load(f)
        
        # اگر فرمت درست بود، جایگزین کن
        with open(WEEK_FILE, "w", encoding="utf-8") as f:
            json.dump(new_data, f, ensure_ascii=False, indent=2)
        
        # بکاپ جدید را هم به تلگرام بفرست که sync شود
        upload_weekly_to_telegram() 
        
        await update.message.reply_text(
            "✅ فایل با موفقیت جایگزین شد و در گروه بکاپ هم آپلود شد.",
            reply_markup=build_week_root_keyboard(load_week_data())
        )
    except Exception as e:
        await update.message.reply_text(f"❌ خطا در خواندن فایل. مطمئن شوید JSON سالم است.\n{e}")
    
    # حذف فایل موقت
    if os.path.exists(temp_path):
        os.remove(temp_path)
        
    return WEEK_ROOT # بازگشت به منوی اصلی
