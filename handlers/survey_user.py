"""Survey — user tarafi (javob berish oqimi).

Callbacklar:
  sv:phone  — dastlabki telefon talabi paneli (faqat info)
  sv:ans:<oid>  — variant tanlandi
"""
import logging

from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    Contact,
)

import database as db

router = Router()
log = logging.getLogger(__name__)


class Survey(StatesGroup):
    phone = State()
    answering = State()


async def _options_kb(qid: int) -> InlineKeyboardMarkup:
    opts = await db.survey_list_options(qid)
    rows = [[InlineKeyboardButton(text=o["text"], callback_data=f"sv:ans:{o['id']}")]
            for o in opts]
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def maybe_start_survey(msg: Message, state: FSMContext) -> bool:
    """User /start bossa chaqiriladi.
    True qaytarsa — survey boshladik (main menyu ko'rsatmang).
    False qaytarsa — main menyu ko'rsatilsin.
    """
    uid = msg.from_user.id
    # Savollar bormi?
    root = await db.survey_get_root_question()
    if not root:
        return False
    # Allaqachon tugatganmi?
    if await db.survey_has_completed(uid):
        return False
    # Variantlar bormi?
    opts = await db.survey_list_options(root["id"])
    if not opts:
        return False

    # Sessionni boshlab olamiz (phone hali NULL)
    await db.survey_session_start(
        user_id=uid,
        username=msg.from_user.username,
        full_name=msg.from_user.full_name,
        phone=None,
        first_qid=root["id"],
    )
    # Telefon raqamini so'raymiz (majburiy)
    await state.set_state(Survey.phone)
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Raqamni ulashish", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await msg.answer(
        "👋 Assalomu alaykum!\n\n"
        "Qisqa so'rovnoma to'ldirishingizni so'raymiz.\n"
        "Avval telefon raqamingizni ulashing (majburiy):",
        reply_markup=kb,
    )
    return True


@router.message(Survey.phone, F.contact)
async def on_contact(msg: Message, state: FSMContext):
    contact: Contact = msg.contact
    if contact.user_id and contact.user_id != msg.from_user.id:
        await msg.answer("❗️ Iltimos, o'zingizning raqamingizni ulashing.")
        return
    uid = msg.from_user.id
    await db.survey_session_set_phone(uid, contact.phone_number)
    # Klaviaturani olib tashlaymiz va birinchi savolni chiqaramiz
    await msg.answer("✅ Rahmat!", reply_markup=ReplyKeyboardRemove())
    root = await db.survey_get_root_question()
    if not root:
        await state.clear()
        await msg.answer("So'rovnoma topilmadi.")
        return
    await state.set_state(Survey.answering)
    await _send_question(msg, root["id"])


@router.message(Survey.phone)
async def on_phone_wrong(msg: Message):
    await msg.answer(
        "❗️ Telefon raqamni [📱 Raqamni ulashish] tugmasi orqali yuboring.\n"
        "(Raqamni qo'lda yozmang)"
    )


async def _send_question(msg: Message, qid: int):
    q = await db.survey_get_question(qid)
    if not q:
        return
    kb = await _options_kb(qid)
    await msg.answer(f"❓ <b>{q['text']}</b>", reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("sv:ans:"))
async def on_answer(cb: CallbackQuery, state: FSMContext):
    oid = int(cb.data.split(":")[2])
    o = await db.survey_get_option(oid)
    if not o:
        await cb.answer("Variant topilmadi", show_alert=True)
        return

    uid = cb.from_user.id
    session = await db.survey_session_get(uid)
    if not session:
        await cb.answer("Sessiya topilmadi. /start bosing.", show_alert=True)
        return
    if session["completed_at"]:
        await cb.answer("Siz allaqachon javob bergansiz.", show_alert=True)
        return
    # Current question check
    if session["current_question_id"] and o["question_id"] != session["current_question_id"]:
        await cb.answer("Bu eski savol. Yangisiga javob bering.", show_alert=True)
        return

    q = await db.survey_get_question(o["question_id"])
    # Javobni yozamiz
    await db.survey_save_answer(
        user_id=uid,
        username=session["username"],
        full_name=session["full_name"],
        phone=session["phone"],
        question_id=q["id"],
        option_id=o["id"],
        question_text=q["text"],
        option_text=o["text"],
    )

    # Tugmalarni "bosildi" qilish uchun edit qilamiz
    try:
        await cb.message.edit_text(
            f"❓ {q['text']}\n\n✅ <i>Javobingiz:</i> <b>{o['text']}</b>",
            parse_mode="HTML",
        )
    except Exception:
        pass

    next_qid = o["next_question_id"]
    if next_qid:
        await db.survey_session_set_current(uid, next_qid)
        await _send_question(cb.message, next_qid)
        await cb.answer()
        return

    # Tugadi
    await db.survey_session_complete(uid)
    await state.clear()
    # Asosiy menyuga o'tkazamiz
    from handlers.user import main_menu_kb
    from config import SUPER_ADMIN_IDS
    kb = await main_menu_kb(uid)
    await cb.message.answer(
        "🎉 <b>Rahmat!</b>\nSo'rovnomani to'ldirdingiz.\n\nAsosiy menyu:",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await cb.answer("Yakunlandi ✅")
