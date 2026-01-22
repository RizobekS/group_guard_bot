import re
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import Command, CommandObject
from ..db import DB
from .base import settings_text
from ..utils.admin import is_admin
from ..utils.access import is_owner, can_manage_bot, can_manage_chat
from ..utils.moderation import unmute_user

router = Router()

CHANNEL_RE = re.compile(r"^@?[A-Za-z0-9_]{5,}$")

def _parse_int(arg: str, min_v: int, max_v: int) -> int | None:
    arg = (arg or "").strip()
    if not arg.isdigit():
        return None
    v = int(arg)
    if v < min_v or v > max_v:
        return None
    return v

@router.message(Command("set"))
async def cmd_set_channel(message: Message, command: CommandObject, db: DB):

    if not await can_manage_bot(message, db):
        return

    if not command.args:
        await message.reply("Foydalanish: /set @kanal  (masalan: /set @mychannel)")
        return
    ch = command.args.strip()

    if not CHANNEL_RE.match(ch):
        await message.reply("Kanal username noto‘g‘ri. Masalan: @mychannel")
        return

    ch = ch.lstrip("@")
    await db.update_settings(message.chat.id, linked_channel=ch)
    await message.reply(f"✅ Force kanal ulandi: @{ch}\nEndi obuna bo‘lmaganlar yozolmaydi.")

@router.message(F.text == "/unlink")
async def cmd_unlink_channel(message: Message, db: DB):
    if not await can_manage_bot(message, db):
        return
    await db.update_settings(message.chat.id, linked_channel="")
    await message.reply("✅ Force kanal o‘chirildi.")

@router.message(F.text.startswith("/limit"))
async def cmd_limit(message: Message, db: DB):
    if not await can_manage_bot(message, db):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply("Foydalanish: /limit <son>  (masalan: /limit 200)")
        return
    v = _parse_int(parts[1], 5, 5000)
    if v is None:
        await message.reply("Noto‘g‘ri son. Limit 5..5000 oralig‘ida bo‘lsin.")
        return
    await db.update_settings(message.chat.id, raid_limit=v)
    s = await db.get_or_create_settings(message.chat.id)
    await message.reply("✅ Anti-raid limit yangilandi.\n\n" + settings_text(s))

@router.message(F.text.startswith("/oyna"))
async def cmd_oyna(message: Message, db: DB):
    if not await can_manage_bot(message, db):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply("Foydalanish: /oyna <min>  (masalan: /oyna 1)")
        return
    v = _parse_int(parts[1], 1, 60)
    if v is None:
        await message.reply("Noto‘g‘ri son. Oyna 1..60 daqiqa.")
        return
    await db.update_settings(message.chat.id, raid_window_min=v)
    s = await db.get_or_create_settings(message.chat.id)
    await message.reply("✅ Anti-raid oyna yangilandi.\n\n" + settings_text(s))

@router.message(F.text.startswith("/yopish"))
async def cmd_yopish(message: Message, db: DB):
    if not await can_manage_bot(message, db):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply("Foydalanish: /yopish <min>  (masalan: /yopish 10)")
        return
    v = _parse_int(parts[1], 1, 180)
    if v is None:
        await message.reply("Noto‘g‘ri son. Yopish 1..180 daqiqa.")
        return
    await db.update_settings(message.chat.id, raid_close_min=v)
    s = await db.get_or_create_settings(message.chat.id)
    await message.reply("✅ Anti-raid yopish vaqti yangilandi.\n\n" + settings_text(s))


def _panel_kb(s) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()

    kb.button(text="➖ Limit", callback_data="ar:limit:-10")
    kb.button(text="➕ Limit", callback_data="ar:limit:+10")
    kb.button(text="➖ Oyna", callback_data="ar:win:-1")
    kb.button(text="➕ Oyna", callback_data="ar:win:+1")
    kb.button(text="➖ Yopish", callback_data="ar:close:-1")
    kb.button(text="➕ Yopish", callback_data="ar:close:+1")

    kb.adjust(2, 2, 2)
    return kb

