from rapidfuzz import fuzz
import re

# --- دیکشنری مترادفات تخصصی پزشکی ---
MEDICAL_SYNONYMS = {
    "اناتومی": ["علوم تشریح", "تشریح", "anatomy"],
    "علوم تشریح": ["اناتومی", "تشریح", "anatomy"],
    "تشریح": ["اناتومی", "علوم تشریح", "anatomy"],
    "هیستولوژی": ["بافت شناسی", "بافت", "histology"],
    "بافت شناسی": ["هیستولوژی", "بافت", "histology"],
    "پاتولوژی": ["اسیب شناسی", "آسیب شناسی", "pathology"],
    "اسیب شناسی": ["پاتولوژی", "آسیب شناسی", "pathology"],
    "آسیب شناسی": ["پاتولوژی", "اسیب شناسی", "pathology"],
    "فیزیولوژی": ["physiology"],
    "بیوشیمی": ["biochemistry"],
    "فارماکولوژی": ["داروشناسی", "pharmacology"],
    "داروشناسی": ["فارماکولوژی", "pharmacology"],
    "نورولوژی": ["مغز و اعصاب", "neurology"],
    "مغز و اعصاب": ["نورولوژی", "neurology"],
    "کاردیولوژی": ["قلب و عروق", "قلب", "cardiology"],
}

def normalize_text(text: str) -> str:
    if not text:
        return ""

    text = str(text).lower()

    # یکسان‌سازی کاراکترهای عربی و فارسی و نیم‌فاصله‌ها
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
        "_": " ",
        "-": " ",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    # حذف پسوندهای متداول فایل جهت جلوگیری از تداخل در جستجو
    text = re.sub(r"\.(pdf|mp4|mp3|zip|rar|docx|pptx|png|jpg|jpeg)\b", " ", text)

    # حذف علائم اضافی به جز حروف و اعداد فارسی و انگلیسی
    text = re.sub(r"[^\w\sآ-ی]", " ", text)

    # حذف فاصله‌های اضافه
    text = re.sub(r"\s+", " ", text).strip()

    return text

def expand_query(query: str) -> str:
    """
    بسط دادن کوئری کاربر با استفاده از دیکشنری هم‌معنی‌ها
    """
    normalized_q = normalize_text(query)
    tokens = normalized_q.split()
    expanded_tokens = list(tokens)

    for token in tokens:
        for key, synonyms in MEDICAL_SYNONYMS.items():
            norm_key = normalize_text(key)
            norm_syns = [normalize_text(s) for s in synonyms]
            
            if token == norm_key or token in norm_syns:
                expanded_tokens.append(norm_key)
                expanded_tokens.extend(norm_syns)

    # حذف توکن‌های تکراری و حفظ ترتیب
    return " ".join(list(dict.fromkeys(expanded_tokens)))

def build_search_documents(db, root_node_id="root"):
    """
    تبدیل دیتابیس درختی به یک لیست تخت از اسناد قابل جستجو (پوشه‌ها و فایل‌ها).
    """
    documents = []

    def get_path_parts(node_id):
        parts = []
        curr = node_id
        while curr and curr in db and curr != "root":
            parts.append(db[curr].get("name", ""))
            curr = db[curr].get("parent")
        return list(reversed(parts))

    def walk(node_id):
        node = db.get(node_id)
        if not node:
            return

        path_parts = get_path_parts(node_id)
        node_name = node.get("name", "")
        path_str = " ⬅️ ".join(path_parts)

        # ۱. افزودن خود پوشه به عنوان یک هدف جستجوی مستقل
        if node_id != "root":
            documents.append({
                "type": "node",
                "node_id": node_id,
                "title": node_name,
                "path": path_str,
                "search_text": normalize_text(f"{node_name} {' '.join(path_parts)}")
            })

        # ۲. افزودن تک‌تک فایل‌ها/محتویات داخل پوشه به عنوان هدف مستقل
        for idx, item in enumerate(node.get("contents", [])):
            # استخراج نام برای فایل (اولویت با نام واقعی فایل، سپس کپشن، سپس متن)
            file_name = item.get("file_name") or item.get("caption") or item.get("text") or "فایل بدون نام"
            
            # تمیزکاری نام برای نمایش در نتایج (خط اول تا حداکثر ۶۰ کاراکتر)
            display_title = str(file_name).split('\n')[0][:60].strip()
            
            # تجمیع متن سرچ فایل: اسم فایل + کپشن + نام پوشه والد + کل مسیر پوشه
            caption_text = item.get("caption") or ""
            search_text_raw = f"{file_name} {caption_text} {node_name} {' '.join(path_parts)}"
            
            documents.append({
                "type": "content",
                "node_id": node_id,
                "content_index": idx,
                "title": display_title,
                "path": path_str,
                "search_text": normalize_text(search_text_raw)
            })

        for child_id in node.get("children", []):
            walk(child_id)

    walk(root_node_id)
    return documents

def smart_search(db, query, root_node_id="root", limit=5, min_score=45):
    query_norm = normalize_text(query)
    if not query_norm:
        return []

    # بسط دادن عبارات جستجو با دیکشنری مترادف‌ها
    query_expanded = expand_query(query)
    
    # ساخت لیست تخت اسناد
    documents = build_search_documents(db, root_node_id)
    results = []

    for doc in documents:
        text = doc["search_text"]

        # اگر کوئری کاربر خیلی کوتاه باشد (کمتر از ۴ کاراکتر) برای جلوگیری از تطابق‌های کاذب
        # از الگوریتم سخت‌گیرانه‌تر استفاده می‌کنیم.
        if len(query_norm) < 4:
            score = fuzz.token_set_ratio(query_expanded, text)
        else:
            # ترکیب روش‌ها با ضریب تعدیل جزیی (کاهش وزن جزئی partial_ratio به میزان ۹۰٪ برای کاهش نتایج کاذب)
            score_set = fuzz.token_set_ratio(query_expanded, text)
            score_partial = fuzz.partial_ratio(query_expanded, text) * 0.9
            score_w = fuzz.WRatio(query_expanded, text)
            score = max(score_set, score_partial, score_w)

        if score >= min_score:
            doc_copy = doc.copy()
            doc_copy["score"] = score
            results.append(doc_copy)

    # مرتب‌سازی بر اساس بیشترین امتیاز
    results.sort(key=lambda x: x["score"], reverse=True)

    return results[:limit]
