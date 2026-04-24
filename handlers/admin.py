from aiogram import Router, F, Bot
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
import json

import database as db
from config import SUPER_ADMIN_IDS
from utils.template_parser import extract_placeholders

router = Router()


async def _allow(uid: int) -> bool:
    if uid in SUPER_ADMIN_IDS:
        return True
    return await db.is_admin(uid)


# Router-level filter: agar user admin/super emas bo'lsa,
# ushbu routerdagi handlerlar UMUMAN mos kelmaydi va update
# jimgina keyingi routerga (user.py) o'tadi.
async def _admin_only_msg(event: Message) -> bool:
    try:
        if event.chat.type != "private":
            return False
    except Exception:
        return False
    return await _allow(event.from_user.id)


async def _admin_only_cb(event: CallbackQuery) -> bool:
    return await _allow(event.from_user.id)


router.message.filter(_admin_only_msg)
router.callback_query.filter(_admin_only_cb)


# ---------- FSM ----------
class AddField(StatesGroup):
    ch_id = State()
    label = State()


class AddChannel(StatesGroup):
    chat_id = State()


class EditChannel(StatesGroup):
    name = State()
    chat_id = State()


class MakeTemplate(StatesGroup):
    text = State()
    btn_choice = State()
    btn_caption = State()
    btn_label = State()
    btn_url_mode = State()
    btn_url_value = State()
    media = State()
    private_choice = State()
    private_chat_id = State()
    private_text = State()
    field_question = State()   # admin savol yozadi
    extra_choice = State()     # ➕ yana maydon qo'shamizmi
    extra_key = State()        # yangi {key} nomi
    extra_where = State()      # qayerga (public/private)
    id_prefix = State()        # #<prefix>0001
    confirm = State()


async def owner_menu_kb(bot: Bot | None = None):
    rows = [
        [InlineKeyboardButton(text="➕ Kanal/Guruh qo'shish", callback_data="own:add")],
        [InlineKeyboardButton(text="📋 Mening kanallarim", callback_data="own:list")],
    ]
    if bot is not None:
        try:
            me = await bot.get_me()
            rows.insert(
                1,
                [InlineKeyboardButton(
                    text="➕ Botni guruhga qo'shish",
                    url=f"https://t.me/{me.username}?startgroup=true",
                )],
            )
            rows.insert(
                2,
                [InlineKeyboardButton(
                    text="➕ Botni kanalga qo'shish",
                    url=f"https://t.me/{me.username}?startchannel=true",
                )],
            )
        except Exception:
            pass
    rows.append([InlineKeyboardButton(text="📊 Kanal statistikasi", callback_data="own:stats")])
    rows.append([InlineKeyboardButton(text="📋 Kutilayotgan so'rovlar", callback_data="own:pending")])
    rows.append([InlineKeyboardButton(text="⬅️ Bosh menyu", callback_data="own:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("mychannels"))
async def my_channels_cmd(msg: Message, state: FSMContext, bot: Bot):
    await state.clear()
    await msg.answer(
        "🧩 Kanal egasi paneli\n\n"
        "Bu yerda siz o'z kanal/guruhingizni qo'shib, unga reklama shablonini "
        "sozlashingiz mumkin. Shartlar:\n"
        "• Siz kanalda admin bo'lishingiz kerak\n"
        "• Bot ham kanalda admin (post yuborish huquqi bilan) bo'lishi kerak",
        reply_markup=await owner_menu_kb(bot),
    )


@router.callback_query(F.data == "own:home")
async def own_home(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    from handlers.user import main_menu_kb
    await cb.message.edit_text("🏠 Bosh menyu", reply_markup=await main_menu_kb(cb.from_user.id))
    await cb.answer()


@router.callback_query(F.data == "own:back")
async def own_back(cb: CallbackQuery, state: FSMContext, bot: Bot):
    await state.clear()
    await cb.message.edit_text("🧩 Kanal egasi paneli", reply_markup=await owner_menu_kb(bot))
    await cb.answer()


# ---------- Add channel ----------
@router.callback_query(F.data == "own:add")
async def add_start(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AddChannel.chat_id)
    await cb.message.answer(
        "Kanal/guruhingizning @username yoki chat_id sini yuboring.\n\n"
        "❗️ Avval shu joyga botni qo'shib admin qiling, keyin shu yerdan yuboring."
    )
    await cb.answer()


@router.message(AddChannel.chat_id)
async def add_chat_id(msg: Message, state: FSMContext, bot: Bot):
    chat_id_raw = msg.text.strip()

    try:
        chat = await bot.get_chat(chat_id_raw)
    except Exception as e:
        await msg.answer(f"❌ Kanal topilmadi yoki bot uni ko'rolmayapti.\n{e}")
        return

    try:
        me = await bot.get_me()
        bot_mem = await bot.get_chat_member(chat.id, me.id)
        if bot_mem.status not in ("administrator", "creator"):
            await msg.answer("❌ Bot bu kanalda admin emas. Avval botni admin qiling.")
            return
    except Exception as e:
        await msg.answer(f"❌ Botning kanaldagi holatini tekshirishda xato: {e}")
        return

    try:
        user_mem = await bot.get_chat_member(chat.id, msg.from_user.id)
        if user_mem.status not in ("administrator", "creator"):
            await msg.answer("❌ Siz bu kanalda admin emassiz. Faqat adminlar qo'sha oladi.")
            return
    except Exception as e:
        await msg.answer(
            f"❌ Sizning kanaldagi holatingizni tekshira olmadim: {e}\n"
            "Shaxsiy (private) kanal bo'lsa, botga va o'zingizga adminlik bering."
        )
        return

    name = chat.title or chat.full_name or str(chat.id)
    try:
        ch_id = await db.add_channel(msg.from_user.id, name, str(chat.id))
    except Exception as e:
        await msg.answer(f"❌ Qo'shishda xato (ehtimol allaqachon bor): {e}")
        await state.clear()
        return

    # --- REJA8: darhol default shablon seed (murakkab flow ixtiyoriy) ---
    default_fields = [
        {"key": "name", "question": "Nomi", "order_idx": 0, "show_in_public": 1},
        {"key": "price", "question": "Narxi", "order_idx": 1, "show_in_public": 1},
        {"key": "condition", "question": "Holati (Yangi/Ishlatilgan)", "order_idx": 2, "show_in_public": 1},
        {"key": "location", "question": "Manzil", "order_idx": 3, "show_in_public": 1},
        {"key": "phone", "question": "Telefon", "order_idx": 4, "show_in_public": 1},
        {"key": "description", "question": "Tavsif", "order_idx": 5, "show_in_public": 1},
    ]
    await db.replace_fields(ch_id, default_fields)

    default_text = (
        "📋 <b>{name}</b>\n\n"
        "💰 Narxi: {price}\n"
        "🆕 Holati: {condition}\n"
        "📍 Manzil: {location}\n"
        "📞 Telefon: {phone}\n\n"
        "📝 {description}"
    )
    try:
        await db.upsert_template(
            channel_id=ch_id,
            text_template=default_text,
            button_label=None,
            button_caption=None,
            button_url=None,
            button_url_by_user=False,
            media_required=False,
            private_chat_id=None,
            private_text_template=None,
        )
    except Exception as e:
        await msg.answer(f"⚠️ Default shablonni o'rnatishda xato: {e}")

    await state.clear()
    await msg.answer(
        f"✅ «{name}» qo'shildi va <b>avtomatik shablon</b> o'rnatildi!\n\n"
        "🤖 Endi foydalanuvchilar AI bilan e'lon bera oladi.\n"
        "📋 Xohlasangiz shablonni keyin tahrirlashingiz mumkin.",
        parse_mode="HTML",
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Shablonni ko'rish / tahrirlash", callback_data=f"own:ch:{ch_id}")],
        [InlineKeyboardButton(text="⬅️ Mening kanallarim", callback_data="own:list")],
    ])
    await msg.answer("Keyingi qadam:", reply_markup=kb)


# ---------- List ----------
@router.callback_query(F.data == "own:list")
async def list_mine(cb: CallbackQuery):
    chs = await db.list_channels_by_owner(cb.from_user.id)
    if not chs:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Kanal qo'shish", callback_data="own:add")],
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="own:back")],
        ])
        await cb.message.edit_text(
            "📋 <b>Mening kanallarim</b>\n\n"
            "😕 Sizda hali birorta kanal/guruh yo'q.\n\n"
            "Kanal qo'shishning 2 ta yo'li bor:\n"
            "1️⃣ <b>Avtomatik:</b> Botni o'zingizning kanal/guruhingizga admin "
            "qiling (post yuborish huquqi bilan) — u o'zi ro'yxatga qo'shiladi.\n"
            "2️⃣ <b>Qo'lda:</b> Pastdagi tugmani bosib, kanal nomi va chat_id "
            "ni kiritishingiz mumkin.\n\n"
            "<i>Shundan so'ng kanalingiz shu yerda ko'rinadi va siz uchun "
            "reklama shabloni sozlash imkoniyati ochiladi.</i>",
            reply_markup=kb,
            parse_mode="HTML",
        )
        await cb.answer()
        return
    kb_rows = []
    for c in chs:
        try:
            cnt = await db.channel_counts(c["id"])
            stat = f" — ⏳{cnt['pending']} ✅{cnt['approved']}"
        except Exception:
            stat = ""
        kb_rows.append([InlineKeyboardButton(
            text=f"📍 {c['name']}{stat}",
            callback_data=f"own:ch:{c['id']}"
        )])
    kb_rows.append([InlineKeyboardButton(text="➕ Yangi kanal qo'shish", callback_data="own:add")])
    kb_rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="own:back")])
    await cb.message.edit_text(
        f"📋 <b>Mening kanal/guruhlarim</b> — {len(chs)} ta\n\n"
        "Har bir kanal yonida: ⏳ kutilayotgan — ✅ tasdiqlangan reklama soni.\n"
        "Boshqarish uchun kanalni tanlang 👇",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows),
        parse_mode="HTML",
    )
    await cb.answer()


