from rapidfuzz import fuzz
import re


# =========================================================
# 1) مترادف‌ها و واژه‌های هم‌معنی
# =========================================================
MEDICAL_SYNONYMS = {
    # ===== علوم پایه =====
    "اناتومی": [
        "کالبد شناسی", "کالبدشناسی", "تشریح", "علوم تشریح", "anatomy"
    ],
    "هیستولوژی": [
        "بافت شناسی", "بافت‌شناسی", "histology"
    ],
    "امبریولوژی": [
        "جنین شناسی", "جنین‌شناسی", "embryology"
    ],
    "فیزیولوژی": [
        "فیزیولوژی بدن", "عملکرد بدن", "physiology"
    ],
    "بیوشیمی": [
        "biochemistry"
    ],
    "ژنتیک": [
        "genetics"
    ],
    "ایمونولوژی": [
        "ایمنی شناسی", "ایمنی‌شناسی", "immunology"
    ],
    "میکروب شناسی": [
        "میکروب‌شناسی", "باکتریولوژی", "ویروس شناسی", "ویروس‌شناسی",
        "قارچ شناسی", "قارچ‌شناسی", "microbiology"
    ],
    "ویروس شناسی": [
        "ویروس‌شناسی", "virology"
    ],
    "باکتریولوژی": [
        "باکتری شناسی", "باکتری‌شناسی", "microbiology"
    ],
    "قارچ شناسی": [
        "قارچ‌شناسی", "mycology"
    ],
    "انگل شناسی": [
        "انگل‌شناسی", "پارازیتولوژی", "parasitology"
    ],
    "پاتولوژی": [
        "آسیب شناسی", "آسیب‌شناسی", "pathology", "histopathology", "histopathology"
    ],
    "فارماکولوژی": [
        "داروشناسی", "pharmacology"
    ],

    # ===== بالینی =====
    "داخلی": ["internal", "internal medicine", "طب داخلی"],
    "جراحی": ["surgery", "surgical"],
    "اطفال": ["کودکان", "پدیاتری", "پزشکی کودکان", "pediatrics"],
    "زنان": ["زنان و زایمان", "مامایی", "obgyn", "obstetrics", "gynecology"],
    "روانپزشکی": ["سایک", "psychiatry"],
    "نورولوژی": ["مغز و اعصاب", "neurology"],
    "ارتوپدی": ["orthopedics", "ارتو", "جراحی استخوان"],
    "اورولوژی": ["urology"],
    "قلب": ["قلب و عروق", "کاردیولوژی", "cardiology"],
    "ریه": ["pulmonology", "تنفس", "بیماری های ریه"],
    "غدد": ["اندوکرین", "endocrine", "endocrinology"],
    "عفونی": ["بیماری های عفونی", "infectious", "infectious disease"],
    "پوست": ["درماتولوژی", "dermatology"],
    "چشم": ["افتالمولوژی", "ophthalmology"],
    "گوش": ["گوش و حلق و بینی", "otolaryngology", "ent"],
    "بیهوشی": ["anesthesia", "anesthesiology"],
    "اورژانس": ["emergency", "طب اورژانس"],
    "رادیولوژی": ["تصویربرداری", "radiology"],
    "رادیوتراپی": ["پرتودرمانی", "radiotherapy"],
    "انکولوژی": ["سرطان", "oncology"],
    "طب فیزیکی": ["توانبخشی", "rehab", "rehabilitation", "pmr"],

    # ===== آناتومی های جزئی =====
    "اناتومی اندام": [
        "آناتومی اندام", "اندام", "اناتومی اسکلتی عضلانی",
        "اسکلتی عضلانی", "musculoskeletal anatomy", "msk anatomy"
    ],
    "اناتومی تنه": [
        "آناتومی تنه", "تنه", "thorax", "abdomen anatomy"
    ],
    "اناتومی سر و گردن": [
        "سر و گردن", "head and neck anatomy", "head neck"
    ],
    "نورواناتومی": [
        "neuroanatomy", "آناتومی اعصاب", "آناتومی مغز"
    ],

    # ===== آموزشی =====
    "کلاس": ["جلسه", "lesson", "session"],
    "جلسه": ["کلاس", "lesson", "session"],
    "نظری": ["تئوری", "theory", "theoretical"],
    "تئوری": ["نظری", "theory", "theoretical"],
    "عملی": ["لاب", "آزمایشگاه", "practical", "lab"],
    "مرور": ["جمع بندی", "جمع‌بندی", "review"],
    "جزوه": ["نوت", "یادداشت", "note", "notes"],
    "نمونه سوال": ["سوالات", "questions", "exam", "امتحان"],
    "امتحان": ["آزمون", "exam", "test"],
    "آزمون": ["امتحان", "exam", "test"],

    # ===== مدیا / فرمت =====
    "وویس": ["صدا", "صوت", "voice", "audio"],
    "ویس": ["وویس", "صدا", "صوت", "voice", "audio"],
    "صدا": ["وویس", "صوت", "voice", "audio"],
    "صوت": ["وویس", "صدا", "voice", "audio"],
    "ویدیو": ["فیلم", "video", "movie", "کلیپ"],
    "فیلم": ["ویدیو", "video", "movie", "کلیپ"],
    "کلیپ": ["ویدیو", "فیلم", "video"],
    "پاور": ["پاورپوینت", "اسلاید", "presentation", "ppt", "pptx"],
    "پاورپوینت": ["پاور", "اسلاید", "presentation", "ppt", "pptx"],
    "اسلاید": ["پاور", "پاورپوینت", "presentation", "slide"],
    "pdf": ["پی دی اف", "جزوه pdf"],
    "کتاب": ["بوک", "book"],
    "مقاله": ["article", "paper"],
    "فایل": ["document", "doc", "مدرک"],
}


