from rapidfuzz import fuzz
import re

# دیکشنری مترادفات تخصصی پزشکی
MEDICAL_SYNONYMS = {
    "اناتومی": ["علوم تشریح", "کالبد شناسی", "کالبدشناسی", "تشریح"],
    "علوم تشریح": ["آناتومی", "کالبد شناسی", "کالبدشناسی", "تشریح"],
    "پاتولوژی": ["آسیب شناسی", "آسیب‌شناسی"],
    "آسیب شناسی": ["پاتولوژی"],
    "فیزیولوژی": ["تن کارشناختی", "عملکرد بدن"],
    "ایمونولوژی": ["ایمنی شناسی", "ایمنی‌شناسی"],
    "پارازیتولوژی": ["انگل شناسی", "انگل‌شناسی"],
    "باکتریولوژی": ["میکروب شناسی", "باکتری شناسی"],
    "ویروسولوژی": ["ویروس شناسی"],
    "قارچولوژی": ["قارچ شناسی"],
}

def strip_html_tags(text: str) -> str:
    """حذف تگ‌های HTML برای جلوگیری از تأثیر منفی روی درصد تطابق"""
    if not text:
        return ""
    clean = re.compile('<.*?>')
    return re.sub(clean, '', text)

def normalize_text(text: str) -> str:
    if not text:
        return ""

    text = str(text)
    text = strip_html_tags(text)

    replacements = {
        "ي": "ی",
        "ك": "ک",
        "ۀ": "ه",
        "ة": "ه",
        "ؤ": "و",
        "إ": "ا",
        "أ": "ا",
        "آ": "ا",
        "\u200c": " ",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    text = text.lower()

    # حذف پسوندهای رایج فایل
    text = re.sub(r'\.(pdf|docx|zip|rar|mp4|mp3|jpg|png|jpeg|apk)$', ' ', text)

    # حذف علائم اضافی و نگارشی
    text = re.sub(r"[^\w\sآ-ی]", " ", text)

    # فاصله‌های اضافه
    text = re.sub(r"\s+", " ", text).strip()

    return text

def get_synonyms(word: str):
    """دریافت مترادفات کلمه"""
    word_norm = normalize_text(word)
    return MEDICAL_SYNONYMS.get(word_norm, [])

def get_content_texts(node):
    """
    استخراج متون کمکی از محتوای یک نود جهت بهبود رتبه پوشه:
    - نام فایل‌ها (file_name)
    - کپشن‌ها (caption)
    - ۵۰ کاراکتر اول پیام‌های متنی (text)
    """
    texts = []

    for item in node.get("contents", []):
        item_type = item.get("type")

        # ۱. اضافه کردن نام فایل
        file_name = item.get("file_name") or item.get("title")
        if file_name:
            texts.append(str(file_name))

        # ۲. اضافه کردن کپشن
        caption = item.get("caption")
        if caption:
            texts.append(str(caption))

        # ۳. اضافه کردن فقط ۵۰ کاراکتر اول محتوای متنی
        if item_type == "text":
            text_content = item.get("text", "")
            if text_content:
                texts.append(text_content[:50])

    return " ".join(texts)

def flatten_db_for_search(db):
    results = []

    # پیدا کردن ریشه‌های دیتابیس
    start_nodes = []
    for node_id, node in db.items():
        parent = node.get("parent")
        if not parent or parent not in db:
            start_nodes.append(node_id)

    def walk(node_id, path_parts):
        node = db.get(node_id)
        if not node:
            return

        node_name = node.get("name", "")
        new_path_parts = path_parts.copy()

        if node_id != "root":
            new_path_parts.append(node_name)

        path_text = " ".join(new_path_parts)
        contents_text = get_content_texts(node)

        # ساخت متن نهایی برای جستجو
        search_text = normalize_text(
            f"{node_name} {path_text} {contents_text}"
        )

        if node_id != "root":
            results.append({
                "node_id": node_id,
                "title": node_name,
                "path": " ⬅️ ".join(new_path_parts),
                "search_text": search_text,
                "node_name_norm": normalize_text(node_name)
            })

        for child_id in node.get("children", []):
            walk(child_id, new_path_parts)

    for start in start_nodes:
        walk(start, [])

    return results

def smart_search(db, query, limit=15, min_score=45):
    query_norm = normalize_text(query)
    if not query_norm:
        return []

    query_words = query_norm.split()
    items = flatten_db_for_search(db)
    results = []

    for item in items:
        text = item["search_text"]
        node_name_norm = item["node_name_norm"]

        # ۱. محاسبه تطابق کلی (مسیر + محتوای درون پوشه)
        score_1 = fuzz.token_set_ratio(query_norm, text)
        score_2 = fuzz.partial_ratio(query_norm, text)
        score_3 = fuzz.WRatio(query_norm, text)
        base_score = max(score_1, score_2, score_3)

        # ۲. بررسی کلمات کلیدی مترادف درون نام نود یا مسیر
        synonym_bonus = 0
        for word in query_words:
            synonyms = get_synonyms(word)
            for syn in synonyms:
                syn_norm = normalize_text(syn)
                if syn_norm and syn_norm in text:
                    # اگر مترادف مستقیم در نام نود بود امتیاز بیشتری بگیرد
                    if syn_norm in node_name_norm:
                        synonym_bonus += 20
                    else:
                        synonym_bonus += 10

        final_score = min(100, base_score + synonym_bonus)

        if final_score >= min_score:
            results.append({
                "node_id": item["node_id"],
                "result_type": "folder",  # تمام خروجی‌ها پوشه هستند
                "score": final_score
            })

    # مرتب‌سازی بر اساس درصد تطابق
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:limit]
