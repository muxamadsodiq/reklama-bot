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

router = Router()
log = logging.getLogger(__name__)


class AddAdmin(StatesGroup):
    user_id = State()


async def _gate(uid: int) -> bool:
    return uid in SUPER_ADMIN_IDS


async def _sa_only_msg(event: Message) -> bool:
    try:
        if event.chat.type != "private":
            return False
    except Exception:
        return False
    return event.from_user.id in SUPER_ADMIN_IDS


async def _sa_only_cb(event: CallbackQuery) -> bool:
    return event.from_user.id in SUPER_ADMIN_IDS


router.message.filter(_sa_only_msg)
router.callback_query.filter(_sa_only_cb)


def sa_menu_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Admin qo'shish", callback_data="sa:add")],
            [InlineKeyboardButton(text="📋 Adminlar ro'yxati", callback_data="sa:list")],
            [InlineKeyboardButton(text="🌐 Global statistika", callback_data="sa:gstats")],
            [InlineKeyboardButton(text="📊 Statistika (so'rovnoma)", callback_data="sa:st:home")],
            [InlineKeyboardButton(text="🧷 Kanal tanlash sozlamalari", callback_data="sa:chs:home")],
            [InlineKeyboardButton(text="⬅️ Bosh menyu", callback_data="u:home")],
        ]
    )


class ChSettings(StatesGroup):
    prompt_text = State()
    btn_label = State()


@router.callback_query(F.data == "sa:gstats")
async def sa_gstats(cb: CallbackQuery):
    g = await db.global_stats()
    text = (
        "🌐 <b>Global statistika</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"📝 Jami reklamalar:      <b>{g['total_ads']}</b>\n"
        f"⏳ Kutilmoqda:            <b>{g['pending']}</b>\n"
        f"✅ Tasdiqlangan:          <b>{g['approved']}</b>\n"
        f"❌ Rad etilgan:           <b>{g['rejected']}</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Unik userlar:          <b>{g['unique_users']}</b>\n"
        f"📡 Kanallar:              <b>{g['channels']}</b>\n"
        f"🧩 Adminlar:              <b>{g['admins']}</b>\n"
    )
    await cb.message.edit_text(text, reply_markup=sa_menu_kb(), parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data == "sa:home")
