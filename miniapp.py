import json
import os

# همون مسیر دیتابیس اصلی ربات
DB_FILE = os.getenv("DB_FILE", "/tmp/database.json")


def load_db():
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def get_style(node):
    """
    رنگ پوشه. چون اسم دقیق فیلد رو مطمئن نیستم، چند حالت رو چک می‌کنه.
    ⚠️ اینجا رو بعداً با فیلد دقیق توی دیتابیس خودت جایگزین کن.
    """
    return (
        node.get("color")
        or node.get("style")
        or node.get("node_style")
        or "none"
    )


def get_layout(node):
    """
    چیدمان دکمه‌ها در هر ردیف.
    می‌تونه عدد (مثلاً ۲) یا لیست (مثلاً [2, 1, 3]) باشه.
    ⚠️ اینجا رو با فیلد دقیق خودت تنظیم کن.
    """
    for key in ("layout", "custom_layout", "rows", "row_count", "buttons_per_row"):
        if key in node and node[key] is not None:
            return node[key]
    return None


def chunk_children(children_ids, layout):
    """تقسیم فرزندان به ردیف‌ها بر اساس چیدمان."""
    if not children_ids:
        return []

    if isinstance(layout, list):
        rows = []
        i = 0
        for count in layout:
            if i >= len(children_ids):
                break
            count = max(1, int(count))
            rows.append(children_ids[i:i + count])
            i += count
        if i < len(children_ids):  # اگر آیتمی مونده بود
            rows.append(children_ids[i:])
        return rows

    if isinstance(layout, int):
        n = max(1, layout)
        return [children_ids[i:i + n] for i in range(0, len(children_ids), n)]

    # پیش‌فرض: ۲ دکمه در هر ردیف
    return [children_ids[i:i + 2] for i in range(0, len(children_ids), 2)]


def serialize_contents(contents):
    """
    متن‌ها رو مستقیم برمی‌گردونه (چون قابل نمایش هستن)
    و فایل‌ها (عکس/ویدیو/PDF) رو فقط به صورت تعداد خلاصه می‌کنه.
    """
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
    """مسیر کامل از روت تا نود فعلی."""
    path = []
    cur = node_id
    while cur:
        node = db.get(cur)
        if not node:
            break
        path.append({"id": cur, "name": node.get("name", "بدون نام")})
        cur = node.get("parent")
    path.reverse()
    return path


def serialize_node(db, node_id):
    node = db.get(node_id)
    if not node:
        return None

    children_ids = node.get("children", [])

    def to_child(cid):
        child = db.get(cid)
        if not child:
            return None
        return {
            "id": cid,
            "name": child.get("name", "بدون نام"),
            "style": get_style(child),
            "has_children": bool(child.get("children")),
            "content_count": len(child.get("contents", [])),
        }

    # چیدمان ردیف‌ها
    rows_ids = chunk_children(children_ids, get_layout(node))
    rows = []
    for row_ids in rows_ids:
        row = [to_child(cid) for cid in row_ids]
        row = [r for r in row if r is not None]
        if row:
            rows.append(row)

    return {
        "id": node_id,
        "name": node.get("name", "بدون نام"),
        "parent": node.get("parent"),
        "style": get_style(node),
        "contents": serialize_contents(node.get("contents", [])),
        "rows": rows,                              # دکمه‌ها به تفکیک ردیف
        "breadcrumb": get_breadcrumb(db, node_id),
    }


def get_node_json(node_id="root"):
    return serialize_node(load_db(), node_id)
