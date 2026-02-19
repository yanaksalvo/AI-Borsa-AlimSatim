# -*- coding: utf-8 -*-
"""
Borsa AlSat Bot — Tam Otomasyon
AI destekli Binance kripto alım-satım botu. Dashboard: durum, bakiye, grafik, log.
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import sqlite3
import json
import os
import re
import threading
import time
from datetime import datetime, timedelta

# Matplotlib
try:
    import matplotlib
    matplotlib.use("TkAgg")
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    from tradingview_ta import TA_Handler
    HAS_TA = True
except ImportError:
    HAS_TA = False

# ==================== Config & DB ====================
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "borsa_ayarlar.json")
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "borsa.db")

BINANCE_BASE = "https://api.binance.com"
ZAMAN_DILIMLERI = ["15m", "1h", "4h"]
SEMBOL_LISTESI = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "SOLUSDT", "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT"]


def load_config():
    default = {
        "binance_api_key": "",
        "binance_api_secret": "",
        "openrouter_api_key": "",
        "ai_model": "anthropic/claude-3.5-sonnet",
        "risk_pct": 2,
        "max_pozisyon": 3,
        "tarama_araligi_sn": 120,
        "min_ai_guven": 7,
        "take_profit_pct": 3,
        "stop_loss_pct": -2,
        "discord_webhook": "",
        "telegram_bot_token": "",
        "telegram_chat_id": "",
    }
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                default.update(data)
        except Exception:
            pass
    return default


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def discord_webhook_gonder(webhook_url, baslik, mesaj, renk=3447003):
    """Discord webhook'a mesaj gönder. renk: 3066993=yeşil, 15158332=kırmızı, 16776960=sarı."""
    if not HAS_REQUESTS or not webhook_url or not webhook_url.strip():
        return
    try:
        body = {
            "embeds": [{
                "title": str(baslik)[:256],
                "description": str(mesaj)[:4096],
                "color": int(renk),
                "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            }]
        }
        requests.post(webhook_url.strip(), json=body, timeout=5)
    except Exception:
        pass


def telegram_gonder(bot_token, chat_id, mesaj, parse_mode="HTML"):
    """Telegram Bot API ile mesaj gönder."""
    if not HAS_REQUESTS or not bot_token or not chat_id:
        return
    try:
        url = f"https://api.telegram.org/bot{bot_token.strip()}/sendMessage"
        body = {"chat_id": chat_id.strip(), "text": str(mesaj)[:4096], "parse_mode": parse_mode}
        requests.post(url, json=body, timeout=5)
    except Exception:
        pass


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tarih_saat TEXT,
            tip TEXT,
            mesaj TEXT,
            detay TEXT
        )
    """)
    conn.commit()
    conn.close()


# ==================== Binance API ====================
def binance_imzali_istek(api_key, api_secret, method, endpoint, params=None):
    if not api_key or not api_secret:
        return None
    try:
        import hmac
        import hashlib
        import urllib.parse
        params = dict(params or {})
        params["timestamp"] = int(time.time() * 1000)
        query = urllib.parse.urlencode(params)
        imza = hmac.new(api_secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()
        params["signature"] = imza
        url = f"{BINANCE_BASE}{endpoint}"
        if method == "GET":
            r = requests.get(url, params=params, headers={"X-MBX-APIKEY": api_key}, timeout=15)
        else:
            r = requests.post(url, params=params, headers={"X-MBX-APIKEY": api_key}, timeout=15)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def binance_bakiye(api_key, api_secret):
    if not HAS_REQUESTS:
        return None, []
    data = binance_imzali_istek(api_key, api_secret, "GET", "/api/v3/account")
    if not data or "balances" not in data:
        return None, []
    usdt = 0.0
    for b in data["balances"]:
        if b.get("asset") == "USDT":
            usdt = float(b.get("free", 0) or 0) + float(b.get("locked", 0) or 0)
            break
    return usdt, data.get("balances", [])


def binance_fiyat(sembol):
    if not HAS_REQUESTS:
        return None
    try:
        r = requests.get(f"{BINANCE_BASE}/api/v3/ticker/price", params={"symbol": sembol}, timeout=5)
        if r.status_code == 200:
            return float(r.json().get("price", 0))
    except Exception:
        pass
    return None


def binance_24h_ticker(sembol):
    if not HAS_REQUESTS:
        return None
    try:
        r = requests.get(f"{BINANCE_BASE}/api/v3/ticker/24hr", params={"symbol": sembol}, timeout=5)
        if r.status_code == 200:
            d = r.json()
            high = float(d.get("highPrice", 0) or 0)
            low = float(d.get("lowPrice", 0) or 0)
            return {
                "priceChangePercent": float(d.get("priceChangePercent", 0) or 0),
                "volume": float(d.get("volume", 0) or 0),
                "quoteVolume": float(d.get("quoteVolume", 0) or 0),
                "lastPrice": float(d.get("lastPrice", 0) or 0),
                "highPrice": high,
                "lowPrice": low,
            }
    except Exception:
        pass
    return None


def fibonacci_seviyeleri(high, low):
    """24h high/low ile Fibonacci düzeltme seviyeleri."""
    if not high or not low or high <= low:
        return {}
    diff = high - low
    return {
        "fib_0": round(high, 2),
        "fib_236": round(high - 0.236 * diff, 2),
        "fib_382": round(high - 0.382 * diff, 2),
        "fib_50": round(high - 0.5 * diff, 2),
        "fib_618": round(high - 0.618 * diff, 2),
        "fib_786": round(high - 0.786 * diff, 2),
        "fib_100": round(low, 2),
    }


def binance_spot_emir(api_key, api_secret, sembol, side, quantity, order_type="MARKET"):
    if not api_key or not api_secret:
        return False, "API yok"
    params = {"symbol": sembol, "side": side, "type": order_type, "quantity": quantity}
    data = binance_imzali_istek(api_key, api_secret, "POST", "/api/v3/order", params)
    if data and "orderId" in data:
        return True, data
    return False, data or "Emir hatası"


def binance_gelismis_analiz(sembol):
    """
    Profesyonel seviye teknik analiz:
    Çoklu göstergeler (RSI, MACD, Stochastic, Bollinger, ATR, ADX),
    multi-timeframe confluence, destek/direnç, EMA/SMA, trend/momentum.
    """
    sonuc = {
        "sembol": sembol,
        "fiyat": None,
        "degisim_24h": 0,
        "hacim_24h": 0,
        "hacim_ortalama": 0,
        "volatilite": "normal",
        "rsi_15m": None, "rsi_1h": None, "rsi_4h": None,
        "macd_15m": None, "macd_1h": None, "macd_4h": None,
        "macd_hist_15m": None, "macd_hist_1h": None, "macd_hist_4h": None,
        "stoch_15m": None, "stoch_1h": None, "stoch_4h": None,
        "bb_position": None, "atr": None, "adx": None, "obv_trend": None,
        "ema_9": None, "ema_21": None, "ema_50": None, "ema_200": None,
        "sma_50": None, "sma_200": None,
        "golden_cross": False, "death_cross": False,
        "resistance_1": None, "resistance_2": None,
        "support_1": None, "support_2": None,
        "distance_to_resistance": 0, "distance_to_support": 0,
        "patterns": [],
        "sinyal_15m": "—", "sinyal_1h": "—", "sinyal_4h": "—", "sinyal_1d": "—",
        "trend_genel": "nötr", "momentum": "nötr",
        "fiyat_1h_degisim": 0, "fiyat_4h_degisim": 0,
        "hacim_anomali": False, "overbought": False, "oversold": False,
        "rsi": None, "macd": None, "macd_hist": None, "hacim": "normal", "trend": "—",
        "fib_0": None, "fib_236": None, "fib_382": None, "fib_50": None, "fib_618": None, "fib_786": None, "fib_100": None,
        "pivot": None,
    }
    fiyat = binance_fiyat(sembol)
    if fiyat:
        sonuc["fiyat"] = fiyat
    ticker = binance_24h_ticker(sembol)
    if ticker:
        sonuc["degisim_24h"] = ticker.get("priceChangePercent", 0)
        sonuc["hacim_24h"] = ticker.get("volume", 0)
        sonuc["quote_volume_24h"] = ticker.get("quoteVolume", 0)
        high = ticker.get("highPrice")
        low = ticker.get("lowPrice")
        if high and low:
            fib = fibonacci_seviyeleri(high, low)
            sonuc.update(fib)
            sonuc["pivot"] = round((high + low + fiyat) / 3, 2) if fiyat else round((high + low) / 2, 2)
    if not HAS_TA or not fiyat:
        return sonuc
    try:
        for iv in ["15m", "1h", "4h", "1d"]:
            try:
                tv = TA_Handler(symbol=sembol, screener="crypto", exchange="BINANCE", interval=iv)
                a = tv.get_analysis()
                if not a:
                    continue
                if a.summary:
                    rec = a.summary.get("RECOMMENDATION", "NEUTRAL")
                    sinyal = "AL" if rec in ["STRONG_BUY", "BUY"] else "SAT" if rec in ["STRONG_SELL", "SELL"] else "BEKLE"
                    sonuc[f"sinyal_{iv}"] = sinyal
                if getattr(a, "indicators", None) and a.indicators:
                    ind = a.indicators
                    if "RSI" in ind and ind["RSI"]:
                        val = round(float(ind["RSI"]), 1)
                        sonuc[f"rsi_{iv}"] = val
                        if iv == "1h":
                            sonuc["rsi"] = val
                            if val > 70:
                                sonuc["overbought"] = True
                            elif val < 30:
                                sonuc["oversold"] = True
                    if "MACD.macd" in ind and ind["MACD.macd"]:
                        sonuc[f"macd_{iv}"] = round(float(ind["MACD.macd"]), 4)
                        if iv == "1h":
                            sonuc["macd"] = sonuc[f"macd_{iv}"]
                    if "MACD.signal" in ind and ind["MACD.signal"]:
                        sig = float(ind["MACD.signal"])
                        if sonuc.get(f"macd_{iv}") is not None:
                            sonuc[f"macd_hist_{iv}"] = round(sonuc[f"macd_{iv}"] - sig, 4)
                            if iv == "1h":
                                sonuc["macd_hist"] = sonuc[f"macd_hist_{iv}"]
                    if "Stoch.K" in ind and ind["Stoch.K"]:
                        sonuc[f"stoch_{iv}"] = round(float(ind["Stoch.K"]), 1)
                    if iv == "1h":
                        if "BB.upper" in ind and "BB.lower" in ind and ind["BB.upper"] and ind["BB.lower"]:
                            bb_u, bb_l = float(ind["BB.upper"]), float(ind["BB.lower"])
                            if bb_u > bb_l:
                                sonuc["bb_position"] = round((fiyat - bb_l) / (bb_u - bb_l), 2)
                        if "ATR" in ind and ind["ATR"]:
                            sonuc["atr"] = round(float(ind["ATR"]), 2)
                        if "ADX" in ind and ind["ADX"]:
                            sonuc["adx"] = round(float(ind["ADX"]), 1)
                        for tv_key, out_key in [("EMA9", "ema_9"), ("EMA21", "ema_21"), ("EMA50", "ema_50"), ("EMA200", "ema_200"), ("SMA50", "sma_50"), ("SMA200", "sma_200")]:
                            if tv_key in ind and ind[tv_key]:
                                try:
                                    sonuc[out_key] = round(float(ind[tv_key]), 2)
                                except (TypeError, ValueError):
                                    pass
                        if sonuc.get("ema_50") and sonuc.get("ema_200"):
                            sonuc["golden_cross"] = sonuc["ema_50"] > sonuc["ema_200"]
                            sonuc["death_cross"] = sonuc["ema_50"] < sonuc["ema_200"]
            except Exception:
                continue
        al_say = sum(1 for k in ["sinyal_15m", "sinyal_1h", "sinyal_4h", "sinyal_1d"] if sonuc.get(k) == "AL")
        sat_say = sum(1 for k in ["sinyal_15m", "sinyal_1h", "sinyal_4h", "sinyal_1d"] if sonuc.get(k) == "SAT")
        if al_say >= 3:
            sonuc["trend_genel"] = "yükseliş"
        elif sat_say >= 3:
            sonuc["trend_genel"] = "düşüş"
        rsi_1h = sonuc.get("rsi_1h")
        macd_hist_1h = sonuc.get("macd_hist_1h")
        if rsi_1h is not None and macd_hist_1h is not None:
            if rsi_1h > 60 and macd_hist_1h > 0:
                sonuc["momentum"] = "güçlü_yükseliş"
            elif rsi_1h > 50 and macd_hist_1h > 0:
                sonuc["momentum"] = "yükseliş"
            elif rsi_1h < 40 and macd_hist_1h < 0:
                sonuc["momentum"] = "güçlü_düşüş"
            elif rsi_1h < 50 and macd_hist_1h < 0:
                sonuc["momentum"] = "düşüş"
        if fiyat:
            sonuc["support_1"] = round(fiyat * 0.98, 2)
            sonuc["support_2"] = round(fiyat * 0.95, 2)
            sonuc["resistance_1"] = round(fiyat * 1.02, 2)
            sonuc["resistance_2"] = round(fiyat * 1.05, 2)
            sonuc["distance_to_resistance"] = round((sonuc["resistance_1"] - fiyat) / fiyat * 100, 2)
            sonuc["distance_to_support"] = round((fiyat - sonuc["support_1"]) / fiyat * 100, 2)
        if sonuc.get("hacim_24h"):
            sonuc["hacim_ortalama"] = sonuc["hacim_24h"]
        if sonuc.get("atr") and fiyat:
            atr_pct = sonuc["atr"] / fiyat * 100
            if atr_pct > 3:
                sonuc["volatilite"] = "yüksek"
            elif atr_pct < 1:
                sonuc["volatilite"] = "düşük"
        if sonuc.get("rsi"):
            sonuc["trend"] = "yükseliş" if sonuc["rsi"] > 50 else "düşüş"
    except Exception:
        pass
    return sonuc


def binance_gelismis_tarama(semboller):
    """Gelişmiş scoring (100 üzerinden) ile en iyi alım adaylarını bul."""
    sonuclar = []
    for sembol in semboller:
        analiz = binance_gelismis_analiz(sembol)
        skor = 0
        al_say = sum(1 for k in ["sinyal_15m", "sinyal_1h", "sinyal_4h", "sinyal_1d"] if analiz.get(k) == "AL")
        skor += al_say * 10
        rsi_1h = analiz.get("rsi_1h")
        if rsi_1h is not None:
            if 40 < rsi_1h < 60:
                skor += 20
            elif 30 < rsi_1h < 70:
                skor += 10
            elif rsi_1h < 30:
                skor += 15
        if analiz.get("macd_hist_1h") and analiz["macd_hist_1h"] > 0:
            skor += 10
        if analiz.get("golden_cross"):
            skor += 10
        if analiz.get("adx") and analiz["adx"] > 25:
            skor += 10
        if analiz.get("momentum") in ["yükseliş", "güçlü_yükseliş"]:
            skor += 10
        if analiz.get("volatilite") == "yüksek":
            skor -= 5
        elif analiz.get("volatilite") == "düşük":
            skor += 5
        sonuclar.append((sembol, skor, analiz))
    sonuclar.sort(key=lambda x: -x[1])
    return sonuclar


# ==================== OpenRouter AI ====================
def openrouter_ask(api_key, model, prompt):
    if not HAS_REQUESTS or not api_key:
        return ""
    try:
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        body = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 800,
        }
        r = requests.post(url, json=body, headers=headers, timeout=60)
        if r.status_code == 200:
            data = r.json()
            if data.get("choices"):
                return data["choices"][0].get("message", {}).get("content", "") or ""
    except Exception:
        pass
    return ""


def parse_ai_alim_cevap(text):
    """Gelişmiş parser — KARAR, GÜVEN, STOP_LOSS, TAKE_PROFIT, RISK_REWARD, GİRİŞ_STRATEJİSİ, GEREKÇE, ALTERNATİF_SENARYO."""
    out = {
        "KARAR": "BEKLE", "GÜVEN": 0, "STOP_LOSS": None, "TAKE_PROFIT": None,
        "RISK_REWARD": None, "GİRİŞ_STRATEJİSİ": "", "GEREKÇE": "", "ALTERNATİF_SENARYO": "",
    }
    if not text:
        return out
    for k in ["AL", "BEKLE", "ALMA"]:
        if re.search(r"KARAR\s*:\s*" + k, text, re.I):
            out["KARAR"] = k
            break
    m = re.search(r"GÜVEN\s*:\s*(\d+)", text, re.I)
    if m:
        out["GÜVEN"] = min(10, max(0, int(m.group(1))))
    m = re.search(r"STOP[_ ]?LOSS\s*:\s*([\d.,]+)", text, re.I)
    if m:
        try:
            out["STOP_LOSS"] = float(m.group(1).replace(",", "").replace(" ", ""))
        except ValueError:
            pass
    m = re.search(r"TAKE[_ ]?PROFIT\s*:\s*([\d.,]+)", text, re.I)
    if m:
        try:
            out["TAKE_PROFIT"] = float(m.group(1).replace(",", "").replace(" ", ""))
        except ValueError:
            pass
    m = re.search(r"RISK[_ ]?REWARD\s*:\s*1\s*:\s*([\d.]+)", text, re.I)
    if m:
        out["RISK_REWARD"] = f"1:{m.group(1)}"
    m = re.search(r"GİRİŞ[_ ]?STRATEJİSİ\s*:\s*(.+?)(?=\n[A-ZĞÜŞÖÇİ]+[_ ]?[A-ZĞÜŞÖÇİ]*\s*:|$)", text, re.S | re.I)
    if m:
        out["GİRİŞ_STRATEJİSİ"] = m.group(1).strip()[:150]
    m = re.search(r"GEREKÇE\s*:\s*(.+?)(?=\n[A-ZĞÜŞÖÇİ]+[_ ]?[A-ZĞÜŞÖÇİ]*\s*:|$)", text, re.S | re.I)
    if m:
        out["GEREKÇE"] = m.group(1).strip()[:300]
    m = re.search(r"ALTERNATİF[_ ]?SENARYO\s*:\s*(.+?)(?=\n[A-ZĞÜŞÖÇİ]+[_ ]?[A-ZĞÜŞÖÇİ]*\s*:|$)", text, re.S | re.I)
    if m:
        out["ALTERNATİF_SENARYO"] = m.group(1).strip()[:200]
    return out


def parse_ai_satim_cevap(text):
    """Gelişmiş satım parser — KARAR, GÜVEN, YENİ_SL, YENİ_TP, KISMİ_ORAN, GEREKÇE, RİSK_ANALİZİ, ALTERNATİF_PLAN."""
    out = {
        "KARAR": "BEKLE", "GÜVEN": 0, "YENİ_SL": None, "YENİ_TP": None, "KISMİ_ORAN": None,
        "GEREKÇE": "", "RİSK_ANALİZİ": "", "ALTERNATİF_PLAN": "",
    }
    if not text:
        return out
    for k in ["SAT", "KISMİ_SAT", "SL_GÜNCELLE", "BEKLE"]:
        if re.search(r"KARAR\s*:\s*" + k.replace("_", "[_ ]?"), text, re.I):
            out["KARAR"] = k
            break
    m = re.search(r"GÜVEN\s*:\s*(\d+)", text, re.I)
    if m:
        out["GÜVEN"] = min(10, max(0, int(m.group(1))))
    m = re.search(r"YENİ[_ ]?SL\s*:\s*([\d.,]+)", text, re.I)
    if m:
        try:
            out["YENİ_SL"] = float(m.group(1).replace(",", "").replace(" ", ""))
        except ValueError:
            pass
    m = re.search(r"YENİ[_ ]?TP\s*:\s*([\d.,]+)", text, re.I)
    if m:
        try:
            out["YENİ_TP"] = float(m.group(1).replace(",", "").replace(" ", ""))
        except ValueError:
            pass
    m = re.search(r"KISMİ[_ ]?ORAN\s*:\s*%?(\d+)", text, re.I)
    if m:
        out["KISMİ_ORAN"] = int(m.group(1))
    m = re.search(r"GEREKÇE\s*:\s*(.+?)(?=\n[A-ZĞÜŞÖÇİ]+[_ ]?[A-ZĞÜŞÖÇİ]*\s*:|$)", text, re.S | re.I)
    if m:
        out["GEREKÇE"] = m.group(1).strip()[:300]
    m = re.search(r"RİSK[_ ]?ANALİZİ\s*:\s*(.+?)(?=\n[A-ZĞÜŞÖÇİ]+[_ ]?[A-ZĞÜŞÖÇİ]*\s*:|$)", text, re.S | re.I)
    if m:
        out["RİSK_ANALİZİ"] = m.group(1).strip()[:200]
    m = re.search(r"ALTERNATİF[_ ]?PLAN\s*:\s*(.+?)(?=\n[A-ZĞÜŞÖÇİ]+[_ ]?[A-ZĞÜŞÖÇİ]*\s*:|$)", text, re.S | re.I)
    if m:
        out["ALTERNATİF_PLAN"] = m.group(1).strip()[:200]
    return out


# ==================== Ana Uygulama ====================
class BorsaAlSatBot:
    def __init__(self):
        init_db()
        self.config = load_config()
        self.root = tk.Tk()
        self.root.title("Borsa AlSat Bot — AI Otomatik Kripto")
        self.root.geometry("1200x750")
        self.root.minsize(900, 600)
        self.root.configure(bg="#0d1117")

        self.bot_aktif = False
        self.bot_thread = None
        self.acik_pozisyonlar = []
        self.bakiye_gecmisi = []
        self.chart_events = []
        self.son_islem_zamani = None
        self.baslangic_bakiye = None
        self.gunluk_kar = 0.0

        self._build_ui()
        self._log_db("Uygulama başlatıldı.", "sistem")
        self._bot_log("Bot hazır. Ayarları yapıp 'Bot Başlat' ile çalıştırın.", "info")

    def _build_ui(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".", background="#0d1117", foreground="#c9d1d9")
        style.configure("TNotebook", background="#0d1117")
        style.configure("TNotebook.Tab", background="#21262d", foreground="#c9d1d9", padding=[12, 6])
        style.map("TNotebook.Tab", background=[("selected", "#238636")], foreground=[("selected", "white")])
        style.configure("TFrame", background="#161b22")
        style.configure("TLabel", background="#161b22", foreground="#c9d1d9")
        style.configure("TLabelframe", background="#161b22", foreground="#58a6ff")
        style.configure("TButton", background="#21262d", foreground="#c9d1d9")
        style.map("TButton", background=[("active", "#30363d")])
        style.configure("TEntry", fieldbackground="#21262d", foreground="#c9d1d9")

        main = ttk.Frame(self.root, padding=10)
        main.pack(fill=tk.BOTH, expand=True)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)

        nb = ttk.Notebook(main)
        nb.pack(fill=tk.BOTH, expand=True)
        self._tab_dashboard(nb)
        self._tab_ayarlar(nb)
        self._tab_log(nb)

    def _tab_dashboard(self, nb):
        f = ttk.Frame(nb, padding=10)
        nb.add(f, text="Dashboard")
        f.columnconfigure(0, weight=1)
        f.rowconfigure(2, weight=1)

        # Üst: Bot kontrol butonları + 3 kart
        ust_satir = ttk.Frame(f)
        ust_satir.grid(row=0, column=0, sticky=tk.EW, pady=(0, 8))
        ust_satir.columnconfigure(1, weight=1)
        btn_frame = ttk.Frame(ust_satir)
        btn_frame.grid(row=0, column=0, sticky=tk.W, padx=(0, 15))
        ttk.Button(btn_frame, text="Bot Başlat", command=self._bot_baslat).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(btn_frame, text="Bot Durdur", command=self._bot_durdur).pack(side=tk.LEFT, padx=5)

        kartlar = ttk.Frame(f)
        kartlar.grid(row=1, column=0, sticky=tk.EW, pady=(0, 10))
        kartlar.columnconfigure(0, weight=1)
        kartlar.columnconfigure(1, weight=1)
        kartlar.columnconfigure(2, weight=1)

        self.kart_bot = tk.Frame(kartlar, bg="#21262d", relief=tk.RIDGE, bd=2)
        self.kart_bot.grid(row=0, column=0, sticky=tk.NSEW, padx=5, pady=5)
        tk.Label(self.kart_bot, text="BOT DURUMU", font=("Segoe UI", 9, "bold"), bg="#21262d", fg="#8b949e").pack(anchor=tk.W, padx=10, pady=(10, 2))
        self.lbl_bot_durum = tk.Label(self.kart_bot, text="● Kapalı", font=("Segoe UI", 12, "bold"), bg="#21262d", fg="#f85149")
        self.lbl_bot_durum.pack(anchor=tk.W, padx=10, pady=2)
        self.lbl_son_islem = tk.Label(self.kart_bot, text="Son işlem: —", font=("Segoe UI", 9), bg="#21262d", fg="#8b949e")
        self.lbl_son_islem.pack(anchor=tk.W, padx=10, pady=(0, 10))

        self.kart_bakiye = tk.Frame(kartlar, bg="#21262d", relief=tk.RIDGE, bd=2)
        self.kart_bakiye.grid(row=0, column=1, sticky=tk.NSEW, padx=5, pady=5)
        tk.Label(self.kart_bakiye, text="TOPLAM BAKİYE", font=("Segoe UI", 9, "bold"), bg="#21262d", fg="#8b949e").pack(anchor=tk.W, padx=10, pady=(10, 2))
        self.lbl_bakiye = tk.Label(self.kart_bakiye, text="$ —", font=("Segoe UI", 12, "bold"), bg="#21262d", fg="#c9d1d9")
        self.lbl_bakiye.pack(anchor=tk.W, padx=10, pady=2)
        self.lbl_gunluk_kar = tk.Label(self.kart_bakiye, text="Bugün: —", font=("Segoe UI", 9), bg="#21262d", fg="#8b949e")
        self.lbl_gunluk_kar.pack(anchor=tk.W, padx=10, pady=(0, 10))

        self.kart_pozisyon = tk.Frame(kartlar, bg="#21262d", relief=tk.RIDGE, bd=2)
        self.kart_pozisyon.grid(row=0, column=2, sticky=tk.NSEW, padx=5, pady=5)
        tk.Label(self.kart_pozisyon, text="AKTİF POZİSYON", font=("Segoe UI", 9, "bold"), bg="#21262d", fg="#8b949e").pack(anchor=tk.W, padx=10, pady=(10, 2))
        self.lbl_pozisyon_say = tk.Label(self.kart_pozisyon, text="0 adet", font=("Segoe UI", 12, "bold"), bg="#21262d", fg="#c9d1d9")
        self.lbl_pozisyon_say.pack(anchor=tk.W, padx=10, pady=2)
        self.lbl_en_karli = tk.Label(self.kart_pozisyon, text="En karlı: —", font=("Segoe UI", 9), bg="#21262d", fg="#8b949e")
        self.lbl_en_karli.pack(anchor=tk.W, padx=10, pady=(0, 10))

        # Orta: Grafik
        chart_frame = ttk.Frame(f)
        chart_frame.grid(row=2, column=0, sticky=tk.NSEW, pady=5)
        chart_frame.columnconfigure(0, weight=1)
        chart_frame.rowconfigure(0, weight=1)
        if HAS_MATPLOTLIB:
            self.chart_fig = Figure(figsize=(10, 3.5), dpi=100, facecolor="#161b22")
            self.chart_ax = self.chart_fig.add_subplot(111)
            self.chart_ax.set_facecolor("#21262d")
            self.chart_ax.tick_params(colors="#8b949e")
            self.chart_ax.set_title("Portföy Değeri (Son 24 Saat)", color="#c9d1d9", fontsize=10)
            self.chart_canvas = FigureCanvasTkAgg(self.chart_fig, master=chart_frame)
            self.chart_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
            self._grafik_ciz()
        else:
            ttk.Label(chart_frame, text="Grafik için: pip install matplotlib").pack(expand=True)

        # Alt: Bot log
        log_lf = ttk.LabelFrame(f, text="Bot Log (Son 50)")
        log_lf.grid(row=3, column=0, sticky=tk.NSEW, pady=(10, 0))
        log_lf.columnconfigure(0, weight=1)
        log_lf.rowconfigure(0, weight=1)
        self.bot_log_text = scrolledtext.ScrolledText(log_lf, height=12, bg="#21262d", fg="#c9d1d9", font=("Consolas", 9), insertbackground="#c9d1d9")
        self.bot_log_text.grid(row=0, column=0, sticky=tk.NSEW)
        self.bot_log_text.tag_config("soru", foreground="#58a6ff")
        self.bot_log_text.tag_config("cevap", foreground="#3fb950")
        self.bot_log_text.tag_config("alim", foreground="#3fb950")
        self.bot_log_text.tag_config("satim", foreground="#f85149")
        self.bot_log_text.tag_config("bekle", foreground="#d29922")
        self.bot_log_text.tag_config("info", foreground="#8b949e")
        self.bot_log_text.tag_config("hata", foreground="#f85149")
        f.rowconfigure(3, weight=1)

    def _tab_ayarlar(self, nb):
        f = ttk.LabelFrame(nb, text="API ve Bot Parametreleri", padding=15)
        nb.add(f, text="Ayarlar")
        f.columnconfigure(1, weight=1)

        row = 0
        tk.Label(f, text="Binance API Key:", bg="#161b22", fg="#c9d1d9").grid(row=row, column=0, sticky=tk.W, pady=4)
        self.ayar_binance_key = ttk.Entry(f, width=45, show="*")
        self.ayar_binance_key.insert(0, self.config.get("binance_api_key", ""))
        self.ayar_binance_key.grid(row=row, column=1, sticky=tk.W, padx=5, pady=4)
        row += 1
        tk.Label(f, text="Binance API Secret:", bg="#161b22", fg="#c9d1d9").grid(row=row, column=0, sticky=tk.W, pady=4)
        self.ayar_binance_secret = ttk.Entry(f, width=45, show="*")
        self.ayar_binance_secret.insert(0, self.config.get("binance_api_secret", ""))
        self.ayar_binance_secret.grid(row=row, column=1, sticky=tk.W, padx=5, pady=4)
        row += 2
        tk.Label(f, text="OpenRouter API Key:", bg="#161b22", fg="#c9d1d9").grid(row=row, column=0, sticky=tk.W, pady=4)
        self.ayar_openrouter = ttk.Entry(f, width=45, show="*")
        self.ayar_openrouter.insert(0, self.config.get("openrouter_api_key", ""))
        self.ayar_openrouter.grid(row=row, column=1, sticky=tk.W, padx=5, pady=4)
        row += 1
        tk.Label(f, text="AI Model:", bg="#161b22", fg="#c9d1d9").grid(row=row, column=0, sticky=tk.W, pady=4)
        self.ayar_ai_model = ttk.Combobox(f, width=42, values=["anthropic/claude-3.5-sonnet", "openai/gpt-4-turbo", "meta-llama/llama-3.1-70b-instruct"], state="readonly")
        self.ayar_ai_model.set(self.config.get("ai_model", "anthropic/claude-3.5-sonnet"))
        self.ayar_ai_model.grid(row=row, column=1, sticky=tk.W, padx=5, pady=4)
        row += 2
        tk.Label(f, text="Discord Webhook URL:", bg="#161b22", fg="#c9d1d9").grid(row=row, column=0, sticky=tk.W, pady=4)
        self.ayar_discord_webhook = ttk.Entry(f, width=45)
        self.ayar_discord_webhook.insert(0, self.config.get("discord_webhook", ""))
        self.ayar_discord_webhook.grid(row=row, column=1, sticky=tk.W, padx=5, pady=4)
        row += 1
        tk.Label(f, text="(Alım/Satım ve bot durumu Discord'a gönderilir)", bg="#161b22", fg="#8b949e", font=("Segoe UI", 8)).grid(row=row, column=1, sticky=tk.W, padx=5, pady=0)
        row += 2
        tk.Label(f, text="Telegram Bot Token:", bg="#161b22", fg="#c9d1d9").grid(row=row, column=0, sticky=tk.W, pady=4)
        self.ayar_telegram_token = ttk.Entry(f, width=45, show="*")
        self.ayar_telegram_token.insert(0, self.config.get("telegram_bot_token", ""))
        self.ayar_telegram_token.grid(row=row, column=1, sticky=tk.W, padx=5, pady=4)
        row += 1
        tk.Label(f, text="Telegram Chat ID:", bg="#161b22", fg="#c9d1d9").grid(row=row, column=0, sticky=tk.W, pady=4)
        self.ayar_telegram_chat = ttk.Entry(f, width=45)
        self.ayar_telegram_chat.insert(0, self.config.get("telegram_chat_id", ""))
        self.ayar_telegram_chat.grid(row=row, column=1, sticky=tk.W, padx=5, pady=4)
        row += 1
        tk.Label(f, text="(Alım/Satım ve bot durumu Telegram'a gönderilir)", bg="#161b22", fg="#8b949e", font=("Segoe UI", 8)).grid(row=row, column=1, sticky=tk.W, padx=5, pady=0)
        row += 2
        tk.Label(f, text="Pozisyon başına risk %:", bg="#161b22", fg="#c9d1d9").grid(row=row, column=0, sticky=tk.W, pady=4)
        self.ayar_risk = ttk.Entry(f, width=10)
        self.ayar_risk.insert(0, str(self.config.get("risk_pct", 2)))
        self.ayar_risk.grid(row=row, column=1, sticky=tk.W, padx=5, pady=4)
        row += 1
        tk.Label(f, text="Maks. eş zamanlı pozisyon:", bg="#161b22", fg="#c9d1d9").grid(row=row, column=0, sticky=tk.W, pady=4)
        self.ayar_max_poz = ttk.Entry(f, width=10)
        self.ayar_max_poz.insert(0, str(self.config.get("max_pozisyon", 3)))
        self.ayar_max_poz.grid(row=row, column=1, sticky=tk.W, padx=5, pady=4)
        row += 1
        tk.Label(f, text="Tarama aralığı (saniye):", bg="#161b22", fg="#c9d1d9").grid(row=row, column=0, sticky=tk.W, pady=4)
        self.ayar_aralik = ttk.Entry(f, width=10)
        self.ayar_aralik.insert(0, str(self.config.get("tarama_araligi_sn", 120)))
        self.ayar_aralik.grid(row=row, column=1, sticky=tk.W, padx=5, pady=4)
        row += 1
        tk.Label(f, text="Min. AI güven skoru (1-10):", bg="#161b22", fg="#c9d1d9").grid(row=row, column=0, sticky=tk.W, pady=4)
        self.ayar_min_guven = ttk.Entry(f, width=10)
        self.ayar_min_guven.insert(0, str(self.config.get("min_ai_guven", 7)))
        self.ayar_min_guven.grid(row=row, column=1, sticky=tk.W, padx=5, pady=4)
        row += 1
        tk.Label(f, text="Take Profit %:", bg="#161b22", fg="#c9d1d9").grid(row=row, column=0, sticky=tk.W, pady=4)
        self.ayar_tp = ttk.Entry(f, width=10)
        self.ayar_tp.insert(0, str(self.config.get("take_profit_pct", 3)))
        self.ayar_tp.grid(row=row, column=1, sticky=tk.W, padx=5, pady=4)
        row += 1
        tk.Label(f, text="Stop Loss %:", bg="#161b22", fg="#c9d1d9").grid(row=row, column=0, sticky=tk.W, pady=4)
        self.ayar_sl = ttk.Entry(f, width=10)
        self.ayar_sl.insert(0, str(self.config.get("stop_loss_pct", -2)))
        self.ayar_sl.grid(row=row, column=1, sticky=tk.W, padx=5, pady=4)
        row += 2
        btn_f = ttk.Frame(f)
        btn_f.grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=10)
        ttk.Button(btn_f, text="Kaydet", command=self._ayarlari_kaydet).pack(side=tk.LEFT, padx=5)

    def _tab_log(self, nb):
        f = ttk.Frame(nb, padding=10)
        nb.add(f, text="Log")
        f.columnconfigure(0, weight=1)
        f.rowconfigure(1, weight=1)
        ttk.Button(f, text="Logu Yenile", command=self._log_doldur).grid(row=0, column=0, sticky=tk.W, pady=(0, 5))
        self.log_tree = ttk.Treeview(f, columns=("Tarih", "Tip", "Mesaj"), show="headings", height=20)
        self.log_tree.column("Tarih", width=180)
        self.log_tree.column("Tip", width=80)
        self.log_tree.column("Mesaj", width=500)
        self.log_tree.grid(row=1, column=0, sticky=tk.NSEW)
        sb = ttk.Scrollbar(f, orient=tk.VERTICAL, command=self.log_tree.yview)
        sb.grid(row=1, column=1, sticky=tk.NS)
        self.log_tree.configure(yscrollcommand=sb.set)
        self._log_doldur()

    def _ayarlari_kaydet(self):
        self.config["binance_api_key"] = self.ayar_binance_key.get().strip()
        self.config["binance_api_secret"] = self.ayar_binance_secret.get().strip()
        self.config["openrouter_api_key"] = self.ayar_openrouter.get().strip()
        self.config["ai_model"] = self.ayar_ai_model.get()
        self.config["discord_webhook"] = self.ayar_discord_webhook.get().strip()
        self.config["telegram_bot_token"] = self.ayar_telegram_token.get().strip()
        self.config["telegram_chat_id"] = self.ayar_telegram_chat.get().strip()
        for key, w, default in [
            ("risk_pct", self.ayar_risk, 2),
            ("max_pozisyon", self.ayar_max_poz, 3),
            ("tarama_araligi_sn", self.ayar_aralik, 120),
            ("min_ai_guven", self.ayar_min_guven, 7),
            ("take_profit_pct", self.ayar_tp, 3),
            ("stop_loss_pct", self.ayar_sl, -2),
        ]:
            try:
                val = w.get().strip().replace(",", ".")
                self.config[key] = float(val) if key in ("take_profit_pct", "stop_loss_pct") else int(float(val))
            except ValueError:
                self.config[key] = default
        save_config(self.config)
        messagebox.showinfo("Bilgi", "Ayarlar kaydedildi.")

    def _bot_log(self, mesaj, tag="info"):
        ts = datetime.now().strftime("%H:%M:%S")
        def upd():
            if hasattr(self, "bot_log_text") and self.bot_log_text.winfo_exists():
                self.bot_log_text.insert(tk.END, f"  [{ts}] {mesaj}\n", tag)
                self.bot_log_text.see(tk.END)
                # Son 50 satır tut
                lines = self.bot_log_text.get("1.0", tk.END).split("\n")
                if len(lines) > 51:
                    self.bot_log_text.delete("1.0", "2.0")
        try:
            self.root.after(0, upd)
        except Exception:
            pass

    def _log_db(self, mesaj, tip="genel"):
        conn = get_db()
        c = conn.cursor()
        c.execute("INSERT INTO log (tarih_saat, tip, mesaj) VALUES (?,?,?)", (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), tip, mesaj))
        conn.commit()
        conn.close()

    def _discord_bildirim(self, baslik, mesaj, renk=3447003):
        """Discord webhook ile bildirim gönder. renk: 3066993=yeşil, 15158332=kırmızı, 16776960=sarı."""
        url = self.config.get("discord_webhook", "").strip()
        if url:
            discord_webhook_gonder(url, baslik, mesaj, renk)

    def _telegram_bildirim(self, baslik, mesaj):
        """Telegram Bot ile bildirim gönder."""
        token = self.config.get("telegram_bot_token", "").strip()
        chat_id = self.config.get("telegram_chat_id", "").strip()
        if token and chat_id:
            metin = f"<b>{baslik}</b>\n\n{mesaj}"
            telegram_gonder(token, chat_id, metin)

    def _bildirim_gonder(self, baslik, mesaj, discord_renk=3447003):
        """Hem Discord hem Telegram'a bildirim gönder."""
        self._discord_bildirim(baslik, mesaj, discord_renk)
        self._telegram_bildirim(baslik, mesaj)

    def _log_doldur(self):
        for i in self.log_tree.get_children():
            self.log_tree.delete(i)
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT tarih_saat, tip, mesaj FROM log ORDER BY id DESC LIMIT 200")
        for row in c.fetchall():
            self.log_tree.insert("", tk.END, values=(row["tarih_saat"] or "", row["tip"] or "", (row["mesaj"] or "")[:120]))
        conn.close()

    def _bot_baslat(self):
        if not self.config.get("binance_api_key") or not self.config.get("binance_api_secret"):
            messagebox.showwarning("Uyarı", "Binance API Key ve Secret girin.")
            return
        if not self.config.get("openrouter_api_key"):
            messagebox.showwarning("Uyarı", "OpenRouter API Key girin.")
            return
        self._ayarlari_kaydet()
        if self.bot_aktif:
            messagebox.showinfo("Bilgi", "Bot zaten çalışıyor.")
            return
        self.bot_aktif = True
        self.bot_thread = threading.Thread(target=self._bot_ana_dongu, daemon=True)
        self.bot_thread.start()
        self.lbl_bot_durum.config(text="● Çalışıyor", fg="#3fb950")
        self._bot_log("Bot başlatıldı.", "info")
        self._log_db("Bot başlatıldı", "bot")
        self._bildirim_gonder("🤖 Bot Başlatıldı", "AlSat botu çalışmaya başladı.", 3066993)

    def _bot_durdur(self):
        self.bot_aktif = False
        self.bot_thread = None
        self.lbl_bot_durum.config(text="● Kapalı", fg="#f85149")
        self._bot_log("Bot durduruldu.", "info")
        self._log_db("Bot durduruldu", "bot")
        self._bildirim_gonder("⏹️ Bot Durduruldu", "AlSat botu durduruldu.", 15158332)

    def _dashboard_guncelle(self, bakiye_usdt, pozisyonlar, toplam_deger):
        def upd():
            if not hasattr(self, "lbl_bakiye") or not self.lbl_bakiye.winfo_exists():
                return
            self.lbl_bakiye.config(text=f"${toplam_deger:,.2f}" if toplam_deger is not None else "$ —")
            self.lbl_pozisyon_say.config(text=f"{len(pozisyonlar)} adet")
            if self.baslangic_bakiye is not None and toplam_deger is not None:
                self.gunluk_kar = toplam_deger - self.baslangic_bakiye
                self.lbl_gunluk_kar.config(text=f"Bugün: {self.gunluk_kar:+,.2f}$", fg="#3fb950" if self.gunluk_kar >= 0 else "#f85149")
            if self.son_islem_zamani:
                self.lbl_son_islem.config(text=f"Son işlem: {self.son_islem_zamani}")
            en_kar = None
            for p in pozisyonlar:
                fiyat = binance_fiyat(p["sembol"])
                if fiyat and p.get("giris_fiyat"):
                    k = (fiyat - p["giris_fiyat"]) / p["giris_fiyat"] * 100
                    if en_kar is None or k > en_kar[1]:
                        en_kar = (p["sembol"].replace("USDT", ""), k)
            if en_kar:
                self.lbl_en_karli.config(text=f"En karlı: %{en_kar[1]:+.1f} ({en_kar[0]})", fg="#3fb950" if en_kar[1] >= 0 else "#f85149")
            else:
                self.lbl_en_karli.config(text="En karlı: —")
        try:
            self.root.after(0, upd)
        except Exception:
            pass

    def _grafik_ciz(self):
        if not HAS_MATPLOTLIB or not hasattr(self, "chart_ax"):
            return
        self.chart_ax.clear()
        self.chart_ax.set_facecolor("#21262d")
        self.chart_ax.tick_params(colors="#8b949e")
        if len(self.bakiye_gecmisi) < 2:
            self.chart_ax.set_title("Portföy Değeri (Son 24 Saat) — Veri bekleniyor", color="#c9d1d9", fontsize=10)
            self.chart_fig.tight_layout()
            self.chart_canvas.draw()
            return
        # Son 24 saat
        cutoff = datetime.now() - timedelta(hours=24)
        pts = [(t, v) for t, v in self.bakiye_gecmisi if t >= cutoff]
        if not pts:
            pts = self.bakiye_gecmisi[-50:]
        if pts:
            times = [p[0] for p in pts]
            values = [p[1] for p in pts]
            self.chart_ax.plot(times, values, color="#3fb950", linewidth=2, label="Portföy")
            try:
                import matplotlib.dates as mdates
                self.chart_ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
                self.chart_ax.xaxis.set_major_locator(mdates.AutoDateLocator())
            except Exception:
                pass
            # Alım/satım noktaları
            for ev in self.chart_events[-30:]:
                if len(ev) >= 3:
                    t, v, tip = ev[0], ev[1], ev[2]
                    if not pts or t >= (cutoff if pts else times[0]):
                        self.chart_ax.scatter([t], [v], color="#f85149" if tip == "satim" else "#58a6ff", s=40, zorder=5, marker="o")
        self.chart_ax.set_title("Portföy Değeri (Son 24 Saat)", color="#c9d1d9", fontsize=10)
        self.chart_ax.legend(loc="upper right", facecolor="#21262d", labelcolor="#c9d1d9")
        self.chart_fig.tight_layout()
        self.chart_canvas.draw()

    def _ai_alim_prompt(self, sembol, analiz, bakiye_usdt=0, acik_pozisyon_sayisi=0, max_pozisyon=3, risk_pct=2):
        """Gelişmiş BIST-tarzı birleşik prompt: Teknik + Hacim/Likidite + Destek/Direnç+Fib + Risk Yönetimi."""
        fiyat = analiz.get("fiyat") or 0
        over_under = " ⚠️ AŞIRI ALIM" if analiz.get("overbought") else " ⚠️ AŞIRI SATIM" if analiz.get("oversold") else ""
        macd_1h_note = " 📈 Pozitif" if (analiz.get("macd_hist_1h") is not None and analiz["macd_hist_1h"] > 0) else " 📉 Negatif" if (analiz.get("macd_hist_1h") is not None) else ""
        bb_note = " (Üst banda yakın)" if (analiz.get("bb_position") and analiz["bb_position"] > 0.8) else " (Alt banda yakın)" if (analiz.get("bb_position") and analiz["bb_position"] < 0.2) else ""
        adx_note = " 🔥 Güçlü trend" if (analiz.get("adx") and analiz["adx"] > 25) else ""
        golden = "✅ GOLDEN CROSS (50 EMA > 200 EMA) — Bullish" if analiz.get("golden_cross") else ""
        death = "⚠️ DEATH CROSS (50 EMA < 200 EMA) — Bearish" if analiz.get("death_cross") else ""
        dist_r = analiz.get("distance_to_resistance") or 0
        dist_s = analiz.get("distance_to_support") or 0
        bos_nakit = bakiye_usdt or 0
        risk_tutar = bos_nakit * (risk_pct / 100) if bos_nakit else 0
        fib = {k: analiz.get(k) for k in ["fib_0", "fib_236", "fib_382", "fib_50", "fib_618", "fib_786", "fib_100"]}
        pivot = analiz.get("pivot") or "—"
        return f"""Sen 15 yıllık deneyimli kripto ve teknik analiz uzmanısın. Tüm verileri birleştirip TEK FİNAL karar vereceksin.

═══════════════════════════════════════════════════════════
                    PAZAR BİLGİLERİ
═══════════════════════════════════════════════════════════
Sembol: {sembol}
Güncel Fiyat: ${fiyat:,.2f}
24 Saat Değişim: %{analiz.get('degisim_24h', 0):.2f}
24 Saat Hacim: {analiz.get('hacim_24h', 0):,.0f} (base) | Quote: ${analiz.get('quote_volume_24h', 0):,.0f}
Volatilite: {(analiz.get('volatilite') or 'normal').upper()}

═══════════════════════════════════════════════════════════
            ÇOKLU ZAMAN DİLİMİ TEKNİK ANALİZ
═══════════════════════════════════════════════════════════
15m: Sinyal {analiz.get('sinyal_15m', '—')} | RSI {analiz.get('rsi_15m') or '—'} | MACD Hist {analiz.get('macd_hist_15m') or '—'} | Stoch {analiz.get('stoch_15m') or '—'}
1h:  Sinyal {analiz.get('sinyal_1h', '—')} | RSI {analiz.get('rsi_1h') or '—'}{over_under} | MACD Hist {analiz.get('macd_hist_1h') or '—'}{macd_1h_note} | Stoch {analiz.get('stoch_1h') or '—'} | BB {analiz.get('bb_position') or '—'}{bb_note} | ATR {analiz.get('atr') or '—'} | ADX {analiz.get('adx') or '—'}{adx_note}
4h:  Sinyal {analiz.get('sinyal_4h', '—')} | RSI {analiz.get('rsi_4h') or '—'} | MACD Hist {analiz.get('macd_hist_4h') or '—'}
Günlük: Sinyal {analiz.get('sinyal_1d', '—')}

Hareketli Ortalamalar: EMA9 {analiz.get('ema_9') or '—'} | EMA21 {analiz.get('ema_21') or '—'} | EMA50 {analiz.get('ema_50') or '—'} | EMA200 {analiz.get('ema_200') or '—'} | SMA50 {analiz.get('sma_50') or '—'} | SMA200 {analiz.get('sma_200') or '—'}
{golden}
{death}

═══════════════════════════════════════════════════════════
              HACİM VE LİKİDİTE ANALİZİ
═══════════════════════════════════════════════════════════
- 24h hacim (base): {analiz.get('hacim_24h', 0):,.0f}
- 24h işlem hacmi (USDT): ${analiz.get('quote_volume_24h', 0):,.0f}
- Fiyat–hacim: 24h fiyat değişimi %{analiz.get('degisim_24h', 0):.2f}
- Hacim anomali: {"Evet — olağandışı hacim" if analiz.get('hacim_anomali') else "Hayır"}
GÖREV: Hacim sağlıklı mı? Yükseliş hacim destekli mi yoksa havai mi? Likidite riski var mı?

═══════════════════════════════════════════════════════════
           DESTEK/DİRENÇ VE FİBONACCİ SEVİYELERİ
═══════════════════════════════════════════════════════════
Fibonacci (24h high/low): %0: ${fib.get('fib_0') or '—'} | %23.6: ${fib.get('fib_236') or '—'} | %38.2: ${fib.get('fib_382') or '—'} | %50: ${fib.get('fib_50') or '—'} | %61.8: ${fib.get('fib_618') or '—'} | %78.6: ${fib.get('fib_786') or '—'} | %100: ${fib.get('fib_100') or '—'}
Pivot: ${pivot}

Destek: S1 ${analiz.get('support_1') or '—'} ({dist_s}% aşağıda) | S2 ${analiz.get('support_2') or '—'}
Direnç: R1 ${analiz.get('resistance_1') or '—'} ({dist_r}% yukarıda) | R2 ${analiz.get('resistance_2') or '—'}
GÖREV: Fiyat hangi Fib seviyesine yakın? Güçlü destek/direnç neresi? Giriş/çıkış noktası öner.

═══════════════════════════════════════════════════════════
                   RİSK YÖNETİMİ
═══════════════════════════════════════════════════════════
- Toplam bakiye (USDT): ${bos_nakit:,.2f}
- Açık pozisyon sayısı: {acik_pozisyon_sayisi} / {max_pozisyon}
- Pozisyon başına risk: %{risk_pct} → yaklaşık ${risk_tutar:,.2f} USDT
- Volatilite: {(analiz.get('volatilite') or 'normal').upper()}
GÖREV: Bu pozisyonu açmak portföy riskini aşar mı? Risk/ödül en az 1:2 olmalı. Tek pozisyonda sermayenin %10+ riske atılmamalı.

═══════════════════════════════════════════════════════════
TREND & MOMENTUM: {analiz.get('trend_genel', 'nötr').upper()} | {analiz.get('momentum', 'nötr').upper()}
═══════════════════════════════════════════════════════════

TÜM BİLGİLERİ BİRLEŞTİR: Teknik + Hacim + Destek/Direnç/Fib + Risk. ŞİMDİ bu varlık alınmalı mı?

CEVAP FORMATI (mutlaka bu formatta ver):
KARAR: [AL / BEKLE / ALMA]
GÜVEN: [1-10]
STOP_LOSS: [fiyat $]
TAKE_PROFIT: [fiyat $]
RISK_REWARD: [örn: 1:3]
GİRİŞ_STRATEJİSİ: [Hemen gir / Pullback bekle / Fib seviyesinde gir]
GEREKÇE: [3-5 cümle. Hangi göstergeler kararı destekliyor? Riskler neler?]
ALTERNATİF_SENARYO: [Fiyat beklediğin gibi gitmezse plan B]

ÖNEMLİ: Belirsizlik varsa BEKLE de. Sadece net fırsatlarda AL öner. Türkiye ve global makro riskleri (faiz, döviz, jeopolitik) aklında tut.
"""

    def _ai_satim_prompt(self, sembol, pozisyon, guncel_analiz):
        giris = pozisyon.get("giris_fiyat", 0)
        fiyat = guncel_analiz.get("fiyat", 0)
        kar_pct = ((fiyat - giris) / giris * 100) if giris else 0
        kar_usd = pozisyon.get("miktar", 0) * (fiyat - giris) if giris else 0
        hedef_tp = pozisyon.get("tp", 0)
        hedef_sl = pozisyon.get("sl", 0)
        acilis = pozisyon.get("acilis_zamani", "—")
        try:
            acilis_dt = datetime.strptime(acilis, "%Y-%m-%d %H:%M")
            sure = datetime.now() - acilis_dt
            sure_saat = int(sure.total_seconds() / 3600)
            sure_str = f"{sure_saat} saat" if sure_saat < 48 else f"{sure_saat // 24} gün"
        except Exception:
            sure_str = "—"
        tp_uzak = ((hedef_tp - fiyat) / fiyat * 100) if fiyat and hedef_tp else 0
        sl_uzak = ((hedef_sl - fiyat) / fiyat * 100) if fiyat and hedef_sl else 0
        over_under = " ⚠️ OVERBOUGHT (sat sinyali)" if guncel_analiz.get("overbought") else " ⚠️ OVERSOLD" if guncel_analiz.get("oversold") else ""
        macd_note = ""
        if guncel_analiz.get("macd_hist_1h") is not None:
            macd_note = " 📈 Pozitif" if guncel_analiz["macd_hist_1h"] > 0 else " 📉 Negatif"
        hacim_24h = guncel_analiz.get("hacim_24h") or 0
        quote_vol = guncel_analiz.get("quote_volume_24h") or 0
        return f"""Sen 15 yıllık deneyimli kripto trader ve risk yönetimi uzmanısın. Açık pozisyon için SATIM stratejisi öner.

═══════════════════════════════════════════════════════════
                    POZİSYON DURUMU
═══════════════════════════════════════════════════════════
Sembol: {sembol}
Giriş: ${giris:,.2f} | Güncel: ${fiyat:,.2f}
Kar/Zarar: %{kar_pct:+.2f} (${kar_usd:+,.2f})
Miktar: {pozisyon.get('miktar', 0)} | Açılış: {acilis} ({sure_str} önce)
Hedef TP: ${hedef_tp:,.2f} ({tp_uzak:+.1f}% uzakta) | Hedef SL: ${hedef_sl:,.2f} ({sl_uzak:+.1f}% uzakta)

═══════════════════════════════════════════════════════════
            GÜNCEL PAZAR VE TEKNİK
═══════════════════════════════════════════════════════════
Çoklu zaman: 15m {guncel_analiz.get('sinyal_15m', '—')} | 1h {guncel_analiz.get('sinyal_1h', '—')} | 4h {guncel_analiz.get('sinyal_4h', '—')} | 1d {guncel_analiz.get('sinyal_1d', '—')}
RSI 1h: {guncel_analiz.get('rsi_1h') or '—'}{over_under} | MACD Hist 1h: {guncel_analiz.get('macd_hist_1h') or '—'}{macd_note} | Stoch: {guncel_analiz.get('stoch_1h') or '—'} | ADX: {guncel_analiz.get('adx') or '—'} | BB: {guncel_analiz.get('bb_position') or '—'}
TREND: {guncel_analiz.get('trend_genel', 'nötr').upper()} | MOMENTUM: {guncel_analiz.get('momentum', 'nötr').upper()} | Volatilite: {guncel_analiz.get('volatilite', 'normal').upper()}

Destek/Direnç: R1 ${guncel_analiz.get('resistance_1') or '—'} | S1 ${guncel_analiz.get('support_1') or '—'}
Hacim 24h: {hacim_24h:,.0f} (base) | ${quote_vol:,.0f} USDT — Hacim sağlıklı mı? Likidite riski var mı?

═══════════════════════════════════════════════════════════
                    RİSK ANALİZİ TALEBİ
═══════════════════════════════════════════════════════════
1. ŞİMDİ SAT: Kar al ve çık
2. BEKLE: Daha fazla kar için tut
3. KISMİ_SAT: Bir kısmını sat, kalanı trailing stop ile tut
4. SL_GÜNCELLE: Stop loss'u yukarı çek (trailing)
Pozisyonu tutmanın riski nedir? Momentum zayıflıyor mu? Kazanan pozisyonu erken kapatma ama açgözlü olma.

CEVAP FORMATI:
KARAR: [SAT / BEKLE / KISMİ_SAT / SL_GÜNCELLE]
GÜVEN: [1-10]
YENİ_SL: [güncellenecekse fiyat]
YENİ_TP: [güncellenecekse fiyat]
KISMİ_ORAN: [kısmi satış öneriyorsan %50, %75 vb.]
GEREKÇE: [3-5 cümle]
RİSK_ANALİZİ: [Pozisyonu tutmanın riski, dip yapma ihtimali]
ALTERNATİF_PLAN: [Fiyat beklenmedik düşerse ne yapmalı?]
"""

    def _bot_ana_dongu(self):
        api_key = self.config.get("binance_api_key", "")
        api_secret = self.config.get("binance_api_secret", "")
        openrouter_key = self.config.get("openrouter_api_key", "")
        model = self.config.get("ai_model", "anthropic/claude-3.5-sonnet")
        risk_pct = self.config.get("risk_pct", 2) / 100.0
        max_poz = self.config.get("max_pozisyon", 3)
        aralik = max(60, self.config.get("tarama_araligi_sn", 120))
        min_guven = self.config.get("min_ai_guven", 7)
        tp_pct = self.config.get("take_profit_pct", 3) / 100.0
        sl_pct = self.config.get("stop_loss_pct", -2) / 100.0

        if self.baslangic_bakiye is None:
            b, _ = binance_bakiye(api_key, api_secret)
            if b is not None:
                self.baslangic_bakiye = b

        while self.bot_aktif and api_key and api_secret:
            try:
                bakiye_usdt, balances = binance_bakiye(api_key, api_secret)
                toplam = bakiye_usdt or 0
                for p in self.acik_pozisyonlar:
                    fiyat = binance_fiyat(p["sembol"])
                    if fiyat:
                        toplam += p["miktar"] * fiyat
                now = datetime.now()
                self.bakiye_gecmisi.append((now, toplam))
                if len(self.bakiye_gecmisi) > 500:
                    self.bakiye_gecmisi = self.bakiye_gecmisi[-400:]
                self._dashboard_guncelle(bakiye_usdt, self.acik_pozisyonlar, toplam)
                self.root.after(0, self._grafik_ciz)

                # 1) Açık pozisyonlar — SATIM kontrolü
                for poz in list(self.acik_pozisyonlar):
                    if not self.bot_aktif:
                        break
                    sembol = poz["sembol"]
                    guncel = binance_gelismis_analiz(sembol)
                    fiyat = guncel.get("fiyat") or binance_fiyat(sembol)
                    if not fiyat:
                        continue
                    kar_pct = (fiyat - poz["giris_fiyat"]) / poz["giris_fiyat"]
                    # Otomatik SL/TP kontrolü
                    if kar_pct <= sl_pct:
                        ok, _ = binance_spot_emir(api_key, api_secret, sembol, "SELL", poz["miktar"])
                        if ok:
                            self.son_islem_zamani = f"{datetime.now().strftime('%H:%M')} (SL)"
                            self.chart_events.append((now, toplam, "satim"))
                            self._bot_log(f"💸 SATIM (SL): {sembol} @ ${fiyat:,.2f} — Kar: %{kar_pct*100:.2f}", "satim")
                            self._log_db(f"AlSat SAT {sembol} SL", "bot")
                            self._bildirim_gonder("🔴 SATIM (Stop Loss)", f"{sembol} @ ${fiyat:,.2f}\nKar/Zarar: %{kar_pct*100:.2f}", 15158332)
                            self.acik_pozisyonlar.remove(poz)
                        continue
                    if kar_pct >= tp_pct:
                        ok, _ = binance_spot_emir(api_key, api_secret, sembol, "SELL", poz["miktar"])
                        if ok:
                            self.son_islem_zamani = f"{datetime.now().strftime('%H:%M')} (TP)"
                            self.chart_events.append((now, toplam, "satim"))
                            self._bot_log(f"💸 SATIM (TP): {sembol} @ ${fiyat:,.2f} — Kar: +%{kar_pct*100:.2f}", "satim")
                            self._log_db(f"AlSat SAT {sembol} TP %{kar_pct*100:.1f}", "bot")
                            self._bildirim_gonder("🟢 SATIM (Take Profit)", f"{sembol} @ ${fiyat:,.2f}\nKar: +%{kar_pct*100:.2f}", 3066993)
                            self.acik_pozisyonlar.remove(poz)
                        continue
                    # AI danış
                    self._bot_log(f"🤖 AI Sorgusu: {sembol} pozisyonu SAT kontrolü (kar %{kar_pct*100:.2f})", "soru")
                    prompt = self._ai_satim_prompt(sembol, poz, guncel)
                    cevap_text = openrouter_ask(openrouter_key, model, prompt)
                    cevap = parse_ai_satim_cevap(cevap_text)
                    self._bot_log(f"✅ AI Cevap: {cevap['KARAR']} (Güven: {cevap['GÜVEN']}) — {cevap['GEREKÇE'][:80]}", "cevap")
                    if cevap["KARAR"] == "SAT" and cevap["GÜVEN"] >= min_guven:
                        ok, _ = binance_spot_emir(api_key, api_secret, sembol, "SELL", poz["miktar"])
                        if ok:
                            self.son_islem_zamani = datetime.now().strftime("%H:%M")
                            self.chart_events.append((now, toplam, "satim"))
                            self._bot_log(f"💸 SATIM: {sembol} @ ${fiyat:,.2f} — Kar: %{kar_pct*100:.2f}", "satim")
                            self._log_db(f"AlSat SAT {sembol} AI", "bot")
                            self._bildirim_gonder("📤 SATIM (AI Önerisi)", f"{sembol} @ ${fiyat:,.2f}\nKar: %{kar_pct*100:.2f}", 16776960)
                            self.acik_pozisyonlar.remove(poz)
                    elif cevap["KARAR"] == "SL_GÜNCELLE" and cevap.get("YENİ_SL"):
                        poz["sl"] = cevap["YENİ_SL"]
                        if cevap.get("YENİ_TP"):
                            poz["tp"] = cevap["YENİ_TP"]
                        self._bot_log(f"⏸️ SL/TP güncellendi: {sembol} → SL ${poz['sl']}", "bekle")
                        self._bildirim_gonder("📌 SL/TP Güncellendi", f"{sembol}\nYeni SL: ${poz['sl']}", 3447003)
                    elif cevap["KARAR"] == "KISMİ_SAT" and cevap.get("KISMİ_ORAN") and 0 < cevap["KISMİ_ORAN"] < 100:
                        # Kısmi satış: pozisyonun yüzdesini sat
                        sat_miktar = round(poz["miktar"] * cevap["KISMİ_ORAN"] / 100, 5)
                        if sat_miktar > 0:
                            ok, _ = binance_spot_emir(api_key, api_secret, sembol, "SELL", sat_miktar)
                            if ok:
                                poz["miktar"] -= sat_miktar
                                self.son_islem_zamani = datetime.now().strftime("%H:%M")
                                self.chart_events.append((now, toplam, "satim"))
                                self._bot_log(f"💸 KISMİ SATIM: {sembol} %{cevap['KISMİ_ORAN']} @ ${fiyat:,.2f}", "satim")
                                self._bildirim_gonder("📊 Kısmi Satım", f"{sembol} %{cevap['KISMİ_ORAN']} @ ${fiyat:,.2f}", 16776960)
                                if poz["miktar"] <= 0:
                                    self.acik_pozisyonlar.remove(poz)
                    time.sleep(1)

                # 2) Yeni alım — slot varsa
                if len(self.acik_pozisyonlar) < max_poz and bakiye_usdt and bakiye_usdt > 15:
                    adaylar = binance_gelismis_tarama(SEMBOL_LISTESI)
                    for sembol, skor, analiz in adaylar[:5]:
                        if not self.bot_aktif or len(self.acik_pozisyonlar) >= max_poz:
                            break
                        if any(p["sembol"] == sembol for p in self.acik_pozisyonlar):
                            continue
                        self._bot_log(f"🤖 AI Sorgusu: {sembol} için AL önerisi (skor {skor})", "soru")
                        prompt = self._ai_alim_prompt(sembol, analiz, bakiye_usdt=bakiye_usdt, acik_pozisyon_sayisi=len(self.acik_pozisyonlar), max_pozisyon=max_poz, risk_pct=risk_pct * 100)
                        cevap_text = openrouter_ask(openrouter_key, model, prompt)
                        cevap = parse_ai_alim_cevap(cevap_text)
                        self._bot_log(f"✅ AI Cevap: {cevap['KARAR']} (Güven: {cevap['GÜVEN']}) — SL: {cevap['STOP_LOSS']} TP: {cevap['TAKE_PROFIT']}", "cevap")
                        if cevap["KARAR"] == "AL" and cevap["GÜVEN"] >= min_guven:
                            fiyat = analiz.get("fiyat") or binance_fiyat(sembol)
                            if not fiyat or fiyat <= 0:
                                continue
                            harcanacak = (bakiye_usdt or 0) * risk_pct
                            if harcanacak < 11:
                                continue
                            miktar = harcanacak / fiyat
                            if "BTC" in sembol:
                                miktar = round(miktar, 5)
                            elif "ETH" in sembol:
                                miktar = round(miktar, 4)
                            else:
                                miktar = round(miktar, 3)
                            if miktar <= 0:
                                continue
                            ok, _ = binance_spot_emir(api_key, api_secret, sembol, "BUY", miktar)
                            if ok:
                                sl = cevap.get("STOP_LOSS") or fiyat * (1 + sl_pct)
                                tp = cevap.get("TAKE_PROFIT") or fiyat * (1 + tp_pct)
                                self.acik_pozisyonlar.append({
                                    "sembol": sembol,
                                    "miktar": miktar,
                                    "giris_fiyat": fiyat,
                                    "sl": sl,
                                    "tp": tp,
                                    "acilis_zamani": datetime.now().strftime("%Y-%m-%d %H:%M"),
                                })
                                self.son_islem_zamani = datetime.now().strftime("%H:%M")
                                self.chart_events.append((now, toplam, "alim"))
                                self._bot_log(f"💰 ALIM: {sembol} @ ${fiyat:,.2f} — Miktar: {miktar}", "alim")
                                self._log_db(f"AlSat AL {sembol} @ {fiyat}", "bot")
                                self._bildirim_gonder("💰 ALIM", f"{sembol} @ ${fiyat:,.2f}\nMiktar: {miktar}\nSL: ${sl:,.2f} | TP: ${tp:,.2f}", 3066993)
                                break
                        time.sleep(1)

            except Exception as e:
                self._bot_log(f"Hata: {e}", "hata")
                self._log_db(f"Bot hata: {e}", "bot")
                self._bildirim_gonder("⚠️ Bot Hata", str(e)[:500], 15158332)
            time.sleep(aralik)

        self.bot_aktif = False
        try:
            self.root.after(0, lambda: self.lbl_bot_durum.config(text="● Kapalı", fg="#f85149"))
        except Exception:
            pass

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = BorsaAlSatBot()
    app.run()
