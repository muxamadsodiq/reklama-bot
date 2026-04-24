import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ErrorEvent

from config import BOT_TOKEN, LOG_PATH
import database as db
from handlers import admin, user, moderation, super_admin, survey_admin, survey_user
from handlers import user_myposts


def setup_logging():
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(LOG_PATH, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


async def main():
    setup_logging()
    log = logging.getLogger("main")

    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN .env da topilmadi")

    await db.init_db()

    # DB'dan qo'shimcha super adminlarni yuklab SUPER_ADMIN_IDS set ga qo'shamiz
    from config import SUPER_ADMIN_IDS
    try:
        for uid in await db.sa_db_ids():
            SUPER_ADMIN_IDS.add(uid)
        log.info(f"Super adminlar yuklandi: {sorted(SUPER_ADMIN_IDS)}")
    except Exception as e:
        log.warning(f"sa_db_ids yuklashda xato: {e}")

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Global error handler — jim yutiladigan odatiy Telegram xatolari
    @dp.errors()
    async def _on_error(event: ErrorEvent):
        exc = event.exception
        log_ = logging.getLogger("errors")
        if isinstance(exc, TelegramBadRequest):
            msg = str(exc).lower()
            # Qayta takroran bosilgan tugma / o'zgarmagan message — foydalanuvchiga ko'rsatmaymiz
            if "message is not modified" in msg or "query is too old" in msg or "message to edit not found" in msg or "message can't be edited" in msg:
                return True
            log_.warning(f"TelegramBadRequest: {exc}")
            return True
        if isinstance(exc, TelegramForbiddenError):
            log_.info(f"Forbidden (user blocked bot?): {exc}")
            return True
        if isinstance(exc, TelegramRetryAfter):
            log_.warning(f"Flood wait {exc.retry_after}s")
            return True
        log_.exception("Unhandled error", exc_info=exc)
        return True

    # Bot faqat shaxsiy chatda javob beradi. Guruh/kanalda sukut saqlaydi.
    admin.router.message.filter(F.chat.type == "private")
    user.router.message.filter(F.chat.type == "private")
    moderation.router.message.filter(F.chat.type == "private")
    super_admin.router.message.filter(F.chat.type == "private")
    survey_admin.router.message.filter(F.chat.type == "private")
    survey_user.router.message.filter(F.chat.type == "private")
    dp.include_router(super_admin.router)
    dp.include_router(survey_admin.router)
    dp.include_router(survey_user.router)
    dp.include_router(admin.router)
    dp.include_router(moderation.router)
    dp.include_router(user.router)
    dp.include_router(user_myposts.router)
    # REJA13: premium obuna arizalari (callbacklar guruhlarda ham ishlasin)
    from handlers import subscription as _sub
    dp.include_router(_sub.router)

    # Guruh/kanalga qo'shilganda owner avtomatik ro'yxatga olinadi
    from handlers.membership import router as membership_router
    dp.include_router(membership_router)

    log.info("Bot ishga tushdi")
    try:
        # Saved search notifier fonda ishlaydi
        from saved_search_notifier import run_notifier
        notifier_task = asyncio.create_task(run_notifier(bot))
        try:
            await dp.start_polling(bot)
        finally:
            notifier_task.cancel()
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
