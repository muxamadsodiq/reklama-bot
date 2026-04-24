"""REJA13: Premium obuna oqimi.

Oqim:
1. Ommaviy post ostidagi inline tugma (admin label'i) → t.me/<bot>?start=sub_<ch>_<ad>
2. User botda 'Ariza yuborish' bosadi → admin'ga notify, kanal egasi ✅/❌ bosadi
3. ✅ → userga maxfiy guruh invite linki yuboriladi
4. ❌ → rad etildi xabari

REJA13b: Agar user allaqachon maxfiy guruh a'zosi bo'lsa — obuna tugmasini bosganda
to'liq to'ldirilgan post matnini (raqam/Telegram bilan) ko'rsatamiz.
"""
import json
import logging
import aiosqlite
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

import database as db
from config import DB_PATH
from utils.preview_builder import build_text_and_kb

router = Router()
log = logging.getLogger(__name__)


async def _get_tpl_texts(channel_id: int):
    async with aiosqlite.connect(DB_PATH) as dbx:
        dbx.row_factory = aiosqlite.Row
        cur = await dbx.execute(
            "SELECT sub_offer_text, private_invite_link, private_chat_id FROM templates WHERE channel_id=?",
            (channel_id,),
        )
        row = await cur.fetchone()
        if not row:
            return ("", "", None)
        return (row["sub_offer_text"] or "", row["private_invite_link"] or "", row["private_chat_id"])


async def _already_pending(user_id: int, channel_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as dbx:
        cur = await dbx.execute(
            "SELECT 1 FROM premium_requests WHERE user_id=? AND channel_id=? AND status='pending' LIMIT 1",
            (user_id, channel_id),
        )
        return (await cur.fetchone()) is not None


async def _is_premium_member(bot: Bot, user_id: int, private_chat_id) -> bool:
    if not private_chat_id:
        return False
    try:
        m = await bot.get_chat_member(int(private_chat_id), user_id)
        return m.status in ("creator", "administrator", "member", "restricted")
    except Exception:
        return False


async def _send_full_post(bot: Bot, chat_id: int, ch_id: int, ad_id: int) -> bool:
    """Premium a'zoga to'liq to'ldirilgan post matnini yuboradi.
    Qaytaradi: True — yuborildi, False — xatolik/topilmadi.
    """
    try:
        ad = await db.get_ad_full(ad_id)
        if not ad:
            return False
        tpl = await db.get_template(ch_id)
        if not tpl:
            return False
        try:
            filled = json.loads(ad["filled_data"] or "{}")
        except Exception:
            filled = {}
        text, _kb = build_text_and_kb(
            tpl, filled, None, ad_id=ad_id, prefix=None,
            bot_username=None, channel_id=ch_id,
        )
        # Media bor bo'lsa media bilan yuboramiz
        mtype = ad["media_type"] or ""
        mfid = ad["media_file_id"] or ""
        header = "💎 <b>Premium ko'rinish</b> (to'liq ma'lumot):\n\n"
        final_text = header + text
        if mtype == "photo" and mfid:
            await bot.send_photo(chat_id, mfid, caption=final_text[:1024], parse_mode="HTML")
        elif mtype == "video" and mfid:
            await bot.send_video(chat_id, mfid, caption=final_text[:1024], parse_mode="HTML")
        else:
            await bot.send_message(chat_id, final_text, parse_mode="HTML", disable_web_page_preview=True)
        return True
    except Exception:
        log.exception("send_full_post failed")
        return False


async def handle_sub_start(msg: Message, payload: str):
    """payload = sub_<ch_id>_<ad_id>"""
    bot = msg.bot
    try:
        _, ch_id_s, ad_id_s = payload.split("_", 2)
        ch_id = int(ch_id_s)
        ad_id = int(ad_id_s)
    except Exception:
        await msg.answer("❌ Noto'g'ri havola")
        return

    ch = await db.get_channel(ch_id)
    if not ch:
        await msg.answer("❌ Kanal topilmadi")
        return

    offer_text, invite_link, private_chat_id = await _get_tpl_texts(ch_id)

    # Agar user allaqachon premium (maxfiy guruh a'zosi) bo'lsa — to'liq post
    if await _is_premium_member(bot, msg.from_user.id, private_chat_id):
        sent = False
        if ad_id:
            sent = await _send_full_post(bot, msg.chat.id, ch_id, ad_id)
        if not sent:
            if invite_link:
                await msg.answer(
                    f"✅ Siz <b>{ch['name']}</b> premium obunachisiz.\n\n🔗 Maxfiy guruh: {invite_link}",
                    parse_mode="HTML",
                )
            else:
                await msg.answer(f"✅ Siz <b>{ch['name']}</b> premium obunachisiz.", parse_mode="HTML")
        return

    if await _already_pending(msg.from_user.id, ch_id):
        await msg.answer(
            "⏳ Sizning arizangiz allaqachon yuborilgan. Admin tasdiqlashini kuting.",
        )
        return

    offer = offer_text or (
        f"💎 <b>{ch['name']}</b> premium obunasi\n\n"
        f"Obuna bo'lganingizda siz maxfiy guruhga qo'shilasiz va barcha e'lonlarning "
        f"to'liq ma'lumotlarini (raqam, Telegram, qo'shimcha ma'lumot) ko'ra olasiz.\n\n"
        f"Arizangizni yuboring — admin ko'rib chiqadi."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📝 Ariza yuborish", callback_data=f"sub:ask:{ch_id}:{ad_id}")
    ]])
    await msg.answer(offer, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data.startswith("sub:ask:"))
