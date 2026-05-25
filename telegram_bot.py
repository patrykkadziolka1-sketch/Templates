import html
import logging
import os
import re
import sqlite3
import threading
import time
from decimal import Decimal, ROUND_HALF_UP

import telebot
from flask import Flask
from telebot.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    LabeledPrice,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

def read_token() -> str:
    raw = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TOKEN") or ""
    token = raw.strip().strip('"').strip("'")

    if not token:
        raise RuntimeError("Brakuje TELEGRAM_BOT_TOKEN (lub TOKEN) w zmiennych środowiskowych.")
    if ":" not in token:
        raise RuntimeError(
            "Niepoprawny token Telegram: musi zawierać dwukropek, np. 123456789:AA.... "
            "Sprawdź zmienną TELEGRAM_BOT_TOKEN w Railway."
        )
    return token


TOKEN = read_token()

TON_PLN_RATE = Decimal(os.getenv("TON_PLN_RATE", "7.00"))
PORTFEL_TON = os.getenv("TON_WALLET", "UQDHVV9a-A4hLUO5mjErrg55D2OsULhYW3gWyeSqKrBCEhXJ")
STARS_PER_PLN = Decimal(os.getenv("STARS_PER_PLN", "10"))
SUPPORT_CONTACT_URL = os.getenv("SUPPORT_CONTACT_URL", "https://t.me/realizacja_ambulans")
BTC_ADDRESS = os.getenv("BTC_ADDRESS", "bc1qd5aj0c80nh53j6pw3d5ecwagarxtypp6un2ard")
LTC_ADDRESS = os.getenv("LTC_ADDRESS", "ltc1qra98acwp9d2taf74gr08a2lwp0a56qptq6627g")
SOL_ADDRESS = os.getenv("SOL_ADDRESS", "E8v6Ext4qs7GHEvigeRTFF3wFZXuu9eBihdTpVNvXESz")
ADMIN_IDS = {
    int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().lstrip("-").isdigit()
}

DB_PATH = os.getenv("BOT_DB_PATH", "bot_data.sqlite3")

PRODUCTS = {
    "A": {"name": "Produkt A", "qty": "3 szt.", "price_grosze": 39900},
    "B": {"name": "Produkt B", "qty": "3 szt.", "price_grosze": 39900},
    "C": {"name": "Produkt C", "qty": "3 szt.", "price_grosze": 34900},
    "D": {"name": "Produkt D", "qty": "1 szt.", "price_grosze": 34900},
    "E": {"name": "Produkt E", "qty": "2 szt.", "price_grosze": 60000},
    "F": {"name": "Produkt F", "qty": "1 szt.", "price_grosze": 99900},
}

QUICK_TOPUP_AMOUNTS = [5000, 10000, 20000, 50000]  # w groszach
PHONE_RE = re.compile(r"^\+?[0-9\s\-()]{7,20}$")
TELEGRAM_USERNAME_RE = re.compile(r"^@[A-Za-z][A-Za-z0-9_]{4,31}$")

bot = telebot.TeleBot(TOKEN)
user_state = {}
stars_payload_map = {}


def get_conn():
    return sqlite3.connect(DB_PATH)


def init_db():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                chat_id INTEGER PRIMARY KEY,
                phone TEXT,
                balance_grosze INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS topup_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                amount_grosze INTEGER NOT NULL,
                amount_ton TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()


def ensure_user(chat_id: int):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("INSERT OR IGNORE INTO users(chat_id) VALUES (?)", (chat_id,))
        conn.commit()


def get_balance(chat_id: int) -> int:
    ensure_user(chat_id)
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT balance_grosze FROM users WHERE chat_id = ?", (chat_id,))
        row = cur.fetchone()
        return int(row[0]) if row else 0


def update_balance(chat_id: int, delta_grosze: int):
    ensure_user(chat_id)
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE users SET balance_grosze = balance_grosze + ? WHERE chat_id = ?",
            (delta_grosze, chat_id),
        )
        conn.commit()


