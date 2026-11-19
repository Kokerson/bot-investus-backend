import os
import sys
import time
import requests
import yfinance as yf
from supabase import create_client

# ================= KONFIGURACJA =================
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = "gemini-3.5-flash-lite"
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
# ================================================

def check_env():
    missing = []
    for var_name, val in [
        ("SUPABASE_URL", SUPABASE_URL),
        ("SUPABASE_KEY", SUPABASE_KEY),
        ("GEMINI_API_KEY", GEMINI_API_KEY),
        ("TELEGRAM_TOKEN", TELEGRAM_TOKEN),
        ("TELEGRAM_CHAT_ID", TELEGRAM_CHAT_ID),
    ]:
        if not val:
            missing.append(var_name)
    if missing:
        print(f"BŁĄD: Brakujące zmienne środowiskowe: {', '.join(missing)}")
        sys.exit(1)

def get_usd_to_pln():
    try:
        res = requests.get("https://api.nbp.pl/api/exchangerates/rates/a/usd/?format=json", timeout=10)
        if res.ok:
            data = res.json()
            rate = float(data["rates"][0]["mid"])
            print(f"   -> Pobrano kurs USD/PLN z NBP: {rate:.4f} zł")
            return rate
    except Exception as e:
        print(f"   -> Ostrzeżenie: Błąd pobierania kursu USD z NBP ({e}), używam kursu 4.00 zł")
    return 4.00