async def _ensure_owner(cb: CallbackQuery, ch):
    if not ch:
        await cb.answer("Topilmadi", show_alert=True)
        return False
    if ch["owner_id"] != cb.from_user.id:
        await cb.answer("Bu sizning kanalingiz emas", show_alert=True)
        return False
    return True


@router.callback_query(F.data.startswith("own:ch:"))
async def ch_view(cb: CallbackQuery):
    ch_id = int(cb.data.split(":")[2])
    ch = await db.get_channel(ch_id)
    if not await _ensure_owner(cb, ch):
        return
    tpl = await db.get_template(ch_id)
    fields = await db.list_fields(ch_id)
    tpl_info = "✅ Shablon bor" if tpl else "⚠️ Shablon yo'q"
    fields_info = f"📝 {len(fields)} ta maydon" if fields else "— maydonlar yo'q"

    # Media / button info
    media_info = "—"
    btn_info = "—"
    priv_info = "yo'q"
    prem_info = "belgilanmagan"
    if tpl:
        try:
            media_info = "✅ Ha" if tpl["media_required"] else "❌ Yo'q"
        except (KeyError, IndexError):
            pass
        try:
            if tpl["button_label"]:
                btn_info = f"«{tpl['button_label']}»"
            else:
                btn_info = "belgilanmagan"
        except (KeyError, IndexError):
            pass
        try:
            if tpl["private_chat_id"]:
                priv_info = "sozlangan ✅"
        except (KeyError, IndexError):
            pass
        try:
            if tpl["premium_url"]:
                prem_info = tpl["premium_url"]
        except (KeyError, IndexError):
            pass

    kb_rows = [
        [InlineKeyboardButton(text="📋 Maydonlar ro'yxati", callback_data=f"own:fields:{ch_id}")],
        [InlineKeyboardButton(text="📝 Shablon matnini tahrirlash", callback_data=f"own:tpl:{ch_id}")],
        [InlineKeyboardButton(text="🔘 Aloqa tugmasi", callback_data=f"own:btn:{ch_id}")],
        [InlineKeyboardButton(text="📝 Sold/Free matnlari", callback_data=f"own:texts:{ch_id}")],
        [InlineKeyboardButton(text="💎 Obuna sozlamalari", callback_data=f"own:sub:{ch_id}")],
        [InlineKeyboardButton(text="📋 Default shablon (qayta o'rnatish)", callback_data=f"own:seed:{ch_id}")],
        [InlineKeyboardButton(text="♻️ Topshirildi qoidalari", callback_data=f"own:done:{ch_id}")],
        [InlineKeyboardButton(text="🎯 Aloqa/Sotildi sozlamalari", callback_data=f"own:r10:{ch_id}")],
        [InlineKeyboardButton(text="✏️ Nomini/chat_id tahrirlash", callback_data=f"own:edit:{ch_id}")],
        [InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"own:del:{ch_id}")],
        [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="own:list")],
    ]
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    text = (
        f"📍 <b>{ch['name']}</b>\n"
        f"🆔 chat_id: <code>{ch['chat_id']}</code>\n\n"
        f"{tpl_info}\n"
        f"{fields_info}\n"
        f"📷 Media: {media_info}\n"
        f"🔘 Aloqa tugmasi: {btn_info}\n"
        f"🔒 Maxfiy guruh: {priv_info}\n"
        f"💎 Premium URL: {prem_info}"
    )
    try:
        await cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await cb.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data.startswith("own:seed:"))
async def ch_seed_template(cb: CallbackQuery):
    ch_id = int(cb.data.split(":")[2])
    ch = await db.get_channel(ch_id)
    if not await _ensure_owner(cb, ch):
        return
    default_fields = [
        {"key": "name", "question": "Nomi", "order_idx": 0, "show_in_public": 1},
        {"key": "price", "question": "Narxi", "order_idx": 1, "show_in_public": 1},
        {"key": "condition", "question": "Holati (Yangi/Ishlatilgan)", "order_idx": 2, "show_in_public": 1},
        {"key": "location", "question": "Manzil", "order_idx": 3, "show_in_public": 1},
        {"key": "phone", "question": "Telefon", "order_idx": 4, "show_in_public": 1},
        {"key": "description", "question": "Tavsif", "order_idx": 5, "show_in_public": 1},
    ]
    await db.replace_fields(ch_id, default_fields)
    await cb.answer("✅ Default shablon o'rnatildi (6 ta maydon)", show_alert=True)
    await ch_view(cb)


# ---------- REJA8: maydonlar UI ----------
async def _render_fields_view(cb: CallbackQuery, ch_id: int):
    ch = await db.get_channel(ch_id)
    if not await _ensure_owner(cb, ch):
        return
    fields = await db.list_fields(ch_id)
    if not fields:
        body = "📋 <b>Maydonlar ro'yxati</b>\n\n😕 Hozircha maydonlar yo'q.\n\n➕ tugmasi orqali yangi maydon qo'shing yoki default shablonni o'rnating."
    else:
        lines = ["📋 <b>Maydonlar ro'yxati</b>\n"]
        for i, f in enumerate(fields, 1):
            lines.append(f"{i}. <b>{f['question']}</b>  <code>{{{f['key']}}}</code>")
        body = "\n".join(lines)

    kb_rows = []
    for f in fields:
        kb_rows.append([
            InlineKeyboardButton(text=f"❌ {f['question']}", callback_data=f"own:fdel:{ch_id}:{f['id']}"),
        ])
    kb_rows.append([InlineKeyboardButton(text="➕ Yangi maydon qo'shish", callback_data=f"own:fadd:{ch_id}")])
    kb_rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data=f"own:ch:{ch_id}")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    try:
        await cb.message.edit_text(body, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await cb.message.answer(body, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("own:fields:"))
async def ch_fields_view(cb: CallbackQuery):
    ch_id = int(cb.data.split(":")[2])
    await _render_fields_view(cb, ch_id)
    await cb.answer()


@router.callback_query(F.data.startswith("own:fdel:"))
async def ch_field_delete(cb: CallbackQuery):
    parts = cb.data.split(":")
    ch_id = int(parts[2])
    field_id = int(parts[3])
    ch = await db.get_channel(ch_id)
    if not await _ensure_owner(cb, ch):
        return
    import aiosqlite
    async with aiosqlite.connect(db.DB_PATH) as conn:
        await conn.execute("DELETE FROM template_fields WHERE id=? AND channel_id=?", (field_id, ch_id))
        await conn.commit()
    await cb.answer("O'chirildi")
    await _render_fields_view(cb, ch_id)


def _slugify_key(label: str) -> str:
    """Uzbek lotin / cyrill / boshqa belgilarni oddiy snake_case key'ga aylantirish."""
    import re as _re
    # cyrillic -> latin minimal
    tr = {
        "а":"a","б":"b","в":"v","г":"g","д":"d","е":"e","ё":"yo","ж":"j","з":"z",
        "и":"i","й":"y","к":"k","л":"l","м":"m","н":"n","о":"o","п":"p","р":"r",
        "с":"s","т":"t","у":"u","ф":"f","х":"h","ц":"ts","ч":"ch","ш":"sh","щ":"sh",
        "ъ":"","ы":"i","ь":"","э":"e","ю":"yu","я":"ya","қ":"q","ғ":"g","ў":"o","ҳ":"h",
    }
    s = (label or "").strip().lower()
    out = []
    for ch in s:
        if ch in tr:
            out.append(tr[ch])
        else:
            out.append(ch)
    s = "".join(out)
    s = _re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    if not s:
        s = "field"
    if s[0].isdigit():
        s = "f_" + s
    return s[:32]


@router.callback_query(F.data.startswith("own:fadd:"))
async def ch_field_add_start(cb: CallbackQuery, state: FSMContext):
    ch_id = int(cb.data.split(":")[2])
    ch = await db.get_channel(ch_id)
    if not await _ensure_owner(cb, ch):
        return
    await state.set_state(AddField.label)
    await state.update_data(ch_id=ch_id)
    await cb.message.answer(
        "➕ Yangi maydon nomini yuboring.\n"
        "Masalan: <code>Rang</code>, <code>Yil</code>, <code>Hajmi</code>\n\n"
        "ℹ️ Shablon matniga <code>{rang}</code> kabi avtomatik qo'shiladi.",
        parse_mode="HTML",
    )
    await cb.answer()


@router.message(AddField.label)
async def ch_field_add_label(msg: Message, state: FSMContext):
    data = await state.get_data()
    ch_id = data.get("ch_id")
    if not ch_id:
        await state.clear()
        return
    label = (msg.text or "").strip()
    if not label or len(label) > 60:
        await msg.answer("❌ Nom bo'sh yoki juda uzun (max 60). Qaytadan:")
        return
    key = _slugify_key(label)
    fields = await db.list_fields(ch_id)
    existing_keys = {f["key"] for f in fields}
    base = key
    i = 2
    while key in existing_keys:
        key = f"{base}{i}"
        i += 1
    next_idx = (max([f["order_idx"] for f in fields], default=-1)) + 1
    import aiosqlite
    async with aiosqlite.connect(db.DB_PATH) as conn:
        await conn.execute(
            """INSERT INTO template_fields(channel_id, key, question, order_idx, show_in_public)
               VALUES(?,?,?,?,?)""",
            (ch_id, key, label, next_idx, 1),
        )
        await conn.commit()
    await state.clear()
    await msg.answer(
        f"✅ Qo'shildi: <b>{label}</b> → <code>{{{key}}}</code>\n\n"
        "📝 Agar shablon matnida bu placeholder yo'q bo'lsa — avtomatik e'tiborsiz qoldiriladi "
        "(bot crash bermaydi). Kerak bo'lsa shablon matnini tahrirlang.",
        parse_mode="HTML",
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Maydonlar ro'yxati", callback_data=f"own:fields:{ch_id}")],
        [InlineKeyboardButton(text="⬅️ Kanal menyusi", callback_data=f"own:ch:{ch_id}")],
    ])
    await msg.answer("Keyingi:", reply_markup=kb)


