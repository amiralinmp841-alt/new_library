import json
import os

DB_FILE = os.getenv("DB_FILE", "/tmp/database.json")

def load_db():
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def get_style(node):
    return node.get("color") or node.get("style") or node.get("node_style") or "none"

def get_rows(node):
    """
    این تابع مستقیماً دیتابیس شما را می‌خواند.
    اگر layout سفارشی باشد، همان را برمی‌گرداند.
    اگر نباشد، بر اساس row_count چیدمان می‌کند.
    """
    children_ids = node.get("children", [])
    layout = node.get("layout")

    # ۱. اگر لایوت سفارشی (لیست لیست‌ها) وجود دارد، همان را برگردان
    if isinstance(layout, list) and layout:
        return layout

    # ۲. اگر لایوت ندارد، بر اساس row_count چیدمان کن
    n = node.get("row_count", 2)
    try:
        n = int(n)
    except:
        n = 2
    
    # تقسیم لیست اصلی به ردیف‌ها
    return [children_ids[i:i + n] for i in range(0, len(children_ids), n)]

def serialize_contents(contents):
    texts = []
    media_counts = {}
    for c in contents:
        t = c.get("type")
        if t == "text":
            texts.append(c.get("text", ""))
        else:
            media_counts[t] = media_counts.get(t, 0) + 1
    return {"texts": texts, "media": media_counts}

def get_breadcrumb(db, node_id):
    path = []
    cur = node_id
    while cur:
        node = db.get(cur)
        if not node: break
        path.append({"id": cur, "name": node.get("name", "بدون نام")})
        cur = node.get("parent")
    path.reverse()
    return path

def serialize_node(db, node_id):
    node = db.get(node_id)
    if not node: return None

    # دریافت ردیف‌ها از تابع اصلاح‌شده
    rows_ids = get_rows(node)
    
    rows = []
    for row_ids in rows_ids:
        row = []
        for cid in row_ids:
            child = db.get(cid)
            if child:
                row.append({
                    "id": cid,
                    "name": child.get("name", "بدون نام"),
                    "style": get_style(child),
                    "has_children": bool(child.get("children")),
                    "content_count": len(child.get("contents", [])),
                })
        if row:
            rows.append(row)

    return {
        "id": node_id,
        "name": node.get("name", "بدون نام"),
        "parent": node.get("parent"),
        "style": get_style(node),
        "contents": serialize_contents(node.get("contents", [])),
        "rows": rows,
        "breadcrumb": get_breadcrumb(db, node_id),
    }

def get_node_json(node_id="root"):
    return serialize_node(load_db(), node_id)