async def sub_ask(cb: CallbackQuery):
    bot = cb.bot
    try:
        _, _, ch_id_s, ad_id_s = cb.data.split(":")
        ch_id = int(ch_id_s)
        ad_id = int(ad_id_s)
    except Exception:
        await cb.answer("❌", show_alert=True)
        return

    ch = await db.get_channel(ch_id)
    if not ch:
        await cb.answer("Kanal topilmadi", show_alert=True)
        return

    if await _already_pending(cb.from_user.id, ch_id):
        await cb.answer("⏳ Arizangiz allaqachon yuborilgan", show_alert=True)
        return

    offer_text, invite_link, private_chat_id = await _get_tpl_texts(ch_id)
    if await _is_premium_member(bot, cb.from_user.id, private_chat_id):
        if invite_link:
            await cb.message.answer(f"✅ Siz allaqachon premium obunachisiz.\n\n🔗 {invite_link}")
        else:
            await cb.message.answer("✅ Siz allaqachon premium obunachisiz.")
        await cb.answer()
        return

    # Request yozamiz
    user = cb.from_user
    uname = f"@{user.username}" if user.username else ""
    full_name = (user.full_name or "").strip()

    async with aiosqlite.connect(DB_PATH) as dbx:
        cur = await dbx.execute(
            "INSERT INTO premium_requests (user_id, user_name, username, channel_id, ad_id) VALUES (?,?,?,?,?)",
            (user.id, full_name, uname, ch_id, ad_id),
        )
        req_id = cur.lastrowid
        await dbx.commit()

    # Adminga xabar
    owner_id = ch["owner_id"] or 0
    if not owner_id:
        await cb.message.answer("❌ Kanal egasi sozlanmagan. Admin bilan bog'laning.")
        await cb.answer()
        return

    admin_text = (
        f"💎 <b>Yangi premium obuna arizasi</b>\n\n"
        f"👤 {full_name} {uname}\n"
        f"🆔 <code>{user.id}</code>\n"
        f"📍 Kanal: <b>{ch['name']}</b>\n"
        f"📝 Ariza #{req_id}"
    )
    if ad_id:
        admin_text += f"\n🔗 Post: #{ad_id}"

    akb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Qabul", callback_data=f"sub:ok:{req_id}"),
        InlineKeyboardButton(text="❌ Rad", callback_data=f"sub:no:{req_id}"),
    ]])
    try:
        sent = await bot.send_message(owner_id, admin_text, parse_mode="HTML", reply_markup=akb)
        async with aiosqlite.connect(DB_PATH) as dbx:
            await dbx.execute(
                "UPDATE premium_requests SET admin_msg_id=?, admin_chat_id=? WHERE id=?",
                (sent.message_id, sent.chat.id, req_id),
            )
            await dbx.commit()
    except Exception as e:
        log.exception("admin notify failed")
        await cb.message.answer("❌ Adminga yuborib bo'lmadi. Keyinroq urinib ko'ring.")
        await cb.answer()
        return

    await cb.message.edit_text(
        "✅ Arizangiz yuborildi!\n\n"
        "Admin ko'rib chiqib qaror qabul qiladi. Qaror natijasi sizga shu bot orqali keladi.",
    )
    await cb.answer("Ariza yuborildi")


