import json
import logging
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

import database as db
from config import SUPER_ADMIN_IDS
from utils.preview_builder import build_text_and_kb, format_ad_id

router = Router()
log = logging.getLogger(__name__)


class UserAd(StatesGroup):
    select_channels = State()
    fill_field = State()
    ask_url = State()
    ask_media = State()
    preview = State()


async def is_super(uid: int) -> bool:
    return uid in SUPER_ADMIN_IDS


async def is_admin_or_super(uid: int) -> bool:
    if uid in SUPER_ADMIN_IDS:
        return True
    return await db.is_admin(uid)


async def main_menu_kb(user_id: int | None = None):
    rows = [
        [InlineKeyboardButton(text="📢 Reklama berish", callback_data="u:new")],
    ]
    if user_id is not None and await is_admin_or_super(user_id):
        rows.append([InlineKeyboardButton(text="🧩 Kanal egasi paneli", callback_data="u:owner")])
    if user_id is not None and user_id in SUPER_ADMIN_IDS:
        rows.append([InlineKeyboardButton(text="👑 Adminlar boshqaruvi", callback_data="sa:home")])
    rows.append([InlineKeyboardButton(text="📖 Qo'llanma", callback_data="u:help")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


HELP_USER = (
    "📖 Qo'llanma — REKLAMA BERUVCHI\n\n"
    "• «📢 Reklama berish» tugmasini bosing\n"
    "• Reklama qo'ymoqchi bo'lgan kanal(lar)ni tanlang\n"
    "• Bot kanal egasi sozlagan savollarni beradi (masalan: «Narxni kiriting», «Telefon raqam»)\n"
    "• Kerak bo'lsa rasm/video yuboring (max 5 ta)\n"
    "• Ko'rinishni tekshirib «Yuborish» bosing\n"
    "• Kanal egasi tasdiqlaganda reklama kanalga chiqadi\n"
    "• Har bir reklamaga #_0001 kabi unik ID beriladi\n\n"
    "Savol bo'lsa: /help"
)

HELP_ADMIN = (
    "📖 Qo'llanma — KANAL EGASI (admin)\n\n"
    "1) Botni kanal/guruhingizga qo'shing va admin qiling\n"
    "   «🧩 Kanal egasi paneli» → «➕ Botni guruh/kanalga qo'shish»\n"
    "2) Kanal/Guruhni botga qo'shing\n"
    "   «➕ Kanal/Guruh qo'shish» → @username yoki chat_id\n\n"
    "📝 Shablon yaratish (ikki xil matn):\n"
    "• 1-qadam: OMMAVIY matn — kanalga chiqadigan matn. {nom} placeholder'lar.\n"
    "  Misol: «📍 Manzil: {manzil}\\n💰 Narx: {narx} so'm»\n"
    "• 2-qadam (ixtiyoriy): MAXFIY guruh matni — to'liq ma'lumot bilan.\n"
    "  Bu yerda {telefon}, {username}, {user_id} kabi maxfiy maydonlarni qo'shing.\n"
    "• 3-qadam: Bot har bir {maydon} uchun:\n"
    "   (a) userga beriladigan SAVOLNI so'raydi «Telefon raqam kiriting»\n"
    "   (b) bu maydon kanalga chiqadimi yoki yo'qmi\n\n"
    "🔒 Maxfiy guruh:\n"
    "• Maxfiy guruh chat_id — -100... bilan yoki oddiy raqam (bot tuzatadi)\n"
    "• Tasdiqlanganda reklama BIR VAQTDA:\n"
    "   - Asosiy kanalga (faqat «public» maydonlar)\n"
    "   - Maxfiy guruhga (to'liq ma'lumot bilan) yuboriladi\n\n"
    "✅ Tasdiqlash/Rad etish:\n"
    "• Reklama berilganda SIZGA (kanal egasiga) xabar keladi\n"
    "• «✅ Tasdiqlash» yoki «❌ Rad etish» tugmalarini bosasiz\n\n"
    "🆔 Unik ID: #_0001 format, {ad_id} placeholder bilan istalgan joyga qo'yiladi\n\n"
    "Savol bo'lsa: /help"
)

HELP_SUPER = (
    "📖 Qo'llanma — SUPER ADMIN\n\n"
    "Siz bu botning bosh egasiz. Sizning vazifangiz:\n"
    "• Kimga kanal egasi (admin) huquqini berish — hal qilasiz\n"
    "• «👑 Adminlar boshqaruvi» orqali admin qo'shasiz/olib tashlaysiz\n\n"
    "Admin qo'shish:\n"
    "• «➕ Admin qo'shish» → user ID (raqam) yozing\n"
    "• User botga /start bosgan bo'lishi kerak\n\n"
    "Admin olib tashlash:\n"
    "• «📋 Adminlar ro'yxati» → kerakli adminni bosing → «🗑 O'chirish»\n\n"
    "Barcha admin imkoniyatlari sizda ham bor (kanal qo'shish, shablon va h.k.)"
)


def help_text_for(uid: int) -> str:
    if uid in SUPER_ADMIN_IDS:
        return HELP_SUPER + "\n\n" + HELP_ADMIN + "\n\n" + HELP_USER
    return HELP_USER


@router.message(Command("help"))
async def cmd_help(msg: Message, state: FSMContext):
    await state.clear()
    uid = msg.from_user.id
    kb = await main_menu_kb(uid)
    if await is_admin_or_super(uid):
        text = help_text_for(uid) if uid in SUPER_ADMIN_IDS else (HELP_ADMIN + "\n\n" + HELP_USER)
    else:
        text = HELP_USER
    await msg.answer(text, reply_markup=kb)


@router.callback_query(F.data == "u:help")
async def cb_help(cb: CallbackQuery):
    uid = cb.from_user.id
    if await is_admin_or_super(uid):
        text = help_text_for(uid) if uid in SUPER_ADMIN_IDS else (HELP_ADMIN + "\n\n" + HELP_USER)
    else:
        text = HELP_USER
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⬅️ Bosh menyu", callback_data="u:home")]]
    )
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data == "u:home")
async def cb_home(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("🏠 Bosh menyu", reply_markup=await main_menu_kb(cb.from_user.id))
    await cb.answer()


@router.message(Command("start"))
async def cmd_start(msg: Message, state: FSMContext):
    await state.clear()
    uid = msg.from_user.id
    # Survey — agar faol bo'lsa va user hali to'ldirmagan bo'lsa, so'rovnomani boshlaymiz
    try:
        from handlers.survey_user import maybe_start_survey
        if await maybe_start_survey(msg, state):
            return
    except Exception:
        log.exception("survey hook failed")
    role = "super admin" if uid in SUPER_ADMIN_IDS else ("admin" if await db.is_admin(uid) else "foydalanuvchi")
    await msg.answer(
        f"👋 Salom, {msg.from_user.first_name}!\n"
        f"Sizning roliyingiz: <b>{role}</b>\n\n"
        "Bu bot orqali reklama bera olasiz"
        + (" yoki o'z kanalingizga reklama qabul qilishni sozlashingiz mumkin." if await is_admin_or_super(uid) else ".")
        + "\n\nℹ️ Batafsil: «📖 Qo'llanma» yoki /help",
        reply_markup=await main_menu_kb(uid),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "u:owner")
async def open_owner(cb: CallbackQuery, state: FSMContext, bot: Bot):
    if not await is_admin_or_super(cb.from_user.id):
        await cb.answer("Bu bo'lim faqat adminlar uchun", show_alert=True)
        return
    from handlers.admin import owner_menu_kb
    await state.clear()
    await cb.message.edit_text("🧩 Kanal egasi paneli", reply_markup=await owner_menu_kb(bot))
    await cb.answer()


async def build_channels_kb(selected: set[int]):
    chs = await db.list_channels()
    # Admin (owner) ma'lumotlarini map qilib olamiz
    admins = await db.list_admins()
    admin_map = {}
    for a in admins:
        uname = a["username"]
        fname = a["full_name"]
        if uname:
            admin_map[a["user_id"]] = f"@{uname}"
        elif fname:
            admin_map[a["user_id"]] = fname
        else:
            admin_map[a["user_id"]] = f"ID:{a['user_id']}"
    rows = []
    for c in chs:
        mark = "✅" if c["id"] in selected else "☑️"
        # Admin belgilagan button_label bo'lsa — shuni ishlatamiz, yo'q bo'lsa kanal nomi
        try:
            custom_label = c["button_label"]
        except (KeyError, IndexError):
            custom_label = None
        base = custom_label if custom_label else c["name"]
        label = f"{mark} {base}"
        if not custom_label:
            owner_label = admin_map.get(c["owner_id"])
            if owner_label:
                label += f" — {owner_label}"
        rows.append(
            [InlineKeyboardButton(text=label, callback_data=f"u:tog:{c['id']}")]
        )
    rows.append([InlineKeyboardButton(text="➡️ Davom etish", callback_data="u:go")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "u:new")
async def new_ad(cb: CallbackQuery, state: FSMContext):
    if await db.user_has_pending(cb.from_user.id):
        await cb.answer("Sizda kutilayotgan so'rov bor. Admin tasdiqlashini kuting.", show_alert=True)
        return
    chs = await db.list_channels()
    if not chs:
        await cb.answer("Hozircha kanal yo'q", show_alert=True)
        return
    await state.set_state(UserAd.select_channels)
    await state.update_data(selected=[])
    kb = await build_channels_kb(set())
    prompt_text = await db.get_setting("channel_select_prompt") or "Kanal(lar)ni tanlang:"
    await cb.message.answer(prompt_text, reply_markup=kb)
    await cb.answer()


@router.callback_query(UserAd.select_channels, F.data.startswith("u:tog:"))
async def toggle_ch(cb: CallbackQuery, state: FSMContext):
    ch_id = int(cb.data.split(":")[2])
    data = await state.get_data()
    sel = set(data.get("selected", []))
    if ch_id in sel:
        sel.remove(ch_id)
    else:
        sel.add(ch_id)
    await state.update_data(selected=list(sel))
    kb = await build_channels_kb(sel)
    try:
        await cb.message.edit_reply_markup(reply_markup=kb)
    except Exception:
        pass
    await cb.answer()


@router.callback_query(UserAd.select_channels, F.data == "u:go")
async def go_fill(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    sel = data.get("selected", [])
    if not sel:
        await cb.answer("Kamida bitta kanal tanlang", show_alert=True)
        return
    await state.update_data(queue=list(sel), current_idx=0)
    await start_channel_flow(cb.message, state)
    await cb.answer()


async def start_channel_flow(msg: Message, state: FSMContext):
    data = await state.get_data()
    idx = data["current_idx"]
    queue = data["queue"]
    if idx >= len(queue):
        await msg.answer("Barcha so'rovlar yuborildi ✨", reply_markup=await main_menu_kb(msg.from_user.id))
        await state.clear()
        return

    ch_id = queue[idx]
    ch = await db.get_channel(ch_id)
    tpl = await db.get_template(ch_id)
    fields = await db.list_fields(ch_id)
    if not tpl:
        await msg.answer(f"⚠️ {ch['name']} uchun shablon yo'q, o'tkazib yuborildi")
        data["current_idx"] += 1
        await state.update_data(**data)
        await start_channel_flow(msg, state)
        return

    # Fallback: agar fields yo'q bo'lsa (eski shablonlar) — text'dan extract qil
    if not fields:
        from utils.template_parser import extract_placeholders
        pub_ph = extract_placeholders(tpl["text_template"])
        prv_ph = extract_placeholders(tpl["private_text_template"] or "")
        reserved = {"username", "user_id", "ad_id"}
        keys = []
        for k in pub_ph + prv_ph:
            if k in reserved: continue
            if k not in keys: keys.append(k)
        fields = [
            {"key": k, "question": f"{k} ni kiriting:",
             "show_in_public": (k in pub_ph)}
            for k in keys
        ]

    await state.update_data(
        cur_ch_id=ch_id,
        cur_fields=[dict(f) for f in fields],
        cur_field_idx=0,
        cur_filled={},
        cur_custom_url=None,
        cur_media_file_id=None,
        cur_media_type=None,
    )
    await msg.answer(f"📍 «{ch['name']}» uchun ma'lumotlarni kiriting:")
    await ask_next_field(msg, state)


async def ask_next_field(msg: Message, state: FSMContext):
    data = await state.get_data()
    fields = data["cur_fields"]
    idx = data["cur_field_idx"]
    if idx < len(fields):
        f = fields[idx]
        await state.set_state(UserAd.fill_field)
        await msg.answer(f["question"])
        return

    tpl = await db.get_template(data["cur_ch_id"])
    if tpl["button_url_by_user"]:
        await state.set_state(UserAd.ask_url)
        await msg.answer("Tugma uchun havolani kiriting (https://...):")
        return

    if tpl["media_required"]:
        await state.set_state(UserAd.ask_media)
        await msg.answer("Rasm yoki video yuboring (o'tkazib yuborish: /skip):")
        return

    await show_preview(msg, state)


@router.message(UserAd.fill_field)
async def fill_field(msg: Message, state: FSMContext):
    data = await state.get_data()
    fields = data["cur_fields"]
    idx = data["cur_field_idx"]
    filled = dict(data["cur_filled"])
    filled[fields[idx]["key"]] = msg.text or ""
    await state.update_data(cur_filled=filled, cur_field_idx=idx + 1)
    await ask_next_field(msg, state)


@router.message(UserAd.ask_url)
async def fill_url(msg: Message, state: FSMContext):
    await state.update_data(cur_custom_url=msg.text.strip())
    data = await state.get_data()
    tpl = await db.get_template(data["cur_ch_id"])
    if tpl["media_required"]:
        await state.set_state(UserAd.ask_media)
        await msg.answer("Rasm yoki video yuboring (/skip):")
    else:
        await show_preview(msg, state)


@router.message(UserAd.ask_media, F.photo)
async def media_photo(msg: Message, state: FSMContext):
    # Media group (album) — boshidagi max 5 rasm
    if msg.media_group_id:
        data = await state.get_data()
        group_id = data.get("cur_media_group_id")
        media_list = list(data.get("cur_media_list", []))
        caption_from_album = data.get("cur_album_caption") or ""
        if group_id != msg.media_group_id:
            # Yangi album boshlandi
            media_list = []
            caption_from_album = ""
        if len(media_list) < 5:
            media_list.append({"type": "photo", "file_id": msg.photo[-1].file_id})
        if msg.caption and not caption_from_album:
            caption_from_album = msg.caption
        await state.update_data(
            cur_media_group_id=msg.media_group_id,
            cur_media_list=media_list,
            cur_album_caption=caption_from_album,
            cur_media_file_id=media_list[0]["file_id"],
            cur_media_type="photo",
        )
        # Debounce: har safar yangi rasmdan keyin 1.5s kutamiz, keyin preview
        import asyncio
        token = f"{msg.media_group_id}:{len(media_list)}"
        await state.update_data(_album_token=token)
        async def _finalize():
            await asyncio.sleep(1.5)
            fresh = await state.get_data()
            if fresh.get("_album_token") == token:
                await show_preview(msg, state)
        asyncio.create_task(_finalize())
        return
    # Oddiy bitta rasm
    await state.update_data(
        cur_media_file_id=msg.photo[-1].file_id,
        cur_media_type="photo",
        cur_media_list=[{"type": "photo", "file_id": msg.photo[-1].file_id}],
    )
    await show_preview(msg, state)


@router.message(UserAd.ask_media, F.video)
async def media_video(msg: Message, state: FSMContext):
    await state.update_data(cur_media_file_id=msg.video.file_id, cur_media_type="video")
    await show_preview(msg, state)


@router.message(UserAd.ask_media, Command("skip"))
async def media_skip(msg: Message, state: FSMContext):
    await show_preview(msg, state)


@router.message(UserAd.ask_media)
async def media_bad(msg: Message):
    await msg.answer("Iltimos, rasm yoki video yuboring (yoki /skip).")


def _public_filtered(fields_meta: list, filled: dict) -> dict:
    """Faqat public=True maydonlarni qoldiradi, boshqalarni bo'sh string."""
    out = {}
    for f in fields_meta:
        key = f["key"]
        if f.get("show_in_public", True):
            out[key] = filled.get(key, "")
        else:
            out[key] = ""  # shablondan masking
    return out


async def show_preview(msg: Message, state: FSMContext):
    data = await state.get_data()
    ch = await db.get_channel(data["cur_ch_id"])

    # Userga to'liq postni ko'rsatmaymiz — faqat kiritilgan ma'lumotlarni qisqa xulosa qilamiz
    lines = [f"👁 «{ch['name']}» uchun kiritilgan ma'lumotlar:"]
    for f in data["cur_fields"]:
        val = data["cur_filled"].get(f["key"], "")
        lines.append(f"• {f['key']}: {val}")
    if data.get("cur_custom_url"):
        lines.append(f"🔗 Tugma havolasi: {data['cur_custom_url']}")
    media_list = data.get("cur_media_list") or []
    if len(media_list) >= 2:
        lines.append(f"🖼 Album: {len(media_list)} ta media")
    elif data.get("cur_media_type") == "photo":
        lines.append("🖼 Rasm biriktirildi")
    elif data.get("cur_media_type") == "video":
        lines.append("🎬 Video biriktirildi")
    lines.append("")
    lines.append("ℹ️ Reklama tasdiqlangandan so'ng kanalga chiqadi.")

    action_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Yuborish", callback_data="u:send"),
                InlineKeyboardButton(text="🔄 Qayta", callback_data="u:retry"),
            ]
        ]
    )
    await state.set_state(UserAd.preview)
    await msg.answer("\n".join(lines), reply_markup=action_kb)