@router.message(F.text == "/antiraidpanel")
async def cmd_antiraidpanel(message: Message, db: DB):
    if not await can_manage_bot(message, db):
        return
    s = await db.get_or_create_settings(message.chat.id)
    kb = _panel_kb(s).as_markup()
    await message.reply("🛡 Anti-raid panel:\n\n" + settings_text(s), reply_markup=kb)


@router.callback_query(F.data.startswith("ar:"))
async def cb_antiraidpanel(query: CallbackQuery, db: DB):
    if not query.message:
        return

    ok = await can_manage_chat(
        query.bot,
        query.message.chat.id,
        query.from_user.id,
        query.from_user.username,
        db
    )
    if not ok:
        await query.answer("Ruxsat yo‘q.", show_alert=True)
        return

    s = await db.get_or_create_settings(query.message.chat.id)
    _, key, delta = query.data.split(":")
    d = int(delta)

    if key == "limit":
        new_v = max(5, min(5000, s.raid_limit + d))
        await db.update_settings(query.message.chat.id, raid_limit=new_v)
    elif key == "win":
        new_v = max(1, min(60, s.raid_window_min + d))
        await db.update_settings(query.message.chat.id, raid_window_min=new_v)
    elif key == "close":
        new_v = max(1, min(180, s.raid_close_min + d))
        await db.update_settings(query.message.chat.id, raid_close_min=new_v)

    s = await db.get_or_create_settings(query.message.chat.id)
    await query.message.edit_text("🛡 Anti-raid panel:\n\n" + settings_text(s), reply_markup=_panel_kb(s).as_markup())
    await query.answer("✅ Yangilandi")

@router.message(F.text.startswith("/botadmin_add"))
async def cmd_botadmin_add(message: Message, db: DB):
    # chat creator / bot owner / global bot admin ruxsat
    if not await can_manage_bot(message, db):
        return

    if not message.reply_to_message:
        await message.reply("Reply qilib yuboring: /botadmin_add")
        return

    uid = message.reply_to_message.from_user.id
    await db.add_chat_bot_admin(message.chat.id, uid)
    await message.reply("✅ Guruh uchun bot admin qo‘shildi.")

@router.message(F.text.startswith("/botadmin_del"))
async def cmd_botadmin_del(message: Message, db: DB):
    if not await can_manage_bot(message, db):
        return

    if not message.reply_to_message:
        await message.reply("Reply qilib yuboring: /botadmin_del")
        return

    uid = message.reply_to_message.from_user.id
    await db.remove_chat_bot_admin(message.chat.id, uid)
    await message.reply("✅ Guruh uchun bot admin olib tashlandi.")

def _norm_arg(s: str) -> str:
    return (s or "").strip().lower()

async def _require_bot_admin(message: Message, db: DB) -> bool:
    if message.chat.type not in ("group", "supergroup"):
        return False
    if not await can_manage_bot(message, db):
        await message.reply("Bu buyruq faqat bot egasi yoki bot adminlari uchun.")
        return False
    return True

async def _toggle(message: Message, db: DB, field: str, label: str):
    if not await _require_bot_admin(message, db):
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply(f"Foydalanish: {parts[0]} yoq yoki {parts[0]} o‘chir")
        return

    arg = _norm_arg(parts[1])
    if arg in ("yoq", "on"):
        await db.update_settings(message.chat.id, **{field: True})
        await message.reply(f"✅ {label}: ON")
    elif arg in ("o‘chir", "ochir", "off"):
        await db.update_settings(message.chat.id, **{field: False})
        await message.reply(f"✅ {label}: OFF")
    else:
        await message.reply(f"Noto‘g‘ri parametr. {parts[0]} yoq yoki {parts[0]} o‘chir")

@router.message(F.text.startswith("/ssilka"))
async def cmd_ssilka(message: Message, db: DB):
    await _toggle(message, db, "block_links", "Ssilka blok")

@router.message(F.text.startswith("/reklama"))
async def cmd_reklama(message: Message, db: DB):
    await _toggle(message, db, "block_ads", "Reklama blok")

@router.message(F.text.startswith("/arab"))
async def cmd_arab(message: Message, db: DB):
    await _toggle(message, db, "block_arab", "Arab blok")

@router.message(F.text.startswith("/sokin"))
async def cmd_sokin(message: Message, db: DB):
    await _toggle(message, db, "block_swear", "So'kinish blok")

