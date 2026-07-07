from rapidfuzz import fuzz
import re

# --- دیکشنری مترادفات پزشکی ---
MEDICAL_SYNONYMS = {
    "اناتومی": ["علوم تشریح", "تشریح", "anatomy"],
    "علوم تشریح": ["اناتومی", "تشریح", "anatomy"],
    "هیستولوژی": ["بافت شناسی", "histology"],
    "بافت شناسی": ["هیستولوژی", "histology"],
    "پاتولوژی": ["اسیب شناسی", "آسیب شناسی", "pathology"],
    "فیزیولوژی": ["physiology"],
    "بیوشیمی": ["biochemistry"],
    "فارماکولوژی": ["داروشناسی", "pharmacology"],
}

def normalize_text(text: str) -> str:
    if not text: return ""
    text = str(text).lower()
    replacements = {"ي": "ی", "ك": "ک", "ۀ": "ه", "ة": "ه", "آ": "ا", "أ": "ا", "\u200c": " ", "_": " ", "-": " "}
    for old, new in replacements.items():
        text = text.replace(old, new)
    # حذف پسوند فایل‌ها برای جلوگیری از تطابق اشتباه
    text = re.sub(r"\.(pdf|mp4|mp3|jpg|jpeg|zip|docx|pptx)\b", " ", text)
    text = re.sub(r"[^\w\sآ-ی]", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def expand_query(query: str) -> str:
    """اضافه کردن هم‌معنی‌ها به کوئری کاربر"""
    tokens = normalize_text(query).split()
    expanded = list(tokens)
    for t in tokens:
        for key, syns in MEDICAL_SYNONYMS.items():
            if t == key or t in syns:
                expanded.extend([normalize_text(key)] + [normalize_text(s) for s in syns])
    return " ".join(list(dict.fromkeys(expanded)))

def build_search_documents(db, root_node_id="root"):
    """تبدیل دیتابیس به لیست تخت از پوشه‌ها و فایل‌ها"""
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
        if not node: return
        
        path_parts = get_path_parts(node_id)
        node_name = node.get("name", "")
        path_str = " ⬅️ ".join(path_parts)

        # ۱. اضافه کردن خود پوشه به عنوان یک نتیجه
        if node_id != "root":
            documents.append({
                "type": "node",
                "id": node_id,
                "title": node_name,
                "path": path_str,
                "search_text": normalize_text(f"{node_name} {' '.join(path_parts)}")
            })

        # ۲. اضافه کردن تک‌تک محتویات (فایل‌ها) به عنوان نتایج مستقل
        for idx, item in enumerate(node.get("contents", [])):
            # استخراج بهترین نام برای فایل (نام فایل یا کپشن)
            f_name = item.get("file_name") or item.get("caption") or item.get("text") or "فایل بدون نام"
            # تمیز کردن برای نمایش (فقط خط اول یا ۶۰ کاراکتر اول)
            display_title = str(f_name).split('\n')[0][:60]
            
            documents.append({
                "type": "content",
                "id": node_id, # آیدی پوشه والد برای دیپ‌لینک
                "content_index": idx,
                "title": display_title,
                "path": path_str,
                "search_text": normalize_text(f"{f_name} {item.get('caption', '')} {node_name} {' '.join(path_parts)}")
            })

        for child_id in node.get("children", []):
            walk(child_id)

    walk(root_node_id)
    return documents

def smart_search(db, query, root_node_id="root", limit=6, min_score=40):
    query_norm = normalize_text(query)
    if not query_norm: return []
    
    expanded_q = expand_query(query)
    docs = build_search_documents(db, root_node_id)
    results = []

    for doc in docs:
        # جلوگیری از ۱۰۰٪ کاذب: اگر کلمه خیلی کوتاه است، سخت‌گیرانه‌تر عمل کن
        if len(query_norm) < 4:
            score = fuzz.token_set_ratio(expanded_q, doc["search_text"])
        else:
            score = max(fuzz.token_set_ratio(expanded_q, doc["search_text"]), 
                        fuzz.partial_ratio(expanded_q, doc["search_text"]) * 0.9) # کاهش وزن تطابق جزئی

        if score >= min_score:
            doc["score"] = score
            results.append(doc)

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:limit]
