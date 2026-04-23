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
    field_visibility = State() # public da ko'rinadimi
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

    await msg.answer(
        f"✅ «{name}» qo'shildi!\n\nEndi shu kanal uchun reklama shablonini yarataylik."
    )
    await start_template_flow(msg, state, ch_id)


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
    fields_info = f"📝 {len(fields)} ta savol" if fields else "—"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📝 Shablonni yangilash", callback_data=f"own:tpl:{ch_id}")],
            [InlineKeyboardButton(text="♻️ Topshirildi qoidalari", callback_data=f"own:done:{ch_id}")],
            [InlineKeyboardButton(text="✏️ Nomini/chat_id tahrirlash", callback_data=f"own:edit:{ch_id}")],
            [InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"own:del:{ch_id}")],
            [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="own:list")],
        ]
    )
    await cb.message.edit_text(
        f"📍 {ch['name']}\nchat_id: {ch['chat_id']}\n{tpl_info}\n{fields_info}",
        reply_markup=kb,
    )
    await cb.answer()


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

    # Default public: agar extra bo'lsa default=private, aks holda pub_keys'ga qarab
    pub_keys = data.get("_pub_keys", [])
    default_public = key in pub_keys and not data.get("_extra_mode")
    hint_pub = "KO'RINADI" if default_public else "KO'RINMAYDI"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Public (kanalda ko'rinadi)", callback_data="fld:vis:1")],
            [InlineKeyboardButton(text="🔒 Maxfiy (faqat maxfiy guruhga)", callback_data="fld:vis:0")],
        ]
    )
    await state.set_state(MakeTemplate.field_visibility)
    await msg.answer(
        f"«{{{key}}}» maydoni asosiy kanal/guruhda ko'rinsinmi?\n"
        f"(Tavsiya: hozir {hint_pub})",
        reply_markup=kb,
    )


@router.callback_query(MakeTemplate.field_visibility, F.data.startswith("fld:vis:"))
async def field_visibility(cb: CallbackQuery, state: FSMContext):
    show_public = cb.data.endswith("1")
    data = await state.get_data()
    fields = list(data.get("fields", []))
    fields.append({
        "key": data["_cur_key"],
        "question": data["_cur_q"],
        "show_in_public": show_public,
    })
    update = {"fields": fields}
    if data.get("_extra_mode"):
        # extra modedan chiqib, yana _ask_extra ga qaytamiz
        update["_extra_mode"] = False
        update["_extra_key"] = None
        await state.update_data(**update)
        await cb.answer("Qo'shildi")
        await _ask_extra(cb.message, state)
        return
    # oddiy flow — keyingi key'ga o'tamiz
    update["field_idx"] = data["field_idx"] + 1
    await state.update_data(**update)
    await cb.answer("Saqlandi")
    await _ask_field_question(cb.message, state)


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
