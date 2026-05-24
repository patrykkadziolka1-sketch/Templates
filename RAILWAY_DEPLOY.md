# Railway deploy (gotowiec)

## 1) Pliki
Projekt jest gotowy do startu:
- `bot.py` (entrypoint)
- `telegram_bot.py` (logika bota)
- `requirements.txt` (zależności)
- `Procfile` (`web: python bot.py`)

## 2) Variables w Railway
W `Service -> Variables` ustaw:

- `TELEGRAM_BOT_TOKEN` = token z BotFather
- `TON_PLN_RATE` = `7.00`
- `STARS_PER_PLN` = np. `10`
- `TON_WALLET` = Twój adres TON
- `SUPPORT_CONTACT_URL` = np. `https://t.me/twoj_support`
- `BTC_ADDRESS` = `bc1...`
- `LTC_ADDRESS` = `ltc1...`
- `SOL_ADDRESS` = `E8v...`
- `ADMIN_IDS` = np. `123456789,987654321`
- `PORT` = `5000` (opcjonalnie, Railway zwykle ustawia sam)
- `BOT_DB_PATH` = `bot_data.sqlite3`

Opcjonalnie:
- `TOKEN` = ten sam token co `TELEGRAM_BOT_TOKEN` (fallback)

## 3) Start command
Jeśli Railway nie czyta `Procfile`, ustaw ręcznie Start Command:

`python bot.py`

## 4) Ważne
Jeśli token był publicznie pokazany, wygeneruj nowy w BotFather i podmień w Railway.
