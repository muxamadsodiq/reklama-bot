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


def _is_super(uid: int) -> bool:
    return uid in SUPER_ADMIN_IDS

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
            [InlineKeyboardButton(text="🌳 Kanal tanlash daraxti", callback_data="sa:rt:home")],
            [InlineKeyboardButton(text="✍️ Adminga yozish (link)", callback_data="sa:ac:home")],
            [InlineKeyboardButton(text="👑 Super adminlar", callback_data="sa:su:home")],
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


# ============================================================================
# SUPER ADMIN BOSHQARUV (dinamik qo'shish/o'chirish)
# ============================================================================
class SuperAdminMgmt(StatesGroup):
    wait_user_id = State()


def _su_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Super admin qo'shish", callback_data="sa:su:add")],
        [InlineKeyboardButton(text="📋 Ro'yxat", callback_data="sa:su:list")],
        [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="sa:home")],
    ])


@router.callback_query(F.data == "sa:su:home")
async def sa_su_home(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    total = len(SUPER_ADMIN_IDS)
    await cb.message.edit_text(
        f"👑 <b>Super adminlar</b>\n\nJoriy soni: <b>{total}</b>\n\n"
        "Eslatma: .env (ROOT) dagi super admin o'chirilmaydi.",
        reply_markup=_su_menu_kb(), parse_mode="HTML",
    )
    await cb.answer()


@router.callback_query(F.data == "sa:su:list")
async def sa_su_list(cb: CallbackQuery):
    from config import ROOT_SUPER_ADMIN_IDS
    rows = await db.sa_list()
    lines = ["👑 <b>Super adminlar</b>\n"]
    lines.append("<b>Root (.env)</b>:")
    for r in sorted(ROOT_SUPER_ADMIN_IDS):
        lines.append(f"  • <code>{r}</code>  🔒")
    lines.append("\n<b>DB (dinamik)</b>:")
    kb_rows = []
    if rows:
        for r in rows:
            name = r["full_name"] or (f"@{r['username']}" if r["username"] else "")
            lines.append(f"  • <code>{r['user_id']}</code>  {name}")
            kb_rows.append([InlineKeyboardButton(
                text=f"🗑 {name or r['user_id']}",
                callback_data=f"sa:su:del:{r['user_id']}")])
    else:
        lines.append("  (bo'sh)")
    kb_rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="sa:su:home")])
    await cb.message.edit_text("\n".join(lines),
                               reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows),
                               parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data == "sa:su:add")
async def sa_su_add(cb: CallbackQuery, state: FSMContext):
    await state.set_state(SuperAdminMgmt.wait_user_id)
    await cb.message.answer(
        "Yangi super admin user ID sini yuboring (raqam).\n\n"
        "❗️ User avval /start bosgan bo'lishi kerak.\n"
        "❗️ User ID ni bilish uchun: @userinfobot"
    )
    await cb.answer()


@router.message(SuperAdminMgmt.wait_user_id)
async def sa_su_add_save(msg: Message, state: FSMContext, bot: Bot):
    txt = (msg.text or "").strip()
    if not txt.lstrip("-").isdigit():
        await msg.answer("❌ Faqat raqam yuboring.")
        return
    uid = int(txt)
    if uid in SUPER_ADMIN_IDS:
        await msg.answer("Bu user allaqachon super admin.")
        await state.clear()
        return
    username, full_name = None, None
    try:
        chat = await bot.get_chat(uid)
        username = chat.username
        full_name = chat.full_name
    except Exception:
        pass
    await db.sa_add(uid, username, full_name, msg.from_user.id)
    SUPER_ADMIN_IDS.add(uid)
    await state.clear()
    try:
        await bot.send_message(uid, "👑 Siz super admin etib tayinlandingiz. /admins buyrug'i bilan panelni ochasiz.")
    except Exception:
        pass
    await msg.answer(f"✅ Super admin qo'shildi: <code>{uid}</code>", parse_mode="HTML",
                     reply_markup=_su_menu_kb())