@router.callback_query(UserAd.preview, F.data == "u:retry")
async def retry_current(cb: CallbackQuery, state: FSMContext):
    await start_channel_flow(cb.message, state)
    await cb.answer()


@router.callback_query(UserAd.preview, F.data == "u:send")
async def send_to_owner(cb: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()

    ad_id = await db.create_ad(
        user_id=cb.from_user.id,
        username=cb.from_user.username,
        filled_data=data["cur_filled"],
        media_file_id=data.get("cur_media_file_id"),
        media_type=data.get("cur_media_type"),
        custom_url=data.get("cur_custom_url"),
        target_channels=[data["cur_ch_id"]],
        media_list=data.get("cur_media_list") or [],
    )

    ch = await db.get_channel(data["cur_ch_id"])
    tpl = await db.get_template(data["cur_ch_id"])
    try:
        prefix = tpl["id_prefix"] or "_"
    except (KeyError, IndexError, TypeError):
        prefix = "_"
    # Admin/owner previewda to'liq data bilan ko'rsatamiz
    full_data = dict(data["cur_filled"])
    full_data["username"] = cb.from_user.username or ""
    full_data["user_id"] = str(cb.from_user.id)
    text, kb = build_text_and_kb(tpl, full_data, data.get("cur_custom_url"), ad_id=ad_id, prefix=prefix)

    header = (
        f"📢 Yangi reklama so'rovi {format_ad_id(ad_id, prefix)}\n"
        f"👤 @{cb.from_user.username or '—'} (ID: {cb.from_user.id})\n"
        f"📍 Joy: {ch['name']}\n\n--- To'liq ma'lumot ---"
    )
    # To'liq info (barcha maydonlar, maxfiy ham)
    full_info_lines = [header]
    for f in data["cur_fields"]:
        val = data["cur_filled"].get(f["key"], "")
        flag = "🔒" if not f.get("show_in_public", True) else "✅"
        full_info_lines.append(f"{flag} {f['key']}: {val}")
    full_info = "\n".join(full_info_lines)

    action_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"m:ok:{ad_id}"),
                InlineKeyboardButton(text="❌ Rad etish", callback_data=f"m:no:{ad_id}"),
            ]
        ]
    )

    owner_id = ch["owner_id"]
    notify_targets = [owner_id] if owner_id else []
    ok = False
    for aid in notify_targets:
        try:
            await bot.send_message(aid, full_info)
            await bot.send_message(aid, "--- Kanal ko'rinishi (preview) ---")
            # Kanal preview — faqat public
            pub_data = _public_filtered(data["cur_fields"], data["cur_filled"])
            pub_text, pub_kb = build_text_and_kb(tpl, pub_data, data.get("cur_custom_url"), ad_id=ad_id)
            media_list = data.get("cur_media_list") or []
            if len(media_list) >= 2:
                from aiogram.types import InputMediaPhoto, InputMediaVideo
                group = []
                for i, m in enumerate(media_list[:5]):
                    cap = pub_text if i == 0 else None
                    if m["type"] == "photo":
                        group.append(InputMediaPhoto(media=m["file_id"], caption=cap))
                    else:
                        group.append(InputMediaVideo(media=m["file_id"], caption=cap))
                await bot.send_media_group(aid, group)
                if pub_kb:
                    await bot.send_message(aid, "👆 Post tugmasi:", reply_markup=pub_kb)
            elif data.get("cur_media_file_id") and data.get("cur_media_type") == "photo":
                await bot.send_photo(aid, data["cur_media_file_id"], caption=pub_text, reply_markup=pub_kb)
            elif data.get("cur_media_file_id") and data.get("cur_media_type") == "video":
                await bot.send_video(aid, data["cur_media_file_id"], caption=pub_text, reply_markup=pub_kb)
            else:
                await bot.send_message(aid, pub_text, reply_markup=pub_kb)
            await bot.send_message(aid, "Harakat:", reply_markup=action_kb)
            ok = True
        except Exception as e:
            log.exception("owner notify failed: %s", e)

    if ok:
        await cb.message.answer(f"✅ So'rov kanal egasiga yuborildi! ID: {format_ad_id(ad_id, prefix)}")
    else:
        await cb.message.answer(
            "⚠️ Kanal egasiga xabar yetmadi (egaga bot'ga /start bosish kerak). "
            "So'rov baribir saqlandi."
        )

    q_data = await state.get_data()
    q_data["current_idx"] += 1
    await state.update_data(**q_data)

    if q_data["current_idx"] < len(q_data["queue"]):
        await start_channel_flow(cb.message, state)
    else:
        await state.clear()
        await cb.message.answer("Tayyor ✨", reply_markup=await main_menu_kb(cb.from_user.id))
    await cb.answer()
