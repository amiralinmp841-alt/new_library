from rapidfuzz import fuzz
import re

# =========================================================
# ۱) مترادف‌های تخصصی پزشکی و آموزشی
# =========================================================
MEDICAL_SYNONYMS = {
    # علوم پایه و بالینی
    "اناتومی": ["کالبد شناسی", "کالبدشناسی", "تشریح", "علوم تشریح", "anatomy"],
    "هیستولوژی": ["بافت شناسی", "بافت‌شناسی", "histology"],
    "امبریولوژی": ["جنین شناسی", "جنین‌شناسی", "embryology"],
    "فیزیولوژی": ["عملکرد بدن", "physiology"],
    "بیوشیمی": ["biochemistry"],
    "ژنتیک": ["genetics"],
    "ایمونولوژی": ["ایمنی شناسی", "ایمنی‌شناسی", "immunology"],
    "میکروب شناسی": ["میکروب‌شناسی", "باکتریولوژی", "ویروس شناسی", "ویروس‌شناسی", "قارچ شناسی", "قارچ‌شناسی", "microbiology"],
    "پاتولوژی": ["آسیب شناسی", "آسیب‌شناسی", "pathology", "histopathology"],
    "فارماکولوژی": ["داروشناسی", "pharmacology"],
    "داخلی": ["internal medicine", "طب داخلی", "internal"],
    "جراحی": ["surgery", "surgical"],
    "اطفال": ["کودکان", "پدیاتری", "pediatrics"],
    "زنان": ["زنان و زایمان", "مامایی", "obgyn", "gynecology"],
    "روانپزشکی": ["سایک", "psychiatry"],
    "نورولوژی": ["مغز و اعصاب", "neurology"],
    "ارتوپدی": ["orthopedics", "ارتو"],
    "اورولوژی": ["urology"],
    "قلب": ["کاردیولوژی", "cardiology"],
    "ریه": ["pulmonology"],
    "غدد": ["اندوکرین", "endocrine", "endocrinology"],
    "عفونی": ["بیماری های عفونی", "infectious"],
    "پوست": ["درماتولوژی", "dermatology"],
    "چشم": ["افتالمولوژی", "ophthalmology"],
    "گوش": ["گوش و حلق و بینی", "ent"],
    "بیهوشی": ["anesthesia"],
    "اورژانس": ["emergency", "طب اورژانس"],
    "رادیولوژی": ["تصویربرداری", "radiology"],
    "انکولوژی": ["سرطان", "oncology"],

    # اصطلاحات آموزشی و مدیا
    "کلاس": ["جلسه", "lesson", "session"],
    "جلسه": ["کلاس", "lesson", "session"],
    "نظری": ["تئوری", "theory"],
    "تئوری": ["نظری", "theory"],
    "عملی": ["لاب", "آزمایشگاه", "practical", "lab"],
    "مرور": ["جمع بندی", "جمع‌بندی", "review"],
    "جزوه": ["نوت", "یادداشت", "note", "notes"],
    "نمونه سوال": ["سوالات", "questions", "exam", "امتحان"],
    "امتحان": ["آزمون", "exam", "test"],
    "آزمون": ["امتحان", "exam", "test"],
    "وویس": ["صدا", "صوت", "voice", "audio"],
    "ویس": ["وویس", "صدا", "صوت", "voice", "audio"],
    "صدا": ["وویس", "صوت", "voice", "audio"],
    "ویدیو": ["فیلم", "video", "media"],
    "فیلم": ["ویدیو", "video"],
    "پاور": ["پاورپوینت", "اسلاید", "presentation", "ppt", "pptx"],
    "پاورپوینت": ["پاور", "اسلاید", "presentation", "ppt", "pptx"],
    "اسلاید": ["پاور", "پاورپوینت", "presentation", "slide"],
    "pdf": ["پی دی اف", "جزوه pdf"],
    "کتاب": ["بوک", "book"],
    "مقاله": ["article", "paper"],
}

