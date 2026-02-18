# base.py
import re

from aiogram import Router, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from ..db import DB
from ..config import Config
from ..utils.access import can_manage_chat

router = Router()

CHANNEL_RE = re.compile(r"^@?[A-Za-z0-9_]{5,}$")
# pending action in PM: user_id -> {"chat_id": int, "action": "add"|"del", "msg_id": int|None}
_ig_pending: dict[int, dict] = {}

def safe_html(text: str) -> str:
    # Telegram yoqtirmaydigan taglarni olib tashlaymiz, faqat <b> qoldiramiz
    allowed = {"b"}
    def repl(m):
        tag = m.group(1).lower()
        if tag in allowed:
            return m.group(0)
        return ""
    text = re.sub(r"</?([a-zA-Z0-9]+)[^>]*>", repl, text)
    return text

def _on(flag: bool) -> str:
    return "ON" if flag else "OFF"

def settings_text(s) -> str:
    anti_raid_line = (
        "• Anti-raid: OFF\n"
        if int(s.raid_limit) <= 0
        else f"• Anti-raid: limit {s.raid_limit} / oyna {s.raid_window_min}soat / yopish {s.raid_close_min}soat\n"
    )
    return (
        "🛡 Guruh Himoya Boti — sozlamalar:\n"
        f"• Ssilka blok: {_on(s.block_links)}\n"
        f"• Reklama blok: {_on(s.block_ads)} (limit {s.ads_daily_limit}/kun)\n"
        f"• Arab blok: {_on(s.block_arab)}\n"
        f"• So'kinish blok: {_on(s.block_swear)}\n"
        f"• Kanal post blok: {_on(s.block_channel_posts)}\n"
        f"• Xizmat xabar yashirish: {_on(s.hide_service_msgs)}\n"
        f"• Anti-flood: {_on(s.antiflood_enabled)} (max {s.flood_max_msgs}/{s.flood_window_sec}s)\n"
        f"{anti_raid_line}"
        f"• Force add: {_on(s.force_add_enabled)} (talab {s.force_add_required})\n"
        f"• Force kanal: {'@'+s.linked_channel if s.linked_channel else 'OFF'}\n"
        f"• Anti-same: {_on(s.antisame_enabled)} ({s.antisame_minutes} min)\n"
    )

def _add_to_group_kb(bot_username: str, video_url: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="🎥 Video qo‘llanma", url=video_url)
    kb.button(text="➕ Guruhga qo‘shish", url=f"https://t.me/{bot_username}?startgroup=true")
    kb.adjust(1)
    return kb.as_markup()

def _help_menu_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="📌 Botni sozlash instruktsiyasi", callback_data="help:setup:0")
    kb.button(text="🧩 Asosiy", callback_data="help:basic")
    kb.button(text="⚙️ Kengaytirilgan", callback_data="help:advanced")
    kb.adjust(1)
    return kb.as_markup()

def _help_kb(bot_username: str, video_url: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="🎥 Video qo‘llanma", url=video_url)
    kb.button(text="➕ Guruhga qo‘shish", url=f"https://t.me/{bot_username}?startgroup=true")
    kb.adjust(1)
    return kb.as_markup()

def _ignore_menu_kb(chat_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="📋 Ro‘yxat", callback_data=f"ig:list:{chat_id}")
    kb.button(text="➕ Qo‘shish", callback_data=f"ig:add:{chat_id}")
    kb.button(text="❌ Yopish", callback_data=f"ig:close:{chat_id}")
    kb.adjust(2, 1)
    return kb.as_markup()

def _ignore_list_kb(chat_id: int, items: list[str]):
    kb = InlineKeyboardBuilder()
    # delete buttons
    for u in items:
        kb.button(text=f"❌ @{u}", callback_data=f"ig:rm:{chat_id}:{u}")
    # actions
    kb.button(text="➕ Qo‘shish", callback_data=f"ig:add:{chat_id}")
    kb.button(text="⬅️ Orqaga", callback_data=f"ig:back:{chat_id}")
    kb.adjust(1)
    return kb.as_markup()