def get_stock_price(ticker):
    try:
        stock = yf.Ticker(ticker)
        price = stock.fast_info.get("last_price")
        if price is not None and price > 0:
            return float(price)
        hist = stock.history(period="5d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception as e:
        print(f"   -> Błąd yfinance dla {ticker}: {e}")
    return None

def main():
    check_env()

    print("1. Pobieranie danych i portfela z bazy...")
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    response = supabase.table("portfolio").select("*").execute()
    portfolio = response.data

    if not portfolio:
        print("Portfel jest pusty! Dodaj akcje w aplikacji webowej.")
        return

    usd_to_pln = get_usd_to_pln()

    print("2. Sprawdzanie aktualnych cen na giełdzie i obliczanie wartości...")
    portfolio_data_for_ai = []
    total_pln = 0.0

    for item in portfolio:
        ticker = item.get("ticker", "").upper()
        qty = float(item.get("quantity") or 0)
        buy_price = float(item.get("buy_price") or 0)
        currency = (item.get("currency") or "PLN").upper()

        current_price = get_stock_price(ticker)
        if current_price is None or current_price <= 0:
            print(f"   -> [Ostrzeżenie] Brak ceny giełdowej dla {ticker}, używam ceny zakupu ({buy_price})")
            current_price = buy_price

        rate = usd_to_pln if currency == "USD" else 1.0
        item_val_pln = round(qty * current_price * rate, 2)
        invested_pln = round(qty * buy_price * rate, 2)
        profit_loss_pct = round(((current_price - buy_price) / buy_price * 100), 2) if buy_price > 0 else 0.0

        total_pln += item_val_pln

        portfolio_data_for_ai.append({
            "Aktywo": ticker,
            "Ilość": qty,
            "Cena zakupu": buy_price,
            "Aktualna cena": round(current_price, 2),
            "Waluta": currency,
            "Wycena (PLN)": item_val_pln,
            "Koszt (PLN)": invested_pln,
            "Wynik (%)": profit_loss_pct
        })
        print(f"   -> {ticker}: {qty} szt. @ {current_price:.2f} {currency} = {item_val_pln:.2f} PLN ({profit_loss_pct:+g}%)")

    total_pln = round(total_pln, 2)
    print(f"\nŁączna aktualna wartość portfela: {total_pln:.2f} PLN")

    # 3. Zapis do bazy Supabase w tabeli portfolio_history
    print("3. Zapisywanie punktu historii do Supabase (portfolio_history)...")
    try:
        supabase.table("portfolio_history").insert({
            "total_pln": total_pln
        }).execute()
        print(f"   -> Zapisano pomyślnie: {total_pln} PLN")
    except Exception as e:
        print(f"   -> [BŁĄD] Nie udało się zapisać do portfolio_history: {e}")

    # 4. Analiza przez Gemini AI
    print(f"4. Generowanie analizy przez AI ({GEMINI_MODEL})...")
    prompt = f"""
Jesteś profesjonalnym doradcą inwestycyjnym dla prywatnego inwestora.
Aktualna data analizy i kurs USD/PLN: {usd_to_pln:.4f} zł.
Całkowita wartość portfela: {total_pln:.2f} PLN.

Szczegóły pozycji w portfelu:
{portfolio_data_for_ai}

Napisz zwięzły, konkretny raport tygodniowy w formacie Markdown dla komunikatora Telegram:
1. 📊 Podsumowanie portfela: łączna wartość ({total_pln:.2f} PLN), szacowany zysk/strata, najmocniejsze i najsłabsze pozycje.
2. 🔍 Krótki komentarz rynkowy dla głównych spółek w portfelu.
3. 💡 2 konkretne okazje rynkowe z innych sektorów do rozważenia z krótkim uzasadnieniem.

Pisz rzeczowo, bez zbędnych wstępów, używaj czytelnych punktorów i emoji.
"""

    raport = None
    max_retries = 3
    gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    gemini_payload = {
        "contents": [{"parts": [{"text": prompt}]}]
    }

    for attempt in range(max_retries):
        try:
            print(f"   -> Zapytanie do AI (próba {attempt + 1}/{max_retries})...")
            res = requests.post(gemini_url, json=gemini_payload, timeout=60)
            if res.status_code == 200:
                data = res.json()
                parts = data.get('candidates', [{}])[0].get('content', {}).get('parts', [])
                raport = "".join(p.get('text', '') for p in parts if not p.get('thought', False)).strip()
                if not raport:
                    raport = "".join(p.get('text', '') for p in parts).strip()
                print("   -> Raport wygenerowany pomyślnie!")
                break
            elif res.status_code in [429, 503]:
                print(f"   -> Limit zapytań / serwery zajęte ({res.status_code}). Czekam 15s...")
                time.sleep(15)
            else:
                print(f"   -> Błąd Gemini API: {res.status_code} - {res.text}")
                break
        except requests.exceptions.Timeout:
            print("   -> Upłynął limit czasu (60s).")
            if attempt < max_retries - 1:
                time.sleep(10)
        except Exception as e:
            print(f"   -> Błąd sieci: {e}")
            break

    if not raport:
        print("Nie udało się wygenerować raportu AI. Zakończono.")
        return

    # 5. Wysyłka raportu na Telegram
    print("5. Wysyłanie raportu na Telegram...")
    telegram_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    # Telegram ma limit 4096 znaków na wiadomość
    if len(raport) > 4000:
        raport = raport[:3990] + "\n\n[...obcięto ze względu na limit znaków...]"

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": raport,
        "parse_mode": "Markdown"
    }

    try:
        res_tg = requests.post(telegram_url, json=payload, timeout=15)
        # Fallback na czysty tekst jeśli formatowanie Markdown zawierało niedozwolone znaki
        if res_tg.status_code != 200:
            print(f"   -> Telegram odrzucił Markdown ({res_tg.status_code}). Ponawiam bez formatowania...")
            payload.pop("parse_mode", None)
            res_tg = requests.post(telegram_url, json=payload, timeout=15)

        if res_tg.status_code == 200:
            print("SUKCES! Raport został wysłany na Twój telefon.")
        else:
            print(f"Błąd wysyłania na Telegram: {res_tg.status_code} - {res_tg.text}")
    except Exception as e:
        print(f"Błąd połączenia z Telegramem: {e}")

if __name__ == "__main__":
    main()
