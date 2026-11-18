import os
import yfinance as yf
import requests
from supabase import create_client
import time

# ================= KONFIGURACJA =================
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = "gemini-3.5-flash-lite"
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
# ================================================

print("1. Pobieranie portfela z bazy...")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
response = supabase.table("portfolio").select("*").execute()
portfolio = response.data

if not portfolio:
    print("Portfel jest pusty! Dodaj akcje w aplikacji React.")
    exit()

print("2. Sprawdzanie aktualnych cen na giełdzie...")
portfolio_data_for_ai = []
for item in portfolio:
    ticker = item['ticker']
    try:
        stock = yf.Ticker(ticker)
        current_price = stock.fast_info['last_price']
        portfolio_data_for_ai.append({
            "Aktywo": ticker,
            "Ilość": item['quantity'],
            "Cena zakupu": item['buy_price'],
            "Aktualna cena": round(current_price, 2),
            "Waluta": item['currency']
        })
        print(f"   -> Pobrano cenę dla {ticker}: {current_price}")
    except Exception as e:
        print(f"   -> Błąd pobierania ceny dla {ticker}: {e}")

print("3. Analiza przez sztuczną inteligencję (Gemini)...")
prompt = f"""
Jesteś profesjonalnym doradcą inwestycyjnym. Poniżej znajduje się mój obecny portfel akcji:
{portfolio_data_for_ai}

Napisz zwięzły raport inwestycyjny w formacie Markdown, który wyślę na komunikator. 
Raport ma zawierać:
1. Szybkie podsumowanie mojego portfela (zysk/strata).
2. Krótkie prognozy dla głównych spółek w moim portfelu.
3. Okazje Rynkowe: 2 konkretne spółki z innych sektorów do kupienia.
Pisz zwięźle, bez lania wody.
"""

raport = None
max_retries = 2

# Bezpośrednie uderzenie w API z pominięciem biblioteki google-genai
gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
gemini_payload = {
    "contents": [{"parts": [{"text": prompt}]}]
}

for attempt in range(max_retries):
    try:
        print(f"   -> Wysyłanie zapytania do AI [{GEMINI_MODEL}] (próba {attempt + 1}/{max_retries})...")
        
        # Czyste połączenie HTTP (bezpieczny limit 60 sekund)
        res = requests.post(gemini_url, json=gemini_payload, timeout=60)
        
        if res.status_code == 200:
            data = res.json()
            parts = data['candidates'][0]['content'].get('parts', [])
            raport = "".join(p.get('text', '') for p in parts if not p.get('thought', False)).strip()
            if not raport:
                raport = "".join(p.get('text', '') for p in parts).strip()
            print("   -> Otrzymano gotowy raport od AI!")
            break
        elif res.status_code in [503, 429]:
            print(f"   -> Serwery zajęte (Błąd {res.status_code}). Czekam 15 sekund...")
            time.sleep(15)
        else:
            print(f"   -> Nieoczekiwany błąd API: {res.status_code} - {res.text}")
            break
            
    except requests.exceptions.Timeout:
        print("   -> Upłynął limit czasu (60s).")
        if attempt < max_retries - 1:
            print("   -> Czekam 15 sekund przed kolejną próbą...")
            time.sleep(15)
    except Exception as e:
        print(f"   -> Inny błąd sieci: {e}")
        break

if raport:
    print("4. Wysyłanie wiadomości na Telegram...")
    telegram_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": raport,
        "parse_mode": "Markdown"
    }

    try:
        res_tg = requests.post(telegram_url, json=payload, timeout=15)
        if res_tg.status_code == 200:
            print("SUKCES! Raport został wysłany na Twój telefon.")
        else:
            print(f"Błąd wysyłania na Telegram. Kod: {res_tg.status_code}, Szczegóły: {res_tg.text}")
    except Exception as e:
        print(f"Błąd połączenia z Telegramem: {e}")
else:
    print("Skrypt przerwany: Nie udało się wygenerować raportu.")