@router.callback_query(F.data.startswith("own:del:"))
async def ch_delete(cb: CallbackQuery):
    ch_id = int(cb.data.split(":")[2])
    ch = await db.get_channel(ch_id)
    if not await _ensure_owner(cb, ch):
        return
    await db.delete_channel(ch_id)
    await cb.answer("O'chirildi", show_alert=True)
    await list_mine(cb)


@router.callback_query(F.data.startswith("own:edit:"))
async def ch_edit_start(cb: CallbackQuery, state: FSMContext):
    ch_id = int(cb.data.split(":")[2])
    ch = await db.get_channel(ch_id)
    if not await _ensure_owner(cb, ch):
        return
    await state.set_state(EditChannel.name)
    await state.update_data(ch_id=ch_id)
    await cb.message.answer("Yangi nom kiriting (eskini saqlash: /skip):")
    await cb.answer()


@router.message(EditChannel.name)
async def ch_edit_name(msg: Message, state: FSMContext):
    data = await state.get_data()
    ch = await db.get_channel(data["ch_id"])
    name = ch["name"] if msg.text == "/skip" else msg.text.strip()
    await state.update_data(name=name)
    await state.set_state(EditChannel.chat_id)
    await msg.answer("Yangi chat_id yoki @username kiriting (/skip):")


@router.message(EditChannel.chat_id)
async def ch_edit_chat(msg: Message, state: FSMContext):
    data = await state.get_data()
    ch = await db.get_channel(data["ch_id"])
    chat_id = ch["chat_id"] if msg.text == "/skip" else msg.text.strip()
    await db.update_channel(data["ch_id"], data["name"], chat_id)
    await state.clear()
    await msg.answer("✅ Yangilandi")


# ---------- Template flow ----------
@router.callback_query(F.data.startswith("own:tpl:"))
async def tpl_start_cb(cb: CallbackQuery, state: FSMContext):
    ch_id = int(cb.data.split(":")[2])
    ch = await db.get_channel(ch_id)
    if not await _ensure_owner(cb, ch):
        return
    await start_template_flow(cb.message, state, ch_id)
    await cb.answer()


async def start_template_flow(msg: Message, state: FSMContext, ch_id: int):
    await state.set_state(MakeTemplate.text)
    await state.update_data(ch_id=ch_id)
    await msg.answer(
        "📝 1/2 — OMMAVIY shablon matnini yuboring.\n"
        "Bu matn kanal/guruhga chiqadi.\n\n"
        "O'zgaruvchi joylar uchun {nom} ishlating.\n"
        "Masalan:\n"
        "🏠 Xonadon sotiladi\n"
        "📍 Manzil: {manzil}\n"
        "💰 Narx: {narx} so'm\n\n"
        "ℹ️ Har bir reklamaga avtomatik #_0001 kabi unik ID qo'shiladi.\n"
        "Agar matnda {ad_id} ishlatsangiz — shu joyga qo'yiladi."
    )


@router.message(MakeTemplate.text)
async def tpl_text(msg: Message, state: FSMContext):
    text = msg.text or msg.caption or ""
    await state.update_data(text=text)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Ha, tugma qo'shish", callback_data="tpl:btn:yes")],
            [InlineKeyboardButton(text="❌ Yo'q", callback_data="tpl:btn:no")],
        ]
    )
    await state.set_state(MakeTemplate.btn_choice)
    await msg.answer("Inline tugma qo'shasizmi?", reply_markup=kb)


@router.callback_query(MakeTemplate.btn_choice, F.data == "tpl:btn:no")
async def tpl_btn_no(cb: CallbackQuery, state: FSMContext):
    await state.update_data(
        btn_caption=None, btn_label=None, btn_url=None, btn_url_by_user=False
    )
    await ask_media(cb.message, state)
    await cb.answer()


@router.callback_query(MakeTemplate.btn_choice, F.data == "tpl:btn:yes")
async def tpl_btn_yes(cb: CallbackQuery, state: FSMContext):
    await state.set_state(MakeTemplate.btn_caption)
    await cb.message.answer("Tugma ustidagi caption matnini yuboring (/skip — bo'sh):")
    await cb.answer()


@router.message(MakeTemplate.btn_caption)
async def tpl_btn_caption(msg: Message, state: FSMContext):
    cap = None if msg.text == "/skip" else msg.text
    await state.update_data(btn_caption=cap)
    await state.set_state(MakeTemplate.btn_label)
    await msg.answer("Tugma matnini (label) yuboring, masalan: 📞 Bog'lanish")


@router.message(MakeTemplate.btn_label)
async def tpl_btn_label(msg: Message, state: FSMContext):
    await state.update_data(btn_label=msg.text.strip())
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Admin beradi", callback_data="tpl:url:admin")],
            [InlineKeyboardButton(text="User kiritadi", callback_data="tpl:url:user")],
        ]
    )
    await state.set_state(MakeTemplate.btn_url_mode)
    await msg.answer("Tugma havolasini kim beradi?", reply_markup=kb)


@router.callback_query(MakeTemplate.btn_url_mode, F.data == "tpl:url:user")
async def tpl_url_user(cb: CallbackQuery, state: FSMContext):
    await state.update_data(btn_url=None, btn_url_by_user=True)
    await ask_media(cb.message, state)
    await cb.answer()


@router.callback_query(MakeTemplate.btn_url_mode, F.data == "tpl:url:admin")
async def tpl_url_admin(cb: CallbackQuery, state: FSMContext):
    await state.update_data(btn_url_by_user=False)
    await state.set_state(MakeTemplate.btn_url_value)
    await cb.message.answer("Tugma havolasini yuboring (https://...):")
    await cb.answer()


@router.message(MakeTemplate.btn_url_value)
async def tpl_url_value(msg: Message, state: FSMContext):
    await state.update_data(btn_url=msg.text.strip())
    await ask_media(msg, state)


async def ask_media(msg: Message, state: FSMContext):
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📷 User yuklaydi", callback_data="tpl:media:yes")],
            [InlineKeyboardButton(text="❌ Kerak emas", callback_data="tpl:media:no")],
        ]
    )
    await state.set_state(MakeTemplate.media)
    await msg.answer("Rasm/video kerakmi?", reply_markup=kb)


@router.callback_query(MakeTemplate.media, F.data.startswith("tpl:media:"))
async def tpl_media(cb: CallbackQuery, state: FSMContext):
    required = cb.data.endswith("yes")
    await state.update_data(media_required=required)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Ha, maxfiy guruh qo'shish", callback_data="tpl:priv:yes")],
            [InlineKeyboardButton(text="❌ Yo'q, kerak emas", callback_data="tpl:priv:no")],
        ]
    )
    await state.set_state(MakeTemplate.private_choice)
    await cb.message.answer(
        "🔒 Maxfiy guruh sozlamasi\n\n"
        "User kiritgan qo'shimcha ma'lumotlar (masalan telefon, manzil) "
        "admin ko'radigan alohida maxfiy guruhga yuboriladi.\n"
        "Asosiy kanalga esa faqat \"public\" deb belgilagan maydonlar chiqadi.\n\n"
        "Maxfiy guruh qo'shasizmi?",
        reply_markup=kb,
    )
    await cb.answer()


@router.callback_query(MakeTemplate.private_choice, F.data == "tpl:priv:no")
async def priv_no(cb: CallbackQuery, state: FSMContext):
    await state.update_data(priv_chat_id=None, priv_text=None)
    await start_field_collection(cb.message, state)
    await cb.answer()


@router.callback_query(MakeTemplate.private_choice, F.data == "tpl:priv:yes")
async def priv_yes(cb: CallbackQuery, state: FSMContext, bot: Bot):
    await state.set_state(MakeTemplate.private_chat_id)
    try:
        me = await bot.get_me()
        add_url = f"https://t.me/{me.username}?startgroup=true"
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="➕ Botni guruhga qo'shish", url=add_url)]]
        )
    except Exception:
        kb = None
    await cb.message.answer(
        "Maxfiy guruhingiz @username yoki chat_id sini yuboring.\n"
        "(Masalan: -1001234567890 yoki @mygroup)\n\n"
        "Avval botni o'sha guruhga admin qilib qo'shing.",
        reply_markup=kb,
    )
    await cb.answer()


