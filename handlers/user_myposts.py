"""REJA10: 'Postlarim' — user o'z approved reklamalarini ko'radi va 'sotildi' deb belgilaydi.

Flow:
  - Main menu → «📋 Postlarim» (u:myposts)
  - Har bir post tugmasi: post ID + sana (u:post:view:<ad_id>)
  - View: qisqa ma'lumot + «🏷 Sotildi» + «⬅️ Orqaga»
  - Sotildi bosilsa: «Ha, sotildi» / «Bekor qilish» (u:post:confirm:<ad_id> / u:myposts)
  - Tasdiqlansa: filled_data.sold_field_key → sold_replacement; kanal/maxfiy post edit.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from aiogram import Router, F, Bot
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

import database as db
from utils.preview_builder import format_ad_id
from utils.template_parser import safe_format

router = Router()
log = logging.getLogger(__name__)


def _parse_filled(ad) -> dict:
    raw = None
    try:
        raw = ad["filled_data"]
    except (KeyError, IndexError, TypeError):
        return {}
    if not raw:
        return {}
    try:
        return json.loads(raw) if isinstance(raw, str) else dict(raw)
    except Exception:
        return {}


def _ad_short(ad, idx: int) -> str:
    filled = _parse_filled(ad)
    title = (
        filled.get("title")
        or filled.get("nomi")
        or filled.get("name")
        or filled.get("description", "")[:30]
        or f"Post #{ad['id']}"
    )
    title = str(title)[:40]
    sold = "🏷 " if _is_sold(ad) else ""
    return f"{sold}{idx}. {title}"


def _is_sold(ad) -> bool:
    try:
        return bool(ad["sold_at"])
    except (KeyError, IndexError, TypeError):
        return False


@router.callback_query(F.data == "u:myposts")
async def my_posts_list(cb: CallbackQuery):
    ads = await db.list_user_ads(cb.from_user.id, limit=30)
    if not ads:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Bosh menyu", callback_data="u:home")],
        ])
        try:
            await cb.message.edit_text(
                "📋 <b>Postlarim</b>\n\nHozircha tasdiqlangan postlaringiz yo'q.",
                reply_markup=kb, parse_mode="HTML"
            )
        except Exception:
            await cb.message.answer(
                "📋 <b>Postlarim</b>\n\nHozircha tasdiqlangan postlaringiz yo'q.",
                reply_markup=kb, parse_mode="HTML"
            )
        await cb.answer()
        return

    rows = []
    for i, ad in enumerate(ads, 1):
        rows.append([InlineKeyboardButton(
            text=_ad_short(ad, i),
            callback_data=f"u:post:view:{ad['id']}",
        )])
    rows.append([InlineKeyboardButton(text="⬅️ Bosh menyu", callback_data="u:home")])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    text = f"📋 <b>Postlarim</b> ({len(ads)} ta)\n\nBirortasini tanlang:"
    try:
        await cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await cb.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data.startswith("u:post:view:"))
async def my_post_view(cb: CallbackQuery):
    ad_id = int(cb.data.split(":")[3])
    ad = await db.get_ad_full(ad_id)
    if not ad or ad["user_id"] != cb.from_user.id:
        await cb.answer("❌ Post topilmadi", show_alert=True)
        return

    filled = _parse_filled(ad)
    lines = [f"📋 <b>Post #{format_ad_id(ad['id'], '_')}</b>"]
    if _is_sold(ad):
        lines.append("🏷 <b>SOTILDI</b>")
    lines.append("")
    for k, v in list(filled.items())[:10]:
        if v:
            lines.append(f"• <b>{k}</b>: {str(v)[:80]}")
    try:
        if ad["created_at"]:
            lines.append(f"\n🕒 {ad['created_at'][:16]}")
    except Exception:
        pass
    try:
        if ad["view_count"]:
            lines.append(f"👁 {ad['view_count']} marta ko'rildi")
    except Exception:
        pass

    rows = []
    if not _is_sold(ad):
        rows.append([InlineKeyboardButton(
            text="🏷 Sotildi deb belgilash",
            callback_data=f"u:post:sold:{ad_id}",
        )])
    rows.append([InlineKeyboardButton(text="⬅️ Postlarim", callback_data="u:myposts")])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    try:
        await cb.message.edit_text("\n".join(lines), reply_markup=kb, parse_mode="HTML")
    except Exception:
        await cb.message.answer("\n".join(lines), reply_markup=kb, parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data.startswith("u:post:sold:"))
async def my_post_sold_confirm(cb: CallbackQuery):
    ad_id = int(cb.data.split(":")[3])
    ad = await db.get_ad_full(ad_id)
    if not ad or ad["user_id"] != cb.from_user.id:
        await cb.answer("❌ Post topilmadi", show_alert=True)
        return
    if _is_sold(ad):
        await cb.answer("Ushbu post allaqachon sotilgan", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Ha, sotildi", callback_data=f"u:post:confirm:{ad_id}")],
        [InlineKeyboardButton(text="⬅️ Bekor qilish", callback_data=f"u:post:view:{ad_id}")],
    ])
    try:
        await cb.message.edit_text(
            "⚠️ <b>Tasdiqlang</b>\n\nPostni <b>sotildi</b> deb belgilamoqchimisiz?\n"
            "Bu ommaviy va maxfiy kanallardagi postni yangilaydi.",
            reply_markup=kb, parse_mode="HTML",
        )
    except Exception:
        await cb.message.answer(
            "Postni sotildi deb belgilamoqchimisiz?",
            reply_markup=kb, parse_mode="HTML",
        )
    await cb.answer()


async def _apply_sold(ad, bot: Bot) -> tuple[bool, str]:
    """Return (ok, message)."""
    # template via posted channel chat_id
    posted_chat = None
    try:
        posted_chat = ad["posted_chat_id"]
    except (KeyError, IndexError, TypeError):
        pass
    if not posted_chat:
        return False, "Kanal posti topilmadi"

    # find channel id
    import aiosqlite
    from config import DB_PATH
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(
            "SELECT id FROM channels WHERE chat_id=? LIMIT 1", (str(posted_chat),)
        )
        ch_row = await cur.fetchone()
    if not ch_row:
        return False, "Kanal topilmadi"

    tpl = await db.get_template(ch_row["id"])
    if not tpl:
        return False, "Shablon topilmadi"

    def _g(k, d=None):
        try:
            v = tpl[k]
            return v if v is not None else d
        except (KeyError, IndexError):
            return d

    filled = _parse_filled(ad)
    from utils.sold_rules import apply_sold
    filled, _applied = apply_sold(filled, tpl)

    new_json = json.dumps(filled, ensure_ascii=False)
    await db.mark_ad_sold(ad["id"], new_json)

    # Build updated public text
    pub_tpl = _g("text_template") or ""
    priv_tpl = _g("private_text_template") or ""
    ad_id_str = format_ad_id(ad["id"], _g("id_prefix", "_") or "_")
    ctx = dict(filled)
    ctx["ad_id"] = ad_id_str

    errors = []

    async def _edit(chat_id, msg_id, new_text):
        if not (chat_id and msg_id):
            return
        try:
            # Try editing caption first (if media)
            try:
                await bot.edit_message_caption(
                    chat_id=chat_id, message_id=msg_id,
                    caption=new_text, parse_mode="HTML",
                )
                return
            except Exception:
                pass
            await bot.edit_message_text(
                chat_id=chat_id, message_id=msg_id,
                text=new_text, parse_mode="HTML",
            )
        except Exception as e:
            errors.append(str(e))

    if pub_tpl:
        try:
            pub_text = safe_format(pub_tpl, ctx)
        except Exception:
            pub_text = pub_tpl
        try:
            await _edit(ad["posted_chat_id"], ad["posted_message_id"], pub_text)
        except Exception as e:
            errors.append(f"pub: {e}")

    try:
        priv_chat = ad["private_posted_chat_id"]
        priv_msg = ad["private_posted_message_id"]
    except (KeyError, IndexError, TypeError):
        priv_chat = priv_msg = None

    if priv_tpl and priv_chat and priv_msg:
        try:
            priv_text = safe_format(priv_tpl, ctx)
        except Exception:
            priv_text = priv_tpl
        await _edit(priv_chat, priv_msg, priv_text)

    if errors:
        log.warning("sold edit errors for ad %s: %s", ad["id"], errors)
        return True, "DB yangilandi, lekin ba'zi postlarni tahrirlashda xatolik."
    return True, "Post sotildi deb belgilandi."


@router.callback_query(F.data.startswith("u:post:confirm:"))
async def my_post_confirm(cb: CallbackQuery, bot: Bot):
    ad_id = int(cb.data.split(":")[3])
    ad = await db.get_ad_full(ad_id)
    if not ad or ad["user_id"] != cb.from_user.id:
        await cb.answer("❌ Post topilmadi", show_alert=True)
        return
    if _is_sold(ad):
        await cb.answer("Allaqachon sotilgan", show_alert=True)
        return
    ok, msg = await _apply_sold(ad, bot)
    await cb.answer(msg, show_alert=True)
    # refresh view
    try:
        # re-fetch
        ad2 = await db.get_ad_full(ad_id)
        if ad2:
            cb.data = f"u:post:view:{ad_id}"
            await my_post_view(cb)
    except Exception:
        pass