def set_phone(chat_id: int, phone: str):
    ensure_user(chat_id)
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE users SET phone = ? WHERE chat_id = ?", (phone, chat_id))
        conn.commit()


def get_phone(chat_id: int):
    ensure_user(chat_id)
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT phone FROM users WHERE chat_id = ?", (chat_id,))
        row = cur.fetchone()
        return row[0] if row else None


def create_topup_request(chat_id: int, amount_grosze: int, amount_ton: Decimal) -> int:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO topup_requests(chat_id, amount_grosze, amount_ton, status)
            VALUES (?, ?, ?, 'created')
            """,
            (chat_id, amount_grosze, str(amount_ton)),
        )
        conn.commit()
        return cur.lastrowid


def get_topup_request(request_id: int):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, chat_id, amount_grosze, amount_ton, status, created_at
            FROM topup_requests
            WHERE id = ?
            """,
            (request_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "chat_id": row[1],
            "amount_grosze": row[2],
            "amount_ton": row[3],
            "status": row[4],
            "created_at": row[5],
        }


def set_topup_status(request_id: int, status: str):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE topup_requests SET status = ? WHERE id = ?", (status, request_id))
        conn.commit()


def is_admin(chat_id: int) -> bool:
    return chat_id in ADMIN_IDS


def to_ton(amount_grosze: int) -> Decimal:
    amount_pln = Decimal(amount_grosze) / Decimal(100)
    return (amount_pln / TON_PLN_RATE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def ton_to_nano(ton_amount: Decimal) -> int:
    return int((ton_amount * Decimal("1000000000")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def fmt_pln(amount_grosze: int) -> str:
    value = Decimal(amount_grosze) / Decimal(100)
    return f"{value:.2f} PLN"


def to_stars(amount_grosze: int) -> int:
    amount_pln = Decimal(amount_grosze) / Decimal(100)
    stars = int((amount_pln * STARS_PER_PLN).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return max(stars, 1)


def sanitize_state_for_topup(chat_id: int):
    state = user_state.get(chat_id, {})
    pending = state.get("pending_order")
    if pending:
        user_state[chat_id] = {"pending_order": pending}
    else:
        clear_state(chat_id)


def get_pending_order(chat_id: int):
    state = user_state.get(chat_id, {})
    order = state.get("pending_order")
    if not order:
        return None
    product_key = order.get("product_key")
    if product_key not in PRODUCTS:
        return None
    return order


def delivery_choice_markup(product_key: str):
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("1. Numer telefonu", callback_data=f"delivery_phone_{product_key}"),
        InlineKeyboardButton("2. Telegram", callback_data=f"delivery_tg_{product_key}"),
        InlineKeyboardButton("⬅️ Produkty", callback_data="menu_products"),
    )
    return markup


def payment_options_markup(product_key: str):
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("💰 Zapłać z salda", callback_data=f"pay_balance_{product_key}"),
        InlineKeyboardButton("👛 Portfel Telegram (TON/STARS)", callback_data=f"pay_wallet_{product_key}"),
        InlineKeyboardButton("🏦 Depozyt BTC/LTC/SOL/BLIK", callback_data=f"pay_deposit_{product_key}"),
        InlineKeyboardButton("⬅️ Menu", callback_data="menu_main"),
    )
    return markup


def wallet_markup(product_key: str, amount_nano: int):
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton(
            "💎 Zapłać TON (Wallet)",
            url=f"ton://transfer/{PORTFEL_TON}?amount={amount_nano}",
        ),
        InlineKeyboardButton("⭐ Zapłać STARS", callback_data=f"pay_stars_{product_key}"),
        InlineKeyboardButton("⬅️ Metody płatności", callback_data=f"back_to_pay_{product_key}"),
    )
    return markup


def order_delivery_line(order: dict) -> str:
    delivery_type = order.get("delivery_type")
    delivery_value = order.get("delivery_value", "brak")
    if delivery_type == "phone":
        return f"📞 Numer telefonu: <b>{html.escape(delivery_value)}</b>"
    return f"💬 Telegram: <b>{html.escape(delivery_value)}</b>"


def create_pending_order(chat_id: int, product_key: str, delivery_type: str, delivery_value: str):
    user_state[chat_id] = {
        "pending_order": {
            "product_key": product_key,
            "delivery_type": delivery_type,
            "delivery_value": delivery_value,
        }
    }


def send_deposit_info(chat_id: int, product_key: str):
    if product_key not in PRODUCTS:
        bot.send_message(chat_id, "Nie znaleziono produktu.")
        return

    product = PRODUCTS[product_key]
    order = get_pending_order(chat_id)
    delivery_line = order_delivery_line(order) if order else "📦 Dane dostawy: <b>uzupełnij ponownie</b>"

    msg = (
        "<b>Depozyt krypto / BLIK</b>\n\n"
        f"📦 Produkt: <b>{html.escape(product['name'])}</b>\n"
        f"{delivery_line}\n"
        f"💵 Kwota zamówienia: <b>{fmt_pln(product['price_grosze'])}</b>\n\n"
        "<b>Adresy depozytowe:</b>\n"
        f"BTC: <code>{BTC_ADDRESS}</code>\n"
        f"LTC: <code>{LTC_ADDRESS}</code>\n"
        f"SOL: <code>{SOL_ADDRESS}</code>\n\n"
        "BLIK: tymczasowo wpłata odbywa się manualnie poprzez kontakt z obsługą."
    )

    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("💬 Kontakt z obsługą (BLIK)", url=SUPPORT_CONTACT_URL),
        InlineKeyboardButton("⬅️ Metody płatności", callback_data=f"back_to_pay_{product_key}"),
    )
    bot.send_message(chat_id, msg, parse_mode="HTML", reply_markup=markup)