@router.callback_query(F.data.startswith("sub:ok:"))
async def sub_ok(cb: CallbackQuery):
    bot = cb.bot
    try:
        req_id = int(cb.data.split(":")[2])
    except Exception:
        await cb.answer("❌", show_alert=True)
        return
    async with aiosqlite.connect(DB_PATH) as dbx:
        dbx.row_factory = aiosqlite.Row
        cur = await dbx.execute("SELECT * FROM premium_requests WHERE id=?", (req_id,))
        req = await cur.fetchone()
    if not req:
        await cb.answer("Topilmadi", show_alert=True)
        return
    if req["status"] != "pending":
        await cb.answer(f"Allaqachon: {req['status']}", show_alert=True)
        return

    ch = await db.get_channel(req["channel_id"])
    if not ch or ch["owner_id"] != cb.from_user.id:
        await cb.answer("Siz bu kanal egasi emassiz", show_alert=True)
        return

    offer_text, invite_link, private_chat_id = await _get_tpl_texts(req["channel_id"])

    # Agar admin invite_link sozlamagan bo'lsa — avtomatik yaratishga urinamiz
    if not invite_link and private_chat_id:
        try:
            link_obj = await bot.create_chat_invite_link(int(private_chat_id), member_limit=1, name=f"prem#{req_id}")
            invite_link = link_obj.invite_link
        except Exception:
            log.exception("invite link create failed")

    if not invite_link:
        await cb.answer("❌ Maxfiy guruh linki sozlanmagan", show_alert=True)
        await cb.message.answer(
            "⚠️ Kanal sozlamasida maxfiy guruh invite linki yo'q. "
            "Kanal menyusi → 💎 Obuna sozlamalari dan qo'shing yoki botni maxfiy guruhga admin qilib qo'shing."
        )
        return

    async with aiosqlite.connect(DB_PATH) as dbx:
        await dbx.execute(
            "UPDATE premium_requests SET status='approved', decided_at=datetime('now'), decided_by=? WHERE id=?",
            (cb.from_user.id, req_id),
        )
        await dbx.commit()

    # Userga xabar
    try:
        await bot.send_message(
            req["user_id"],
            f"🎉 Tabriklaymiz! Sizning <b>{ch['name']}</b> premium obuna arizangiz <b>qabul qilindi</b>.\n\n"
            f"🔗 Maxfiy guruhga qo'shiling: {invite_link}",
            parse_mode="HTML",
        )
    except Exception:
        log.exception("user notify approve failed")

    # Admin xabarini yangilash
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
        await cb.message.edit_text(
            (cb.message.text or "") + "\n\n✅ <b>Qabul qilindi</b>",
            parse_mode="HTML",
        )
    except Exception:
        pass
    await cb.answer("Qabul qilindi")


@router.callback_query(F.data.startswith("sub:no:"))
async def sub_no(cb: CallbackQuery):
    bot = cb.bot
    try:
        req_id = int(cb.data.split(":")[2])
    except Exception:
        await cb.answer("❌", show_alert=True)
        return
    async with aiosqlite.connect(DB_PATH) as dbx:
        dbx.row_factory = aiosqlite.Row
        cur = await dbx.execute("SELECT * FROM premium_requests WHERE id=?", (req_id,))
        req = await cur.fetchone()
    if not req:
        await cb.answer("Topilmadi", show_alert=True)
        return
    if req["status"] != "pending":
        await cb.answer(f"Allaqachon: {req['status']}", show_alert=True)
        return

    ch = await db.get_channel(req["channel_id"])
    if not ch or ch["owner_id"] != cb.from_user.id:
        await cb.answer("Siz bu kanal egasi emassiz", show_alert=True)
        return

    async with aiosqlite.connect(DB_PATH) as dbx:
        await dbx.execute(
            "UPDATE premium_requests SET status='rejected', decided_at=datetime('now'), decided_by=? WHERE id=?",
            (cb.from_user.id, req_id),
        )
        await dbx.commit()

    try:
        await bot.send_message(
            req["user_id"],
            f"❌ Sizning <b>{ch['name']}</b> premium obuna arizangiz rad etildi.\n\n"
            f"Batafsil ma'lumot uchun admin bilan bog'laning.",
            parse_mode="HTML",
        )
    except Exception:
        log.exception("user notify reject failed")

    try:
        await cb.message.edit_reply_markup(reply_markup=None)
        await cb.message.edit_text(
            (cb.message.text or "") + "\n\n❌ <b>Rad etildi</b>",
            parse_mode="HTML",
        )
    except Exception:
        pass
    await cb.answer("Rad etildi")