# =========================================================
# 2) نرمال‌سازی متن
# =========================================================
def normalize_text(text: str) -> str:
    if not text:
        return ""

    text = str(text)

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

    text = text.lower()

    # حذف HTML
    text = re.sub(r"<[^>]+>", " ", text)

    # حذف پسوند فایل‌ها
    text = re.sub(
        r"\.(pdf|doc|docx|ppt|pptx|xls|xlsx|zip|rar|mp3|mp4|mkv|avi|jpg|jpeg|png)$",
        " ",
        text,
        flags=re.IGNORECASE
    )

    # حذف علائم
    text = re.sub(r"[^\w\sآ-ی]", " ", text)

    # فشرده‌سازی فاصله‌ها
    text = re.sub(r"\s+", " ", text).strip()

    return text


# =========================================================
# 3) ساخت مترادف دوطرفه
# =========================================================
def build_bidirectional_synonyms(synonyms_dict):
    result = {}

    for key, values in synonyms_dict.items():
        all_terms = set([key] + values)
        normalized_terms = {normalize_text(term) for term in all_terms if term}

        for term in normalized_terms:
            result.setdefault(term, set()).update(normalized_terms - {term})

    return result


BIDIRECTIONAL_SYNONYMS = build_bidirectional_synonyms(MEDICAL_SYNONYMS)


def get_synonyms(term: str):
    term_norm = normalize_text(term)
    return list(BIDIRECTIONAL_SYNONYMS.get(term_norm, []))


def expand_query_terms(query: str):
    query_norm = normalize_text(query)
    words = query_norm.split()

    expanded = set(words)

    # عبارت کامل
    if query_norm in BIDIRECTIONAL_SYNONYMS:
        expanded.update(BIDIRECTIONAL_SYNONYMS[query_norm])

    # تک‌واژه‌ها
    for word in words:
        expanded.update(get_synonyms(word))

    # bigram ها
    for i in range(len(words) - 1):
        phrase = f"{words[i]} {words[i + 1]}"
        expanded.update(get_synonyms(phrase))

    return expanded


# =========================================================
# 4) استخراج متن‌های قابل جستجو از داخل پوشه
#    - file_name
#    - caption
#    - 50 کاراکتر اول متن
# =========================================================
def get_content_texts(node):
    texts = []

    for item in node.get("contents", []):
        # اسم فایل
        file_name = item.get("file_name") or item.get("title")
        if file_name:
            texts.append(str(file_name))

        # کپشن
        caption = item.get("caption")
        if caption:
            texts.append(str(caption))

        # متن خام: فقط 50 کاراکتر اول
        if item.get("type") == "text":
            raw_text = item.get("text", "")
            if raw_text:
                texts.append(str(raw_text)[:50])

    return " ".join(texts)


# =========================================================
# 5) فلت‌کردن دیتابیس برای سرچ فقط روی پوشه‌ها
# =========================================================
def flatten_db_for_search(db):
    results = []

    # پیدا کردن ریشه‌های واقعی
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

        search_text = normalize_text(
            f"{node_name} {path_text} {contents_text}"
        )

        # فقط خود پوشه به عنوان نتیجه
        if node_id != "root":
            results.append({
                "node_id": node_id,
                "title": node_name,
                "path": " ⬅️ ".join(new_path_parts),
                "search_text": search_text,
                "name_norm": normalize_text(node_name),
                "path_norm": normalize_text(path_text),
                "content_norm": normalize_text(contents_text),
            })

        for child_id in node.get("children", []):
            walk(child_id, new_path_parts)

    for start in start_nodes:
        walk(start, [])

    return results


# =========================================================
# 6) سرچ هوشمند
#    - فایل‌ها نتیجه نمی‌شوند
#    - فقط پوشه نتیجه است
#    - اسم فایل / کپشن / 50 کاراکتر اول متن روی score اثر می‌گذارند
# =========================================================
def smart_search(db, query, limit=5, min_score=45):
    query_norm = normalize_text(query)
    if not query_norm:
        return []

    expanded_terms = expand_query_terms(query)
    items = flatten_db_for_search(db)

    results = []

    for item in items:
        search_text = item["search_text"]
        name_norm = item["name_norm"]
        path_norm = item["path_norm"]
        content_norm = item["content_norm"]

        # امتیازهای پایه
        score_name = fuzz.token_set_ratio(query_norm, name_norm)
        score_path = fuzz.token_set_ratio(query_norm, path_norm)
        score_content = fuzz.token_set_ratio(query_norm, content_norm)
        score_partial = fuzz.partial_ratio(query_norm, search_text)
        score_wratio = fuzz.WRatio(query_norm, search_text)

        base_score = max(
            score_name,
            score_path,
            score_content,
            score_partial,
            score_wratio
        )

        # بونوس مترادف‌ها
        synonym_bonus = 0
        for term in expanded_terms:
            if not term:
                continue

            if term in name_norm:
                synonym_bonus += 8
            elif term in path_norm:
                synonym_bonus += 5
            elif term in content_norm:
                synonym_bonus += 3

        synonym_bonus = min(synonym_bonus, 30)

        # وزن‌دهی بهتر
        final_score = max(
            base_score,
            score_name * 0.95 + score_path * 0.85 + score_content * 0.55
        ) + synonym_bonus

        final_score = min(100, int(final_score))

        if final_score >= min_score:
            results.append({
                "node_id": item["node_id"],
                "type": "node",
                "title": item["title"],
                "path": item["path"],
                "score": final_score
            })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:limit]