def main_menu_markup():
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("🛍️ Zamów produkt", callback_data="menu_products"),
        InlineKeyboardButton("💰 Panel salda", callback_data="menu_balance"),
        InlineKeyboardButton("ℹ️ Pomoc", callback_data="menu_help"),
    )
    return markup


def products_markup():
    markup = InlineKeyboardMarkup(row_width=1)
    for key, data in PRODUCTS.items():
        price = fmt_pln(data["price_grosze"])
        text = f"📦 {data['name']} ({data['qty']}) - {price}"
        markup.add(InlineKeyboardButton(text, callback_data=f"select_prod_{key}"))
    markup.add(InlineKeyboardButton("⬅️ Wróć", callback_data="menu_main"))
    return markup


def balance_panel_markup():
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("➕ Doładuj saldo", callback_data="topup_menu"),
        InlineKeyboardButton("⬅️ Wróć", callback_data="menu_main"),
    )
    return markup


def topup_menu_markup():
    markup = InlineKeyboardMarkup(row_width=2)
    for amount in QUICK_TOPUP_AMOUNTS:
        markup.add(
            InlineKeyboardButton(
                f"{int(amount / 100)} PLN", callback_data=f"topup_quick_{amount}"
            )
        )
    markup.add(
        InlineKeyboardButton("✍️ Inna kwota", callback_data="topup_manual"),
        InlineKeyboardButton("⬅️ Panel salda", callback_data="menu_balance"),
    )
    return markup


def ask_for_phone_markup():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(KeyboardButton("📱 Udostępnij swój numer", request_contact=True))
    return markup


def clear_state(chat_id: int):
    user_state.pop(chat_id, None)


def send_main_menu(chat_id: int):
    ensure_user(chat_id)
    balance = get_balance(chat_id)
    msg = (
        "Witaj w panelu zamówień.\n\n"
        f"Twoje saldo: <b>{fmt_pln(balance)}</b>\n"
        "Wybierz, co chcesz zrobić:"
    )
    bot.send_message(chat_id, msg, parse_mode="HTML", reply_markup=main_menu_markup())


