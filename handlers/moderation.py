import json
import logging
from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton

import database as db
from utils.preview_builder import build_text_and_kb, format_ad_id

router = Router()
log = logging.getLogger(__name__)


class Reject(StatesGroup):
    reason = State()


async def _is_channel_owner(user_id: int, ch_ids: list[int]) -> bool:
    for ch_id in ch_ids:
        ch = await db.get_channel(ch_id)
        if not ch or ch["owner_id"] != user_id:
            return False
    return True


def _public_filtered(fields_meta, filled: dict) -> dict:
    out = {}
    for f in fields_meta:
        key = f["key"]
        if f["show_in_public"] if not isinstance(f, dict) else f.get("show_in_public", True):
            out[key] = filled.get(key, "")
        else:
            out[key] = ""
    return out


@router.callback_query(F.data.startswith("m:ok:"))
async def approve(cb: CallbackQuery, bot: Bot):
    ad_id = int(cb.data.split(":")[2])
    ad = await db.get_ad(ad_id)
    if not ad:
        await cb.answer("Topilmadi", show_alert=True)
        return
    if ad["status"] != "pending":
        await cb.answer(f"Allaqachon: {ad['status']}", show_alert=True)
        return

    target_channels = json.loads(ad["target_channels"])
    if not await _is_channel_owner(cb.from_user.id, target_channels):
        await cb.answer("Bu so'rov sizga tegishli emas", show_alert=True)
        return

    filled = json.loads(ad["filled_data"])

    errors = []
    sent_private_chats: set = set()  # dedup: bir xil maxfiy guruhga 1 marta
    for ch_id in target_channels:
        ch = await db.get_channel(ch_id)
        tpl = await db.get_template(ch_id)
        fields_meta = await db.list_fields(ch_id)
        if not ch or not tpl:
            errors.append(f"ch_id={ch_id}: topilmadi")
            continue
        try:
            prefix = tpl["id_prefix"] or "_"
        except (KeyError, IndexError):
            prefix = "_"

        try:
            me = await bot.get_me()
            member = await bot.get_chat_member(ch["chat_id"], me.id)
            if member.status not in ("administrator", "creator"):
                errors.append(f"{ch['name']}: bot admin emas")
                continue
        except Exception as e:
            errors.append(f"{ch['name']}: {e}")
            continue

        # PUBLIC — asosiy kanal/guruh
        if fields_meta:
            pub_data = _public_filtered(fields_meta, filled)
        else:
            pub_data = dict(filled)
        # bot username REJA13 obuna tugmasi uchun
        try:
            _me = await bot.get_me()
            _bot_username = _me.username
        except Exception:
            _bot_username = None
        pub_text, pub_kb = build_text_and_kb(tpl, pub_data, ad["custom_url"], ad_id=ad_id, bot_username=_bot_username, channel_id=int(ch["id"]))
        sent_msg = None
        try:
            media_list = []
            try:
                ml_raw = ad["media_list"]
                if ml_raw:
                    media_list = json.loads(ml_raw)
            except (KeyError, IndexError, TypeError):
                media_list = []
            if len(media_list) >= 2:
                from aiogram.types import InputMediaPhoto, InputMediaVideo
                group = []
                for i, m in enumerate(media_list[:5]):
                    cap = pub_text if i == 0 else None
                    if m.get("type") == "photo":
                        group.append(InputMediaPhoto(media=m["file_id"], caption=cap))
                    else:
                        group.append(InputMediaVideo(media=m["file_id"], caption=cap))
                sent_group = await bot.send_media_group(ch["chat_id"], group)
                if sent_group:
                    sent_msg = sent_group[0]
                if pub_kb:
                    await bot.send_message(ch["chat_id"], "👆", reply_markup=pub_kb)
            elif ad["media_file_id"] and ad["media_type"] == "photo":
                sent_msg = await bot.send_photo(ch["chat_id"], ad["media_file_id"], caption=pub_text, reply_markup=pub_kb)
            elif ad["media_file_id"] and ad["media_type"] == "video":
                sent_msg = await bot.send_video(ch["chat_id"], ad["media_file_id"], caption=pub_text, reply_markup=pub_kb)
            else:
                sent_msg = await bot.send_message(ch["chat_id"], pub_text, reply_markup=pub_kb)
        except Exception as e:
            errors.append(f"{ch['name']}: {e}")
            log.exception("send to channel failed")

        # Birinchi muvaffaqiyatli post ref'ini saqlab qo'yamiz (user keyinroq "Topshirildi" bossa tahrirlash uchun)
        if sent_msg is not None:
            try:
                await db.set_ad_posted_refs(
                    ad_id=ad_id,
                    posted_chat_id=str(ch["chat_id"]),
                    posted_message_id=sent_msg.message_id,
                )
            except Exception as e:
                log.warning(f"set_ad_posted_refs failed: {e}")

        # PRIVATE — maxfiy guruh, to'liq data
        try:
            priv_chat = tpl["private_chat_id"]
            priv_tpl = tpl["private_text_template"]
        except (KeyError, IndexError):
            priv_chat = priv_tpl = None
        if priv_chat and priv_tpl:
            if priv_chat in sent_private_chats:
                # Bu maxfiy guruhga allaqachon yuborilgan — takrorlamaymiz
                continue
            sent_private_chats.add(priv_chat)
            from utils.template_parser import fill_template
            extra = dict(filled)
            extra.setdefault("user_id", str(ad["user_id"]))
            try:
                uname = ad["username"] or ""
            except (KeyError, IndexError):
                uname = ""
            extra.setdefault("username", uname)
            extra["ad_id"] = format_ad_id(ad_id, prefix)
            priv_sent_msg = None
            try:
                priv_text = fill_template(priv_tpl, extra)
                if "{ad_id}" not in (priv_tpl or ""):
                    priv_text = f"{priv_text}\n\n🆔 {format_ad_id(ad_id, prefix)}"
                if len(media_list) >= 2:
                    from aiogram.types import InputMediaPhoto, InputMediaVideo
                    pgroup = []
                    for i, m in enumerate(media_list[:5]):
                        cap = priv_text if i == 0 else None
                        if m.get("type") == "photo":
                            pgroup.append(InputMediaPhoto(media=m["file_id"], caption=cap))
                        else:
                            pgroup.append(InputMediaVideo(media=m["file_id"], caption=cap))
                    sent_group = await bot.send_media_group(priv_chat, pgroup)
                    if sent_group:
                        priv_sent_msg = sent_group[0]
                elif ad["media_file_id"] and ad["media_type"] == "photo":
                    priv_sent_msg = await bot.send_photo(priv_chat, ad["media_file_id"], caption=priv_text)
                elif ad["media_file_id"] and ad["media_type"] == "video":
                    priv_sent_msg = await bot.send_video(priv_chat, ad["media_file_id"], caption=priv_text)
                else:
                    priv_sent_msg = await bot.send_message(priv_chat, priv_text)
                # Save private refs for later "full info" resends / sold edits
                if priv_sent_msg is not None:
                    try:
                        await db.set_ad_private_refs(
                            ad_id=ad_id,
                            private_chat_id=str(priv_chat),
                            private_message_id=priv_sent_msg.message_id,
                        )
                    except Exception as e:
                        log.warning(f"set_ad_private_refs failed: {e}")
            except Exception as e:
                errors.append(f"{ch['name']} (maxfiy): {e}")
                log.exception("send to private chat failed")

    await db.set_ad_status(ad_id, "approved")

    # Birinchi tpl'dan prefiks olamiz foydalanuvchi xabari uchun
    try:
        first_tpl = await db.get_template(target_channels[0]) if target_channels else None
        user_prefix = (first_tpl["id_prefix"] if first_tpl else "_") or "_"
    except (KeyError, IndexError, TypeError):
        user_prefix = "_"

    # User'ga "Topshirildi" tugmali xabar — shunda user reklama bajarilganda bosib kanal postini yangilaydi
    done_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Topshirildi bo'ldi", callback_data=f"u:dn:{ad_id}")],
    ])
    try:
        if errors:
            await bot.send_message(
                ad["user_id"],
                f"⚠️ Reklamangiz {format_ad_id(ad_id, user_prefix)} qisman jo'natildi:\n" + "\n".join(errors),
                reply_markup=done_kb,
            )
        else:
            await bot.send_message(
                ad["user_id"],
                f"✅ Reklamangiz {format_ad_id(ad_id, user_prefix)} jo'natildi!\n\n"
                f"Agar xizmat topshirilsa / bajarilsa quyidagi tugmani bosing — "
                f"post kanalda yangilanadi.",
                reply_markup=done_kb,
            )
    except Exception:
        pass

    await cb.message.edit_text(
        f"✅ Tasdiqlandi {format_ad_id(ad_id, user_prefix)}"
        + (f"\nXatoliklar:\n" + "\n".join(errors) if errors else "")
    )
    await cb.answer("OK")