def _candidate_chat_ids(raw: str) -> list[str]:
    """User turli formatda chat_id yozishi mumkin. Bot har variantni sinaydi:
    - @username -> shunday qaytaradi
    - -100xxxxxxxxxx / -xxxxxxxxxx -> shunday qaytaradi
    - toza musbat raqam -> [-100<raw>, -<raw>, <raw>] (supergroup/channel, basic group, user)
    """
    raw = (raw or "").strip()
    if not raw:
        return []
    if raw.startswith("@"):
        return [raw]
    if raw.startswith("-"):
        return [raw]
    if raw.isdigit():
        cands = []
        # Agar user Telegram UI'dan ko'chirgan bo'lsa va "100..." bilan boshlansa
        if raw.startswith("100") and len(raw) >= 13:
            cands.append(f"-{raw}")         # -100xxxxxxxxxx (to'g'ridan)
        cands.append(f"-100{raw}")           # supergroup/channel
        cands.append(f"-{raw}")              # basic group
        cands.append(raw)                    # private user/chat (oxirgi chora)
        # dedup tartibni saqlab
        seen = set()
        out = []
        for c in cands:
            if c not in seen:
                seen.add(c)
                out.append(c)
        return out
    return [raw]


def _normalize_private_chat_id(raw: str) -> str:
    """Eski API — birinchi nomzodni qaytaradi (asosiy logika endi _candidate_chat_ids'da)."""
    cands = _candidate_chat_ids(raw)
    return cands[0] if cands else raw


@router.message(MakeTemplate.private_chat_id)
async def priv_chat_id(msg: Message, state: FSMContext, bot: Bot):
    candidates = _candidate_chat_ids(msg.text or "")
    if not candidates:
        await msg.answer("❌ Bo'sh yuborildi. Qaytadan urinib ko'ring.")
        return

    chat = None
    last_err = None
    tried = []
    for cand in candidates:
        try:
            c = await bot.get_chat(cand)
            chat = c
            break
        except Exception as e:
            last_err = e
            tried.append(cand)
            continue

    if chat is None:
        await msg.answer(
            "❌ Guruh/kanal topilmadi.\n\n"
            f"Sinab ko'rilgan formatlar:\n• " + "\n• ".join(tried) + "\n\n"
            f"Oxirgi xato: <code>{last_err}</code>\n\n"
            "Eslatma:\n"
            "• Supergroup/kanal id: <code>-1001234567890</code>\n"
            "• Oddiy guruh id: <code>-123456789</code>\n"
            "• Telegram UI dagi 10 xonali raqamni yuborsangiz ham bo'ladi — bot avtomatik sinaydi.\n"
            "• Botni avval o'sha guruhga qo'shganingizga ishonch hosil qiling.",
            parse_mode="HTML",
        )
        return

    try:
        me = await bot.get_me()
        mem = await bot.get_chat_member(chat.id, me.id)
        if mem.status not in ("administrator", "creator", "member"):
            await msg.answer("❌ Bot bu guruhda emas. Avval qo'shing.")
            return
        user_mem = await bot.get_chat_member(chat.id, msg.from_user.id)
        if user_mem.status not in ("administrator", "creator"):
            await msg.answer("❌ Siz bu guruhda admin emassiz.")
            return
    except Exception as e:
        await msg.answer(f"❌ A'zolikni tekshirishda xato: {e}")
        return

    await state.update_data(priv_chat_id=str(chat.id))
    await state.set_state(MakeTemplate.private_text)
    await msg.answer(
        f"✅ Guruh topildi: <b>{chat.title or chat.id}</b> (<code>{chat.id}</code>)\n\n"
        "Endi MAXFIY guruhga yuboriladigan shablon matnini yuboring.\n"
        "To'liq ma'lumotli (barcha maydonlar bilan) bo'lishi mumkin.\n\n"
        "Misol:\n"
        "🆕 Yangi reklama {ad_id}\n"
        "📍 {manzil}\n"
        "💰 {narx}\n"
        "📞 {telefon}\n"
        "👤 @{username} (ID: {user_id})",
        parse_mode="HTML",
    )


@router.message(MakeTemplate.private_text)
async def priv_text(msg: Message, state: FSMContext):
    priv_text = msg.text or msg.caption or ""
    await state.update_data(priv_text=priv_text)
    await start_field_collection(msg, state)


# ---------- Field collection ----------
async def start_field_collection(msg: Message, state: FSMContext):
    """
    Public + private matndagi hamma {placeholder}'larni yig'ib, har biri uchun
    admin'dan: (1) user'ga beriladigan SAVOL, (2) public'da ko'rinadimi — so'raydi.
    """
    data = await state.get_data()
    public_text = data.get("text", "")
    priv_text_val = data.get("priv_text") or ""
    reserved = {"username", "user_id", "ad_id"}
    pub_ph = extract_placeholders(public_text)
    prv_ph = extract_placeholders(priv_text_val)
    all_keys = []
    for k in pub_ph + prv_ph:
        if k in reserved:
            continue
        if k not in all_keys:
            all_keys.append(k)

    if not all_keys:
        await state.update_data(fields=[], field_keys=[], field_idx=0, _pub_keys=[])
        await _ask_extra(msg, state)
        return

    await state.update_data(
        field_keys=all_keys,
        fields=[],
        field_idx=0,
        _pub_keys=pub_ph,
    )
    await _ask_field_question(msg, state)


async def _ask_field_question(msg: Message, state: FSMContext):
    data = await state.get_data()
    idx = data["field_idx"]
    keys = data["field_keys"]
    if idx >= len(keys):
        await _ask_extra(msg, state)
        return
    key = keys[idx]
    await state.set_state(MakeTemplate.field_question)
    await msg.answer(
        f"❓ «{{{key}}}» maydoni uchun userga beriladigan SAVOLNI yozing.\n\n"
        f"Masalan agar {{{key}}} = telefon bo'lsa:\n"
        f"«Telefon raqamingizni kiriting (+998...)»\n\n"
        f"⚠️ Har bir maydon uchun savol majburiy."
    )


@router.message(MakeTemplate.field_question)
async def field_question(msg: Message, state: FSMContext):
    data = await state.get_data()
    if data.get("_extra_mode"):
        key = data["_extra_key"]
    else:
        idx = data["field_idx"]
        keys = data["field_keys"]
        key = keys[idx]
    if msg.text == "/skip" or not (msg.text or "").strip():
        await msg.answer("❌ Savol matni majburiy. Savolni to'liq yozib yuboring:")
        return
    question = msg.text.strip()
    await state.update_data(_cur_key=key, _cur_q=question)

    # Visibility bosqichi olib tashlandi — endi ikkita alohida shablon bor
    # (public + maxfiy), admin shablon matnida qaysi {maydon}ni qayerga qo'yishni
    # o'zi belgilaydi. Barcha maydonlar show_in_public=1 bilan saqlanadi.
    data = await state.get_data()
    fields = list(data.get("fields", []))
    fields.append({
        "key": key,
        "question": question,
        "show_in_public": True,
    })
    update = {"fields": fields}
    if data.get("_extra_mode"):
        update["_extra_mode"] = False
        update["_extra_key"] = None
        await state.update_data(**update)
        await _ask_extra(msg, state)
        return
    update["field_idx"] = data["field_idx"] + 1
    await state.update_data(**update)
    await _ask_field_question(msg, state)


async def _ask_extra(msg: Message, state: FSMContext):
    """Admin'dan yana qo'shimcha maydon qo'shishni so'raydi."""
    data = await state.get_data()
    count = len(data.get("fields", []))
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Yana maydon qo'shish", callback_data="tpl:extra:yes")],
            [InlineKeyboardButton(text="➡️ Davom etish", callback_data="tpl:extra:no")],
        ]
    )
    await state.set_state(MakeTemplate.extra_choice)
    await msg.answer(
        f"Hozircha {count} ta maydon saqlandi.\n\n"
        "Yana qo'shimcha maydon qo'shasizmi?\n"
        "(masalan: texnik ma'lumot, izoh — shablon matnida {} bo'lmasa ham "
        "maxfiy guruhga yuborilishi mumkin)",
        reply_markup=kb,
    )


@router.callback_query(MakeTemplate.extra_choice, F.data == "tpl:extra:no")
async def extra_no(cb: CallbackQuery, state: FSMContext):
    await _ask_id_prefix(cb.message, state)
    await cb.answer()


@router.callback_query(MakeTemplate.extra_choice, F.data == "tpl:extra:yes")
async def extra_yes(cb: CallbackQuery, state: FSMContext):
    await state.set_state(MakeTemplate.extra_key)
    await cb.message.answer(
        "Yangi maydonning nomini (inglizcha, bo'shliqsiz) yuboring.\n"
        "Masalan: telefon, izoh, manzil\n\n"
        "⚠️ Shablon matniga qo'shmoqchi bo'lsangiz keyin qo'lda {nom} ko'rinishida yozishingiz kerak. "
        "Yoki shunchaki maxfiy guruhga yuborish uchun qo'shsangiz bo'ladi."
    )
    await cb.answer()


@router.message(MakeTemplate.extra_key)
async def extra_key_input(msg: Message, state: FSMContext):
    key = msg.text.strip().lstrip("{").rstrip("}").strip().replace(" ", "_")
    if not key or not all(c.isalnum() or c == "_" for c in key):
        await msg.answer("❌ Faqat harf/raqam/_ ishlating. Qayta yuboring:")
        return
    data = await state.get_data()
    existing = [f["key"] for f in data.get("fields", [])]
    if key in existing:
        await msg.answer("❌ Bu nom allaqachon bor. Boshqa nom bering:")
        return
    await state.update_data(_extra_key=key)
    await state.set_state(MakeTemplate.field_question)
    # Endi savol so'rayapti — field_question handler'ini qayta ishlatamiz
    # Lekin idx oshirmaydigan alohida yo'l kerak. Oddiy yo'l: savol so'raymiz
    await state.update_data(_extra_mode=True)
    await msg.answer(
        f"«{{{key}}}» uchun userga beriladigan SAVOLNI yozing.\n"
        "(majburiy — to'liq savol matnini yozing)"
    )