async def sa_home(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    admins = await db.list_admins()
    await cb.message.edit_text(
        f"👑 Super admin paneli\n\n"
        f"Joriy adminlar soni: <b>{len(admins)}</b>\n\n"
        f"Bu yerdan adminlarni boshqarasiz. Admin bo'lgan user kanal/guruhini qo'shib, "
        f"reklama qabul qilishni sozlay oladi.",
        reply_markup=sa_menu_kb(),
        parse_mode="HTML",
    )
    await cb.answer()


@router.message(Command("admins"))
async def cmd_admins(msg: Message, state: FSMContext):
    await state.clear()
    admins = await db.list_admins()
    await msg.answer(
        f"👑 Super admin paneli\nJoriy adminlar: <b>{len(admins)}</b>",
        reply_markup=sa_menu_kb(),
        parse_mode="HTML",
    )


# ---------- Add admin ----------
@router.callback_query(F.data == "sa:add")
async def sa_add_start(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AddAdmin.user_id)
    await cb.message.answer(
        "Yangi admin user ID sini (raqam) yuboring.\n\n"
        "❗️ Bu user avval botga /start bosgan bo'lishi kerak, aks holda bot unga xabar yubora olmaydi.\n"
        "User ID ni bilish uchun: user @userinfobot ga xabar yozsin."
    )
    await cb.answer()


@router.message(AddAdmin.user_id)
async def sa_add_save(msg: Message, state: FSMContext, bot: Bot):
    txt = (msg.text or "").strip()
    if not txt.lstrip("-").isdigit():
        await msg.answer("❌ Faqat raqam yuboring. Masalan: 123456789")
        return
    uid = int(txt)
    if uid in SUPER_ADMIN_IDS:
        await msg.answer("Bu user allaqachon super admin.")
        await state.clear()
        return
    if await db.is_admin(uid):
        await msg.answer("Bu user allaqachon admin.")
        await state.clear()
        return

    username = None
    full_name = None
    try:
        # try to fetch profile by sending chat action won't give data; use getChat
        chat = await bot.get_chat(uid)
        username = chat.username
        full_name = chat.full_name
    except Exception:
        pass

    await db.add_admin(uid, username, full_name, msg.from_user.id)
    await state.clear()
    admins = await db.list_admins()
    disp = f"@{username}" if username else (full_name or f"id={uid}")
    await msg.answer(
        f"✅ Admin qo'shildi: {disp} (id={uid})\n\nJami adminlar: {len(admins)}",
        reply_markup=sa_menu_kb(),
    )
    # notify the new admin
    try:
        from handlers.user import main_menu_kb
        await bot.send_message(
            uid,
            "🎉 Siz bu botga admin (kanal egasi) sifatida qo'shildingiz!\n\n"
            "Endi «🧩 Kanal egasi paneli» orqali o'z kanal/guruhingizni qo'shib, "
            "reklama qabul qilishni sozlashingiz mumkin.\n\n"
            "Batafsil: /help",
            reply_markup=await main_menu_kb(uid),
        )
    except Exception as e:
        await msg.answer(
            f"⚠️ Eslatma: userga xabar yuborib bo'lmadi (bot bilan /start bosmagan bo'lishi mumkin).\nXato: {e}"
        )


# ---------- List / remove ----------
@router.callback_query(F.data == "sa:list")
async def sa_list(cb: CallbackQuery):
    admins = await db.list_admins()
    if not admins:
        await cb.message.edit_text(
            "📋 Hozircha adminlar yo'q.",
            reply_markup=sa_menu_kb(),
        )
        await cb.answer()
        return

    rows = []
    for a in admins:
        disp = f"@{a['username']}" if a["username"] else (a["full_name"] or f"id={a['user_id']}")
        rows.append([InlineKeyboardButton(text=f"👤 {disp}", callback_data=f"sa:v:{a['user_id']}")])
    rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="sa:home")])
    await cb.message.edit_text(
        f"📋 Adminlar ro'yxati ({len(admins)}):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("sa:v:"))
async def sa_view(cb: CallbackQuery):
    uid = int(cb.data.split(":")[2])
    admins = await db.list_admins()
    a = next((x for x in admins if x["user_id"] == uid), None)
    if not a:
        await cb.answer("Topilmadi", show_alert=True)
        return
    disp = f"@{a['username']}" if a["username"] else (a["full_name"] or f"id={uid}")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"sa:rm:{uid}")],
        [InlineKeyboardButton(text="⬅️ Ro'yxatga", callback_data="sa:list")],
    ])
    await cb.message.edit_text(
        f"👤 Admin ma'lumotlari\n\n"
        f"• Ism: {a['full_name'] or '—'}\n"
        f"• Username: {('@'+a['username']) if a['username'] else '—'}\n"
        f"• User ID: <code>{uid}</code>\n"
        f"• Qo'shilgan: {a['added_at'][:19].replace('T',' ')}\n",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await cb.answer()


@router.callback_query(F.data.startswith("sa:rm:"))
async def sa_remove(cb: CallbackQuery, bot: Bot):
    uid = int(cb.data.split(":")[2])
    await db.remove_admin(uid)
    try:
        await bot.send_message(uid, "ℹ️ Sizning adminlik huquqingiz super admin tomonidan olib tashlandi.")
    except Exception:
        pass
    await cb.answer("O'chirildi", show_alert=True)
    # back to list
    cb.data = "sa:list"
    await sa_list(cb)


# ---------- Grant (membership so'rovi tasdig'i) ----------
@router.callback_query(F.data.startswith("sa:grant:"))
async def sa_grant_approve(cb: CallbackQuery, bot: Bot):
    uid = int(cb.data.split(":")[2])
    grants = await db.get_pending_grants_for_user(uid)
    if not grants:
        await cb.answer("Bu so'rov endi mavjud emas.", show_alert=True)
        return

    # User ni admins jadvaliga qo'shamiz
    username = None
    full_name = None
    try:
        chat = await bot.get_chat(uid)
        username = chat.username
        full_name = chat.full_name
    except Exception:
        pass
    if not await db.is_admin(uid):
        await db.add_admin(uid, username, full_name, cb.from_user.id)

    # Barcha kutilayotgan kanal(lar)ni qo'shamiz
    added_titles = []
    for g in grants:
        try:
            # agar allaqachon bor bo'lsa add_channel UNIQUE xato beradi — o'tkazib yuboramiz
            existing = await db.get_channel_by_chat_id(g["chat_id"])
            if not existing:
                await db.add_channel(uid, g["chat_title"] or g["chat_id"], g["chat_id"])
            added_titles.append(g["chat_title"] or g["chat_id"])
        except Exception as e:
            log.warning(f"grant add_channel: {e}")

    await db.delete_pending_grants_for_user(uid)

    # Userga xabar
    disp = f"@{username}" if username else (full_name or f"id={uid}")
    try:
        from handlers.user import main_menu_kb
        chans = "\n".join(f"• <b>{t}</b>" for t in added_titles)
        await bot.send_message(
            uid,
            f"🎉 <b>Tabriklaymiz!</b>\n\n"
            f"Super admin sizni kanal egasi (admin) sifatida tasdiqladi. "
            f"Quyidagi kanal(lar) avtomatik ro'yxatga olindi:\n\n{chans}\n\n"
            f"Endi <b>🧩 Kanal egasi paneli</b> → <b>📋 Mening kanallarim</b> "
            f"orqali har bir kanalga reklama shabloni yarating.",
            reply_markup=await main_menu_kb(uid),
            parse_mode="HTML",
        )
    except Exception as e:
        log.warning(f"notify granted user: {e}")

    await cb.message.edit_text(
        f"✅ <b>Tasdiqlandi</b>\n\n"
        f"👤 {disp} (ID: <code>{uid}</code>) endi admin.\n"
        f"📍 Qo'shilgan kanallar: {len(added_titles)} ta",
        parse_mode="HTML",
    )
    await cb.answer("Tasdiqlandi", show_alert=False)


@router.callback_query(F.data.startswith("sa:grant_deny:"))
async def sa_grant_deny(cb: CallbackQuery, bot: Bot):
    uid = int(cb.data.split(":")[2])
    await db.delete_pending_grants_for_user(uid)
    try:
        await bot.send_message(
            uid,
            "❌ Afsus, super admin sizning admin bo'lish so'rovingizni rad etdi.\n"
            "Batafsil ma'lumot uchun bevosita murojaat qiling.",
        )
    except Exception:
        pass
    await cb.message.edit_text(
        f"❌ <b>Rad etildi</b>\n\nFoydalanuvchi ID: <code>{uid}</code>",
        parse_mode="HTML",
    )
    await cb.answer("Rad etildi", show_alert=False)


# ========== Kanal tanlash sozlamalari ==========
def _chs_home_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Savol matnini o'zgartirish", callback_data="sa:chs:prompt")],
        [InlineKeyboardButton(text="🏷 Kanal tugma yozuvlari", callback_data="sa:chs:btns")],
        [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="sa:home")],
    ])


