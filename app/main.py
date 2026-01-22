# app/main.py
import asyncio
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from .config import load_config
from .db import DB
from .handlers import base, settings, guard, ads
from .utils.antiflood import AntiFlood
from .utils.antiraid import AntiRaid

async def main():
    cfg = load_config()
    db = DB(cfg.database_url)
    await db.init_models()

    bot = Bot(cfg.bot_token)
    dp = Dispatcher(storage=MemoryStorage())

    dp["db"] = db
    dp["antiflood"] = AntiFlood()
    dp["antiraid"] = AntiRaid()
    dp["config"] = cfg

    dp.include_router(base.router)
    dp.include_router(settings.router)
    dp.include_router(guard.router)
    dp.include_router(ads.router)

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