async def _ask_id_prefix(msg: Message, state: FSMContext):
    await state.set_state(MakeTemplate.id_prefix)
    await msg.answer(
        "🆔 Unik ID prefiksini kiriting.\n\n"
        "Masalan:\n"
        "• _  → #_0001\n"
        "• REK → #REK0001\n"
        "• A → #A0001\n\n"
        "Default uchun (_): /skip"
    )


@router.message(MakeTemplate.id_prefix)
async def id_prefix_input(msg: Message, state: FSMContext):
    if msg.text == "/skip":
        prefix = "_"
    else:
        prefix = msg.text.strip()
        if not prefix:
            prefix = "_"
        if len(prefix) > 10:
            await msg.answer("❌ Juda uzun. Maks 10 ta belgi. Qayta:")
            return
    await state.update_data(id_prefix=prefix)
    await _finalize_template(msg, state)


async def _finalize_template(msg: Message, state: FSMContext):
    data = await state.get_data()
    await db.upsert_template(
        channel_id=data["ch_id"],
        text_template=data["text"],
        button_label=data.get("btn_label"),
        button_caption=data.get("btn_caption"),
        button_url=data.get("btn_url"),
        button_url_by_user=data.get("btn_url_by_user", False),
        media_required=data.get("media_required", False),
        private_chat_id=data.get("priv_chat_id"),
        private_text_template=data.get("priv_text"),
        id_prefix=data.get("id_prefix", "_"),
    )
    await db.replace_fields(data["ch_id"], data.get("fields", []))
    await state.clear()
    bot = msg.bot
    sample_prefix = data.get("id_prefix", "_")
    await msg.answer(
        "✅ Shablon saqlandi!\n\n"
        f"• Maydonlar: {len(data.get('fields', []))} ta\n"
        f"• Maxfiy guruh: {'bor' if data.get('priv_chat_id') else 'yo`q'}\n"
        f"• ID format: #{sample_prefix}0001",
        reply_markup=await owner_menu_kb(bot),
    )


# ============================================================
# 📊 KANAL STATISTIKASI (admin uchun)
# ============================================================
@router.callback_query(F.data == "own:stats")
async def own_stats(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    stats = await db.channel_stats_for_owner(cb.from_user.id)
    if not stats:
        await cb.message.edit_text(
            "📊 <b>Kanal statistikasi</b>\n\n"
            "Sizda hali kanal yo'q. Avval kanal qo'shing.",
            reply_markup=await owner_menu_kb(cb.bot),
            parse_mode="HTML",
        )
        await cb.answer()
        return
    lines = ["📊 <b>Kanal statistikasi</b>\n"]
    for s in stats:
        lines.append(
            f"📡 <b>{s['name']}</b>\n"
            f"  📝 Jami: <b>{s['total']}</b>\n"
            f"  ⏳ Kutilmoqda: <b>{s['pending']}</b>\n"
            f"  ✅ Tasdiqlangan: <b>{s['approved']}</b>\n"
            f"  ❌ Rad etilgan: <b>{s['rejected']}</b>\n"
        )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Panel", callback_data="own:home")],
    ])
    await cb.message.edit_text("\n".join(lines), reply_markup=kb, parse_mode="HTML")
    await cb.answer()


# ============================================================
# 📋 KUTILAYOTGAN SO'ROVLAR (admin uchun)
# ============================================================
@router.callback_query(F.data == "own:pending")
async def own_pending(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    ads = await db.list_owner_pending_ads(cb.from_user.id, limit=20)
    if not ads:
        await cb.message.edit_text(
            "📋 <b>Kutilayotgan so'rovlar</b>\n\n"
            "Hozircha kutilayotgan reklamalar yo'q. ✨",
            reply_markup=await owner_menu_kb(cb.bot),
            parse_mode="HTML",
        )
        await cb.answer()
        return
    lines = [f"📋 <b>Kutilayotgan so'rovlar ({len(ads)})</b>\n"]
    for a in ads:
        try:
            fd = json.loads(a["filled_data"] or "{}")
        except Exception:
            fd = {}
        snippet = " | ".join(f"{k}: {v}" for k, v in list(fd.items())[:2])
        uname = f"@{a['username']}" if a["username"] else f"id={a['user_id']}"
        lines.append(f"⏳ <code>#{a['id']}</code> — {uname}\n   {snippet or '—'}")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Panel", callback_data="own:home")],
    ])
    await cb.message.edit_text("\n\n".join(lines), reply_markup=kb, parse_mode="HTML")
    await cb.answer()


# ============================================================================
# TOPSHIRILDI QOIDALARI — admin kanal uchun maydonlarga done_text sozlaydi
# ============================================================================
class DoneCfg(StatesGroup):
    wait_text = State()


@router.callback_query(F.data.startswith("own:done:"))
async def own_done_fields(cb: CallbackQuery):
    ch_id = int(cb.data.split(":")[2])
    ch = await db.get_channel(ch_id)
    if not await _ensure_owner(cb, ch):
        return
    fields = await db.list_fields(ch_id)
    if not fields:
        await cb.answer("Avval shablon va maydonlarni qo'shing", show_alert=True)
        return
    rows = []
    for f in fields:
        try:
            rep = f["done_replace"]
            dt = f["done_text"]
        except (KeyError, IndexError, TypeError):
            rep = 0; dt = None
        state_txt = "✅" if rep else "⚪️"
        preview = (dt[:20] if dt else "—")
        rows.append([InlineKeyboardButton(
            text=f"{state_txt} {f['key']} → {preview}",
            callback_data=f"own:doneset:{f['id']}")])
    rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data=f"own:ch:{ch_id}")])
    await cb.message.edit_text(
        "♻️ <b>Topshirildi qoidalari</b>\n\n"
        "Har bir maydon uchun tugma bosib, user 'Topshirildi' bossa shu maydon qaysi matnga "
        "almashishini belgilang. Yoqilgan maydonlar ✅ bilan ko'rinadi.\n\n"
        "Masalan: <code>telefon</code> maydoni → <code>✅ Topshirildi</code> matniga almashsin.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("own:doneset:"))
async def own_done_set(cb: CallbackQuery, state: FSMContext):
    fid = int(cb.data.split(":")[2])
    f = await db.get_field(fid)
    if not f:
        await cb.answer("Topilmadi", show_alert=True)
        return
    ch = await db.get_channel(f["channel_id"])
    if not await _ensure_owner(cb, ch):
        return
    try:
        rep = f["done_replace"]
    except (KeyError, IndexError, TypeError):
        rep = 0
    # Tezkor toggle: agar yoqilgan bo'lsa — o'chiramiz; agar yo'q bo'lsa matn so'raymiz
    if rep:
        await db.field_set_done_rule(fid, 0, None)
        await cb.answer("⚪️ O'chirildi")
        cb.data = f"own:done:{f['channel_id']}"
        await own_done_fields(cb)
        return
    await state.set_state(DoneCfg.wait_text)
    await state.update_data(done_fid=fid, done_ch_id=f["channel_id"])
    await cb.message.answer(
        f"<b>{f['key']}</b> maydoni uchun 'Topshirildi' holatidagi matnni yuboring.\n"
        f"Masalan: <code>✅ Topshirildi</code>",
        parse_mode="HTML",
    )
    await cb.answer()


@router.message(DoneCfg.wait_text)
async def own_done_set_save(msg: Message, state: FSMContext):
    data = await state.get_data()
    fid = data.get("done_fid")
    ch_id = data.get("done_ch_id")
    txt = (msg.text or "").strip()
    if not txt or len(txt) > 200:
        await msg.answer("❌ 1-200 belgi bo'lsin")
        return
    await db.field_set_done_rule(fid, 1, txt)
    await state.clear()
    await msg.answer(f"✅ Saqlandi: <code>{txt}</code>", parse_mode="HTML")


# ============================================================================
# REJA9: Aloqa tugmasi sozlash — button_label + private_text + premium_url
# ============================================================================
class BtnConfig(StatesGroup):
    btn_label = State()
    btn_private_text = State()
    btn_premium_url = State()


def _btn_skip_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⏭ O'tkazib yuborish", callback_data="own:btn:skip")
    ]])


@router.callback_query(F.data.startswith("own:btn:") & ~F.data.endswith(":skip"))
async def own_btn_start(cb: CallbackQuery, state: FSMContext):
    try:
        ch_id = int(cb.data.split(":")[2])
    except (ValueError, IndexError):
        return
    ch = await db.get_channel(ch_id)
    if not await _ensure_owner(cb, ch):
        return
    tpl = await db.get_template(ch_id)
    if not tpl:
        await cb.answer("Avval shablon yarating", show_alert=True)
        return
    await state.set_state(BtnConfig.btn_label)
    await state.update_data(btn_ch_id=ch_id)
    cur = ""
    try:
        cur = tpl["button_label"] or ""
    except (KeyError, IndexError):
        pass
    await cb.message.answer(
        f"🔘 <b>Aloqa tugmasi yozuvi</b>\n\n"
        f"Tugma yozuvini yuboring (masalan: <code>📞 Aloqa</code>)\n"
        f"Hozirgi: <code>{cur or '—'}</code>",
        parse_mode="HTML",
    )
    await cb.answer()


