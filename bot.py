import telebot
import os
import threading
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from flask import Flask

TOKEN = "8779022539:AAEiKsz2R3s-_kh6cQvDCQPrHl1os8dChpw"
bot = telebot.TeleBot(TOKEN)

# Aktualny kurs TON do PLN (wartość na maj 2026, możesz ją tu swobodnie zmieniać)
TON_PLN_RATE = 7.53

# Baza dostępnych pozycji, ilości i cen w PLN
PRODUCTS = {
    "medikinet": {"name": "Medikinet 20mg", "qty": "3 op", "price_pln": 399},
    "xanax": {"name": "Xanax 2 mg", "qty": "3 op", "price_pln": 399},
    "clonazepanum": {"name": "Clonazepanum 2mg", "qty": "3 op", "price_pln": 349},
    "dormicum": {"name": "Dormicum", "qty": "1 op", "price_pln": 349},
    "dhc": {"name": "DHC 90", "qty": "2 op", "price_pln": 600},
    "oxydolor": {"name": "Oxydolor 80 mg", "qty": "1 op", "price_pln": 999}
}

# Przechowywanie tymczasowych danych pacjenta
user_data = {}

# 1. START - Menu wyboru
@bot.message_handler(commands=['start'])
def start(message):
    chat_id = message.chat.id
    user_data[chat_id] = {} # Reset sesji
    
    markup = InlineKeyboardMarkup(row_width=1) # Układ: 1 przycisk na wiersz (wygląda czytelniej)
    
    # Generowanie przycisków na podstawie bazy produktów
    for key, data in PRODUCTS.items():
        btn_text = f"💊 {data['name']} ({data['qty']}) - {data['price_pln']} PLN"
        markup.add(InlineKeyboardButton(btn_text, callback_data=f"item_{key}"))
        
    bot.send_message(
        chat_id, 
        "Witaj w systemie! Wybierz pozycję, o którą wnioskujesz:", 
        reply_markup=markup
    )

# 2. WYBÓR LEKU I PROŚBA O TELEFON
@bot.callback_query_handler(func=lambda call: call.data.startswith('item_'))
def ask_phone(call):
    chat_id = call.message.chat.id
    item_key = call.data.split('_')[1]
    
    # Zapisujemy wybrany produkt w pamięci dla danego użytkownika
    user_data[chat_id]['product'] = PRODUCTS[item_key]
    
    # Tworzymy klawiaturę do szybkiego wysłania numeru
    markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    btn_phone = KeyboardButton("📱 Udostępnij swój numer telefonu", request_contact=True)
    markup.add(btn_phone)
    
    bot.delete_message(chat_id, call.message.message_id)
    bot.send_message(
        chat_id, 
        f"Wybrałeś: **{PRODUCTS[item_key]['name']}**.\n\nNa jaki numer telefonu ma zostać przypisana recepta? Udostępnij kontakt przyciskiem poniżej lub wpisz go ręcznie:", 
        parse_mode="Markdown", 
        reply_markup=markup
    )

# 3. PODSUMOWANIE WNIOSKU I PŁATNOŚĆ W TON
@bot.message_handler(content_types=['contact', 'text'])
def process_payment(message):
    chat_id = message.chat.id
    
    # Ignorowanie losowych wiadomości, jeśli ktoś nie zaczął od /start
    if chat_id not in user_data or 'product' not in user_data[chat_id]:
        if message.text != '/start':
            bot.send_message(chat_id, "Wpisz /start, aby rozpocząć od nowa.", reply_markup=ReplyKeyboardRemove())
        return

    # Pobieranie numeru telefonu
    if message.contact:
        telefon = message.contact.phone_number
    else:
        telefon = message.text
        
    product = user_data[chat_id]['product']
    
    # Obliczanie ceny w TON
    price_ton = round(product['price_pln'] / TON_PLN_RATE, 2)
    
    # Konstruowanie podsumowania
    podsumowanie = (
        f"📋 *PODSUMOWANIE WNIOSKU*\n\n"
        f"💊 **Pozycja:** {product['name']}\n"
        f"📦 **Ilość:** {product['qty']}\n"
        f"📞 **Telefon:** {telefon}\n"
        f"💵 **Kwota (PLN):** {product['price_pln']} PLN\n\n"
        f"💎 *Do zapłaty w krypto: ~{price_ton} TON*\n\n"
        f"Aby sfinalizować zamówienie, prześlij wymaganą kwotę w sieci TON na adres portfela, a następnie wyślij zrzut ekranu potwierdzający przelew."
    )
    
    markup = InlineKeyboardMarkup()
    # Przycisk może prowadzić bezpośrednio do portfela (URI dla sieci TON) lub instrukcji
    # Tu wstawiasz swój adres portfela, np. ton://transfer/TWÓJ_ADRES
    markup.add(InlineKeyboardButton("💎 ZAPŁAĆ W TON", url="https://tonkeeper.com/")) 
    
    # Usuwamy dolną klawiaturę proszącą o telefon i wysyłamy rachunek
    bot.send_message(chat_id, "Generowanie podsumowania...", reply_markup=ReplyKeyboardRemove()).delete()
    bot.send_message(chat_id, podsumowanie, parse_mode="Markdown", reply_markup=markup)
    
    # Czyścimy sesję (jeśli pacjent chce złożyć nowe zamówienie, wpisze znów /start)
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