@router.callback_query(F.data.startswith("sa:su:del:"))
async def sa_su_del(cb: CallbackQuery):
    from config import ROOT_SUPER_ADMIN_IDS
    uid = int(cb.data.split(":")[3])
    if uid in ROOT_SUPER_ADMIN_IDS:
        await cb.answer("❌ Root super adminni o'chirib bo'lmaydi", show_alert=True)
        return
    if uid == cb.from_user.id:
        await cb.answer("❌ O'zingizni o'chirolmaysiz", show_alert=True)
        return
    await db.sa_remove(uid)
    SUPER_ADMIN_IDS.discard(uid)
    await cb.answer("🗑 O'chirildi")
    await sa_su_list(cb)


# ============================================================================
# ROUTING TREE (kanal tanlash daraxti) — REJA4
# ============================================================================
class RTState(StatesGroup):
    wait_q_text = State()      # savol matni
    wait_a_text = State()      # javob matni
    edit_text = State()        # node matnini tahrirlash


def _rt_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌿 Daraxtni ko'rish", callback_data="sa:rt:view:0")],
        [InlineKeyboardButton(text="➕ Root savol yaratish", callback_data="sa:rt:newroot")],
        [InlineKeyboardButton(text="🗑 Butun daraxtni o'chirish", callback_data="sa:rt:wipe")],
        [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="sa:home")],
    ])