@router.message(BtnConfig.btn_label)
async def own_btn_label_save(msg: Message, state: FSMContext):
    txt = (msg.text or "").strip()
    if not txt or len(txt) > 64:
        await msg.answer("❌ 1-64 belgi bo'lsin")
        return
    await state.update_data(btn_label=txt)
    await state.set_state(BtnConfig.btn_private_text)
    await msg.answer(
        "🔒 <b>Maxfiy guruhga yuboriladigan matn</b>\n\n"
        "A'zo bo'lgan user'lar 'Aloqa' tugmasini bosganda botdan shu matn yuboriladi.\n"
        "Placeholder: <code>{name}</code>, <code>{price}</code>, <code>{phone}</code> va h.k.\n\n"
        "Matn yuboring yoki o'tkazib yuborish tugmasini bosing.",
        parse_mode="HTML",
        reply_markup=_btn_skip_kb(),
    )


@router.message(BtnConfig.btn_private_text)
async def own_btn_private_save(msg: Message, state: FSMContext):
    txt = (msg.text or "").strip()
    if not txt:
        await msg.answer("❌ Matn bo'sh")
        return
    await state.update_data(btn_private_text=txt)
    await state.set_state(BtnConfig.btn_premium_url)
    await msg.answer(
        "💎 <b>Premium URL</b>\n\n"
        "A'zo bo'lmagan user uchun ko'rsatiladigan URL (masalan: <code>https://t.me/admin</code>)\n"
        "URL yuboring yoki o'tkazib yuboring.",
        parse_mode="HTML",
        reply_markup=_btn_skip_kb(),
    )


@router.message(BtnConfig.btn_premium_url)
async def own_btn_premium_save(msg: Message, state: FSMContext):
    txt = (msg.text or "").strip()
    if not (txt.startswith("http://") or txt.startswith("https://") or txt.startswith("tg://")):
        await msg.answer("❌ URL http(s):// yoki tg:// bilan boshlansin")
        return
    await state.update_data(btn_premium_url=txt)
    await _btn_finalize(msg, state)


@router.callback_query(F.data == "own:btn:skip")
async def own_btn_skip(cb: CallbackQuery, state: FSMContext):
    cur = await state.get_state()
    if cur == BtnConfig.btn_private_text.state:
        await state.update_data(btn_private_text="__KEEP__")
        await state.set_state(BtnConfig.btn_premium_url)
        await cb.message.answer(
            "💎 Premium URL yuboring yoki o'tkazib yuboring.",
            reply_markup=_btn_skip_kb(),
        )
        await cb.answer()
        return
    if cur == BtnConfig.btn_premium_url.state:
        await state.update_data(btn_premium_url="__KEEP__")
        await _btn_finalize(cb.message, state)
        await cb.answer()
        return
    await state.clear()
    await cb.message.answer("❌ Bekor qilindi")
    await cb.answer()


async def _btn_finalize(msg: Message, state: FSMContext):
    data = await state.get_data()
    ch_id = data.get("btn_ch_id")
    new_label = data.get("btn_label")
    new_private = data.get("btn_private_text", "__KEEP__")
    new_premium = data.get("btn_premium_url", "__KEEP__")
    await state.clear()

    tpl = await db.get_template(ch_id)
    if not tpl:
        await msg.answer("❌ Shablon topilmadi")
        return

    def _get(k, default=None):
        try:
            return tpl[k]
        except (KeyError, IndexError):
            return default

    final_private = _get("private_text_template") if new_private == "__KEEP__" else new_private
    final_premium = _get("premium_url") if new_premium == "__KEEP__" else new_premium

    await db.upsert_template(
        channel_id=ch_id,
        text_template=_get("text_template") or "",
        button_label=new_label,
        button_caption=_get("button_caption"),
        button_url=_get("button_url"),
        button_url_by_user=bool(_get("button_url_by_user")),
        media_required=bool(_get("media_required")),
        private_chat_id=_get("private_chat_id"),
        private_text_template=final_private,
        id_prefix=_get("id_prefix") or "_",
        premium_url=final_premium,
    )
    priv_msg = "yangilandi" if new_private != "__KEEP__" else "o'zgarmadi"
    await msg.answer(
        f"✅ Saqlandi\n"
        f"🔘 Tugma: «{new_label}»\n"
        f"🔒 Maxfiy matn: {priv_msg}\n"
        f"💎 Premium URL: {final_premium or '—'}",
        parse_mode="HTML",
    )


# ============================================================
# REJA10: Aloqa field + Sotildi field/replacement sozlamalari
# ============================================================

class R10State(StatesGroup):
    sold_replacement = State()
    sold_rule_value = State()


def _tpl_get(tpl, key, default=None):
    try:
        v = tpl[key]
        return v if v is not None else default
    except (KeyError, IndexError):
        return default


async def _r10_render(cb_or_msg, ch_id: int, bot=None):
    tpl = await db.get_template(ch_id)
    fields = await db.list_fields(ch_id)
    contact_key = _tpl_get(tpl, "contact_field_key") if tpl else None
    tg_key = _tpl_get(tpl, "telegram_field_key") if tpl else None

    # Parse sold_rules (backward compat)
    from utils.sold_rules import parse_rules
    rules = parse_rules(tpl) if tpl else []

    def _label(k):
        if not k:
            return "belgilanmagan"
        for f in fields:
            if f["key"] == k:
                return f"«{f['question']}» ({k})"
        return f"{k} (maydon topilmadi)"

    rules_txt = ""
    if rules:
        for i, r in enumerate(rules, 1):
            v = r.get("value") or ""
            v_disp = f"<code>{v}</code>" if v else "<i>(bo'sh — qiymat olib tashlanadi)</i>"
            rules_txt += f"   {i}. <b>{{{r['key']}}}</b> → {v_disp}\n"
    else:
        rules_txt = "   <i>Hali qoidalar yo'q — default: title oldiga 🔴 SOTILDI</i>\n"

    text = (
        "🎯 <b>Aloqa / Sotildi sozlamalari</b>\n\n"
        "📞 <b>Aloqa maydoni</b> — WebApp'da «Aloqa» tugmasi bosilganda "
        "shu maydon qiymati DM qilinadi.\n"
        f"   Hozir: <b>{_label(contact_key)}</b>\n\n"
        "💬 <b>Telegram maydoni</b> — «Aloqa» link sifatida "
        "https://t.me/&lt;username&gt; ga yo'naltiradi.\n"
        f"   Hozir: <b>{_label(tg_key)}</b>\n\n"
        "🏷 <b>Sotildi qoidalari</b> — user «Sotildi» bosganda "
        "quyidagi maydonlar qiymati almashtiriladi. Agar qiymat bo'sh bo'lsa, "
        "shu maydon postdan ko'rinmay qoladi (bo'sh qator).\n\n"
        f"{rules_txt}"
    )

    kb_rows = [
        [InlineKeyboardButton(text="📞 Aloqa maydoni", callback_data=f"own:r10c:{ch_id}")],
        [InlineKeyboardButton(text="💬 Telegram maydoni", callback_data=f"own:r10t:{ch_id}")],
        [InlineKeyboardButton(text="➕ Sotildi qoida qo'shish", callback_data=f"own:srad:{ch_id}")],
    ]
    for i, r in enumerate(rules):
        short_v = (r.get("value") or "bo'sh")[:20]
        kb_rows.append([
            InlineKeyboardButton(
                text=f"🗑 {{{r['key']}}} → {short_v}",
                callback_data=f"own:srd:{ch_id}:{i}"
            )
        ])
    kb_rows.append([InlineKeyboardButton(text="⬅️ Kanal menyusi", callback_data=f"own:ch:{ch_id}")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    target = cb_or_msg.message if isinstance(cb_or_msg, CallbackQuery) else cb_or_msg
    try:
        await target.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await target.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("own:r10:"))
async def r10_home(cb: CallbackQuery, state: FSMContext):
    ch_id = int(cb.data.split(":")[2])
    ch = await db.get_channel(ch_id)
    if not await _ensure_owner(cb, ch):
        return
    await state.clear()
    await _r10_render(cb, ch_id)
    await cb.answer()


async def _r10_pick_field(cb: CallbackQuery, ch_id: int, kind: str):
    """kind: 'c' contact | 'sr' sold_rule_add | 't' telegram"""
    ch = await db.get_channel(ch_id)
    if not await _ensure_owner(cb, ch):
        return
    fields = await db.list_fields(ch_id)
    if not fields:
        await cb.answer("Avval maydonlar qo'shing (Default shablon)", show_alert=True)
        return
    titles = {
        "c": "📞 Aloqa maydonini tanlang",
        "sr": "🏷 Sotildi qoidasi uchun maydonni tanlang",
        "t": "💬 Telegram maydonini tanlang (username maydoni)",
    }
    title = titles.get(kind, "Maydonni tanlang")
    kb_rows = []
    for f in fields:
        kb_rows.append([InlineKeyboardButton(
            text=f"{f['question']} ({{{f['key']}}})",
            callback_data=f"own:r10set:{kind}:{ch_id}:{f['id']}"
        )])
    kb_rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data=f"own:r10:{ch_id}")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    try:
        await cb.message.edit_text(title, reply_markup=kb)
    except Exception:
        await cb.message.answer(title, reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.startswith("own:r10c:"))
