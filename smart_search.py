from rapidfuzz import fuzz
import re
import copy

# --- دیکشنری هم‌معنی‌ها و معادل‌های پزشکی ---
MEDICAL_SYNONYMS = {
    "اناتومی": ["علوم تشریح", "تشریح", "anatomy"],
    "علوم تشریح": ["اناتومی", "تشریح", "anatomy"],
    "تشریح": ["اناتومی", "علوم تشریح", "anatomy"],
    "anatomy": ["اناتومی", "علوم تشریح", "تشریح"],

    "هیستولوژی": ["بافت شناسی", "histology"],
    "بافت شناسی": ["هیستولوژی", "histology"],
    "histology": ["هیستولوژی", "بافت شناسی"],

    "پاتولوژی": ["اسیب شناسی", "آسیب شناسی", "pathology"],
    "آسیب شناسی": ["پاتولوژی", "اسیب شناسی", "pathology"],
    "اسیب شناسی": ["پاتولوژی", "آسیب شناسی", "pathology"],
    "pathology": ["پاتولوژی", "آسیب شناسی", "اسیب شناسی"],

    "فیزیولوژی": ["physiology"],
    "physiology": ["فیزیولوژی"],

    "بیوشیمی": ["biochemistry"],
    "biochemistry": ["بیوشیمی"],

    "فارماکولوژی": ["داروشناسی", "pharmacology"],
    "داروشناسی": ["فارماکولوژی", "pharmacology"],
    "pharmacology": ["فارماکولوژی", "داروشناسی"],
    
    "جنینی": ["جنین شناسی", "embryology"],
    "جنین شناسی": ["جنینی", "embryology"],
    "embryology": ["جنینی", "جنین شناسی"],
}

def normalize_text(text: str) -> str:
    """نرمالایز کردن متن برای جستجو (تبدیل حروف، حذف پسوندهای فایل، حذف علائم غیرضروری)."""
    if not text:
        return ""

    text = str(text)

    # جایگزینی حروف عربی به فارسی و فاصله‌های مجازی
    replacements = {
        "ي": "ی", "ك": "ک", "ۀ": "ه", "ة": "ه",
        "ؤ": "و", "إ": "ا", "أ": "ا", "آ": "ا",
        "\u200c": " ",
        "_": " ", "-": " ",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)

    text = text.lower()

    # حذف پسوند فایل‌ها برای جلوگیری از تداخل در جستجوی نام فایل
    text = re.sub(r"\.(pdf|epub|mobi|mp4|mp3|jpg|jpeg|png|docx?|pptx?|xlsx?|zip|rar)\b", " ", text, flags=re.IGNORECASE)

    # حذف کاراکترهای غیر الفبایی (فقط حروف فارسی، انگلیسی و اعداد)
    text = re.sub(r"[^\w\sآ-ی]", " ", text)

    # حذف فاصله‌های تکراری
    text = re.sub(r"\s+", " ", text).strip()

    return text


def expand_query_with_synonyms(query: str) -> str:
    """بسط دادن عبارت جستجو شده با کلمات هم‌معنی پزشکی."""
    query_norm = normalize_text(query)
    if not query_norm:
        return ""

    tokens = query_norm.split()
    expanded_tokens = list(tokens)

    # بررسی تک‌کلمه‌ها
    for token in tokens:
        if token in MEDICAL_SYNONYMS:
            expanded_tokens.extend(normalize_text(s) for s in MEDICAL_SYNONYMS[token])

    # بررسی عبارت کامل
    for key, synonyms in MEDICAL_SYNONYMS.items():
        if normalize_text(key) == query_norm:
            expanded_tokens.extend(normalize_text(s) for s in synonyms)

    # حذف تکراری‌ها و حفظ ترتیب
    seen = set()
    final_tokens = []
    for t in expanded_tokens:
        if t and t not in seen:
            seen.add(t)
            final_tokens.append(t)

    return " ".join(final_tokens)


def get_file_display_name(item):
    """یافتن بهترین نام برای نمایش فایل (نام فایل ذخیره شده، عنوان یا کپشن)."""
    preferred_keys = ["file_name", "filename", "title", "name", "caption"]
    for key in preferred_keys:
        value = item.get(key)
        if value and str(value).strip():
            # اگر کپشن خیلی طولانی بود، خلاصه آن را استفاده کن
            val_str = str(value).strip()
            return val_str[:60] + "..." if len(val_str) > 63 else val_str
            
    item_type = item.get("type", "file")
    return f"{item_type.capitalize()} File"


