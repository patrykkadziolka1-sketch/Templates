import telebot
import os
import threading
import time
from flask import Flask, render_template, request, jsonify
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

# KONFIGURACJA
TOKEN = "8779022539:AAEiKsz2R3s-_kh6cQvDCQPrHl1os8dChpw"
URL_STRONY = "https://bot-production-e8ce.up.railway.app" 

bot = telebot.TeleBot(TOKEN)

# POPRAWKA CHMURY: Wymuszamy na Flasku bezwzględną ścieżkę do folderu templates
base_dir = os.path.dirname(os.path.abspath(__file__))
template_dir = os.path.join(base_dir, 'templates')
app = Flask(__name__, template_folder=template_dir)

wnioski = []

@app.route('/')
def home(): 
    return "Serwer Aktywny - Receptomat"

@app.route('/patient')
def patient(): 
    return render_template('patient.html')

@app.route('/doctor')
def doctor(): 
    return render_template('doctor.html')

@app.route('/api/apply', methods=['POST'])
def apply():
    data = request.json
    if not data:
        return jsonify({"success": False, "error": "Brak danych"}), 400
    data['id'] = len(wnioski) + 1
    data['status'] = 'pending'
    wnioski.append(data)
    return jsonify({"success": True})

@app.route('/api/requests')
def get_reqs(): 
    return jsonify(wnioski)

@app.route('/api/approve', methods=['POST'])
def approve():
    data = request.json
    for w in wnioski:
        if w['id'] == int(data['id']):
            w['status'] = 'approved'
            bot.send_message(w['chatId'], f"✅ Recepta wystawiona! Kod: {data['code']}")
    return jsonify({"success": True})

@bot.message_handler(commands=['start'])
def start(message):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🚀 WYSTAW RECEPTĘ", web_app=WebAppInfo(url=f"{URL_STRONY}/patient")))
    bot.send_message(message.chat.id, "Witaj w systemie! Kliknij przycisk poniżej, aby wypełnić formularz medyczny:", reply_markup=markup)

def run_flask():
    import logging
    log = logging.getLogger('werkzeug')
    log.disabled = True
    
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

if __name__ == "__main__":
    print("Uruchamianie serwera...")
    threading.Thread(target=run_flask, daemon=True).start()
    time.sleep(1)
    
    print("Czyszczenie starych blokad Telegrama...")
    bot.remove_webhook()
    
    print("✅ Bot jest AKTYWNY!")
    bot.infinity_polling()
