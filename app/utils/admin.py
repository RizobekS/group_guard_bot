from aiogram import Bot
from aiogram.types import ChatMemberAdministrator, ChatMemberOwner

async def is_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    member = await bot.get_chat_member(chat_id, user_id)
    return isinstance(member, (ChatMemberAdministrator, ChatMemberOwner))
