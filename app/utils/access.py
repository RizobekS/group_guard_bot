# access.py

from aiogram.types import Message
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from ..db import DB
from ..config import Config


async def is_owner(message: Message, config: Config) -> bool:
    if not message.from_user:
        return False
    if not message.from_user.username:
        return False
    return message.from_user.username.lower() == config.owner_username

async def is_chat_creator(bot: Bot, chat_id: int, user_id: int) -> bool:
    """
    Guruh egasi (creator) ekanligini tekshiradi.
    Bot admin bo‘lmasa yoki huquq yetmasa False qaytaradi.
    """
    try:
        m = await bot.get_chat_member(chat_id, user_id)
        return getattr(m, "status", None) == "creator"
    except TelegramBadRequest:
        return False
    except Exception:
        return False

async def can_manage_chat(bot: Bot, chat_id: int, user_id: int, username: str | None, db: DB, config: Config) -> bool:
    # 1) Bot egasi (global)
    if (username or "").lower() == config.owner_username.lower():
        return True

    # 2) Global super-admin (agar qoldirmoqchi bo‘lsangiz)
    if await db.is_bot_admin(user_id):
        return True

    # 3) Guruh egasi (creator)
    if await is_chat_creator(bot, chat_id, user_id):
        return True

    # 4) Shu chat bo‘yicha bot admin
    return await db.is_chat_bot_admin(chat_id, user_id)

async def can_manage_bot(message: Message, db: DB) -> bool:
    if not message.chat or not message.from_user:
        return False
    return await can_manage_chat(
        message.bot,
        message.chat.id,
        message.from_user.id,
        message.from_user.username,
        db
    )
