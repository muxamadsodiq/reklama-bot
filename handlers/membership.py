"""Bot guruh/kanalga qo'shilganda yoki admin qilinganda avtomatik ro'yxatga olish."""
import logging
from aiogram import Router, Bot, F
from aiogram.types import ChatMemberUpdated, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import ChatMemberUpdatedFilter, IS_NOT_MEMBER, IS_MEMBER, ADMINISTRATOR

import database as db
from config import SUPER_ADMIN_IDS

router = Router()
log = logging.getLogger(__name__)


@router.my_chat_member(ChatMemberUpdatedFilter(IS_NOT_MEMBER >> ADMINISTRATOR))
async def bot_promoted_to_admin(event: ChatMemberUpdated, bot: Bot):
    await _register(event, bot)


@router.my_chat_member(ChatMemberUpdatedFilter(IS_MEMBER >> ADMINISTRATOR))
async def bot_member_became_admin(event: ChatMemberUpdated, bot: Bot):
    await _register(event, bot)


@router.my_chat_member(ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER))
async def bot_added_as_member(event: ChatMemberUpdated, bot: Bot):
    who = event.from_user
    try:
        await bot.send_message(
            who.id,
            f"ℹ️ «{event.chat.title}» guruh/kanaliga botni qo'shdingiz, lekin admin qilmadingiz.\n\n"
            "Reklama yuborish uchun botni <b>admin</b> qiling (post yuborish huquqi bilan).",
            parse_mode="HTML",
        )
    except Exception:
        pass


async def _register(event: ChatMemberUpdated, bot: Bot):
    chat = event.chat
    who = event.from_user
    if not who or who.is_bot:
        return

    chat_id_str = str(chat.id)
    existing = await db.get_channel_by_chat_id(chat_id_str)
    if existing:
        try:
            await bot.send_message(
                who.id,
                f"✅ «{chat.title}» allaqachon ro'yxatda.\n"
                "Botni DM'ga yozib /start → 🧩 <b>Kanal egasi paneli</b> orqali boshqaring.",
                parse_mode="HTML",
            )
        except Exception:
            pass
        return

    # User shu chatda admin/creator bo'lishi kerak
    try:
        member = await bot.get_chat_member(chat.id, who.id)
        if member.status not in ("administrator", "creator"):
            return
    except Exception as e:
        log.warning(f"check member failed: {e}")
        return

    # User botda admin yoki super admin bo'lishi kerak
    is_super = who.id in SUPER_ADMIN_IDS
    is_bot_admin = is_super or await db.is_admin(who.id)

    if is_bot_admin:
        # hammasi joyida — avtomatik qo'shamiz
        name = chat.title or str(chat.id)
        try:
            await db.add_channel(who.id, name, chat_id_str)
        except Exception as e:
            log.warning(f"add_channel: {e}")
            return
        try:
            await bot.send_message(
                who.id,
                f"🎉 <b>«{name}»</b> avtomatik ro'yxatga olindi!\n\n"
                "Endi DM'da /start → 🧩 <b>Kanal egasi paneli</b> → 📋 <b>Mening kanallarim</b> orqali "
                "shablon yarating.",
                parse_mode="HTML",
            )
        except Exception:
            log.info(f"Could not DM {who.id} — user never /start'ed bot")
        return

    # ⛔ User botda admin emas — super adminlarga so'rov yuboramiz
    uname = f"@{who.username}" if who.username else who.full_name
    try:
        await bot.send_message(
            who.id,
            f"⏳ <b>«{chat.title}» qo'shish uchun super admin tasdig'i kerak.</b>\n\n"
            "Siz bu bot'da kanal egasi (admin) sifatida ro'yxatdan o'tmagansiz. "
            "Administratorga so'rov yuborildi. Tasdiqlanishi bilan kanalingiz "
            "avtomatik ro'yxatga qo'shiladi va sizga xabar beriladi.\n\n"
            "<i>Iltimos, shu bot'ga /start bosib qo'ying.</i>",
            parse_mode="HTML",
        )
    except Exception:
        pass

    # Super adminlarga — tasdiqlash tugmasi bilan
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"sa:grant:{who.id}"),
            InlineKeyboardButton(text="❌ Rad etish", callback_data=f"sa:grant_deny:{who.id}"),
        ]
    ])
    notify_text = (
        f"🔔 <b>Yangi admin so'rovi</b>\n\n"
        f"👤 Foydalanuvchi: {uname} (ID: <code>{who.id}</code>)\n"
        f"📍 Kanal: <b>{chat.title}</b>\n"
        f"🆔 chat_id: <code>{chat_id_str}</code>\n\n"
        f"Bu foydalanuvchi «{chat.title}» da admin va sizdan bot'da ham admin "
        f"huquqini so'rayapti. Tasdiqlasangiz:\n"
        f"• Uning user_id si <b>admins</b> jadvaliga qo'shiladi\n"
        f"• «{chat.title}» avtomatik ro'yxatga olinadi\n"
        f"• Unga DM orqali xabar beriladi"
    )
    for sa_id in SUPER_ADMIN_IDS:
        try:
            await bot.send_message(sa_id, notify_text, reply_markup=kb, parse_mode="HTML")
        except Exception as e:
            log.warning(f"notify super admin {sa_id}: {e}")

    # Kanalni keyinroq qo'shish uchun saqlash — pending_grants jadvali bor bo'lsa...
    # Bu erda oddiyroq: chat ma'lumotini memory'da emas, DB'ga yozish kerak.
    # Hozircha super_admin handler chat_id ni bilishi uchun DB ga yozib qo'yamiz:
    try:
        await db.save_pending_grant(who.id, chat_id_str, chat.title or str(chat.id))
    except Exception as e:
        log.warning(f"save_pending_grant: {e}")