def build_search_documents(db, root_node_id="root"):
    """
    تبدیل دیتابیس درختی به لیستی مسطح از اسناد (پوشه‌ها و محتوای فایل‌ها به صورت جداگانه).
    فقط زیرشاخه مشخص شده در root_node_id پیمایش می‌شود (برای سرچ در پوشه فعلی).
    """
    documents = []
    if root_node_id not in db:
        return documents

    def build_node_path(node_id):
        parts = []
        current = node_id
        while current and current in db:
            if current != "root":
                parts.append(db[current].get("name", ""))
            current = db[current].get("parent")
        parts.reverse()
        return parts

    def walk(node_id):
        node = db.get(node_id)
        if not node:
            return

        path_parts = build_node_path(node_id)
        node_name = node.get("name", "")
        display_path = " ⬅️ ".join(path_parts) if path_parts else "Root"

        # ۱. اضافه کردن خود پوشه (نود)
        if node_id != "root":
            folder_search_text = normalize_text(f"{node_name} {' '.join(path_parts)}")
            documents.append({
                "result_type": "node",
                "node_id": node_id,
                "content_index": None,
                "title": node_name,
                "path": display_path,
                "search_text": folder_search_text
            })

        # ۲. اضافه کردن تک‌تک فایل‌ها و محتویات داخل پوشه به عنوان نتایج مستقل
        for idx, item in enumerate(node.get("contents", [])):
            item_type = item.get("type", "")
            
            text_parts_for_search = []
            
            # نام فایل
            file_display_name = get_file_display_name(item)
            if file_display_name:
                text_parts_for_search.append(file_display_name)
                
            # کپشن فایل
            caption = item.get("caption", "")
            if caption:
                text_parts_for_search.append(caption)

            # متن پیام متنی
            if item_type == "text":
                text_value = item.get("text", "")
                if text_value:
                    text_parts_for_search.append(text_value)

            # افزودن نام پوشه والد و مسیر برای جستجوی متنی دقیق‌تر
            if node_name:
                text_parts_for_search.append(node_name)
            text_parts_for_search.extend(path_parts)

            content_search_text = normalize_text(" ".join(text_parts_for_search))

            documents.append({
                "result_type": "content",
                "node_id": node_id,
                "content_index": idx,
                "title": file_display_name,
                "path": display_path,
                "search_text": content_search_text,
                "file_type": item_type
            })

        # پیمایش فرزندان
        for child_id in node.get("children", []):
            walk(child_id)

    walk(root_node_id)
    return documents


def smart_search(db, query, root_node_id="root", limit=5, min_score=45):
    """جستجوی هوشمند در اسناد به همراه برطرف کردن انطباق‌های ۱۰۰ کاذب."""
    query_norm = normalize_text(query)
    if not query_norm:
        return []

    # توسعه کوئری با هم‌معنی‌ها
    expanded_query = expand_query_with_synonyms(query)
    
    # ساخت لیست اسناد
    items = build_search_documents(db, root_node_id)
    results = []

    for item in items:
        text = item["search_text"]
        if not text:
            continue

        # محاسبه انواع الگوهای فازی
        score_set = fuzz.token_set_ratio(expanded_query, text)
        score_partial = fuzz.partial_ratio(expanded_query, text)
        score_wratio = fuzz.WRatio(expanded_query, text)

        # جلوگیری از انطباق ۱۰۰ کاذب (Partial Matchهای بسیار کوتاه که امتیاز کاذب می‌گیرند)
        if len(query_norm) <= 4 and score_partial == 100:
            # اگر کوئری خیلی کوتاه است، به جای تطابق جزئی، به انطباق توکن‌ها یا تطابق کامل وزن بدهید
            score = max(score_set, score_wratio * 0.8)
        else:
            score = max(score_set, score_partial, score_wratio)

        # اگر کوئری دقیقاً در عنوان سند وجود داشت، امتیاز اضافی (Bonus) بدهیم
        title_norm = normalize_text(item["title"])
        if query_norm in title_norm:
            score = max(score, 90.0)
            if title_norm.startswith(query_norm):
                score = max(score, 98.0)

        if score >= min_score:
            results.append({
                "node_id": item["node_id"],
                "content_index": item["content_index"],
                "result_type": item["result_type"],
                "title": item["title"],
                "path": item["path"],
                "score": score
            })

    # مرتب‌سازی نزولی
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:limit]