async def r10_pick_contact(cb: CallbackQuery):
    ch_id = int(cb.data.split(":")[2])
    await _r10_pick_field(cb, ch_id, "c")


@router.callback_query(F.data.startswith("own:r10t:"))
async def r10_pick_telegram(cb: CallbackQuery):
    ch_id = int(cb.data.split(":")[2])
    await _r10_pick_field(cb, ch_id, "t")


@router.callback_query(F.data.startswith("own:srad:"))
async def r10_sold_rule_add(cb: CallbackQuery):
    ch_id = int(cb.data.split(":")[2])
    await _r10_pick_field(cb, ch_id, "sr")


async def _save_tpl(ch_id, tpl, **overrides):
    params = dict(
        channel_id=ch_id,
        text_template=_tpl_get(tpl, "text_template", "") or "",
        button_label=_tpl_get(tpl, "button_label"),
        button_caption=_tpl_get(tpl, "button_caption"),
        button_url=_tpl_get(tpl, "button_url"),
        button_url_by_user=bool(_tpl_get(tpl, "button_url_by_user", 0)),
        media_required=bool(_tpl_get(tpl, "media_required", 0)),
        private_chat_id=_tpl_get(tpl, "private_chat_id"),
        private_text_template=_tpl_get(tpl, "private_text_template"),
        id_prefix=_tpl_get(tpl, "id_prefix", "_") or "_",
        premium_url=_tpl_get(tpl, "premium_url"),
        contact_field_key=_tpl_get(tpl, "contact_field_key"),
        sold_field_key=_tpl_get(tpl, "sold_field_key"),
        sold_replacement=_tpl_get(tpl, "sold_replacement"),
        telegram_field_key=_tpl_get(tpl, "telegram_field_key"),
        sold_rules=_tpl_get(tpl, "sold_rules") or "",
    )
    params.update(overrides)
    await db.upsert_template(**params)


@router.callback_query(F.data.startswith("own:r10set:"))
async def r10_set_field(cb: CallbackQuery, state: FSMContext):
    parts = cb.data.split(":")
    # own:r10set:<kind>:<ch_id>:<field_id>
    kind = parts[2]
    ch_id = int(parts[3])
    field_id = int(parts[4])
    ch = await db.get_channel(ch_id)
    if not await _ensure_owner(cb, ch):
        return
    fields = await db.list_fields(ch_id)
    target_field = next((f for f in fields if f["id"] == field_id), None)
    if not target_field:
        await cb.answer("❌ Maydon topilmadi", show_alert=True)
        return

    tpl = await db.get_template(ch_id) or {}
    if kind == "c":
        await _save_tpl(ch_id, tpl, contact_field_key=target_field["key"])
        await cb.answer("✅ Saqlandi", show_alert=False)
        await _r10_render(cb, ch_id)
    elif kind == "t":
        await _save_tpl(ch_id, tpl, telegram_field_key=target_field["key"])
        await cb.answer("✅ Saqlandi", show_alert=False)
        await _r10_render(cb, ch_id)
    elif kind == "sr":
        # So'raymiz: qoidani qanday qiymatga almashtirish (bo'sh yuborsa — maydon bo'sh bo'ladi)
        await state.set_state(R10State.sold_rule_value)
        await state.update_data(r10_ch_id=ch_id, r10_key=target_field["key"])
        await cb.message.answer(
            f"✏️ <b>{{{target_field['key']}}}</b> maydoni «Sotildi» bosilganda nimaga almashsin?\n\n"
            "• Matn yuboring: masalan <code>TOPSHIRILDI</code>\n"
            "• <code>-</code> (bitta chiziq) yuborsangiz qiymat <b>bo'sh</b> qoladi "
            "(ya'ni postda bu maydon ko'rinmaydi)\n"
            "• /cancel bekor qilish",
            parse_mode="HTML",
        )
        await cb.answer()


@router.message(R10State.sold_rule_value)
async def r10_sold_rule_save(msg: Message, state: FSMContext):
    text = (msg.text or "").strip()
    if text.lower() in ("/cancel", "cancel", "bekor"):
        await state.clear()
        await msg.answer("❌ Bekor qilindi")
        return
    if len(text) > 120:
        await msg.answer("⚠️ 120 belgidan oshmasin")
        return
    data = await state.get_data()
    ch_id = data.get("r10_ch_id")
    key = data.get("r10_key")
    await state.clear()
    if not ch_id or not key:
        await msg.answer("❌ Xato: context yo'qolgan")
        return

    # "-" → bo'sh qiymat
    value = "" if text == "-" else text

    tpl = await db.get_template(ch_id) or {}
    from utils.sold_rules import parse_rules, dump_rules
    rules = parse_rules(tpl)
    # Shu key uchun bor qoidani yangilaymiz yoki yangisini qo'shamiz
    found = False
    for r in rules:
        if r["key"] == key:
            r["value"] = value
            found = True
            break
    if not found:
        rules.append({"key": key, "value": value})

    await _save_tpl(ch_id, tpl, sold_rules=dump_rules(rules))
    disp = f"«{value}»" if value else "<i>bo'sh</i>"
    await msg.answer(f"✅ Qoida saqlandi: <b>{{{key}}}</b> → {disp}", parse_mode="HTML")
    await _r10_render(msg, ch_id)


@router.callback_query(F.data.startswith("own:srd:"))
async def r10_sold_rule_delete(cb: CallbackQuery):
    # own:srd:<ch_id>:<index>
    parts = cb.data.split(":")
    ch_id = int(parts[2])
    idx = int(parts[3])
    ch = await db.get_channel(ch_id)
    if not await _ensure_owner(cb, ch):
        return
    tpl = await db.get_template(ch_id) or {}
    from utils.sold_rules import parse_rules, dump_rules
    rules = parse_rules(tpl)
    if 0 <= idx < len(rules):
        removed = rules.pop(idx)
        await _save_tpl(ch_id, tpl, sold_rules=dump_rules(rules))
        await cb.answer(f"🗑 O'chirildi: {{{removed['key']}}}", show_alert=False)
    else:
        await cb.answer("Topilmadi", show_alert=True)
    await _r10_render(cb, ch_id)



# ============================================================================
# REJA12: Sold/Free matnlar — admin o'zgartiradi
# ============================================================================
class TextsConfig(StatesGroup):
    sold_text = State()
    free_text = State()
    free_btn_label = State()
    free_btn_url = State()


def _texts_skip_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⏭ O'tkazib yuborish", callback_data="own:txskip")
    ]])


async def _save_text_col(ch_id: int, col: str, value: str):
    """templates jadvalidagi matn ustunini yangilaydi (yoki yaratadi)."""
    import aiosqlite
    from config import DB_PATH
    async with aiosqlite.connect(DB_PATH) as dbx:
        cur = await dbx.execute("SELECT id FROM templates WHERE channel_id=?", (ch_id,))
        row = await cur.fetchone()
        if row:
            await dbx.execute(f"UPDATE templates SET {col}=? WHERE channel_id=?", (value, ch_id))
        else:
            # Default shablon yaratib, keyin update
            await dbx.execute(
                "INSERT INTO templates (channel_id, text_template, id_prefix) VALUES (?, '', '_')",
                (ch_id,),
            )
            await dbx.execute(f"UPDATE templates SET {col}=? WHERE channel_id=?", (value, ch_id))
        await dbx.commit()


@router.callback_query(F.data.startswith("own:texts:"))
async def own_texts_start(cb: CallbackQuery, state: FSMContext):
    try:
        ch_id = int(cb.data.split(":")[2])
    except (ValueError, IndexError):
        return
    ch = await db.get_channel(ch_id)
    if not await _ensure_owner(cb, ch):
        return
    tpl = await db.get_template(ch_id) or {}
    cur = _tpl_get(tpl, "sold_text", "") or ""
    await state.set_state(TextsConfig.sold_text)
    await state.update_data(tx_ch_id=ch_id)
    await cb.message.answer(
        "📝 <b>1/4 — TOPSHIRILDI matni</b>\n\n"
        "Post topshirilganda (sotildi / yopildi) <u>barcha</u> userlar "
        "Aloqa va To'liq ma'lumot tugmalarini bosganda ko'radigan matn.\n\n"
        f"Hozirgi: <code>{(cur[:200] + '…') if len(cur) > 200 else (cur or '—')}</code>\n\n"
        "Matn yuboring yoki o'tkazib yuborish tugmasini bosing.",
        parse_mode="HTML",
        reply_markup=_texts_skip_kb(),
    )
    await cb.answer()


