import json
import os
from aiohttp import web

# تعیین داینامیک مسیر دیتابیس جهت سازگاری کامل با ویندوز و لینوکس
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.environ.get("DATABASE_PATH", os.path.join(BASE_DIR, "database.json"))

def load_db():
    try:
        if not os.path.exists(DB_FILE):
            # اگر فایل در پوشه جاری نبود، بررسی مسیر پیش‌فرض ریشه پروژه
            parent_db = os.path.join(os.path.dirname(BASE_DIR), "database.json")
            if os.path.exists(parent_db):
                with open(parent_db, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data if isinstance(data, dict) else {}
            return {}

        with open(DB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        return data if isinstance(data, dict) else {}

    except Exception as e:
        print("miniapp load_db error:", repr(e))
        return {}

def get_style(node):
    raw_style = node.get("color") or node.get("style") or node.get("node_style") or "none"
    return str(raw_style).strip().lower()

def get_rows(node):
    children_ids = [str(cid) for cid in node.get("children", [])]
    layout = node.get("layout")

    if isinstance(layout, list) and layout:
        cleaned = []
        child_set = set(children_ids)
        for row in layout:
            if isinstance(row, list):
                new_row = [str(cid) for cid in row if str(cid) in child_set]
                if new_row:
                    cleaned.append(new_row)
        if cleaned:
            return cleaned

    try:
        n = int(node.get("row_count", 2))
        n = n if n > 0 else 2
    except:
        n = 2

    return [children_ids[i:i+n] for i in range(0, len(children_ids), n)]

def serialize_contents(contents):
    result = []
    for item in contents or []:
        if not isinstance(item, dict):
            continue

        c_type = item.get("type", "unknown")
        text_val = item.get("text") or item.get("content") or ""
        caption_val = item.get("caption", "")
        file_name = (
            item.get("file_name")
            or item.get("filename")
            or item.get("document_name")
            or item.get("title")
            or ""
        )

        result.append({
            "type": c_type,
            "text": text_val,
            "caption": caption_val,
            "file_name": file_name
        })

    return result

def get_breadcrumb(db, node_id):
    path = []
    seen = set()
    cur = str(node_id)

    while cur and cur not in seen:
        seen.add(cur)
        node = db.get(cur)
        if not node:
            break
        path.append({
            "id": cur,
            "name": node.get("name", "بدون نام")
        })
        cur = str(node.get("parent")) if node.get("parent") else None

    path.reverse()
    return path

def serialize_node(db, node_id):
    str_node_id = str(node_id)
    node = db.get(str_node_id)
    if not node:
        return None

    children_ids = [str(cid) for cid in node.get("children", [])]
    rows_ids = get_rows(node)

    rows = []
    for row_ids in rows_ids:
        row = []
        for cid in row_ids:
            child = db.get(str(cid))
            if child:
                row.append({
                    "id": str(cid),
                    "name": child.get("name", "بدون نام"),
                    "style": get_style(child),
                    "has_children": bool(child.get("children")),
                    "content_count": len(child.get("contents", [])),
                })
        if row:
            rows.append(row)

    return {
        "id": str_node_id,
        "name": node.get("name", "بدون نام"),
        "parent": node.get("parent"),
        "style": get_style(node),
        "children_count": len(children_ids),
        "contents": serialize_contents(node.get("contents", [])),
        "rows": rows,
        "breadcrumb": get_breadcrumb(db, str_node_id),
    }

async def miniapp_data(request):
    node_id = request.query.get("node", "root")
    db = load_db()

    if not db:
        return web.json_response({
            "ok": False,
            "error": "دیتابیس در دسترس نیست یا خالی است."
        }, status=500)

    str_node_id = str(node_id)
    if str_node_id not in db:
        # در صورت نامعتبر بودن نود، بازگشت به root
        str_node_id = "root"

    payload = serialize_node(db, str_node_id)
    if not payload:
        return web.json_response({
            "ok": False,
            "error": f"نود '{node_id}' یافت نشد."
        }, status=404)

    return web.json_response({
        "ok": True,
        "data": payload
    })
