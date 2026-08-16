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


def chunk_children(children_ids, layout):
    """
    تقسیم فرزندان به ردیف‌ها با پشتیبانی از همه فرمت‌های ممکن دیتابیس:
    1. ماتریس مستقیم آی‌دی‌ها: [["id1", "id2"], ["id3"]]
    2. لیست تعداد در هر ردیف: [2, 1, 3] یا [[2], [1]]
    3. عدد ثابت: 2
    4. پیش‌فرض: ۲ دکمه در هر ردیف
    """
    if not children_ids:
        return []

    # حالت ۱: چیدمان از قبل یک لیست/ماتریس است
    if isinstance(layout, list) and layout:
        # اگر عناصر داخلی خودشون لیست هستند
        if isinstance(layout[0], list):
            # بررسی اینکه آیا ماتریسی از ID هاست یا ماتریسی از اعداد
            # اگر شامل رشته/ID است، دقیقاً همان چیدمان را فیلتر و استفاده می‌کنیم
            if any(isinstance(x, str) for x in layout[0]):
                valid_ids = set(children_ids)
                rows = []
                for row in layout:
                    filtered_row = [cid for cid in row if cid in valid_ids]
                    if filtered_row:
                        rows.append(filtered_row)
                # اگر فرزندی جا مونده بود اضافه بشه
                placed = {cid for row in rows for cid in row}
                remaining = [cid for cid in children_ids if cid not in placed]
                if remaining:
                    rows.append(remaining)
                return rows if rows else [children_ids]

            # اگر لیستی از لیست‌های عددی بود مثلاً [[2], [1]]
            layout_counts = []
            for item in layout:
                if isinstance(item, list) and item:
                    try:
                        layout_counts.append(int(item[0]))
                    except (ValueError, TypeError):
                        pass
                elif isinstance(item, (int, str)):
                    try:
                        layout_counts.append(int(item))
                    except (ValueError, TypeError):
                        pass
            if layout_counts:
                layout = layout_counts

        # اگر لیست یک‌بعدی از اعداد باشد مثل [2, 1, 3]
        if isinstance(layout, list) and layout and not isinstance(layout[0], list):
            rows = []
            i = 0
            for count in layout:
                if i >= len(children_ids):
                    break
                try:
                    c = max(1, int(count))
                except (ValueError, TypeError):
                    c = 2
                rows.append(children_ids[i:i + c])
                i += c
            if i < len(children_ids):
                rows.append(children_ids[i:])
            return rows

    # حالت ۲: عدد صحیح یکتا (مثلاً ۲)
    if isinstance(layout, int):
        n = max(1, layout)
        return [children_ids[i:i + n] for i in range(0, len(children_ids), n)]

    if isinstance(layout, str) and layout.isdigit():
        n = max(1, int(layout))
        return [children_ids[i:i + n] for i in range(0, len(children_ids), n)]

    # حالت ۳: پیش‌فرض اگر هیچ چیدمانی تعریف نشده باشد (۲ دکمه در هر ردیف)
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