async def _texts_next_ask(msg_or_cb, state: FSMContext, next_state):
    data = await state.get_data()
    ch_id = int(data.get("tx_ch_id") or 0)
    tpl = await db.get_template(ch_id) or {}
    await state.set_state(next_state)
    send = msg_or_cb.message.answer if isinstance(msg_or_cb, CallbackQuery) else msg_or_cb.answer
    if next_state == TextsConfig.free_text:
        cur = _tpl_get(tpl, "free_text", "") or ""
        await send(
            "👤 <b>2/4 — ODDIY USER matni</b>\n\n"
            "Premium bo'lmagan user 'Aloqa' yoki 'To'liq ma'lumot' bosganda "
            "ko'radigan matn (odatda: 'Admin bilan bog'laning', 'Premium oling' va h.k.).\n\n"
            f"Hozirgi: <code>{(cur[:200] + '…') if len(cur) > 200 else (cur or '—')}</code>\n\n"
            "Matn yuboring yoki o'tkazib yuboring.",
            parse_mode="HTML", reply_markup=_texts_skip_kb(),
        )
    elif next_state == TextsConfig.free_btn_label:
        cur = _tpl_get(tpl, "free_btn_label", "") or ""
        await send(
            "🔘 <b>3/4 — Oddiy user tugmasi nomi</b>\n\n"
            "Masalan: <code>📝 Adminga yozish</code>\n\n"
            f"Hozirgi: <code>{cur or '—'}</code>\n\n"
            "Nom yuboring yoki o'tkazib yuboring (tugma ko'rinmaydi).",
            parse_mode="HTML", reply_markup=_texts_skip_kb(),
        )
    elif next_state == TextsConfig.free_btn_url:
        cur = _tpl_get(tpl, "free_btn_url", "") or ""
        await send(
            "🔗 <b>4/4 — Oddiy user tugmasi linki</b>\n\n"
            "Masalan: <code>https://t.me/admin</code>\n\n"
            f"Hozirgi: <code>{cur or '—'}</code>\n\n"
            "URL yuboring yoki o'tkazib yuboring.",
            parse_mode="HTML", reply_markup=_texts_skip_kb(),
        )


@router.message(TextsConfig.sold_text)
async def txt_sold_save(msg: Message, state: FSMContext):
    data = await state.get_data()
    ch_id = int(data.get("tx_ch_id") or 0)
    await _save_text_col(ch_id, "sold_text", (msg.text or "").strip())
    await msg.answer("✅ Saqlandi")
    await _texts_next_ask(msg, state, TextsConfig.free_text)


@router.message(TextsConfig.free_text)
async def txt_free_save(msg: Message, state: FSMContext):
    data = await state.get_data()
    ch_id = int(data.get("tx_ch_id") or 0)
    await _save_text_col(ch_id, "free_text", (msg.text or "").strip())
    await msg.answer("✅ Saqlandi")
    await _texts_next_ask(msg, state, TextsConfig.free_btn_label)


@router.message(TextsConfig.free_btn_label)
async def txt_free_lbl_save(msg: Message, state: FSMContext):
    data = await state.get_data()
    ch_id = int(data.get("tx_ch_id") or 0)
    txt = (msg.text or "").strip()
    if len(txt) > 64:
        await msg.answer("❌ 64 belgidan uzun bo'lmasin")
        return
    await _save_text_col(ch_id, "free_btn_label", txt)
    await msg.answer("✅ Saqlandi")
    await _texts_next_ask(msg, state, TextsConfig.free_btn_url)


@router.message(TextsConfig.free_btn_url)
async def txt_free_url_save(msg: Message, state: FSMContext):
    data = await state.get_data()
    ch_id = int(data.get("tx_ch_id") or 0)
    txt = (msg.text or "").strip()
    if txt and not (txt.startswith("http://") or txt.startswith("https://") or txt.startswith("tg://") or txt.startswith("t.me/") or txt.startswith("@")):
        await msg.answer("❌ URL https:// yoki t.me/ bilan boshlansin")
        return
    if txt.startswith("t.me/"):
        txt = "https://" + txt
    elif txt.startswith("@"):
        txt = "https://t.me/" + txt.lstrip("@")
    await _save_text_col(ch_id, "free_btn_url", txt)
    await state.clear()
    await msg.answer("✅ Barcha matnlar saqlandi. Kanal menyusiga qayting.")


@router.callback_query(F.data == "own:txskip", StateFilter(TextsConfig.sold_text, TextsConfig.free_text, TextsConfig.free_btn_label, TextsConfig.free_btn_url))
async def txt_skip(cb: CallbackQuery, state: FSMContext):
    cur = await state.get_state()
    if cur == TextsConfig.sold_text.state:
        await _texts_next_ask(cb, state, TextsConfig.free_text)
    elif cur == TextsConfig.free_text.state:
        await _texts_next_ask(cb, state, TextsConfig.free_btn_label)
    elif cur == TextsConfig.free_btn_label.state:
        await _texts_next_ask(cb, state, TextsConfig.free_btn_url)
    else:
        await state.clear()
        await cb.message.answer("✅ Tugadi")
    await cb.answer("O'tkazildi")


# ============================================================================
# REJA13: Obuna (premium) sozlamalari — 3 bosqich
# ============================================================================
class SubConfig(StatesGroup):
    btn_label = State()
    offer_text = State()
    invite_link = State()


def _sub_skip_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⏭ O'tkazib yuborish", callback_data="own:subskip")
    ]])


@router.callback_query(F.data.startswith("own:sub:"))
async def own_sub_start(cb: CallbackQuery, state: FSMContext):
    try:
        ch_id = int(cb.data.split(":")[2])
    except (ValueError, IndexError):
        return
    ch = await db.get_channel(ch_id)
    if not await _ensure_owner(cb, ch):
        return
    tpl = await db.get_template(ch_id) or {}
    cur = _tpl_get(tpl, "sub_btn_label", "") or ""
    await state.set_state(SubConfig.btn_label)
    await state.update_data(sub_ch_id=ch_id)
    await cb.message.answer(
        "💎 <b>1/3 — Obuna tugma nomi</b>\n\n"
        "Ommaviy post ostida ko'rinadigan inline tugma nomi. "
        "Ichida <code>{maydon}</code> ishlatish mumkin (masalan: "
        "<code>💎 Premium obuna — {price}</code>).\n\n"
        f"Hozirgi: <code>{cur or '—'}</code>\n\n"
        "Matn yuboring. Bo'sh qoldirish uchun — bitta tire <code>-</code> yuboring (tugma ko'rinmaydi).",
        parse_mode="HTML",
        reply_markup=_sub_skip_kb(),
    )
    await cb.answer()


async def _sub_next_ask(m_or_cb, state: FSMContext, next_state):
    data = await state.get_data()
    ch_id = int(data.get("sub_ch_id") or 0)
    tpl = await db.get_template(ch_id) or {}
    send = m_or_cb.message.answer if isinstance(m_or_cb, CallbackQuery) else m_or_cb.answer
    await state.set_state(next_state)
    if next_state == SubConfig.offer_text:
        cur = _tpl_get(tpl, "sub_offer_text", "") or ""
        await send(
            "📝 <b>2/3 — Obuna taklif matni</b>\n\n"
            "User tugmani bosib botga o'tganda ko'radigan matn. "
            "Keyin user 'Ariza yuborish' tugmasini bosadi.\n\n"
            f"Hozirgi: <code>{(cur[:250] + '…') if len(cur) > 250 else (cur or '—')}</code>\n\n"
            "Matn yuboring yoki o'tkazib yuboring (default matn ishlatiladi).",
            parse_mode="HTML", reply_markup=_sub_skip_kb(),
        )
    elif next_state == SubConfig.invite_link:
        cur = _tpl_get(tpl, "private_invite_link", "") or ""
        await send(
            "🔗 <b>3/3 — Maxfiy guruh invite linki</b>\n\n"
            "Admin obunani qabul qilganda userga yuboriladigan havola. "
            "Masalan: <code>https://t.me/+AbCdEf...</code>\n\n"
            f"Hozirgi: <code>{cur or '—'}</code>\n\n"
            "Agar o'tkazib yuborsangiz va maxfiy guruh chat_id sozlangan bo'lsa, "
            "bot har safar avtomatik invite link yaratadi (bot guruhda admin bo'lishi shart).",
            parse_mode="HTML", reply_markup=_sub_skip_kb(),
        )


@router.message(SubConfig.btn_label)
async def sub_lbl_save(msg: Message, state: FSMContext):
    data = await state.get_data()
    ch_id = int(data.get("sub_ch_id") or 0)
    txt = (msg.text or "").strip()
    if txt == "-":
        txt = ""
    if len(txt) > 64:
        await msg.answer("❌ 64 belgidan uzun bo'lmasin")
        return
    await _save_text_col(ch_id, "sub_btn_label", txt)
    await msg.answer("✅ Saqlandi")
    await _sub_next_ask(msg, state, SubConfig.offer_text)


@router.message(SubConfig.offer_text)
async def sub_offer_save(msg: Message, state: FSMContext):
    data = await state.get_data()
    ch_id = int(data.get("sub_ch_id") or 0)
    await _save_text_col(ch_id, "sub_offer_text", (msg.text or "").strip())
    await msg.answer("✅ Saqlandi")
    await _sub_next_ask(msg, state, SubConfig.invite_link)


@router.message(SubConfig.invite_link)
async def sub_link_save(msg: Message, state: FSMContext):
    data = await state.get_data()
    ch_id = int(data.get("sub_ch_id") or 0)
    txt = (msg.text or "").strip()
    if txt and not (txt.startswith("https://t.me/") or txt.startswith("http://t.me/")):
        await msg.answer("❌ Invite link https://t.me/+... ko'rinishida bo'lsin")
        return
    await _save_text_col(ch_id, "private_invite_link", txt)
    await state.clear()
    await msg.answer("✅ Obuna sozlamalari saqlandi.")


@router.callback_query(F.data == "own:subskip", StateFilter(SubConfig.btn_label, SubConfig.offer_text, SubConfig.invite_link))
async def sub_skip(cb: CallbackQuery, state: FSMContext):
    cur = await state.get_state()
    if cur == SubConfig.btn_label.state:
        await _sub_next_ask(cb, state, SubConfig.offer_text)
    elif cur == SubConfig.offer_text.state:
        await _sub_next_ask(cb, state, SubConfig.invite_link)
    else:
        await state.clear()
        await cb.message.answer("✅ Tugadi")
    await cb.answer("O'tkazildi")