@router.callback_query(F.data == "sa:rt:home")
async def sa_rt_home(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    root = await db.routing_get_root_question()
    txt = (
        "🌳 <b>Kanal tanlash daraxti</b>\n\n"
        "User reklama joylashda savollarga javob beradi. "
        "Har javob keyingi savolga olib boradi. Oxirgi (leaf) node'ga kanallar biriktiriladi.\n\n"
    )
    if root:
        txt += f"Root savol: <b>{root['text']}</b> (ID: <code>{root['id']}</code>)"
    else:
        txt += "⚠️ Root savol hali yaratilmagan. Fallback rejim: barcha aktiv kanallar ko'rsatiladi."
    await cb.message.edit_text(txt, reply_markup=_rt_menu_kb(), parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data == "sa:rt:newroot")
async def sa_rt_newroot(cb: CallbackQuery, state: FSMContext):
    root = await db.routing_get_root_question()
    if root:
        await cb.answer("Root allaqachon bor. Uni o'chiring yoki tahrirlang.", show_alert=True)
        return
    await state.set_state(RTState.wait_q_text)
    await state.update_data(rt_parent_id=None, rt_kind="question")
    await cb.message.answer("Root savol matnini yuboring (masalan: <i>Qaysi sohadasiz?</i>):",
                            parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data == "sa:rt:wipe")
async def sa_rt_wipe(cb: CallbackQuery):
    root = await db.routing_get_root_question()
    if not root:
        await cb.answer("Daraxt bo'sh", show_alert=True)
        return
    await db.routing_delete_node(root["id"])
    await cb.answer("🗑 Daraxt o'chirildi", show_alert=True)
    await sa_rt_home(cb, FSMContext(storage=None, key=None) if False else cb.message.bot and None)  # noqa
    # soddaroq: redirect
    root = await db.routing_get_root_question()
    await cb.message.edit_text(
        "🌳 <b>Kanal tanlash daraxti</b>\n\n⚠️ Daraxt bo'sh. Fallback: barcha aktiv kanallar.",
        reply_markup=_rt_menu_kb(), parse_mode="HTML",
    )


async def _rt_view_node(cb: CallbackQuery, node_id: int):
    if node_id == 0:
        node = await db.routing_get_root_question()
    else:
        node = await db.routing_get_node(node_id)
    if not node:
        await cb.message.edit_text(
            "⚠️ Node topilmadi yoki daraxt bo'sh.",
            reply_markup=_rt_menu_kb(), parse_mode="HTML",
        )
        await cb.answer()
        return
    children = await db.routing_list_children(node["id"])
    is_leaf = len(children) == 0
    kind = "❓ Savol" if node["is_question"] else "💬 Javob"
    parent_txt = ""
    if node["parent_id"]:
        p = await db.routing_get_node(node["parent_id"])
        if p:
            parent_txt = f"\nOta: <i>{p['text']}</i>"
    txt = (
        f"🌳 <b>{kind}</b>\n\n"
        f"Matn: <b>{node['text']}</b>\n"
        f"ID: <code>{node['id']}</code>{parent_txt}\n\n"
    )
    rows = []
    if node["is_question"]:
        txt += f"Javob variantlari: <b>{len(children)}</b>\n"
        for ch in children:
            rows.append([InlineKeyboardButton(
                text=f"💬 {ch['text'][:40]}",
                callback_data=f"sa:rt:view:{ch['id']}")])
        rows.append([InlineKeyboardButton(text="➕ Javob variant qo'shish",
                                          callback_data=f"sa:rt:addans:{node['id']}")])
    else:
        # javob node
        if is_leaf:
            linked = await db.routing_get_node_channels(node["id"])
            txt += f"📡 Biriktirilgan kanallar: <b>{len(linked)}</b>\n"
            rows.append([InlineKeyboardButton(text="📡 Kanallarni tanlash",
                                              callback_data=f"sa:rt:ch:{node['id']}")])
            rows.append([InlineKeyboardButton(text="❓ Keyingi savol qo'shish",
                                              callback_data=f"sa:rt:addq:{node['id']}")])
        else:
            # javob → keyingi savol bor
            for ch in children:
                rows.append([InlineKeyboardButton(
                    text=f"❓ {ch['text'][:40]}",
                    callback_data=f"sa:rt:view:{ch['id']}")])
    rows.append([InlineKeyboardButton(text="✏️ Matnni tahrirlash",
                                      callback_data=f"sa:rt:edit:{node['id']}")])
    rows.append([InlineKeyboardButton(text="🗑 O'chirish",
                                      callback_data=f"sa:rt:del:{node['id']}")])
    if node["parent_id"]:
        rows.append([InlineKeyboardButton(text="⬅️ Ota nodega",
                                          callback_data=f"sa:rt:view:{node['parent_id']}")])
    rows.append([InlineKeyboardButton(text="🏠 Daraxt bosh", callback_data="sa:rt:home")])
    await cb.message.edit_text(txt, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
                               parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data.startswith("sa:rt:view:"))
async def sa_rt_view(cb: CallbackQuery):
    node_id = int(cb.data.split(":")[3])
    await _rt_view_node(cb, node_id)


@router.callback_query(F.data.startswith("sa:rt:addans:"))
async def sa_rt_addans(cb: CallbackQuery, state: FSMContext):
    parent_id = int(cb.data.split(":")[3])
    await state.set_state(RTState.wait_a_text)
    await state.update_data(rt_parent_id=parent_id, rt_kind="answer")
    await cb.message.answer("Javob variant matnini yuboring (masalan: <i>Taksi</i>):",
                            parse_mode="HTML")
    await cb.answer()


@router.callback_query(F.data.startswith("sa:rt:addq:"))
async def sa_rt_addq(cb: CallbackQuery, state: FSMContext):
    parent_id = int(cb.data.split(":")[3])
    # Faqat javob nodega savol qo'shish mumkin
    parent = await db.routing_get_node(parent_id)
    if not parent or parent["is_question"]:
        await cb.answer("❌ Savolga to'g'ridan-to'g'ri savol qo'shib bo'lmaydi", show_alert=True)
        return
    # Agar javobga kanallar biriktirilgan bo'lsa, ogohlantirish
    linked = await db.routing_get_node_channels(parent_id)
    if linked:
        await cb.answer("⚠️ Bu javobda kanallar biriktirilgan. Savol qo'shsangiz kanallar o'chadi.",
                        show_alert=True)
    await state.set_state(RTState.wait_q_text)
    await state.update_data(rt_parent_id=parent_id, rt_kind="question")
    await cb.message.answer("Savol matnini yuboring:")
    await cb.answer()


@router.message(RTState.wait_q_text)
@router.message(RTState.wait_a_text)
async def sa_rt_save_new(msg: Message, state: FSMContext):
    text = (msg.text or "").strip()
    if not text or len(text) > 200:
        await msg.answer("❌ Matn bo'sh yoki 200 belgidan uzun bo'lmasligi kerak.")
        return
    data = await state.get_data()
    parent_id = data.get("rt_parent_id")
    kind = data.get("rt_kind")
    is_q = 1 if kind == "question" else 0
    # Agar parent javob node bo'lsa va unga kanallar bog'langan bo'lsa, savol qo'shilganda kanallarni o'chiramiz
    if parent_id:
        await db.routing_set_node_channels(parent_id, [])
    new_id = await db.routing_create_node(parent_id, text, is_q, position=0)
    await state.clear()
    await msg.answer(f"✅ Qo'shildi (ID: <code>{new_id}</code>)", parse_mode="HTML")
    # view the new node
    class _Fake:
        pass
    # Reuse by editing a sent message:
    sent = await msg.answer("Yuklanmoqda...")
    # Avoid duplicating logic: build keyboard inline
    node = await db.routing_get_node(new_id)
    rows = [[InlineKeyboardButton(text="🌳 Daraxt bosh", callback_data="sa:rt:home")],
            [InlineKeyboardButton(text="👀 Ko'rish", callback_data=f"sa:rt:view:{new_id}")]]
    await sent.edit_text(
        f"Yangi node: <b>{node['text']}</b> (ID: <code>{new_id}</code>)",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data.startswith("sa:rt:edit:"))
async def sa_rt_edit(cb: CallbackQuery, state: FSMContext):
    node_id = int(cb.data.split(":")[3])
    await state.set_state(RTState.edit_text)
    await state.update_data(rt_edit_id=node_id)
    await cb.message.answer("Yangi matnni yuboring:")
    await cb.answer()


@router.message(RTState.edit_text)
async def sa_rt_edit_save(msg: Message, state: FSMContext):
    data = await state.get_data()
    node_id = data.get("rt_edit_id")
    text = (msg.text or "").strip()
    if not text or len(text) > 200:
        await msg.answer("❌ Matn noto'g'ri")
        return
    await db.routing_update_text(node_id, text)
    await state.clear()
    await msg.answer("✅ Tahrirlandi")


@router.callback_query(F.data.startswith("sa:rt:del:"))
async def sa_rt_del(cb: CallbackQuery):
    node_id = int(cb.data.split(":")[3])
    node = await db.routing_get_node(node_id)
    if not node:
        await cb.answer("Topilmadi", show_alert=True)
        return
    parent_id = node["parent_id"]
    await db.routing_delete_node(node_id)
    await cb.answer("🗑 O'chirildi")
    if parent_id:
        # go to parent
        cb.data = f"sa:rt:view:{parent_id}"
        await _rt_view_node(cb, parent_id)
    else:
        await sa_rt_home(cb, None)


@router.callback_query(F.data.startswith("sa:rt:ch:"))
async def sa_rt_ch(cb: CallbackQuery):
    node_id = int(cb.data.split(":")[3])
    node = await db.routing_get_node(node_id)
    if not node:
        await cb.answer("Topilmadi", show_alert=True)
        return
    linked = set(await db.routing_get_node_channels(node_id))
    channels = await db.list_channels()
    rows = []
    for ch in channels:
        mark = "✅" if ch["id"] in linked else "☑️"
        rows.append([InlineKeyboardButton(
            text=f"{mark} {ch['title']}",
            callback_data=f"sa:rt:chtg:{node_id}:{ch['id']}")])
    rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data=f"sa:rt:view:{node_id}")])
    await cb.message.edit_text(
        f"📡 <b>{node['text']}</b>\n\nKanallarni tanlang (tugmani bosib belgilang):",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("sa:rt:chtg:"))