@router.callback_query(F.data == "sa:chs:home")
async def sa_chs_home(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    current = await db.get_setting("channel_select_prompt") or "Kanal(lar)ni tanlang:"
    await cb.message.edit_text(
        "🧷 <b>Kanal tanlash sozlamalari</b>\n\n"
        "Bu yerda user reklama berayotganda ko'radigan:\n"
        "• <b>Savol matni</b> (tugmalar ustidagi yozuv)\n"
        "• Har kanal uchun <b>tugma yozuvi</b> (inline button text)\n"
        "sozlanadi.\n\n"
        f"📝 <b>Hozirgi savol matni:</b>\n<code>{current}</code>",
        reply_markup=_chs_home_kb(),
        parse_mode="HTML",
    )
    await cb.answer()


@router.callback_query(F.data == "sa:chs:prompt")
async def sa_chs_prompt_start(cb: CallbackQuery, state: FSMContext):
    await state.set_state(ChSettings.prompt_text)
    current = await db.get_setting("channel_select_prompt") or "Kanal(lar)ni tanlang:"
    await cb.message.answer(
        "✏️ Kanal tanlash sahifasida ko'rinadigan matnni yuboring.\n\n"
        f"Hozirgisi:\n<code>{current}</code>\n\n"
        "Standart qiymatga qaytarish uchun: <code>-</code> yuboring.",
        parse_mode="HTML",
    )
    await cb.answer()


@router.message(ChSettings.prompt_text)
async def sa_chs_prompt_save(msg: Message, state: FSMContext):
    txt = (msg.text or "").strip()
    if txt == "-":
        await db.set_setting("channel_select_prompt", None)
        await msg.answer("✅ Standart matnga qaytarildi.", reply_markup=_chs_home_kb())
    else:
        await db.set_setting("channel_select_prompt", txt)
        await msg.answer(f"✅ Saqlandi:\n<code>{txt}</code>", reply_markup=_chs_home_kb(), parse_mode="HTML")
    await state.clear()


@router.callback_query(F.data == "sa:chs:btns")
async def sa_chs_btns(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    chs = await db.list_channels()
    if not chs:
        await cb.message.edit_text(
            "Hozircha kanallar yo'q.",
            reply_markup=_chs_home_kb(),
        )
        await cb.answer()
        return
    rows = []
    for c in chs:
        try:
            lbl = c["button_label"]
        except (KeyError, IndexError):
            lbl = None
        mark = "🏷" if lbl else "▫️"
        preview = lbl or c["name"]
        if len(preview) > 30:
            preview = preview[:30] + "…"
        rows.append([InlineKeyboardButton(
            text=f"{mark} {preview}",
            callback_data=f"sa:chs:b:{c['id']}"
        )])
    rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="sa:chs:home")])
    await cb.message.edit_text(
        "🏷 <b>Kanal tugma yozuvlari</b>\n\n"
        "Tahrirlash uchun kanalni tanlang.\n"
        "🏷 — admin belgilagan maxsus yozuv\n"
        "▫️ — standart (kanal nomi)",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        parse_mode="HTML",
    )
    await cb.answer()


