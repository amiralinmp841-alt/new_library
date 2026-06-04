import os
import logging
import aiohttp

BALE_BOT_TOKEN = os.getenv("BALE_BOT_TOKEN")

BALE_API_BASE = f"https://tapi.bale.ai/bot{BALE_BOT_TOKEN}"


async def bale_api(method: str, payload: dict):
    url = f"{BALE_API_BASE}/{method}"

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            text = await resp.text()
            if resp.status >= 400:
                logging.error(f"Bale API error {resp.status}: {text}")
            return text


async def send_bale_message(chat_id, text, reply_markup=None):
    payload = {
        "chat_id": chat_id,
        "text": text
    }

    if reply_markup:
        payload["reply_markup"] = reply_markup

    return await bale_api("sendMessage", payload)


async def handle_bale_update(data: dict):
    logging.info(f"Bale update: {data}")

    message = data.get("message")
    if not message:
        return

    chat = message.get("chat", {})
    chat_id = chat.get("id")

    text = message.get("text", "")

    if not chat_id:
        return

    if text == "/start":
        await send_bale_message(chat_id, "سلام، ربات بله وصل شد ✅")
    else:
        await send_bale_message(chat_id, f"پیام شما دریافت شد:\n{text}")