async def sa_rt_chtg(cb: CallbackQuery):
    parts = cb.data.split(":")
    node_id = int(parts[3])
    ch_id = int(parts[4])
    added = await db.routing_toggle_channel(node_id, ch_id)
    await cb.answer("✅ Qo'shildi" if added else "❌ Olindi")
    # refresh
    cb.data = f"sa:rt:ch:{node_id}"
    await sa_rt_ch(cb)


# ============================================================================
# TOPSHIRILDI / DONE RULES — REJA5 (super admin template field'larga qoida qo'shish)
# ============================================================================
# Bu yerda "sa:fld:done:<field_id>" tugmasi template_fields ro'yxatida
# har bir maydon uchun ko'rinadi — uni toggle qiladi va matnni so'raydi.
# Admin tarafida template_fields ro'yxatida yangi tugma qo'shamiz (admin.py'da).
class DoneRule(StatesGroup):
    wait_text = State()


@router.callback_query(F.data.startswith("sa:fld:donetxt:"))
async def sa_fld_donetxt(cb: CallbackQuery, state: FSMContext):
    field_id = int(cb.data.split(":")[3])
    await state.set_state(DoneRule.wait_text)
    await state.update_data(fld_id=field_id)
    await cb.message.answer(
        "Bu maydon uchun 'Topshirildi' holatidagi matnni yuboring.\n"
        "Masalan: <code>✅ Topshirildi</code> yoki <code>🔒 Yopildi</code>",
        parse_mode="HTML",
    )
    await cb.answer()


