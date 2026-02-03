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
    "• reply + /botadmin_add — shu guruhda bot admin beradi\n"
    "• reply + /botadmin_del — olib tashlaydi\n",
]


HELP_ALL = (
    "📘 <b>YORDAM — BOT BUYRUQLARI</b>\n\n"
    
    "👋 Ushbu bot guruhni tartibga solish, spam va bezorilikdan himoya qilish uchun xizmat qiladi.\n"
    "Pastdagi buyruqlar orqali botni boshqarishingiz mumkin.\n\n"

    "⚙️ <b>Asosiy buyruqlar</b>\n"
    "• <b>/holat</b> — 📖 guruhdagi bot sozlamalari (qaysi bloklar ON/OFF).\n"
    "• <b>/help</b> — 🔍 Bot hozir qaysi sozlamalarda ishlayotganini ko‘rsatadi.\n\n"
    
    "━━━━━━━━━━━━━━━━━━\n\n"

    "🔒 <b>Xabarlarni bloklash (Filtrlar)</b>\n"
    "• <b>/ssilka yoq</b> — 🔗 Havola yuborishni taqiqlaydi.\n"
    "• <b>/ssilka o‘chir</b> — 🔓 Havolalarga ruxsat beradi.\n\n"

    "• <b>/reklama yoq</b> — ❌ Reklama va spam xabarlarni o‘chiradi.\n"
    "• <b>/reklama o‘chir</b> — 📢 Reklama blokini o‘chiradi.\n"
    "• <b>/rek_limit &lt;son&gt;</b> — 🚫 Reklama limitini o‘zgartirish.\n\n"
    
    "<b>Arab harflari</b>\n"

    "• <b>/arab yoq</b> — 🈲 Arab harflari bor xabarlarni o‘chiradi.\n"
    "• <b>/arab o‘chir</b> — 🆗 Arab harflariga ruxsat beradi.\n\n"
    
    "<b>So‘kinish xabarlari</b>\n"

    "• <b>/sokin yoq</b> — 🤬 So‘kinish yozilgan xabarlarni o‘chiradi.\n"
    "• <b>/sokin o‘chir</b> — 🙂 So‘kinishga ruxsat beradi.\n\n"
    
    "<b>Kanal postlari</b>\n"

    "• <b>/kanalpost yoq</b> — 📛 Kanal nomidan yuborilgan postlarni o‘chiradi.\n"
    "• <b>/kanalpost o‘chir</b> — 📬 Kanal postlariga ruxsat beradi.\n\n"
    
    "<b>Xizmat xabarlari</b>\n"

    "• <b>/xizmat yoq</b> — 👻 Kim kirdi / chiqdi degan xabarlarni yashiradi.\n"
    "• <b>/xizmat o‘chir</b> — 👀 Kim kirdi / chiqdi xabarlarni ko‘rsatadi.\n\n"
    
    "━━━━━━━━━━━━━━━━━━\n\n"
    
    "<b>🈲 So‘kinish so‘zlari (BadWords)</b>\n"

    "• <b>/yomonqosh &lt;so‘z&gt;</b> — ➕ Yomon so‘z qo‘shish.\n"
    "• <b>/yomondel &lt;so‘z&gt;</b> — ➖ So‘zni o‘chirish.\n"
    "• <b>/yomonlist</b> — 📄 Barcha yomon so‘zlar ro‘yxati.\n\n"
    
    "<b>🌊 ANTI-FLOOD (KO‘P XABAR)</b>\n"

    "• <b>/antiflood yoq</b> — 🚫 Ketma-ket yozishni cheklaydi.\n"
    "• <b>/antiflood o‘chir</b> — ✅ Cheklovni o‘chiradi.\n\n"
    "• <b>/setflood &lt;son&gt;</b> — 📊 Nechta xabar yozsa cheklanadi\n"
    "• <b>/setfloodtime &lt;soniya&gt;</b> — ⏱ Necha soniya ichida sanaydi\n\n"
    
    "<b>📌 Misol:</b>\n"
    "/setflood 5\n"
    "/setfloodtime 7\n\n"
    
    "➡️ 7 soniyada 5 tadan ko‘p xabar — blok 🚫\n\n"
    
    "━━━━━━━━━━━━━━━━━━\n\n"

    "♻️ <b>ANTI-SAME (BIR XIL XABAR)</b>\n"
    "• <b>/antisame yoq</b> — 🔁 Bir xil xabarni bloklaydi.\n"
    "• <b>/antisame o‘chir</b> — 🔓 Ruxsat beradi.\n"
    "• <b>/settime &lt;min&gt;</b> — ⏳ Qancha vaqtda takrorlansa blok.\n\n"
    
    "━━━━━━━━━━━━━━━━━━\n\n"

    "🧯 <b>ANTI-RAID (OMMAVIY KIRISH)</b>\n"
    "• <b>/limit &lt;son&gt;</b> — 🚪 Nechta odam kirsa xavf deb hisoblansin.\n"
    "• <b>/oyna &lt;soat&gt;</b> — ⏱ Qaysi vaqt ichida sanaydi.\n"
    "• <b>/yopish &lt;soat&gt;</b> — 🔒 Guruhni vaqtincha yopadi.\n"
    "• <b>/limit 0</b> bo'lganda — ANTI-RAID off.\n"
    "• <b>/antiraidpanel</b> — 🎛 Tugmali boshqaruv paneli.\n\n"
    
    "<b>📌 Misol sozlama:</b>\n"
    "/limit 10\n"
    "/oyna 1\n"
    "/yopish 5\n\n"
    
    "➡️ 1 minutda 10 ta odam kirsa — guruh 5 minut yopiladi 🚫\n\n"
    
    "━━━━━━━━━━━━━━━━━━\n\n"        

    "📢 <b>MAJBURIY KANAL OBUNA</b>\n\n"
    "• <b>/set @kanal</b> — 📌 Kanalga obuna bo‘lmaguncha yozishga ruxsat bermaydi.\n"
    "• <b>/unlink</b> — ❌ Majburiy obunani o‘chiradi.\n\n"
    
    "━━━━━━━━━━━━━━━━━━\n\n" 

    "👥 <b>MAJBURIY ODAM QO‘SHISH (FORCE ADD)</b>\n"
    "• <b>/add &lt;son&gt;</b> — ➕ Nechta odam qo‘shish shartligini belgilaydi.\n"
    "• <b>/add off</b> — 🛑 Majburiy qo‘shishni o‘chiradi.\n"
    "• <b>/textforce &lt;matn&gt;</b> — 📝 Ogohlantirish matni.\n"
    "• <b>/text_time &lt;soniya&gt;</b> — ⏰ Matn qachon o‘chishi.\n"
    "• <b>/text_repeat &lt;1h - bir soat | 30m - 30 daqiqa | 60s - 60 soniya&gt;</b> — ⏰ Matn takrorlanadigan vaqt.\n\n"
    "• <b>/priv</b> (reply) — ⭐ Foydalanuvchiga imtiyoz.\n"
    "• <b>/delson</b> (reply) — 🗑 Hisobini 0 qilish.\n"
    "• <b>/deforce</b> — ♻️ Force-add ma’lumotlarini tozalash.\n\n"
    
    "━━━━━━━━━━━━━━━━━━\n\n"

    "🧹 <b>Tozalash</b>\n"
    "• <b>/clean</b> (reply) — 🧽 Foydalanuvchi statistikasini tozalaydi.\n\n"

    "👮 <b>BOT ADMINLARI</b>\n"
    "• <b>/botadmin_add</b> (reply) — ➕ Bot admin qo‘shish.\n"
    "• <b>/botadmin_del</b> (reply) — ➖ Bot adminni olib tashlash.\n"
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