@router.message(F.text.startswith("/kanalpost"))
async def cmd_kanalpost(message: Message, db: DB):
    await _toggle(message, db, "block_channel_posts", "Kanal post blok")

@router.message(F.text.startswith("/xizmat"))
async def cmd_xizmat(message: Message, db: DB):
    await _toggle(message, db, "hide_service_msgs", "Xizmat xabar yashirish")

@router.message(F.text.startswith("/antisame"))
async def cmd_antisame(message: Message, db: DB):
    await _toggle(message, db, "antisame_enabled", "Anti-same")

@router.message(F.text.startswith("/antiflood"))
async def cmd_antiflood(message: Message, db: DB):
    await _toggle(message, db, "antiflood_enabled", "Anti-flood")


@router.message(Command("settime"))
async def cmd_settime(message: Message, command: CommandObject, db: DB):
    if not await _require_bot_admin(message, db):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip().isdigit():
        await message.reply("Foydalanish: /settime <min>. Masalan: /settime 120")
        return

    minutes = int(parts[1].strip())
    if minutes < 1 or minutes > 10080:
        await message.reply("Minut 1 dan 10080 gacha bo‘lsin.")
        return

    await db.update_settings(message.chat.id, antisame_minutes=minutes)
    await message.reply(f"✅ Anti-same vaqti: {minutes} minut.")

@router.message(Command("setflood"))
async def cmd_setflood(message: Message, command: CommandObject, db: DB):
    if not await _require_bot_admin(message, db):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip().isdigit():
        await message.reply("Foydalanish: /setflood <son>. Masalan: /setflood 15")
        return

    n = int(parts[1].strip())
    if n < 3 or n > 100:
        await message.reply("Son 3 dan 100 gacha bo‘lsin.")
        return

    await db.update_settings(message.chat.id, flood_max_msgs=n)
    await message.reply(f"✅ Flood limiti: {n} ta xabar / { (await db.get_or_create_settings(message.chat.id)).flood_window_sec }s")

@router.message(Command("setfloodtime"))
async def cmd_setfloodtime(message: Message, command: CommandObject, db: DB):
    if not await _require_bot_admin(message, db):
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip().isdigit():
        await message.reply("Foydalanish: /setfloodtime <soniya>. Masalan: /setfloodtime 7")
        return

    sec = int(parts[1].strip())
    # адекватные пределы, чтобы не поставить 0 или 9999
    if sec <= 2 or sec >= 720:
        await message.reply("Soniya 2 dan 720 gacha bo‘lsin.")
        return

    await db.update_settings(message.chat.id, flood_window_sec=sec)
    s = await db.get_or_create_settings(message.chat.id)
    await message.reply(f"✅ Anti-flood oynasi: {s.flood_window_sec}s. Limit: {s.flood_max_msgs} ta xabar.")


@router.message(F.text.startswith("/yomonqosh"))
async def cmd_yomonqosh(message: Message, db: DB):
    if not await can_manage_bot(message, db):
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply("Foydalanish: /yomonqosh so‘z")
        return

    word = parts[1].strip().lower()
    if len(word) < 2 or len(word) > 30:
        await message.reply("So‘z uzunligi 2..30 oralig‘ida bo‘lsin.")
        return

    ok = await db.add_bad_word(message.chat.id, word)
    if ok:
        await message.reply(f"✅ Yomon so‘z qo‘shildi: '{word}'")
    else:
        await message.reply("⚠️ Bu so‘z avval qo‘shilgan yoki noto‘g‘ri.")

# Не по ТЗ, но полезно:
@router.message(F.text.startswith("/yomondel"))
async def cmd_yomondel(message: Message, db: DB):
    if not await can_manage_bot(message, db):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply("Foydalanish: /yomondel so‘z")
        return
    word = parts[1].strip().lower()
    await db.remove_bad_word(message.chat.id, word)
    await message.reply(f"✅ O‘chirildi: <code>{word}</code>")