def _ignore_cancel_kb(chat_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Bekor qilish", callback_data=f"ig:cancel:{chat_id}")
    kb.adjust(1)
    return kb.as_markup()


SETUP_STEPS = [
    "1/4 — Botni guruhga qo‘shing va Admin qiling.\n\n"
    "• Guruh → Add members → botni tanlang\n"
    "• Guruh Settings → Administrators → botga ruxsat bering\n\n"
    "✅ Muhim: <b>Delete messages</b> va <b>Restrict members</b> ruxsatlari <b>yoqilgan</b> bo‘lsin.\n"
    "Aks holda bot o‘chira olmaydi yoki mute qila olmaydi.",

    "2/4 — Tavsiya etiladigan bazaviy sozlash.\n\n"
    "• /ssilka yoq\n"
    "• /antiflood yoq\n"
    "• /setflood 5\n"
    "• /setfloodtime 5\n"
    "Keyin /holat bilan tekshiring.",

    "3/4 — Anti-raid sozlash.\n\n"
    "• /antiraidpanel\n"
    "Paneldagi tugmalar orqali limit/oyna/yopish qiymatlarini o‘rnating.",

    "4/4 — Bot admin boshqaruvi.\n\n"
    "Guruh egasi (creator) yoki bot admin:\n"
    "• /botadmin_add (reply yoki @username) — shu guruhda bot admin beradi\n"
    "• /botadmin_del (reply yoki @username) — olib tashlaydi\n",
]


HELP_ALL = (
    "📘 <b>GURUH HIMOYA BOT | ADMIN PANEL</b>\n\n"
    
    "👋  <b>Guruh xavfsizligi uchun yaratilgan professional avtomatik himoya tizimi.</b>\n"
    "⚡️ 24/7 faol nazorat va tezkor himoya.\n"
    "🔐 To‘liq boshqaruv adminlar qo‘lida.\n\n"

    "⚙️ <b>Asosiy buyruqlar</b>\n\n"
    
    "/help — Barcha buyruqlar ro‘yxati\n"
    "/holat — Hozirgi faol sozlamalar (ON/OFF)\n\n"
    
    "━━━━━━━━━━━━━━━━━━\n\n"

    "🔒 <b>XABAR FILTRLARI</b>\n\n"
    
    "🔗 <b>Havola</b>\n\n"
    
    "/ssilka yoq — Havolani bloklaydi\n"
    "/ssilka o‘chir — Ruxsat beradi\n\n"
    
    "📢 <b>Reklama</b>\n\n"

    "/reklama yoq — Reklama va spamni o‘chiradi\n"
    "/reklama o‘chir — Ruxsat beradi\n"
    "/rek_limit son — Reklama limitini belgilaydi\n\n"
    
    "🈲 <b>Arab harfi</b>\n\n"

    "/arab yoq — Arab harfli xabarni o‘chiradi\n"
    "/arab o‘chir — Ruxsat beradi\n\n"
    
    "🤬 <b> So‘kinish</b>\n\n"

    "/sokin yoq — So‘kinishni o‘chiradi\n"
    "/sokin o‘chir — Ruxsat beradi\n\n"
    
    "🈲 <b>YOMON SO‘ZLAR (BADWORDS)</b>\n\n"
    
    "/yomonqosh &lt;so‘z&gt; — Yomon so‘z qo‘shadi\n"
    "/yomondel &lt;so‘z&gt; — So‘zni o‘chiradi.\n"
    "/yomonlist — Barcha yomon so‘zlar ro‘yxatini ko‘rsatadi\n\n"
    
    "📛 <b>Kanal postlari</b>\n\n"

    "/kanalpost yoq — Kanal nomidan yuborilgan postlarni o‘chiradi.\n"
    "/kanalpost o‘chir — Kanal postlariga ruxsat beradi.\n\n"
    
    "👻 <b>Xizmat xabarlari</b>\n"
    "/xizmat yoq — Kirish/Chiqish xabarlarni yashiradi.\n"
    "/xizmat o‘chir — Kirish/Chiqish xabarlarni ko‘rsatadi.\n\n"
    
    "━━━━━━━━━━━━━━━━━━\n\n"
    
    "🌊 <b>ANTI-FLOOD (KO‘P XABAR)</b>\n"

    "/antiflood yoq — Ketma-ket yozishni cheklaydi\n"
    "/antiflood o‘chir — Cheklovni o‘chiradi\n"
    "/setflood 5 — Ruxsat etilgan xabar soni\n"
    "/setfloodtime 7 — Hisoblash vaqti (soniya)\n\n"
    
    "➡️ 7 soniyada 5 tadan ko‘p xabar yozsa — MUTE 🚫\n\n"
    
    "━━━━━━━━━━━━━━━━━━\n\n"

    "♻️ <b>ANTI-SAME (BIR XIL XABAR)</b>\n"
    "/antisame yoq — Bir xil xabarni bloklaydi\n"
    "/antisame o‘chir — Ruxsat beradi.\n"
    "/settime 2 — 2 minut ichida takrorlansa blok\n\n"
    
    "━━━━━━━━━━━━━━━━━━\n\n"

    "🧯 <b>ANTI-RAID (OMMAVIY KIRISH)</b>\n\n"
    
    "/limit son —  Kiruvchilar limiti\n"
    "/oyna soat —  Vaqt oralig‘i (soat)\n"
    "/yopish soat — Yopish muddati (soat)\n"
    "/limit 0 — O‘chiradi\n"
    "/antiraidpanel — Tugmali panel\n\n"
    
    "➡️ Limit oshsa — guruh vaqtincha yopiladi 🚫\n\n"
    
    "<b>📌 Misol:</b>\n"
    "/limit 100\n"
    "/oyna 1\n"
    "/yopish 2\n\n"
    
    "➡️ 1 soatda 100 ta odam kirsa — guruh 2 soatga yopiladi 🚫\n\n"
    
    "━━━━━━━━━━━━━━━━━━\n\n"        

    "📢 <b>MAJBURIY KANAL</b>\n\n"
    "/set @kanal — Majburiy obunani yoqadi\n"
    "/unlink — Majburiy obunani o‘chiradi\n\n"
    
    "➡️ Kanalga obuna bo‘lmagan foydalanuvchi yozolmaydi 🚫\n\n"
    
    "/ignore — Boshqa kanallar yoki botlar xabarlarini o'chirmaydi\n\n"
    
    "━━━━━━━━━━━━━━━━━━\n\n" 

    "👥 <b>FORCE ADD MAJBURIY ODAM QO‘SHISH</b>\n\n"
    
    "🔹 <b>Asosiy sozlama</b>\n\n"
    
    "/add 3 — 3 ta odam qo‘shsa yozadi\n"
    "/add off — Majburiy qo‘shishni o‘chiradi\n"
    "/text_time 30 — Matn o‘chish vaqti (soniya)\n"
    "━━━\n"
    "🔹 <b>Ogohlantirish matni</b>\n\n"
    
    "/textforce matn — Ogohlantirish matni.\n"
    "/text_repeat 1h — Takrorlash vaqti 1h/30m/60s\n"
    "/text_repeat_time soniya — Matnni o'chish vaqti.\n"
    "/text_repeat 0 — Takrorlashni o‘chiradi\n"
    "━━━\n"
    "🔹 <b> Foydalanuvchi boshqaruvi</b>\n\n"
    
    "/priv — Foydalanuvchiga imtiyoz beradi\n"
    "/priv_del — Imtiyozni olib tashlaydi\n"
    "/delson — Qo‘shgan odam sonini 0 qiladi\n"
    "/deforce — Force add ma’lumotlarini tozalaydi\n\n"
    
    "━━━━━━━━━━━━━━━━━━\n\n"

    "🧹 <b>Tozalash</b>\n"
    "/clean —  Statistikani tozalaydi + unmute qiladi\n"
    "/unmute — Faqat muteni ochadi\n\n"
    
    "━━━━━━━━━━━━━━━━━━\n\n"

    "👮 <b>BOT ADMIN</b>\n\n"
    "/botadmin_add — Bot admin qiladi\n"
    "/botadmin_del — Bot adminni olib tashlaydi\n\n"
    
    "━━━━━━━━━━━━━━━━━━\n\n"

    "✅ Bot avtomatik ishlaydi\n"
    "✅ Buyruqlar reply yoki @username bilan ishlaydi\n"
    "✅ Faqat adminlar boshqaradi"
)


@router.message(Command("help"))
async def cmd_help(message: Message, db: DB, config: Config):
    me = await message.bot.get_me()

    await message.answer(
        safe_html(HELP_ALL),
        reply_markup=_help_kb(me.username, config.video_url),
        parse_mode="HTML",
        disable_web_page_preview=True
    )


@router.message(Command("start", "holat"))
async def cmd_start(message: Message, command: CommandObject, db: DB, config: Config):
    await db.touch_chat(message.chat.id, message.chat.title or "")

    args = (command.args or "").strip()
    # ---- Ignore usernames panel via deep link: /start ig_<chat_id> ----
    if args.startswith("ig_"):

        if message.chat.type != "private":
            return
        try:
            chat_id = int(args.split("_", 1)[1])
        except Exception:
            await message.answer("Noto‘g‘ri so‘rov.")
            return

        # check permission: only who can manage that chat
        ok = await can_manage_chat(
            message.bot,
            chat_id,
            message.from_user.id,
            message.from_user.username,
            db,
            config
        )
        if not ok:
            await message.answer("Bu guruhni sozlashga ruxsat yo‘q.")
            return
        await db.touch_user(
            message.from_user.id,
            message.from_user.username or "",
            message.from_user.full_name or ""
            )

        await message.answer(
            "🧩 <b>IGNORE USERNAMES</b>\n\n"
            "Bu ro‘yxatdagi @username'lar uchun:\n"
            "✅ /set majburiy obuna tekshiruvi o‘tkazib yuboriladi\n"
            "✅ /kanalpost blokidan o‘tadi\n"
            "⚠️ Lekin: ssilka/reklama/arab/so‘kinish/antiflood/antisame baribir ishlaydi.\n\n"
            "Kerakli bo‘limni tanlang:",
            parse_mode = "HTML",
            reply_markup = _ignore_menu_kb(chat_id)
        )
        return

    args = (command.args or "").strip()
    if args.startswith("force_"):
        if message.chat.type != "private":
            return

        try:
            chat_id = int(args.split("_", 1)[1])
        except Exception:
            await message.answer("Noto‘g‘ri so‘rov.")
            return

        s = await db.get_or_create_settings(chat_id)
        required = int(s.force_add_required or 0)
        added = await db.get_force_progress(chat_id, message.from_user.id)
        need = max(0, required - added)

        await message.answer(
            "📌 <b>Guruh bo‘yicha hisobingiz</b>\n\n"
            f"✅ Qo‘shganingiz: <b>{added}</b> ta\n"
            f"🎯 Talab: <b>{required}</b> ta\n"
            f"⏳ Qoldi: <b>{need}</b> ta\n\n"
            "Guruhga odam qo‘shib bo‘lgach, qayta yozib ko‘ring.",
            parse_mode="HTML"
        )
        return

    me = await message.bot.get_me()
    if message.chat.type == "private":
        text = (
            "👋 Assalomu alaykum! \n\n"
            
            "🔐 <b>GURUH HIMOYA BOT</b> ga xush kelibsiz.\n\n"
            
            "<b>24/7 avtomatik xavfsizlik tizimi.</b>\n"
            "Spam, reklama, flood va raidlar endi muammo emas.\n\n"

            "─────────────────\n\n"
            
            "🛡 <b>Himoya imkoniyatlari</b>\n\n"
            
            "⚡️ Anti-Spam\n"
            "🌊 Anti-Flood\n"
            "♻️ Anti-Same\n"
            "🧯 Anti-Raid\n"
            "📢 Majburiy kanal\n"
            "👥 Force Add\n\n"

            "─────────────────\n\n"
            
            "🚀 <b>Ishga tushirish</b>\n\n"
            
            "1️⃣ Botni superguruhga qo‘shing\n"
            "2️⃣ Admin huquqini bering\n\n"

            "<b>Himoya darhol faollashadi.</b>\n\n"

            "─────────────────\n\n"

            "📖 Buyruqlar: /help\n"
            "👮 Admin: @shaxzod_733"
        )
        await db.touch_user(
            message.from_user.id,
            message.from_user.username or "",
            message.from_user.full_name or ""
        )
        await db.touch_chat(message.chat.id, message.chat.title or "")
        await message.answer(text, parse_mode="HTML", reply_markup=_add_to_group_kb(me.username, config.video_url))
        return

    # guruhda /start ishlatilsa: holatni ko‘rsatib qo‘yamiz
    s = await db.get_or_create_settings(message.chat.id)
    await db.touch_chat(message.chat.id, message.chat.title or "")
    await message.answer(settings_text(s))

@router.callback_query(F.data.startswith("ig:"))
async def cb_ignore_panel(query: CallbackQuery, db: DB, config: Config):
    if not query.message:
        return
    parts = (query.data or "").split(":")
    if len(parts) not in (3, 4):
        await query.answer("Noto‘g‘ri tugma.", show_alert=True)
        return
    _, action, chat_id_raw = parts[0], parts[1], parts[2]
    try:
        chat_id = int(chat_id_raw)
    except Exception:
        await query.answer("Noto‘g‘ri chat.", show_alert=True)
        return

    ok = await can_manage_chat(
        query.bot,
        chat_id,
        query.from_user.id,
        query.from_user.username,
        db,
        config
    )
    if not ok:
        await query.answer("Ruxsat yo‘q.", show_alert=True)
        return

    # close
    if action == "close":
        try:
            await query.message.edit_text("✅ Yopildi.")
        except Exception:
            pass
        await query.answer()
        return

    if action == "back":
        try:
            await query.message.edit_text(
                "Kerakli bo‘limni tanlang:",
                reply_markup=_ignore_menu_kb(chat_id)
            )
        except Exception:
            pass
        await query.answer()
        return

    # cancel pending add/del
    if action == "cancel":
        _ig_pending.pop(query.from_user.id, None)
        try:
            await query.message.edit_text(
                "Kerakli bo‘limni tanlang:",
                reply_markup=_ignore_menu_kb(chat_id)
            )
        except Exception:
            pass
        await query.answer("Bekor qilindi")
        return

    # list
    if action == "list":
        items = await db.list_ignore_usernames(chat_id, limit=200)
        txt = "📋 <b>Ignore ro‘yxati</b>\n\n"
        if not items:
            txt += "📭 Bo‘sh."
            kb = _ignore_menu_kb(chat_id)
        else:
            txt += "Quyidagi username'lar /set tekshiruvini va kanalpost blokini chetlab o‘tadi.\n"
            txt += "O‘chirish uchun ❌ tugmasini bosing."
            kb = _ignore_list_kb(chat_id, items)
        try:
            await query.message.edit_text(
                txt,
                parse_mode="HTML",
                reply_markup=kb
            )
        except Exception:
            pass
        await query.answer()
        return

    if action == "rm":
        if len(parts) != 4:
            await query.answer("Noto‘g‘ri tugma.", show_alert=True)
            return
        u = (parts[3] or "").strip().lstrip("@").lower()
        if not u:
            await query.answer("Noto‘g‘ri username.", show_alert=True)
            return
        await db.remove_ignore_username(chat_id, u)
        # refresh list
        items = await db.list_ignore_usernames(chat_id, limit=200)
        txt = "📋 <b>Ignore ro‘yxati</b>\n\n"
        if not items:
            txt += "📭 Bo‘sh."
            kb = _ignore_menu_kb(chat_id)
        else:
            txt += "Quyidagi username'lar /set tekshiruvini va kanalpost blokini chetlab o‘tadi.\n"
            txt += "O‘chirish uchun ❌ tugmasini bosing."
            kb = _ignore_list_kb(chat_id, items)
        try:
            await query.message.edit_text(txt, parse_mode="HTML", reply_markup=kb)
        except Exception:
            pass
        await query.answer("✅ O‘chirildi")
        return

    # add/del -> ask username
    if action in ("add"):
        _ig_pending[query.from_user.id] = {"chat_id": chat_id, "action": action, "msg_id": query.message.message_id}
        prompt = (
            "➕ @username yuboring (masalan: @mychannel)\n"
            "Username kanalda/guruhda/userda bo‘lishi kerak."
        )
        try:
            await query.message.edit_text(
                prompt,
                reply_markup=_ignore_cancel_kb(chat_id)
            )
        except Exception:
            pass
        await query.answer()
        return

    await query.answer("Noma’lum amal.", show_alert=True)


@router.message(F.chat.type == "private")
async def pm_ignore_input(message: Message, db: DB, config: Config):
    """
    If user is in pending ignore add/del flow, treat plain text as @username and apply.
    """
    if not message.from_user:
        return
    ctx = _ig_pending.get(message.from_user.id)
    if not ctx:
        return

    chat_id = int(ctx["chat_id"])
    action = ctx["action"]

    ok = await can_manage_chat(
        message.bot,
        chat_id,
        message.from_user.id,
        message.from_user.username,
        db,
        config
    )
    if not ok:
        _ig_pending.pop(message.from_user.id, None)
        await message.answer("Bu guruhni sozlashga ruxsat yo‘q.")
        return

    raw = (message.text or "").strip()
    if not raw or not CHANNEL_RE.match(raw):
        await message.answer("❌ Noto‘g‘ri username. Masalan: @mychannel", reply_markup=_ignore_cancel_kb(chat_id))
        return

    u = raw.lstrip("@").lower()

    if action == "add":
        await db.add_ignore_username(chat_id, u)
        await message.answer(f"✅ Qo‘shildi: @{u}", reply_markup=_ignore_menu_kb(chat_id))

    _ig_pending.pop(message.from_user.id, None)


# @router.callback_query(F.data.startswith("help:"))
# async def cb_help(query: CallbackQuery):
#     if not query.message:
#         return
#
#     parts = query.data.split(":")
#     # help:main | help:basic | help:advanced | help:setup:IDX
#     if parts[1] == "main":
#         await query.message.edit_text(
#             "🆘 Yordam menyusiga xush kelibsiz!\n\nBo‘limni tanlang:",
#             reply_markup=_help_menu_kb()
#         )
#         await query.answer()
#         return
#
#     if parts[1] == "basic":
#         kb = InlineKeyboardBuilder()
#         kb.button(text="⬅️ Orqaga", callback_data="help:main")
#         kb.adjust(1)
#         await query.message.edit_text(HELP_BASIC, reply_markup=kb.as_markup(), parse_mode="HTML")
#         await query.answer()
#         return
#
#     if parts[1] == "advanced":
#         kb = InlineKeyboardBuilder()
#         kb.button(text="⬅️ Orqaga", callback_data="help:main")
#         kb.adjust(1)
#         await query.message.edit_text(HELP_ADVANCED, reply_markup=kb.as_markup(), parse_mode="HTML")
#         await query.answer()
#         return
#
#     if parts[1] == "setup":
#         idx = int(parts[2])
#         idx = max(0, min(idx, len(SETUP_STEPS) - 1))
#
#         kb = InlineKeyboardBuilder()
#         if idx > 0:
#             kb.button(text="⬅️ Orqaga", callback_data=f"help:setup:{idx-1}")
#         kb.button(text="🏠 Menu", callback_data="help:main")
#         if idx < len(SETUP_STEPS) - 1:
#             kb.button(text="➡️ Davom etish", callback_data=f"help:setup:{idx+1}")
#         kb.adjust(1)
#
#         await query.message.edit_text("📌 <b>Sozlash instruktsiyasi</b>\n\n" + SETUP_STEPS[idx],
#                                       reply_markup=kb.as_markup(),
#                                       parse_mode="HTML")
#         await query.answer()
#         return
