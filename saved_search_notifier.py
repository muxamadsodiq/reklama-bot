"""
Saved search notifier — har 5 daqiqada yangi tasdiqlangan e'lonlarni tekshirib,
saqlangan qidiruvlarga mos kelsa foydalanuvchiga DM yuboradi.
"""
import asyncio
import json
import logging
import re

import aiosqlite
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config import DB_PATH

log = logging.getLogger("saved_search_notifier")

CHECK_INTERVAL_SEC = 300  # 5 daqiqa

PRICE_RE = re.compile(r"(\d[\d\s.,]*)")


def parse_price(s):
    if s is None:
        return None
    m = PRICE_RE.search(str(s))
    if not m:
        return None
    num = m.group(1).replace(" ", "").replace(",", "").replace(".", "")
    try:
        return int(num)
    except Exception:
        return None


def ad_matches(ad_row, search):
    try:
        data = json.loads(ad_row["filled_data"] or "{}")
    except Exception:
        data = {}
    haystack = (ad_row["filled_data"] or "").lower()

    q = (search["query"] or "").strip()
    if q:
        tokens = [t.lower() for t in q.split() if t.strip()]
        for t in tokens:
            if t not in haystack:
                return False

    if search["category_id"] and ad_row["category_id"] != search["category_id"]:
        return False

    if search["location"]:
        if search["location"].lower() not in haystack:
            return False

    if search["price_min"] is not None or search["price_max"] is not None:
        price = None
        for key in ("price", "narx", "narxi"):
            if key in data:
                price = parse_price(data[key])
                if price is not None:
                    break
        if price is None:
            return False
        if search["price_min"] is not None and price < search["price_min"]:
            return False
        if search["price_max"] is not None and price > search["price_max"]:
            return False

    return True


def build_title(data, ad_id):
    for k in ("title", "nomi", "name"):
        if data.get(k):
            return str(data[k])[:80]
    return f"E'lon #{ad_id}"


async def run_notifier(bot: Bot):
    log.info(f"Saved-search notifier ishga tushdi (interval: {CHECK_INTERVAL_SEC}s)")
    while True:
        try:
            await _tick(bot)
        except Exception as e:
            log.exception(f"notifier tick error: {e}")
        await asyncio.sleep(CHECK_INTERVAL_SEC)


async def _tick(bot: Bot):
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(
            "SELECT id, user_id, query, category_id, location, price_min, price_max, "
            "last_notified_ad_id FROM saved_searches"
        )
        searches = await cur.fetchall()
        if not searches:
            return

        max_id = 0
        for s in searches:
            if s["last_notified_ad_id"] and s["last_notified_ad_id"] > max_id:
                max_id = s["last_notified_ad_id"]

        min_since = min(s["last_notified_ad_id"] or 0 for s in searches)
        cur = await conn.execute(
            "SELECT id, user_id, filled_data, media_file_id, category_id, "
            "posted_chat_id, posted_message_id "
            "FROM ads WHERE status='approved' AND id > ? ORDER BY id ASC LIMIT 200",
            (min_since,),
        )
        new_ads = await cur.fetchall()
        if not new_ads:
            return

        latest_id = new_ads[-1]["id"]
        # For each search, find matching ads newer than its last_notified_ad_id
        for s in searches:
            threshold = s["last_notified_ad_id"] or 0
            matched = []
            for ad in new_ads:
                if ad["id"] <= threshold:
                    continue
                if ad["user_id"] == s["user_id"]:
                    continue  # skip own ads
                if ad_matches(ad, s):
                    matched.append(ad)
                    if len(matched) >= 3:
                        break

            if matched:
                for ad in matched:
                    try:
                        await _send_match(bot, s["user_id"], ad, s)
                    except (TelegramForbiddenError, TelegramBadRequest) as e:
                        log.warning(f"send failed user={s['user_id']}: {e}")
                        break
                    await asyncio.sleep(0.1)

            # Update last_notified_ad_id regardless of matches (to avoid rescanning)
            await conn.execute(
                "UPDATE saved_searches SET last_notified_ad_id=? WHERE id=?",
                (latest_id, s["id"]),
            )
        await conn.commit()


async def _send_match(bot: Bot, user_id: int, ad, search):
    try:
        data = json.loads(ad["filled_data"] or "{}")
    except Exception:
        data = {}
    title = build_title(data, ad["id"])
    price = data.get("price") or data.get("narx") or data.get("narxi") or ""
    loc = data.get("location") or data.get("manzil") or ""

    q_label = search["query"] or (f"kategoriya" if search["category_id"] else "filtr")
    text = (
        f"🔔 <b>Saqlangan qidiruv:</b> <i>{q_label}</i>\n\n"
        f"📌 <b>{title}</b>\n"
    )
    if price:
        text += f"💰 {price}\n"
    if loc:
        text += f"📍 {loc}\n"

    # Channel link
    url = None
    if ad["posted_chat_id"] and ad["posted_message_id"]:
        cid = str(ad["posted_chat_id"])
        if cid.startswith("@"):
            url = f"https://t.me/{cid[1:]}/{ad['posted_message_id']}"
        elif cid.startswith("-100"):
            url = f"https://t.me/c/{cid[4:]}/{ad['posted_message_id']}"

    kb_rows = []
    if url:
        kb_rows.append([InlineKeyboardButton(text="📢 E'lonni ochish", url=url)])
    kb_rows.append([InlineKeyboardButton(
        text="🗑 Bu qidiruvni o'chirish",
        callback_data=f"ss:del:{search['id']}"
    )])

    await bot.send_message(
        user_id, text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows),
    )