# =========================================================
# ۲) نرمال‌سازی متن (پاکسازی کاراکترهای عربی و علائم)
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
    
    # حذف تگ‌های HTML در صورت وجود در متون دیتابیس
    text = re.sub(r"<[^>]+>", " ", text)
    
    # حذف پسوند فایل‌ها برای جلوگیری از تداخل در جستجوی نام فایل
    text = re.sub(
        r"\.(pdf|doc|docx|ppt|pptx|xls|xlsx|zip|rar|mp3|mp4|mkv|avi|jpg|jpeg|png)$",
        " ",
        text,
        flags=re.IGNORECASE
    )

    # حذف علائم نگارشی و کاراکترهای اضافه
    text = re.sub(r"[^\w\sآ-ی]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    return text

# =========================================================
# ۳) ساخت دیکشنری مترادف‌های دوطرفه و بسط کوئری
# =========================================================
def build_bidirectional_synonyms(syn_dict):
    bidirectional = {}
    for key, values in syn_dict.items():
        all_terms = set([key] + values)
        normalized_terms = {normalize_text(t) for t in all_terms if t}
        for term in normalized_terms:
            bidirectional.setdefault(term, set()).update(normalized_terms - {term})
    return bidirectional

BIDIRECTIONAL_SYNONYMS = build_bidirectional_synonyms(MEDICAL_SYNONYMS)

def expand_query_terms(query: str):
    query_norm = normalize_text(query)
    words = query_norm.split()
    expanded = set(words)

    # بررسی انطباق کل عبارت
    if query_norm in BIDIRECTIONAL_SYNONYMS:
        expanded.update(BIDIRECTIONAL_SYNONYMS[query_norm])

    # بررسی انطباق تک‌واژه‌ها
    for word in words:
        if word in BIDIRECTIONAL_SYNONYMS:
            expanded.update(BIDIRECTIONAL_SYNONYMS[word])
            
    return expanded

# =========================================================
# ۴) استخراج اطلاعات فایل‌های درون پوشه (با محدودیت ۵۰ حرف اول متن‌ها)
# =========================================================
def get_contents_data(node):
    """
    استخراج جداگانه نام فایل‌ها، کپشن‌ها و بخش کوتاه متون متنی 
    برای اعمال وزن‌دهی تفکیک‌شده در امتیازدهی.
    """
    file_names = []
    captions = []
    short_texts = []

    for item in node.get("contents", []):
        item_type = item.get("type")

        # ۱. نام فایل (برای انواع مدیا و اسناد)
        file_name = item.get("file_name") or item.get("title")
        if file_name:
            file_names.append(file_name)

        # ۲. کپشن فایل‌ها
        caption = item.get("caption")
        if caption:
            captions.append(caption)

        # ۳. متون متنی (فقط ۵۰ کاراکتر اول)
        if item_type == "text":
            text_val = item.get("text", "")
            if text_val:
                short_texts.append(text_val[:50])

    return {
        "file_names": " ".join(file_names),
        "captions": " ".join(captions),
        "short_texts": " ".join(short_texts)
    }

# =========================================================
# ۵) تخت‌سازی دیتابیس با حفظ ساختار محتویات تفکیک شده
# =========================================================
def flatten_db_for_search(db):
    results = []
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
        contents = get_contents_data(node)

        # آماده‌سازی متون نرمال‌شده برای هر بخش به صورت مجزا
        node_name_norm = normalize_text(node_name)
        path_norm = normalize_text(path_text)
        file_names_norm = normalize_text(contents["file_names"])
        captions_norm = normalize_text(contents["captions"])
        short_texts_norm = normalize_text(contents["short_texts"])

        if node_id != "root":
            results.append({
                "node_id": node_id,
                "title": node_name,
                "path": " ⬅️ ".join(new_path_parts),
                "node_name_norm": node_name_norm,
                "path_norm": path_norm,
                "file_names_norm": file_names_norm,
                "captions_norm": captions_norm,
                "short_texts_norm": short_texts_norm
            })

        for child_id in node.get("children", []):
            walk(child_id, new_path_parts)

    for start in start_nodes:
        walk(start, [])

    return results

# =========================================================
# ۶) تابع اصلی سرچ هوشمند با منطق امتیازدهی وزن‌دار
# =========================================================
def smart_search(db, query, limit=5, min_score=45):
    query_norm = normalize_text(query)
    if not query_norm:
        return []

    expanded_terms = expand_query_terms(query)
    items = flatten_db_for_search(db)
    results = []

    for item in items:
        # دریافت متون بخش‌های مختلف پوشه
        n_norm = item["node_name_norm"]
        p_norm = item["path_norm"]
        f_norm = item["file_names_norm"]
        c_norm = item["captions_norm"]
        t_norm = item["short_texts_norm"]

        # الف) محاسبه میزان شباهت کوئری اصلی با هر بخش
        # امتیاز نام پوشه (بالاترین اهمیت)
        score_name = max(
            fuzz.token_set_ratio(query_norm, n_norm),
            fuzz.partial_ratio(query_norm, n_norm) * 0.9
        )
        
        # امتیاز مسیر پوشه
        score_path = max(
            fuzz.token_set_ratio(query_norm, p_norm),
            fuzz.partial_ratio(query_norm, p_norm) * 0.85
        )

        # امتیاز محتویات داخلی پوشه (تأثیرگذار ولی غیر حیاتی - مانع از ۱۰۰ شدن الکی امتیاز کل)
        score_file = fuzz.token_set_ratio(query_norm, f_norm) * 0.8  # نام فایل‌ها
        score_caption = fuzz.token_set_ratio(query_norm, c_norm) * 0.65  # کپشن‌ها
        score_text = fuzz.token_set_ratio(query_norm, t_norm) * 0.5  # ۵۰ حرف اول متن‌ها

        # ادغام امتیازهای خام بر اساس اولویت
        base_score = max(score_name, score_path, score_file, score_caption, score_text)

        # ب) اعمال بونوس مترادف‌ها به صورت وزن‌دار
        # (مترادف‌ها نمره را کمی ارتقا می‌دهند تا نتایج مرتبط بالا بیایند ولی تضمین‌کننده نمره ۱۰۰ نیستند)
        synonym_bonus = 0
        for term in expanded_terms:
            if not term or term == query_norm:
                continue
            if term in n_norm:
                synonym_bonus += 10
            elif term in p_norm:
                synonym_bonus += 7
            elif term in f_norm:
                synonym_bonus += 5
            elif term in c_norm:
                synonym_bonus += 3
            elif term in t_norm:
                synonym_bonus += 2

        # محدود کردن سقف بونوس مترادف‌ها برای جلوگیری از امتیازهای کاذب
        synonym_bonus = min(synonym_bonus, 20)

        # محاسبه نهایی امتیاز ترکیب شده
        final_score = base_score + synonym_bonus
        final_score = min(100, int(final_score))

        # ج) فیلتر کردن بر اساس حداقل امتیاز
        if final_score >= min_score:
            results.append({
                "node_id": item["node_id"],
                "title": item["title"],
                "path": item["path"],
                "score": final_score
            })

    # د) مرتب‌سازی نزولی بر اساس امتیاز
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:limit]