@router.message(DoneRule.wait_text)
async def sa_fld_donetxt_save(msg: Message, state: FSMContext):
    data = await state.get_data()
    fld_id = data.get("fld_id")
    txt = (msg.text or "").strip()
    if not txt or len(txt) > 200:
        await msg.answer("❌ Matn 1-200 belgi bo'lishi kerak")
        return
    await db.field_set_done_rule(fld_id, 1, txt)
    await state.clear()
    await msg.answer(f"✅ Saqlandi. Endi user 'Topshirildi' bossa bu maydon '<b>{txt}</b>' ga almashadi.",
                     parse_mode="HTML")


# ---------- Kategoriya icon sozlash (routing_nodes) ----------
@router.message(Command("seticon"))
async def cmd_seticon(msg: Message):
    if not _is_super(msg.from_user.id):
        return
    parts = (msg.text or "").split(maxsplit=2)
    if len(parts) < 3:
        # Show list of root-level routing nodes
        import aiosqlite
        from config import DB_PATH
        async with aiosqlite.connect(DB_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            cur = await conn.execute(
                "SELECT id, text, icon FROM routing_nodes ORDER BY id"
            )
            rows = await cur.fetchall()
        if not rows:
            await msg.answer("Daraxt bo'sh.")
            return
        lines = ["<b>📝 /seticon &lt;id&gt; &lt;emoji&gt;</b>\n"]
        for r in rows[:40]:
            ic = r["icon"] or "—"
            txt = (r["text"] or "")[:40]
            lines.append(f"<code>{r['id']}</code> {ic} — {txt}")
        await msg.answer("\n".join(lines))
        return
    try:
        node_id = int(parts[1])
    except ValueError:
        await msg.answer("ID raqam bo'lishi kerak")
        return
    icon = parts[2].strip()[:8]
    import aiosqlite
    from config import DB_PATH
    async with aiosqlite.connect(DB_PATH) as conn:
        cur = await conn.execute(
            "UPDATE routing_nodes SET icon=? WHERE id=?",
            (icon, node_id),
        )
        await conn.commit()
        if cur.rowcount == 0:
            await msg.answer(f"❌ ID {node_id} topilmadi")
            return
    await msg.answer(f"✅ #{node_id} icon o'rnatildi: {icon}")




# ============================================================================
# ADMIN CONTACT LINK — REJA11 (bosh menyudagi "Adminga yozish" tugma sozlash)
# ============================================================================
class AdminContact(StatesGroup):
    wait_label = State()
    wait_url = State()


def _ac_home_kb(has_url: bool):
    rows = [
        [InlineKeyboardButton(text="🏷 Tugma matnini o'zgartirish", callback_data="sa:ac:label")],
        [InlineKeyboardButton(text="🔗 Havolani o'zgartirish", callback_data="sa:ac:url")],
    ]
    if has_url:
        rows.append([InlineKeyboardButton(text="🗑 Tugmani o'chirish", callback_data="sa:ac:del")])
    rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="sa:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "sa:ac:home")
async def sa_ac_home(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    label = (await db.get_setting("admin_contact_label")) or "✍️ Adminga yozish"
    url = (await db.get_setting("admin_contact_url")) or ""
    status = "✅ Faol" if url else "⛔ Faolsiz (havola yo'q)"
    await cb.message.edit_text(
        "✍️ <b>Adminga yozish tugmasi</b>\n\n"
        "Bu tugma foydalanuvchilar bosh menyusida ko'rinadi va bosilganda\n"
        "siz bergan havolaga o'tkazadi (masalan Telegram profili yoki t.me/username).\n\n"
        f"<b>Holat:</b> {status}\n"
        f"<b>Tugma matni:</b> <code>{label}</code>\n"
        f"<b>Havola:</b> <code>{url or '—'}</code>",
        parse_mode="HTML",
        reply_markup=_ac_home_kb(bool(url)),
    )
    await cb.answer()


@router.callback_query(F.data == "sa:ac:label")
async def sa_ac_label_start(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AdminContact.wait_label)
    current = (await db.get_setting("admin_contact_label")) or "✍️ Adminga yozish"
    await cb.message.answer(
        "🏷 Tugma matnini yuboring (max 64 belgi).\n\n"
        f"Hozirgi: <code>{current}</code>\n\n"
        "Standart matnga qaytarish uchun: <code>-</code>",
        parse_mode="HTML",
    )
    await cb.answer()


@router.message(AdminContact.wait_label)
async def sa_ac_label_save(msg: Message, state: FSMContext):
    txt = (msg.text or "").strip()
    if txt == "-":
        await db.set_setting("admin_contact_label", None)
        await msg.answer("✅ Standart matnga qaytarildi: ✍️ Adminga yozish")
    else:
        if len(txt) > 64:
            txt = txt[:64]
        await db.set_setting("admin_contact_label", txt)
        await msg.answer(f"✅ Saqlandi: <code>{txt}</code>", parse_mode="HTML")
    await state.clear()
    url = (await db.get_setting("admin_contact_url")) or ""
    label = (await db.get_setting("admin_contact_label")) or "✍️ Adminga yozish"
    status = "✅ Faol" if url else "⛔ Faolsiz (havola yo'q)"
    await msg.answer(
        f"<b>Holat:</b> {status}\n<b>Tugma matni:</b> <code>{label}</code>\n<b>Havola:</b> <code>{url or '—'}</code>",
        parse_mode="HTML",
        reply_markup=_ac_home_kb(bool(url)),
    )


@router.callback_query(F.data == "sa:ac:url")
async def sa_ac_url_start(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AdminContact.wait_url)
    current = (await db.get_setting("admin_contact_url")) or "—"
    await cb.message.answer(
        "🔗 Havolani yuboring.\n\n"
        "Qabul qilinadigan formatlar:\n"
        "• <code>@username</code> → t.me/username ga aylantiriladi\n"
        "• <code>https://t.me/username</code>\n"
        "• <code>tg://user?id=123456</code>\n"
        "• <code>https://...</code>\n\n"
        f"Hozirgi: <code>{current}</code>\n\n"
        "O'chirish uchun: <code>-</code>",
        parse_mode="HTML",
    )
    await cb.answer()


@router.message(AdminContact.wait_url)
async def sa_ac_url_save(msg: Message, state: FSMContext):
    raw = (msg.text or "").strip()
    if raw == "-":
        await db.set_setting("admin_contact_url", None)
        await msg.answer("🗑 Havola o'chirildi. Tugma endi ko'rinmaydi.")
        await state.clear()
        return
    # normalize
    if raw.startswith("@") and len(raw) > 1:
        url = f"https://t.me/{raw[1:]}"
    elif raw.startswith("t.me/") or raw.startswith("telegram.me/"):
        url = "https://" + raw
    elif raw.startswith(("http://", "https://", "tg://")):
        url = raw
    else:
        await msg.answer(
            "❌ Havola formati noto'g'ri. Namuna:\n"
            "• @username\n• https://t.me/username\n• https://example.com"
        )
        return
    await db.set_setting("admin_contact_url", url)
    await msg.answer(f"✅ Saqlandi: <code>{url}</code>", parse_mode="HTML")
    await state.clear()
    label = (await db.get_setting("admin_contact_label")) or "✍️ Adminga yozish"
    await msg.answer(
        f"<b>Holat:</b> ✅ Faol\n<b>Tugma matni:</b> <code>{label}</code>\n<b>Havola:</b> <code>{url}</code>",
        parse_mode="HTML",
        reply_markup=_ac_home_kb(True),
    )


@router.callback_query(F.data == "sa:ac:del")
async def sa_ac_del(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await db.set_setting("admin_contact_url", None)
    await cb.answer("🗑 Havola o'chirildi", show_alert=True)
    await sa_ac_home(cb, state)