def send_balance_panel(chat_id: int):
    balance = get_balance(chat_id)
    text = (
        "<b>Panel salda</b>\n\n"
        f"Dostępne środki: <b>{fmt_pln(balance)}</b>\n"
        "Możesz doładować saldo i potem płacić nim za produkty."
    )
    bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=balance_panel_markup())


def send_product_summary(chat_id: int, product_key: str, delivery_type: str, delivery_value: str):
    product = PRODUCTS[product_key]
    balance = get_balance(chat_id)

    price_ton = to_ton(product["price_grosze"])
    stars_amount = to_stars(product["price_grosze"])
    create_pending_order(chat_id, product_key, delivery_type, delivery_value)

    delivery_line = (
        f"📞 Numer telefonu: <b>{html.escape(delivery_value)}</b>"
        if delivery_type == "phone"
        else f"💬 Telegram: <b>{html.escape(delivery_value)}</b>"
    )

    summary = (
        "<b>Podsumowanie zamówienia</b>\n\n"
        f"📦 Produkt: <b>{html.escape(product['name'])}</b>\n"
        f"🔢 Ilość: <b>{html.escape(product['qty'])}</b>\n"
        f"{delivery_line}\n"
        f"💵 Kwota: <b>{fmt_pln(product['price_grosze'])}</b>\n"
        f"💎 Kwota w TON: <b>~{price_ton} TON</b>\n"
        f"⭐ Kwota w STARS: <b>~{stars_amount} XTR</b>\n"
        f"💰 Twoje saldo: <b>{fmt_pln(balance)}</b>"
    )

    try:
        temp_msg = bot.send_message(chat_id, "Przygotowuję metody płatności...", reply_markup=ReplyKeyboardRemove())
        bot.delete_message(chat_id, temp_msg.message_id)
    except Exception:
        pass

    bot.send_message(
        chat_id,
        summary,
        parse_mode="HTML",
        reply_markup=payment_options_markup(product_key),
    )


def send_stars_invoice(chat_id: int, product_key: str):
    if product_key not in PRODUCTS:
        bot.send_message(chat_id, "Nie znaleziono produktu.")
        return

    order = get_pending_order(chat_id)
    if not order or order.get("product_key") != product_key:
        bot.send_message(chat_id, "Najpierw utwórz zamówienie ponownie przez /start.")
        return

    product = PRODUCTS[product_key]
    stars_amount = to_stars(product["price_grosze"])
    payload = f"stars_{chat_id}_{product_key}_{int(time.time())}"
    stars_payload_map[payload] = order

    try:
        bot.send_invoice(
            chat_id=chat_id,
            title=f"Opłata: {product['name']}",
            description=(
                f"{product['name']} ({product['qty']}) | "
                f"Dostawa: {order.get('delivery_value', 'brak')}"
            ),
            invoice_payload=payload,
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label=f"{product['name']} - STARS", amount=stars_amount)],
        )
    except Exception:
        bot.send_message(
            chat_id,
            (
                "Nie udało się uruchomić płatności STARS.\n"
                "Sprawdź w BotFather, czy płatności STARS są aktywne dla tego bota."
            ),
        )


def start_topup(chat_id: int, amount_grosze: int):
    if amount_grosze < 100:
        bot.send_message(chat_id, "Minimalna kwota doładowania to 1 PLN.")
        return

    amount_ton = to_ton(amount_grosze)
    amount_nano = ton_to_nano(amount_ton)
    request_id = create_topup_request(chat_id, amount_grosze, amount_ton)

    text = (
        "<b>Doładowanie salda</b>\n\n"
        f"Kwota: <b>{fmt_pln(amount_grosze)}</b>\n"
        f"Do zapłaty: <b>~{amount_ton} TON</b>\n"
        f"ID doładowania: <code>{request_id}</code>\n\n"
        "1) Opłać doładowanie przyciskiem TON.\n"
        "2) Kliknij 'Opłaciłem', aby wysłać zgłoszenie do weryfikacji."
    )

    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton(
            "💎 Opłać w TON",
            url=(
                f"ton://transfer/{PORTFEL_TON}?amount={amount_nano}"
                f"&text=TOPUP_{chat_id}_{request_id}"
            ),
        ),
        InlineKeyboardButton("✅ Opłaciłem", callback_data=f"report_topup_{request_id}"),
        InlineKeyboardButton("⬅️ Panel salda", callback_data="menu_balance"),
    )

    bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)