@router.message(F.text == "/yomonlist")
async def cmd_yomonlist(message: Message, db: DB):
    if not await can_manage_bot(message, db):
        return
    words = await db.list_bad_words(message.chat.id, limit=100)
    if not words:
        await message.reply("📭 Yomon so‘zlar ro‘yxati bo‘sh.")
        return
    txt = "📌 Yomon so‘zlar:\n" + "\n".join(f"• '{w}'" for w in words)
    await message.reply(txt)


@router.message(Command("add"))
async def cmd_add(message: Message, command: CommandObject, db: DB):
    if not await can_manage_bot(message, db):
        return

    if not command.args:
        await message.reply("Foydalanish: /add <matn>\nMasalan: /add 10")
        return

    if command.args == "off":
        await db.update_settings(message.chat.id, force_add_enabled=False)
        await message.reply("Force add o‘chirildi.")
        return

    if not command.args.isdigit():
        await message.reply("Foydalanish: /add 10 yoki /add off")
        return

    await db.update_settings(
        message.chat.id,
        force_add_enabled=True,
        force_add_required=int(command.args)
    )
    await message.reply(f"Force add yoqildi: {command.args} ta odam")


@router.message(Command("textforce"))
async def cmd_textforce(message: Message, command: CommandObject, db: DB):
    if not await can_manage_bot(message, db):
        return
    if not command.args:
        await message.reply("Foydalanish: /textforce <matn>\nMasalan: /textforce Guruhda yozish uchun odam qo‘shing.")
        return
    await db.update_settings(message.chat.id, force_text=command.args.strip())
    await message.reply("✅ Force matni saqlandi.")


@router.message(Command("text_time"))
async def cmd_texttime(message,command: CommandObject, db: DB):
    if not await can_manage_bot(message, db):
        return
    if not command.args:
        await message.reply("Foydalanish: /texttime <matn>\nMasalan: /texttime 10")
        return
    await db.update_settings(message.chat.id, force_text_delete_sec=command.args)
    await message.reply("Force xabar vaqti saqlandi.")


@router.message(F.text.startswith("/priv"))
async def cmd_priv(message, db):
    if not await can_manage_bot(message, db):
        return
    if not message.reply_to_message:
        await message.reply("Reply qiling.")
        return
    await db.add_force_priv(message.chat.id, message.reply_to_message.from_user.id)
    await message.reply("User priv qo‘shildi.")


@router.message(F.text.startswith("/delson"))
async def cmd_delson(message, db):
    if not await can_manage_bot(message, db):
        return
    if not message.reply_to_message:
        return
    await db.reset_force_user(message.chat.id, message.reply_to_message.from_user.id)
    await message.reply("Hisob tozalandi.")

@router.message(F.text == "/clean")
async def cmd_clean(message: Message, db: DB, antiflood):
    # Только владелец/бот-админ
    if not await can_manage_bot(message, db):
        return
    if message.chat.type not in ("group", "supergroup"):
        return

    # ТЗ: reply qilingan user statistikasi 0
    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.reply("Foydalanish: reply qilib /clean")
        return

    uid = message.reply_to_message.from_user.id
    await db.clean_user_stats(message.chat.id, uid)
    await unmute_user(message.bot, message.chat.id, uid)

    # Сброс антифлуда из памяти
    try:
        antiflood.clear_user(message.chat.id, uid)
    except Exception:
        pass

    await message.reply("✅ User statistikasi tozalandi.")


@router.message(F.text == "/deforce")
async def cmd_deforce(message: Message, db: DB):
    if not await can_manage_bot(message, db):
        return
    if message.chat.type not in ("group", "supergroup"):
        return

    # ТЗ: Force add ma’lumotlari tozalanadi
    await db.deforce_chat(message.chat.id)

    await message.reply("✅ Force add ma’lumotlari tozalandi.")


@router.message(Command("/unmute"))
async def cmd_unmute(message: Message, db: DB):
    if not await can_manage_bot(message, db):
        return
    if message.chat.type not in ("group", "supergroup"):
        return
    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.reply("Foydalanish: reply qilib /unmute")
        return

    uid = message.reply_to_message.from_user.id
    ok = await unmute_user(message.bot, message.chat.id, uid)
    if ok:
        await message.reply("✅ User blokdan chiqarildi.")
    else:
        await message.reply("⚠️ Userni blokdan chiqarib bo‘lmadi (botda ruxsat yetarli emas).")