@router.callback_query(F.data.startswith("sa:chs:b:"))
async def sa_chs_btn_edit(cb: CallbackQuery, state: FSMContext):
    ch_id = int(cb.data.split(":")[3])
    ch = await db.get_channel(ch_id)
    if not ch:
        await cb.answer("Kanal topilmadi", show_alert=True)
        return
    try:
        lbl = ch["button_label"]
    except (KeyError, IndexError):
        lbl = None
    await state.set_state(ChSettings.btn_label)
    await state.update_data(ch_id=ch_id)
    await cb.message.answer(
        f"🏷 <b>{ch['name']}</b> kanali uchun tugma yozuvi\n\n"
        f"Hozirgi: <code>{lbl or '(standart — kanal nomi)'}</code>\n\n"
        "Yangi yozuvni yuboring.\n"
        "Standartga qaytarish uchun: <code>-</code>",
        parse_mode="HTML",
    )
    await cb.answer()


@router.message(ChSettings.btn_label)
async def sa_chs_btn_save(msg: Message, state: FSMContext):
    data = await state.get_data()
    ch_id = data.get("ch_id")
    txt = (msg.text or "").strip()
    if txt == "-":
        await db.set_channel_button_label(ch_id, None)
        await msg.answer("✅ Standartga qaytarildi.", reply_markup=_chs_home_kb())
    else:
        if len(txt) > 60:
            await msg.answer("❌ Juda uzun (max 60 belgi). Qisqartiring.")
            return
        await db.set_channel_button_label(ch_id, txt)
        await msg.answer(
            f"✅ Saqlandi:\n<code>{txt}</code>",
            reply_markup=_chs_home_kb(),
            parse_mode="HTML",
        )
    await state.clear()