def notify_admins_about_topup(request_data: dict):
    if not ADMIN_IDS:
        return

    txt = (
        "<b>Nowe zgłoszenie doładowania</b>\n\n"
        f"ID: <code>{request_data['id']}</code>\n"
        f"Użytkownik: <code>{request_data['chat_id']}</code>\n"
        f"Kwota: <b>{fmt_pln(request_data['amount_grosze'])}</b>\n"
        f"TON: <b>~{request_data['amount_ton']} TON</b>\n"
        f"Status: <b>{request_data['status']}</b>"
    )

    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("✅ Zatwierdź", callback_data=f"admin_topup_approve_{request_data['id']}"),
        InlineKeyboardButton("❌ Odrzuć", callback_data=f"admin_topup_reject_{request_data['id']}"),
    )

    for admin_id in ADMIN_IDS:
        try:
            bot.send_message(admin_id, txt, parse_mode="HTML", reply_markup=markup)
        except Exception:
            continue


@bot.message_handler(commands=["start"])
def handle_start(message):
    clear_state(message.chat.id)
    send_main_menu(message.chat.id)


@bot.message_handler(commands=["saldo", "panel"])
def handle_saldo_panel(message):
    send_balance_panel(message.chat.id)


@bot.message_handler(commands=["help"])
def handle_help(message):
    msg = (
        "Dostępne komendy:\n"
        "/start - menu główne\n"
        "/saldo - panel salda\n"
        "/panel - panel salda\n"
        "/help - pomoc"
    )
    bot.send_message(message.chat.id, msg)


@bot.message_handler(commands=["admin"])
def handle_admin(message):
    if not is_admin(message.chat.id):
        bot.send_message(message.chat.id, "Ta komenda jest tylko dla administratora.")
        return

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM topup_requests WHERE status = 'reported'")
        pending_count = cur.fetchone()[0]
    bot.send_message(
        message.chat.id,
        f"Panel admina\nOczekujące zgłoszenia doładowania: {pending_count}",
    )


