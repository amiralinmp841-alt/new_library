import json
import os
from aiohttp import web

DB_FILE = "/tmp/database.json"

def load_db():
    try:
        print("MINIAPP DB FILE:", DB_FILE)
        print("MINIAPP DB EXISTS:", os.path.exists(DB_FILE))

        with open(DB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        print("MINIAPP DB SIZE:", len(data))
        print("MINIAPP ROOT:", data.get("root"))
        print(
            "MINIAPP ROOT CHILDREN:",
            data.get("root", {}).get("children", [])
        )

        if isinstance(data, dict):
            return data

        return {}

    except Exception as e:
        print("miniapp load_db error:", repr(e))
        return {}

def get_style(node):
    return node.get("color") or node.get("style") or node.get("node_style") or "none"

def get_rows(node):
    children_ids = node.get("children", [])
    layout = node.get("layout")

    # اگر layout معتبر باشد، فقط آی‌دی‌هایی را نگه دار که واقعاً داخل children هستند
    if isinstance(layout, list) and layout:
        cleaned = []
        child_set = set(children_ids)
        for row in layout:
            if isinstance(row, list):
                new_row = [cid for cid in row if cid in child_set]
                if new_row:
                    cleaned.append(new_row)
        if cleaned:
            return cleaned

    # fallback: بر اساس row_count
    try:
        n = int(node.get("row_count", 2))
        if n <= 0:
            n = 2
    except:
        n = 2

    return [children_ids[i:i+n] for i in range(0, len(children_ids), n)]

def serialize_contents(contents):
    result = []

    for item in contents or []:
        if not isinstance(item, dict):
            continue

        content_type = item.get("type", "unknown")

        # متن
        if content_type == "text":
            result.append({
                "type": "text",
                "text": item.get("text", "")
            })
            continue

        # مدیا و فایل‌ها
        result.append({
            "type": content_type,
            "caption": item.get("caption", ""),
            "file_name": (
                item.get("file_name")
                or item.get("filename")
                or item.get("document_name")
                or ""
            )
        })

    return result

def get_breadcrumb(db, node_id):
    path = []
    seen = set()
    cur = node_id

    while cur and cur not in seen:
        seen.add(cur)
        node = db.get(cur)
        if not node:
            break
        path.append({
            "id": cur,
            "name": node.get("name", "بدون نام")
        })
        cur = node.get("parent")

    path.reverse()
    return path

def serialize_node(db, node_id):
    node = db.get(node_id)
    if not node:
        return None

    children_ids = node.get("children", [])
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
        "children_count": len(children_ids),
        "contents": serialize_contents(node.get("contents", [])),
        "rows": rows,
        "breadcrumb": get_breadcrumb(db, node_id),
    }

async def miniapp_data(request):
    node_id = request.query.get("node", "root")
    db = load_db()

    if node_id not in db:
        return web.json_response({
            "ok": False,
            "error": f"node '{node_id}' not found",
            "debug": {
                "db_keys_sample": list(db.keys())[:20],
                "db_size": len(db),
            }
        })

    payload = serialize_node(db, node_id)
    return web.json_response({
        "ok": True,
        "data": payload,
        "debug": {
            "db_size": len(db),
            "root_exists": "root" in db,
            "root_children": db.get("root", {}).get("children", []),
        }
    })
