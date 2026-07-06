from rapidfuzz import fuzz
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
import re
import numpy as np

# مدل فقط یک بار هنگام اجرای ربات لود می‌شود
embedding_model = SentenceTransformer(
    "paraphrase-multilingual-mpnet-base-v2"
)

def normalize_text(text: str) -> str:
    if not text:
        return ""

    text = str(text)

    # ۱. نقشه جایگزینی کاراکترهای خاص
    replacements = {
        "ي": "ی", "ك": "ک", "ۀ": "ه", "ة": "ه", "ؤ": "و",
        "إ": "ا", "أ": "ا", "آ": "ا", "\u200c": " ",
    }

    # ۲. نقشه تبدیل اعداد فارسی و کلمات ترتیبی به عدد واحد
    # این لیست را می‌توانید بر اساس نیاز گسترش دهید
    ordinal_replacements = {
        "اول": "1", "یک": "1",
        "دوم": "2", "دو": "2",
        "سوم": "3", "سه": "3",
        "چهارم": "4", "چهار": "4",
        "پنجم": "5", "پنج": "5",
        "ششم": "6", "شش": "6",
        "هفتم": "7", "هفت": "7",
        "هشتم": "8", "هشت": "8",
        "نهم": "9", "نه": "9",
        "دهم": "10", "ده": "10",
        "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4",
        "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9"
    }

    # جایگزینی حروف
    for old, new in replacements.items():
        text = text.replace(old, new)

    # جایگزینی کلمات ترتیبی و اعداد (با استفاده از کلمات کامل)
    # توجه: باید کلمات طولانی‌تر را اول چک کنیم تا تداخل پیش نیاید
    for old, new in sorted(ordinal_replacements.items(), key=lambda x: len(x[0]), reverse=True):
        text = text.replace(old, new)

    text = text.lower()

    # حذف علائم اضافی (به جز اعداد و حروف فارسی)
    text = re.sub(r"[^\w\sآ-ی0-9]", " ", text)

    # فاصله‌های اضافه
    text = re.sub(r"\s+", " ", text).strip()

    return text


def get_content_texts(node):
    """
    متن قابل جستجو از محتواهای یک نود:
    - متن‌ها
    - کپشن فایل‌ها
    """
    texts = []

    for item in node.get("contents", []):
        item_type = item.get("type")

        if item_type == "text":
            texts.append(item.get("text", ""))

        caption = item.get("caption")
        if caption:
            texts.append(caption)

    return " ".join(texts)


def flatten_db_for_search(db):
    results = []

    # پیدا کردن ریشه دیتابیس (نودی که parent ندارد یا parent داخل db نیست)
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

        if node_id not in start_nodes:
            results.append({
                "node_id": node_id,
                "title": node_name,
                "path": " ⬅️ ".join(new_path_parts),
                "search_text": search_text
            })
            
        for child_id in node.get("children", []):
            walk(child_id, new_path_parts)

    # شروع از ریشه‌های واقعی
    for start in start_nodes:
        walk(start, [])

    return results

def embedding_search(db, query, limit=5, threshold=0.45):

    query_norm = normalize_text(query)

    if not query_norm:
        return []


    items = flatten_db_for_search(db)

    if not items:
        return []


    texts = [
        item["search_text"]
        for item in items
    ]


    # تبدیل دیتابیس به بردار
    vectors = embedding_model.encode(
        texts,
        convert_to_numpy=True
    )


    # تبدیل سرچ کاربر
    query_vector = embedding_model.encode(
        [query_norm],
        convert_to_numpy=True
    )


    scores = cosine_similarity(
        query_vector,
        vectors
    )[0]


    results = []


    for item, score in zip(items, scores):

        if score >= threshold:

            results.append({
                "node_id": item["node_id"],
                "title": item["title"],
                "path": item["path"],
                "score": score * 100
            })


    results.sort(
        key=lambda x: x["score"],
        reverse=True
    )


    return results[:limit]


def smart_search(db, query, limit=5, min_score=45):

    # =========================
    # مرحله اول: Embedding
    # =========================

    semantic_results = embedding_search(
        db,
        query,
        limit=limit,
        threshold=0.45
    )


    # اگر جواب معنایی پیدا شد
    if semantic_results:
        return semantic_results



    # =========================
    # مرحله دوم: RapidFuzz
    # =========================

    query_norm = normalize_text(query)

    if not query_norm:
        return []


    items = flatten_db_for_search(db)

    results = []


    for item in items:

        text = item["search_text"]


        score_1 = fuzz.token_set_ratio(
            query_norm,
            text
        )

        score_2 = fuzz.partial_ratio(
            query_norm,
            text
        )

        score_3 = fuzz.WRatio(
            query_norm,
            text
        )


        score = max(
            score_1,
            score_2,
            score_3
        )


        if score >= min_score:

            results.append({
                "node_id": item["node_id"],
                "title": item["title"],
                "path": item["path"],
                "score": score
            })


    results.sort(
        key=lambda x:x["score"],
        reverse=True
    )


    return results[:limit]