@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    chat_id = call.message.chat.id
    data = call.data

    try:
        if data == "menu_main":
            clear_state(chat_id)
            send_main_menu(chat_id)

        elif data == "menu_products":
            bot.send_message(
                chat_id,
                "Wybierz produkt z listy:",
                reply_markup=products_markup(),
            )

        elif data == "menu_balance":
            clear_state(chat_id)
            send_balance_panel(chat_id)

        elif data == "menu_help":
            handle_help(call.message)

        elif data == "topup_menu":
            sanitize_state_for_topup(chat_id)
            bot.send_message(
                chat_id,
                "Wybierz kwotę doładowania:",
                reply_markup=topup_menu_markup(),
            )

        elif data == "topup_manual":
            sanitize_state_for_topup(chat_id)
            state = user_state.get(chat_id, {})
            state["awaiting_topup_amount"] = True
            user_state[chat_id] = state
            bot.send_message(
                chat_id,
                "Podaj kwotę doładowania w PLN (np. 150):",
                reply_markup=ReplyKeyboardRemove(),
            )

        elif data.startswith("topup_quick_"):
            pending = get_pending_order(chat_id)
            if pending:
                user_state[chat_id] = {"pending_order": pending}
            else:
                clear_state(chat_id)
            amount_grosze = int(data.split("_")[-1])
            start_topup(chat_id, amount_grosze)

        elif data.startswith("select_prod_"):
            key = data.replace("select_prod_", "")
            if key not in PRODUCTS:
                bot.send_message(chat_id, "Nie znaleziono produktu.")
            else:
                user_state[chat_id] = {"selected_product": key}
                bot.send_message(
                    chat_id,
                    (
                        f"Wybrałeś: <b>{html.escape(PRODUCTS[key]['name'])}</b>\n\n"
                        "Dostawa na?"
                    ),
                    parse_mode="HTML",
                    reply_markup=delivery_choice_markup(key),
                )

        elif data.startswith("delivery_phone_"):
            key = data.replace("delivery_phone_", "")
            if key not in PRODUCTS:
                bot.send_message(chat_id, "Nie znaleziono produktu.")
            else:
                user_state[chat_id] = {
                    "selected_product": key,
                    "delivery_type": "phone",
                    "awaiting_phone": True,
                }
                bot.send_message(
                    chat_id,
                    (
                        "Podaj numer telefonu do dostawy\n"
                        "(np. 123321123), albo użyj przycisku udostępnienia kontaktu."
                    ),
                    reply_markup=ask_for_phone_markup(),
                )

        elif data.startswith("delivery_tg_"):
            key = data.replace("delivery_tg_", "")
            if key not in PRODUCTS:
                bot.send_message(chat_id, "Nie znaleziono produktu.")
            else:
                user_state[chat_id] = {
                    "selected_product": key,
                    "delivery_type": "telegram",
                    "awaiting_tg_username": True,
                }
                bot.send_message(
                    chat_id,
                    "Podaj Telegram username do dostawy (np. @klient):",
                    reply_markup=ReplyKeyboardRemove(),
                )

        elif data.startswith("back_to_pay_"):
            key = data.replace("back_to_pay_", "")
            if key not in PRODUCTS:
                bot.send_message(chat_id, "Produkt nie istnieje.")
            else:
                bot.send_message(
                    chat_id,
                    "Wybierz metodę płatności:",
                    reply_markup=payment_options_markup(key),
                )

        elif data.startswith("pay_wallet_"):
            key = data.replace("pay_wallet_", "")
            if key not in PRODUCTS:
                bot.send_message(chat_id, "Produkt nie istnieje.")
            else:
                order = get_pending_order(chat_id)
                if not order or order.get("product_key") != key:
                    bot.send_message(chat_id, "Najpierw utwórz zamówienie ponownie przez /start.")
                else:
                    amount_nano = ton_to_nano(to_ton(PRODUCTS[key]["price_grosze"]))
                    bot.send_message(
                        chat_id,
                        "Wybierz płatność portfelem Telegram:",
                        reply_markup=wallet_markup(key, amount_nano),
                    )

        elif data.startswith("pay_stars_"):
            key = data.replace("pay_stars_", "")
            send_stars_invoice(chat_id, key)

        elif data.startswith("pay_deposit_"):
            key = data.replace("pay_deposit_", "")
            send_deposit_info(chat_id, key)

        elif data.startswith("pay_balance_"):
            key = data.replace("pay_balance_", "")
            if key not in PRODUCTS:
                bot.send_message(chat_id, "Ten produkt nie jest już dostępny.")
            else:
                order = get_pending_order(chat_id)
                if not order or order.get("product_key") != key:
                    bot.send_message(chat_id, "Najpierw utwórz zamówienie ponownie przez /start.")
                else:
                    price = PRODUCTS[key]["price_grosze"]
                    balance = get_balance(chat_id)
                    delivery = order.get("delivery_value", "brak")
                    delivery_title = "Telefon" if order.get("delivery_type") == "phone" else "Telegram"

                    if balance < price:
                        missing = price - balance
                        bot.send_message(
                            chat_id,
                            (
                                "Brakuje środków na saldzie.\n"
                                f"Do zapłaty: {fmt_pln(price)}\n"
                                f"Twoje saldo: {fmt_pln(balance)}\n"
                                f"Brakuje: {fmt_pln(missing)}"
                            ),
                        )
                    else:
                        update_balance(chat_id, -price)
                        new_balance = get_balance(chat_id)
                        bot.send_message(
                            chat_id,
                            (
                                "✅ Płatność saldem zakończona sukcesem.\n\n"
                                f"Produkt: {PRODUCTS[key]['name']}\n"
                                f"Kwota: {fmt_pln(price)}\n"
                                f"{delivery_title}: {delivery}\n"
                                f"Nowe saldo: {fmt_pln(new_balance)}"
                            ),
                            reply_markup=ReplyKeyboardRemove(),
                        )
                        clear_state(chat_id)

        elif data.startswith("report_topup_"):
            request_id = int(data.split("_")[-1])
            req = get_topup_request(request_id)
            if not req or req["chat_id"] != chat_id:
                bot.send_message(chat_id, "Nie znaleziono takiego zgłoszenia.")
            elif req["status"] != "created":
                bot.send_message(chat_id, f"To zgłoszenie ma już status: {req['status']}.")
            else:
                set_topup_status(request_id, "reported")
                req = get_topup_request(request_id)
                notify_admins_about_topup(req)
                bot.send_message(
                    chat_id,
                    "Zgłoszenie wysłane do admina. Po weryfikacji saldo zostanie zaktualizowane.",
                )

        elif data.startswith("admin_topup_"):
            if not is_admin(chat_id):
                bot.send_message(chat_id, "Brak uprawnień.")
            else:
                parts = data.split("_")
                action = parts[2]
                request_id = int(parts[3])
                req = get_topup_request(request_id)

                if not req:
                    bot.send_message(chat_id, "Zgłoszenie nie istnieje.")
                elif req["status"] != "reported":
                    bot.send_message(chat_id, f"Nie można przetworzyć: status = {req['status']}.")
                elif action == "approve":
                    update_balance(req["chat_id"], req["amount_grosze"])
                    set_topup_status(request_id, "approved")
                    new_balance = get_balance(req["chat_id"])

                    bot.send_message(chat_id, f"✅ Doładowanie {request_id} zatwierdzone.")
                    bot.send_message(
                        req["chat_id"],
                        (
                            "✅ Twoje doładowanie zostało zatwierdzone.\n"
                            f"Kwota: {fmt_pln(req['amount_grosze'])}\n"
                            f"Nowe saldo: {fmt_pln(new_balance)}"
                        ),
                    )
                elif action == "reject":
                    set_topup_status(request_id, "rejected")
                    bot.send_message(chat_id, f"❌ Doładowanie {request_id} odrzucone.")
                    bot.send_message(
                        req["chat_id"],
                        (
                            "❌ Twoje zgłoszenie doładowania zostało odrzucone.\n"
                            "Jeśli to pomyłka, skontaktuj się z obsługą."
                        ),
                    )

        bot.answer_callback_query(call.id)

    except Exception as exc:
        bot.answer_callback_query(call.id)
        bot.send_message(chat_id, "Wystąpił błąd. Spróbuj ponownie za chwilę.")
        logging.exception("Błąd callback: %s", exc)