@router.callback_query(F.data.startswith("m:no:"))
async def reject_start(cb: CallbackQuery, state: FSMContext):
    ad_id = int(cb.data.split(":")[2])
    ad = await db.get_ad(ad_id)
    if not ad or ad["status"] != "pending":
        await cb.answer("Mavjud emas yoki tugatilgan", show_alert=True)
        return
    target_channels = json.loads(ad["target_channels"])
    if not await _is_channel_owner(cb.from_user.id, target_channels):
        await cb.answer("Bu so'rov sizga tegishli emas", show_alert=True)
        return
    try:
        tpl = await db.get_template(target_channels[0]) if target_channels else None
        prefix = (tpl["id_prefix"] if tpl else "_") or "_"
    except (KeyError, IndexError, TypeError):
        prefix = "_"
    await state.set_state(Reject.reason)
    await state.update_data(ad_id=ad_id, prefix=prefix)
    await cb.message.answer(
        f"Rad etish sababini yozing (ixtiyoriy — /skip):\nAd {format_ad_id(ad_id, prefix)}"
    )
    await cb.answer()


@router.message(Reject.reason)
async def reject_reason(msg: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    ad_id = data["ad_id"]
    prefix = data.get("prefix", "_")
    ad = await db.get_ad(ad_id)
    if not ad:
        await state.clear()
        return
    target_channels = json.loads(ad["target_channels"])
    if not await _is_channel_owner(msg.from_user.id, target_channels):
        await state.clear()
        return
    reason = "" if msg.text == "/skip" else msg.text.strip()
    await db.set_ad_status(ad_id, "rejected", reason)
    try:
        txt = f"❌ Reklamangiz {format_ad_id(ad_id, prefix)} rad etildi."
        if reason:
            txt += f"\nSabab: {reason}"
        await bot.send_message(ad["user_id"], txt)
    except Exception:
        pass
    await state.clear()
    await msg.answer(f"Rad etildi {format_ad_id(ad_id, prefix)}")
