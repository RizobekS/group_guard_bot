# base.py
import re

from aiogram import Router, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from ..db import DB
from ..config import Config

router = Router()

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
    
    "/holat — Barcha buyruqlar ro‘yxati\n"
    "/help — Hozirgi faol sozlamalar (ON/OFF)\n\n"
    
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
    
    "➡️ 1 soatda 10 ta odam kirsa — guruh 2 soatga yopiladi 🚫\n\n"
    
    "━━━━━━━━━━━━━━━━━━\n\n"        

    "📢 <b>MAJBURIY KANAL</b>\n\n"
    "/set @kanal — Majburiy obunani yoqadi\n"
    "/unlink — Majburiy obunani o‘chiradi\n\n"
    
    "➡️ Kanalga obuna bo‘lmagan foydalanuvchi yozolmaydi 🚫\n\n"
    
    "━━━━━━━━━━━━━━━━━━\n\n" 

    "👥 <b>FORCE ADD MAJBURIY ODAM QO‘SHISH</b>\n\n"
    
    "🔹 <b>Asosiy sozlama</b>\n\n"
    
    "/add 3 — 3 ta odam qo‘shsa yozadi\n"
    "/add off — Majburiy qo‘shishni o‘chiradi\n"
    "━━━\n"
    "🔹 <b>Ogohlantirish matni</b>\n\n"
    
    "/textforce matn — Ogohlantirish matni.\n"
    "/text_time 30 — Matn o‘chish vaqti (soniya)\n"
    "/text_repeat 1h — Takrorlash vaqti 1h/30m/60s\n"
    "/text_repeat_time soniya — Takrorlash matnni o'chish vaqti.\n"
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



@router.message(Command("start", "holat"))
async def cmd_start(message: Message, command: CommandObject, db: DB, config: Config):
    await db.touch_chat(message.chat.id, message.chat.title or "")

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
            "👋 Salom! \n"
            "Sizning guruhingizni xavfsiz, tartibli va samarali boshqarish uchun mo‘ljallangan 💎 Guruh Himoya Boti siz bilan!\n\n"

            "─────────────────\n\n"

            "⚡ Tez ishga tushirish\n"
            "1️⃣ Meni superguruhga qo‘shing\n"
            "2️⃣ Menga Admin huquqini bering\n\n"

            "➡️ Shunda bot darhol ishlay boshlaydi va guruhingizni himoya qiladi.\n\n"

            "─────────────────\n\n"

            "📌 Botning asosiy imkoniyatlari\n"
            "• 🔒 Spam va reklama xabarlarini avtomatik bloklash\n"
            "• 🌊 Ketma-ket xabarlar (Anti-Flood) nazorati\n"
            "• ♻️ Bir xil xabarlarni takrorlashni oldini olish(Anti - Same)\n"
            "• 🧯 Birdaniga ko‘p odam kirishidan himoya(Anti - Raid)\n"
            "• 📢 Majburiy kanal obuna va odam qo‘shish(Force Add)\n"
            "• 📊 Guruh statistikasini ko‘rish va foydalanuvchilarni boshqarish\n\n"

            "─────────────────\n\n"

            "❓ Buyruqlarni ko‘rish • /help — barcha buyruqlar ro‘yxati\n\n"

            "─────────────────\n\n"

            "👮 Admin bilan bog‘lanish\n"
            f"• Admin: @{config.owner_username}\n"
            "• Savol, taklif yoki muammo bo‘lsa — admin bilan bog‘laning\n\n"

            "─────────────────\n\n"
            "💡 Eslatma\n"
            "- Botni superguruhga qo‘shish va admin qilish shart\n"
            "- Foydalanuvchi /start bosgan zahoti bot avtomatik ishga tushadi\n"
            "- Guruh 24/7 to‘liq nazorat ostida bo‘ladi"
        )
        await db.touch_user(
            message.from_user.id,
            message.from_user.username or "",
            message.from_user.full_name or ""
        )
        await db.touch_chat(message.chat.id, message.chat.title or "")
        await message.answer(text, reply_markup=_add_to_group_kb(me.username, config.video_url))
        return

    # guruhda /start ishlatilsa: holatni ko‘rsatib qo‘yamiz
    s = await db.get_or_create_settings(message.chat.id)
    await db.touch_chat(message.chat.id, message.chat.title or "")
    await message.answer(settings_text(s))

@router.message(Command("help"))
async def cmd_help(message: Message, db: DB, config: Config):
    me = await message.bot.get_me()

    await message.answer(
        safe_html(HELP_ALL),
        reply_markup=_help_kb(me.username, config.video_url),
        parse_mode="HTML",
        disable_web_page_preview=True
    )


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