@bot.message_handler(content_types=["contact"])
def handle_contact(message):
    chat_id = message.chat.id
    state = user_state.get(chat_id, {})

    if not state.get("awaiting_phone"):
        bot.send_message(chat_id, "Kontakt zapisany. Użyj /start, aby rozpocząć zakupy.")
        return

    phone = message.contact.phone_number.strip()
    if not PHONE_RE.match(phone):
        bot.send_message(chat_id, "Numer wygląda na niepoprawny. Spróbuj ponownie.")
        return

    set_phone(chat_id, phone)
    product_key = state.get("selected_product")
    if product_key not in PRODUCTS:
        bot.send_message(chat_id, "Nie znaleziono produktu. Użyj /start.")
        return
    send_product_summary(chat_id, product_key, "phone", phone)


@bot.message_handler(content_types=["text"])
def handle_text(message):
    chat_id = message.chat.id
    text = message.text.strip()
    state = user_state.get(chat_id, {})

    if text.startswith("/"):
        return

    if state.get("awaiting_topup_amount"):
        normalized = text.replace(",", ".").replace(" ", "")
        try:
            value = Decimal(normalized)
            value = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            amount_grosze = int(value * 100)
        except Exception:
            bot.send_message(chat_id, "Podaj poprawną kwotę, np. 150 albo 150.50")
            return

        if amount_grosze < 100:
            bot.send_message(chat_id, "Minimalna kwota doładowania to 1 PLN.")
            return
        if amount_grosze > 500000:
            bot.send_message(chat_id, "Maksymalna jednorazowa kwota to 5000 PLN.")
            return

        pending = state.get("pending_order")
        if pending:
            user_state[chat_id] = {"pending_order": pending}
        else:
            clear_state(chat_id)
        start_topup(chat_id, amount_grosze)
        return

    if state.get("awaiting_phone"):
        if not PHONE_RE.match(text):
            bot.send_message(chat_id, "Podaj poprawny numer telefonu albo użyj przycisku kontaktu.")
            return

        set_phone(chat_id, text)
        product_key = state.get("selected_product")
        if product_key not in PRODUCTS:
            bot.send_message(chat_id, "Nie znaleziono produktu. Użyj /start.")
            return
        send_product_summary(chat_id, product_key, "phone", text)
        return

    if state.get("awaiting_tg_username"):
        if not TELEGRAM_USERNAME_RE.match(text):
            bot.send_message(chat_id, "Podaj poprawny username Telegram, np. @klient")
            return

        product_key = state.get("selected_product")
        if product_key not in PRODUCTS:
            bot.send_message(chat_id, "Nie znaleziono produktu. Użyj /start.")
            return
        send_product_summary(chat_id, product_key, "telegram", text)
        return

    bot.send_message(
        chat_id,
        "Nie rozpoznałem polecenia. Użyj /start, aby otworzyć menu.",
        reply_markup=ReplyKeyboardRemove(),
    )


