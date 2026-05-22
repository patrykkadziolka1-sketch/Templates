import telebot
import os
import threading
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from flask import Flask

TOKEN = "8779022539:AAEiKsz2R3s-_kh6cQvDCQPrHl1os8dChpw"
bot = telebot.TeleBot(TOKEN)

# Słownik do przechowywania danych sesji pacjentów (kto, co wybrał)
user_data = {}

# 1. START - Wybór leku
@bot.message_handler(commands=['start'])
def start(message):
    chat_id = message.chat.id
    user_data[chat_id] = {} # Resetujemy dane dla nowej sesji
    
    markup = InlineKeyboardMarkup()
    # Tutaj możesz dodać własne nazwy leków
    markup.add(InlineKeyboardButton("💊 Medyczna Marihuana", callback_data="lek_Medyczna Marihuana"))
    markup.add(InlineKeyboardButton("💊 Ozempic", callback_data="lek_Ozempic"))
    markup.add(InlineKeyboardButton("💊 Medikinet", callback_data="lek_Medikinet"))
    
    bot.send_message(chat_id, "Witaj w Receptomacie! Wybierz lek, o który wnioskujesz:", reply_markup=markup)

# 2. WYBÓR ILOŚCI
@bot.callback_query_handler(func=lambda call: call.data.startswith('lek_'))
def ask_quantity(call):
    chat_id = call.message.chat.id
    wybrany_lek = call.data.split('_')[1] # Wyciągamy nazwę leku z przycisku
    user_data[chat_id]['lek'] = wybrany_lek
    
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("1 op.", callback_data="ilosc_1"),
        InlineKeyboardButton("2 op.", callback_data="ilosc_2"),
        InlineKeyboardButton("3 op.", callback_data="ilosc_3")
    )
    
    # Edytujemy poprzednią wiadomość, aby czat był czysty
    bot.edit_message_text(f"Wybrałeś: **{wybrany_lek}**.\n\nIle opakowań potrzebujesz?", chat_id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

# 3. NUMER TELEFONU
@bot.callback_query_handler(func=lambda call: call.data.startswith('ilosc_'))
def ask_phone(call):
    chat_id = call.message.chat.id
    ilosc = call.data.split('_')[1]
    user_data[chat_id]['ilosc'] = ilosc
    
    # Klawiatura systemowa Telegrama prosząca o udostępnienie numeru
    markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    btn_phone = KeyboardButton("📱 Udostępnij swój numer", request_contact=True)
    markup.add(btn_phone)
    
    bot.delete_message(chat_id, call.message.message_id) # Usuwamy starą wiadomość z przyciskami
    bot.send_message(chat_id, "Prawie gotowe! Udostępnij swój numer telefonu (kliknij przycisk poniżej) lub wpisz go ręcznie:", reply_markup=markup)

# 4. PODSUMOWANIE I PŁATNOŚĆ
@bot.message_handler(content_types=['contact', 'text'])
def process_payment(message):
    chat_id = message.chat.id
    
    # Blokada - jeśli ktoś coś wpisze poza procesem
    if chat_id not in user_data or 'ilosc' not in user_data[chat_id]:
        if message.text != '/start':
            bot.send_message(chat_id, "Wpisz /start, aby rozpocząć od nowa.", reply_markup=ReplyKeyboardRemove())
        return

    # Pobieramy telefon z systemowego kontaktu lub z tekstu wpisanego z palca
    if message.contact:
        telefon = message.contact.phone_number
    else:
        telefon = message.text
        
    user_data[chat_id]['telefon'] = telefon
    
    lek = user_data[chat_id].get('lek')
    ilosc = user_data[chat_id].get('ilosc')
    
    # Generujemy podsumowanie
    podsumowanie = (
        f"📋 *PODSUMOWANIE WNIOSKU*\n\n"
        f"💊 Lek: {lek}\n"
        f"📦 Ilość: {ilosc} szt.\n"
        f"📞 Telefon: {telefon}\n\n"
        f"💰 *Do zapłaty: 89.00 PLN*\n\n"
        f"Opłać zamówienie, aby lekarz mógł zająć się Twoim wnioskiem."
    )
    
    markup = InlineKeyboardMarkup()
    # Tu wstawisz swój prawdziwy link do płatności, np. Stripe, PayU, BLIK
    markup.add(InlineKeyboardButton("💳 OPŁAĆ ZAMÓWIENIE", url="https://google.com")) 
    
    # Ukrywamy starą klawiaturę proszącą o telefon
    bot.send_message(chat_id, "Ukrywanie klawiatury...", reply_markup=ReplyKeyboardRemove()).delete()
    # Wysyłamy finalną wiadomość z linkiem do zapłaty
    bot.send_message(chat_id, podsumowanie, parse_mode="Markdown", reply_markup=markup)


# --- DUMMY FLASK (Tylko po to, żeby Railway nie ubił aplikacji) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Serwer bota działa w tle."

def run_flask():
    import logging
    log = logging.getLogger('werkzeug')
    log.disabled = True
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

if __name__ == "__main__":
    print("Uruchamianie serwera dla Railway...")
    threading.Thread(target=run_flask, daemon=True).start()
    
    print("Czyszczenie Webhooków...")
    bot.remove_webhook()
    
    print("✅ Bot konwersacyjny jest gotowy!")
    bot.infinity_polling()
