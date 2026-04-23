import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN, LOG_PATH
import database as db
from handlers import admin, user, moderation, super_admin, survey_admin, survey_user


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

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
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

    # Guruh/kanalga qo'shilganda owner avtomatik ro'yxatga olinadi
    from handlers.membership import router as membership_router
    dp.include_router(membership_router)

    log.info("Bot ishga tushdi")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