@bot.pre_checkout_query_handler(func=lambda query: True)
def handle_pre_checkout_query(query):
    bot.answer_pre_checkout_query(query.id, ok=True)


@bot.message_handler(content_types=["successful_payment"])
def handle_successful_payment(message):
    payment = message.successful_payment
    payload = payment.invoice_payload
    order = stars_payload_map.get(payload)

    if payload.startswith("stars_") and order:
        product_key = order.get("product_key")
        if product_key in PRODUCTS:
            product = PRODUCTS[product_key]
            delivery_type = "Telefon" if order.get("delivery_type") == "phone" else "Telegram"
            delivery_value = order.get("delivery_value", "brak")
            bot.send_message(
                message.chat.id,
                (
                    "✅ Płatność STARS zakończona sukcesem.\n\n"
                    f"Produkt: {product['name']}\n"
                    f"Kwota: {payment.total_amount} XTR\n"
                    f"{delivery_type}: {delivery_value}\n"
                    "Zamówienie zostało przekazane do realizacji."
                ),
            )
            clear_state(message.chat.id)
            stars_payload_map.pop(payload, None)
            return

    bot.send_message(
        message.chat.id,
        "✅ Płatność przyjęta. Jeśli to pomyłka, skontaktuj się z obsługą.",
    )


app = Flask(__name__)


@app.route("/")
def home():
    return "Bot Telegram działa stabilnie."


def run_flask():
    log = logging.getLogger("werkzeug")
    log.disabled = True
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)


def main():
    logging.basicConfig(level=logging.INFO)
    init_db()

    print("Uruchamianie serwera Railway...")
    threading.Thread(target=run_flask, daemon=True).start()

    bot.remove_webhook()
    print("✅ Bot jest gotowy!")
    bot.infinity_polling()


if __name__ == "__main__":
    main()
