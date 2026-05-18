import telebot
import os
import threading
from flask import Flask, render_template, request, jsonify
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

# KONFIGURACJA
TOKEN = "8779022539:AAEiKsz2R3s-_kh6cQvDCQPrHl1os8dChpw"
# TUTAJ WKLEJ ADRES Z RAILWAY (z kroku 1)
URL_STRONY = "https://bot-production-e8ce.up.railway.app" 

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)
wnioski = []

@app.route('/')
def home(): return "Serwer Aktywny"

@app.route('/patient')
def patient(): return render_template('patient.html')

@app.route('/doctor')
def doctor(): return render_template('doctor.html')

@app.route('/api/apply', methods=['POST'])
def apply():
    data = request.json
    data['id'] = len(wnioski) + 1
    data['status'] = 'pending'
    wnioski.append(data)
    return jsonify({"success": True})

@app.route('/api/requests')
def get_reqs(): return jsonify(wnioski)

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
    bot.send_message(message.chat.id, "Witaj w Receptomacie!", reply_markup=markup)

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))

if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    bot.infinity_polling()