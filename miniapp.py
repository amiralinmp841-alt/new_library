import json
from aiohttp import web

# مهم:
# این تابع باید با دیتابیس اصلی ربات کار کند.
# اگر load_db در main.py است، از همان استفاده می‌کنیم.
from main import load_db


def get_style(node):
    raw_style = (
        node.get("color")
        or node.get("style")
        or node.get("node_style")
        or "none"
    )

    return str(raw_style).strip().lower()


def get_rows(node):
    children_ids = [
        str(cid)
        for cid in node.get("children", [])
    ]

    layout = node.get("layout")

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

    result = []

    for item in contents or []:

        if not isinstance(item, dict):
            continue

        # کل اطلاعات content حفظ شود
        content = dict(item)

        if not content.get("type"):
            content["type"] = "unknown"

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

        if parent is not None:
            cur = str(parent)
        else:
            cur = None

    path.reverse()

    return path


def serialize_node(db, node_id):

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

            if not isinstance(
                child_contents,
                list
            ):
                child_contents = []

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
                )

            })

        if row:
            rows.append(row)

    node_contents = node.get(
        "contents",
        []
    )

    if not isinstance(
        node_contents,
        list
    ):
        node_contents = []

    return {

        "id": str_node_id,

        "name": node.get(
            "name",
            "بدون نام"
        ),

        "parent": (
            str(node["parent"])
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
        )

    }


async def miniapp_data(request):

    node_id = request.query.get(
        "node",
        "root"
    )

    try:
        # این همان load_db اصلی main.py است
        db = load_db()

    except Exception as e:

        print(
            "❌ Miniapp load_db error:",
            repr(e)
        )

        return web.json_response(
            {
                "ok": False,
                "error": (
                    "خطا در بارگذاری دیتابیس: "
                    + str(e)
                )
            },
            status=500
        )

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
