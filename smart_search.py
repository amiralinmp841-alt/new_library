from rapidfuzz import fuzz
import re


MEDICAL_SYNONYMS = {
    "اناتومی": ["علوم تشریح", "تشریح", "anatomy"],
    "علوم تشریح": ["اناتومی", "تشریح", "anatomy"],
    "تشریح": ["اناتومی", "علوم تشریح", "anatomy"],

    "هیستولوژی": ["بافت شناسی", "histology"],
    "بافت شناسی": ["هیستولوژی", "histology"],

    "پاتولوژی": ["آسیب شناسی", "اسيب شناسی", "pathology"],
    "آسیب شناسی": ["پاتولوژی", "pathology"],

    "فارماکولوژی": ["داروشناسی", "pharmacology"],
    "داروشناسی": ["فارماکولوژی", "pharmacology"],

    "فیزیولوژی": ["physiology"],
    "بیوشیمی": ["biochemistry"],
}


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

    # حذف پسوند فایل‌ها
    text = re.sub(r"\.(pdf|mp4|mp3|zip|rar|doc|docx|ppt|pptx|jpg|jpeg|png)\b", " ", text, flags=re.IGNORECASE)

    # حذف علائم اضافی
    text = re.sub(r"[^\w\sآ-ی]", " ", text)

    # فاصله‌های اضافه
    text = re.sub(r"\s+", " ", text).strip()

    return text


def expand_query(query: str) -> str:
    query_norm = normalize_text(query)
    tokens = query_norm.split()
    expanded = list(tokens)

    for token in tokens:
        for key, values in MEDICAL_SYNONYMS.items():
            norm_key = normalize_text(key)
            norm_vals = [normalize_text(v) for v in values]

            if token == norm_key or token in norm_vals:
                expanded.append(norm_key)
                expanded.extend(norm_vals)

    # حذف تکراری با حفظ ترتیب
    return " ".join(dict.fromkeys(expanded))


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

        # خود پوشه
        if node_id != "root":
            search_text = normalize_text(f"{node_name} {path_text}")
            results.append({
                "result_type": "node",
                "node_id": node_id,
                "title": node_name,
                "path": " ⬅️ ".join(new_path_parts),
                "search_text": search_text,
            })

        # محتواهای داخل پوشه
        for idx, item in enumerate(node.get("contents", [])):
            item_type = item.get("type")

            text_parts = []

            file_name = item.get("file_name")
            caption = item.get("caption")
            text_value = item.get("text")

            if file_name:
                text_parts.append(file_name)

            if caption:
                text_parts.append(caption)

            if item_type == "text" and text_value:
                text_parts.append(text_value)

            if not text_parts:
                continue

            # برای نمایش نام فایل
            display_name = (
                file_name
                or caption
                or (text_value[:60] if text_value else "بدون نام")
            )
            display_name = str(display_name).strip().split("\n")[0][:80]

            content_search_text = normalize_text(
                f"{' '.join(text_parts)} {node_name} {path_text}"
            )

            results.append({
                "result_type": "content",
                "node_id": node_id,
                "content_index": idx,
                "title": display_name,
                "path": " ⬅️ ".join(new_path_parts),
                "search_text": content_search_text,
            })

        for child_id in node.get("children", []):
            walk(child_id, new_path_parts)

    for start in start_nodes:
        walk(start, [])

    return results


def smart_search(db, query, limit=5, min_score=45):
    query_norm = normalize_text(query)

    if not query_norm:
        return []

    expanded_query = expand_query(query)
    items = flatten_db_for_search(db)
    results = []

    for item in items:
        text = item["search_text"]

        score_1 = fuzz.token_set_ratio(expanded_query, text)
        score_2 = fuzz.WRatio(expanded_query, text)

        # partial برای کوئری‌های کوتاه خیلی کاذب می‌شود، پس وزنش کمتر
        score_3 = fuzz.partial_ratio(expanded_query, text) * 0.88

        # اگر سرچ خیلی کوتاه بود، partial را عملاً کم‌اثرتر کن
        if len(query_norm) <= 3:
            score = max(score_1, score_2)
        else:
            score = max(score_1, score_2, score_3)

        if score >= min_score:
            results.append({
                "result_type": item["result_type"],
                "node_id": item["node_id"],
                "content_index": item.get("content_index"),
                "title": item["title"],
                "path": item["path"],
                "score": score,
            })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:limit]
