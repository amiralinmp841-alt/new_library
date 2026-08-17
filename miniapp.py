import json
import os
from aiohttp import web


DB_FILE = "/tmp/database.json"


def load_db():
    """دریافت دیتابیس مشترک با ربات."""

    try:
        if not os.path.exists(DB_FILE):
            print(f"❌ Miniapp DB not found: {DB_FILE}")
            return {}

        with open(DB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            print("❌ Miniapp database is not a dictionary.")
            return {}

        return data

    except json.JSONDecodeError as e:
        print(f"❌ Miniapp database JSON error: {e}")
        return {}

    except Exception as e:
        print(f"❌ Miniapp load_db error: {repr(e)}")
        return {}


def get_style(node):
    """تعیین استایل/رنگ نود."""

    raw_style = (
        node.get("color")
        or node.get("style")
        or node.get("node_style")
        or "none"
    )

    return str(raw_style).strip().lower()


def get_rows(node):
    """
    ساخت ردیف‌های دکمه‌ها.
    اگر layout تعریف شده باشد، از همان استفاده می‌شود.
    در غیر این صورت بر اساس row_count تقسیم می‌شود.
    """

    children_ids = [
        str(cid)
        for cid in node.get("children", [])
    ]

    layout = node.get("layout")

    # اگر layout دستی وجود داشته باشد
    if isinstance(layout, list) and layout:
        cleaned = []

        child_set = set(children_ids)

        for row in layout:
            if isinstance(row, list):
                new_row = [
                    str(cid)
                    for cid in row
                    if str(cid) in child_set
                ]

                if new_row:
                    cleaned.append(new_row)

        if cleaned:
            return cleaned

    # در غیر این صورت row_count
    try:
        n = int(node.get("row_count", 2))

        if n <= 0:
            n = 2

    except (TypeError, ValueError):
        n = 2

    return [
        children_ids[i:i + n]
        for i in range(0, len(children_ids), n)
    ]


def serialize_contents(contents):
    """
    محتواها را برای Mini App آماده می‌کند.

    عمداً تمام فیلدهای content حفظ می‌شوند
    تا اطلاعاتی مثل:
    file_id
    media_group_id
    caption
    entities
    و سایر فیلدهای دیتابیس حذف نشوند.
    """

    result = []

    for item in contents or []:

        if not isinstance(item, dict):
            continue

        # کپی کامل content
        content = dict(item)

        # اطمینان از وجود type
        if not content.get("type"):
            content["type"] = "unknown"

        # برای سازگاری با HTML
        if "text" not in content:
            content["text"] = (
                content.get("content")
                or ""
            )

        if "caption" not in content:
            content["caption"] = ""

        if "file_name" not in content:
            content["file_name"] = (
                content.get("filename")
                or content.get("document_name")
                or content.get("title")
                or ""
            )

        result.append(content)

    return result


def get_breadcrumb(db, node_id):
    """ساخت مسیر والدین نود."""

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
            "name": node.get(
                "name",
                "بدون نام"
            )
        })

        parent = node.get("parent")

        if parent:
            cur = str(parent)
        else:
            cur = None

    path.reverse()

    return path


def serialize_node(db, node_id):
    """تبدیل یک نود دیتابیس به داده قابل استفاده برای Mini App."""

    str_node_id = str(node_id)

    node = db.get(str_node_id)

    if not node:
        return None

    children_ids = [
        str(cid)
        for cid in node.get("children", [])
    ]

    rows_ids = get_rows(node)

    rows = []

    for row_ids in rows_ids:

        row = []

        for cid in row_ids:

            child = db.get(str(cid))

            if not child:
                continue

            child_contents = child.get(
                "contents",
                []
            )

            row.append({
                "id": str(cid),

                "name": child.get(
                    "name",
                    "بدون نام"
                ),

                "style": get_style(child),

                "has_children": bool(
                    child.get("children")
                ),

                "content_count": len(
                    child_contents
                    if isinstance(child_contents, list)
                    else []
                ),
            })

        if row:
            rows.append(row)

    node_contents = node.get(
        "contents",
        []
    )

    if not isinstance(node_contents, list):
        node_contents = []

    return {
        "id": str_node_id,

        "name": node.get(
            "name",
            "بدون نام"
        ),

        "parent": (
            str(node.get("parent"))
            if node.get("parent") is not None
            else None
        ),

        "style": get_style(node),

        "children_count": len(
            children_ids
        ),

        "contents": serialize_contents(
            node_contents
        ),

        "rows": rows,

        "breadcrumb": get_breadcrumb(
            db,
            str_node_id
        ),
    }


async def miniapp_data(request):
    """API اصلی Mini App."""

    node_id = request.query.get(
        "node",
        "root"
    )

    db = load_db()

    if not db:

        return web.json_response(
            {
                "ok": False,
                "error": (
                    "دیتابیس در دسترس نیست "
                    "یا خالی است."
                )
            },
            status=500
        )

    str_node_id = str(node_id)

    # اگر نود وجود نداشت → root
    if str_node_id not in db:
        str_node_id = "root"

    payload = serialize_node(
        db,
        str_node_id
    )

    if not payload:

        return web.json_response(
            {
                "ok": False,
                "error": (
                    f"نود '{node_id}' یافت نشد."
                )
            },
            status=404
        )

    return web.json_response(
        {
            "ok": True,
            "data": payload
        }
    )
