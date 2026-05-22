import telebot
import os
import threading
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from flask import Flask

TOKEN = "8779022539:AAEiKsz2R3s-_kh6cQvDCQPrHl1os8dChpw"
bot = telebot.TeleBot(TOKEN)

# Aktualny kurs TON do PLN i adres portfela
TON_PLN_RATE = 7.00
PORTFEL_TON = "UQDHVV9a-A4hLUO5mjErrg55D2OsULhYW3gWyeSqKrBCEhXJ"

# Bezpieczne środowisko testowe
PRODUCTS = {
    "A": {"name": "Xanax 2mg/3op", "qty": "3 szt.", "price_pln": 399},
    "B": {"name": "Medikinet 20mg/3op", "qty": "3 szt.", "price_pln": 399},
    "C": {"name": "Clonazepanum 2mg/3op", "qty": "3 szt.", "price_pln": 349},
    "D": {"name": "Dormicum 15mg/100tabl.", "qty": "1 szt.", "price_pln": 349},
    "E": {"name": "DHC 90mg/2op", "qty": "2 szt.", "price_pln": 600},
    "F": {"name": "Oxydolor 80mg/1op", "qty": "1 szt.", "price_pln": 999}
}

user_data = {}

# 1. START - Menu wyboru
@bot.message_handler(commands=['start'])
def start(message):
    chat_id = message.chat.id
    user_data[chat_id] = {} 
    
    markup = InlineKeyboardMarkup(row_width=1)
    
    for key, data in PRODUCTS.items():
        btn_text = f"📦 {data['name']} ({data['qty']}) - {data['price_pln']} PLN"
        markup.add(InlineKeyboardButton(btn_text, callback_data=f"item_{key}"))
        
    bot.send_message(
        chat_id, 
        "Witaj w systemie testowym! Wybierz pozycję:", 
        reply_markup=markup
    )

# 2. WYBÓR POZYCJI I PROŚBA O TELEFON
@bot.callback_query_handler(func=lambda call: call.data.startswith('item_'))
def ask_phone(call):
    chat_id = call.message.chat.id
    item_key = call.data.split('_')[1]
    
    user_data[chat_id]['product'] = PRODUCTS[item_key]
    
    markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    btn_phone = KeyboardButton("📱 Udostępnij swój numer telefonu", request_contact=True)
    markup.add(btn_phone)
    
    bot.delete_message(chat_id, call.message.message_id)
    bot.send_message(
        chat_id, 
        f"Wybrałeś: **{PRODUCTS[item_key]['name']}**.\n\nNa jaki numer telefonu ma zostać przypisane zamówienie? Udostępnij kontakt przyciskiem poniżej lub wpisz go ręcznie:", 
        parse_mode="Markdown", 
        reply_markup=markup
    )

# 3. PODSUMOWANIE WNIOSKU I WYBÓR PŁATNOŚCI
@bot.message_handler(content_types=['contact', 'text'])
def process_payment(message):
    chat_id = message.chat.id
    
    if chat_id not in user_data or 'product' not in user_data[chat_id]:
        if message.text != '/start':
            bot.send_message(chat_id, "Wpisz /start, aby rozpocząć od nowa.", reply_markup=ReplyKeyboardRemove())
        return

    if message.contact:
        telefon = message.contact.phone_number
    else:
        telefon = message.text
        
    product = user_data[chat_id]['product']
    
    # Przeliczenia
    price_ton = round(product['price_pln'] / TON_PLN_RATE, 2)
    kwota_nano = int(price_ton * 1000000000) # Format wymagany przez linki TON
    
    podsumowanie = (
        f"📋 *PODSUMOWANIE ZAMÓWIENIA*\n\n"
        f"📦 **Pozycja:** {product['name']}\n"
        f"🔢 **Ilość:** {product['qty']}\n"
        f"📞 **Telefon:** {telefon}\n"
        f"💵 **Kwota (PLN):** {product['price_pln']} PLN\n"
        f"💎 **Kwota (TON):** ~{price_ton} TON\n\n"
        f"Wybierz preferowaną metodę płatności poniżej. Jeśli wybierzesz BLIK, zostaniesz przekierowany do obsługi."
    )
    
    markup = InlineKeyboardMarkup(row_width=1)
    # Przyciski płatności
    markup.add(
        InlineKeyboardButton("💎 ZAPŁAĆ W TON", url=f"ton://transfer/{PORTFEL_TON}?amount={kwota_nano}"),
        InlineKeyboardButton("💳 ZAPŁAĆ BLIKIEM", url="https://t.me/realizacja_ambulans")
    )
    
    temp_msg = bot.send_message(chat_id, "Generowanie podsumowania...", reply_markup=ReplyKeyboardRemove())
    bot.delete_message(chat_id, temp_msg.message_id)
    
    bot.send_message(chat_id, podsumowanie, parse_mode="Markdown", reply_markup=markup)
    
    user_data.pop(chat_id, None)

# --- SERWER DLA RAILWAY ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot Telegram działa stabilnie."

def run_flask():
    import logging
    log = logging.getLogger('werkzeug')
    log.disabled = True
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

if __name__ == "__main__":
    print("Uruchamianie serwera Railway...")
    threading.Thread(target=run_flask, daemon=True).start()
    
    bot.remove_webhook()
    print("✅ Bot konwersacyjny jest gotowy!")
    bot.infinity_polling()
