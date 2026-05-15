import requests
import numpy as np

SPOT_BASE    = "https://api.binance.com"
FUTURES_BASE = "https://fapi.binance.com"
TIMEOUT      = 8


def _get(base: str, path: str, params: dict) -> any:
    r = requests.get(f"{base}{path}", params=params, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def _klines(symbol: str, interval: str, limit: int = 100, futures: bool = True) -> np.ndarray:
    base = FUTURES_BASE if futures else SPOT_BASE
    path = "/fapi/v1/klines" if futures else "/api/v3/klines"
    raw = _get(base, path, {"symbol": symbol, "interval": interval, "limit": limit})
    arr = np.array([[float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])]
                    for k in raw])
    return arr


def _funding_rate(symbol: str) -> float | None:
    try:
        data = _get(FUTURES_BASE, "/fapi/v1/fundingRate", {"symbol": symbol, "limit": 1})
        return float(data[-1]["fundingRate"]) if data else None
    except Exception:
        return None


def _open_interest_hist(symbol: str, limit: int = 7) -> list[float] | None:
    try:
        data = _get(FUTURES_BASE, "/futures/data/openInterestHist",
                    {"symbol": symbol, "period": "4h", "limit": limit})
        return [float(d["sumOpenInterest"]) for d in data]
    except Exception:
        return None


def _order_book(symbol: str, depth: int = 20) -> dict | None:
    try:
        data = _get(FUTURES_BASE, "/fapi/v1/depth", {"symbol": symbol, "limit": depth})
        bid_vol = sum(float(b[1]) for b in data["bids"])
        ask_vol = sum(float(a[1]) for a in data["asks"])
        return {"bid_vol": bid_vol, "ask_vol": ask_vol,
                "ratio": bid_vol / (bid_vol + ask_vol) if (bid_vol + ask_vol) else 0.5}
    except Exception:
        return None


def _rsi(closes: np.ndarray, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    d = np.diff(closes)
    g = np.where(d > 0, d, 0.0)
    l = np.where(d < 0, -d, 0.0)
    ag, al = np.mean(g[:period]), np.mean(l[:period])
    for i in range(period, len(g)):
        ag = (ag * (period - 1) + g[i]) / period
        al = (al * (period - 1) + l[i]) / period
    return 100.0 if al == 0 else 100 - 100 / (1 + ag / al)


def _ema(closes: np.ndarray, period: int) -> np.ndarray:
    k = 2 / (period + 1)
    out = np.empty_like(closes)
    out[0] = closes[0]
    for i in range(1, len(closes)):
        out[i] = closes[i] * k + out[i - 1] * (1 - k)
    return out


def _atr(ohlcv: np.ndarray, period: int = 14) -> float:
    hi, lo, cl = ohlcv[:, 1], ohlcv[:, 2], ohlcv[:, 3]
    tr = np.maximum(hi[1:] - lo[1:],
         np.maximum(np.abs(hi[1:] - cl[:-1]), np.abs(lo[1:] - cl[:-1])))
    return float(np.mean(tr[-period:])) if len(tr) >= period else float(np.mean(tr))


def _volume_spike(volumes: np.ndarray, period: int = 20) -> float:
    if len(volumes) < period + 1:
        return 1.0
    avg = np.mean(volumes[-period - 1:-1])
    return float(volumes[-1] / avg) if avg else 1.0


def _support_resistance(ohlcv: np.ndarray, lookback: int = 50) -> dict:
    hi = ohlcv[-lookback:, 1]
    lo = ohlcv[-lookback:, 2]
    cl = ohlcv[-lookback:, 3]
    resistance = float(np.max(hi))
    support    = float(np.min(lo))
    price      = float(cl[-1])
    rng        = resistance - support or 1.0
    position   = (price - support) / rng
    return {"support": support, "resistance": resistance, "position": position}


def _btc_direction() -> str:
    try:
        ohlcv = _klines("BTCUSDT", "15m", limit=60, futures=True)
        cl = ohlcv[:, 3]
        ema21 = _ema(cl, 21)[-1]
        ema50 = _ema(cl, 50)[-1]
        rsi   = _rsi(cl)
        price = cl[-1]
        if price > ema21 > ema50 and rsi > 52:
            return "UP"
        if price < ema21 < ema50 and rsi < 48:
            return "DOWN"
        return "FLAT"
    except Exception:
        return "FLAT"


def _score_rsi(rsi: float) -> tuple[float, str | None]:
    if rsi <= 25:
        return 1.0,  "RSI aşırı satım bölgesinde"
    if rsi <= 35:
        return 0.7,  "RSI satım bölgesine yakın"
    if rsi <= 45:
        return 0.3,  None
    if rsi >= 75:
        return -1.0, "RSI aşırı alım bölgesinde"
    if rsi >= 65:
        return -0.7, "RSI alım bölgesine yakın"
    if rsi >= 55:
        return -0.3, None
    return 0.0, None


def _score_ema(ohlcv: np.ndarray) -> tuple[float, str | None]:
    cl = ohlcv[:, 3]
    e9  = _ema(cl, 9)[-1]
    e21 = _ema(cl, 21)[-1]
    e50 = _ema(cl, 50)[-1]
    price = float(cl[-1])
    if e9 > e21 > e50 and price > e9:
        return 1.0,  None
    if e9 > e21 > e50:
        return 0.6,  None
    if e9 < e21 < e50 and price < e9:
        return -1.0, None
    if e9 < e21 < e50:
        return -0.6, None
    return 0.0, None


def _rsi_trend_label(ohlcv: np.ndarray, tf: str) -> str | None:
    cl = ohlcv[:, 3]
    if len(cl) < 20:
        return None
    rsi_now  = _rsi(cl)
    rsi_prev = _rsi(cl[:-3])
    diff = rsi_now - rsi_prev
    if rsi_now < 50 and diff > 3:
        return f"RSI {tf} toparlanıyor"
    if rsi_now > 50 and diff < -3:
        return f"RSI {tf} zayıflıyor"
    return None


def full_analysis(raw_symbol: str) -> dict:
    symbol = raw_symbol.upper().strip()
    if not symbol.endswith("USDT"):
        symbol += "USDT"

    try:
        ohlcv_1m  = _klines(symbol, "1m",  limit=100, futures=True)
        ohlcv_5m  = _klines(symbol, "5m",  limit=100, futures=True)
        ohlcv_15m = _klines(symbol, "15m", limit=100, futures=True)
        ohlcv_1h  = _klines(symbol, "1h",  limit=100, futures=True)
    except Exception:
        try:
            ohlcv_1m  = _klines(symbol, "1m",  limit=100, futures=False)
            ohlcv_5m  = _klines(symbol, "5m",  limit=100, futures=False)
            ohlcv_15m = _klines(symbol, "15m", limit=100, futures=False)
            ohlcv_1h  = _klines(symbol, "1h",  limit=100, futures=False)
        except Exception:
            return {"error": f"{symbol} için veri alınamadı. Sembolün Binance'te işlem gördüğünden emin olun."}

    price = float(ohlcv_1m[-1, 3])
    btc_dir = _btc_direction()
    rsi_1m  = _rsi(ohlcv_1m[:, 3])
    rsi_5m  = _rsi(ohlcv_5m[:, 3])
    rsi_15m = _rsi(ohlcv_15m[:, 3])
    ema_val_1m,  _ = _score_ema(ohlcv_1m)
    ema_val_5m,  _ = _score_ema(ohlcv_5m)
    ema_val_15m, _ = _score_ema(ohlcv_15m)
    vol_spike_1m = _volume_spike(ohlcv_1m[:, 4])
    vol_spike_5m = _volume_spike(ohlcv_5m[:, 4])
    atr = _atr(ohlcv_1h)
    sr = _support_resistance(ohlcv_1h, lookback=50)
    funding   = _funding_rate(symbol)
    oi_hist   = _open_interest_hist(symbol)
    orderbook = _order_book(symbol)

    signals: list[tuple[float, float]] = []
    reasons: list[str] = []

    btc_val = {"UP": 1.0, "DOWN": -1.0, "FLAT": 0.0}[btc_dir]
    signals.append((15, btc_val))
    if btc_dir == "UP":
        reasons.append("BTC yukarı")
    elif btc_dir == "DOWN":
        reasons.append("BTC aşağı")

    v1m, _ = _score_rsi(rsi_1m)
    signals.append((8, v1m))

    v5m, _ = _score_rsi(rsi_5m)
    signals.append((12, v5m))
    trend_5m = _rsi_trend_label(ohlcv_5m, "5m")
    if trend_5m:
        reasons.append(trend_5m)

    v15m, r15m = _score_rsi(rsi_15m)
    signals.append((15, v15m))
    trend_15m = _rsi_trend_label(ohlcv_15m, "15m")
    if trend_15m:
        reasons.append(trend_15m)
    elif r15m:
        reasons.append(r15m)

    signals.append((8,  ema_val_1m))
    signals.append((12, ema_val_5m))
    signals.append((15, ema_val_15m))
    ema_5m_cl = ohlcv_5m[:, 3]
    e9_5m  = _ema(ema_5m_cl, 9)[-1]
    e21_5m = _ema(ema_5m_cl, 21)[-1]
    e50_5m = _ema(ema_5m_cl, 50)[-1]
    if e9_5m > e21_5m > e50_5m:
        reasons.append("EMA düzeni yükselişçi")
    elif e9_5m < e21_5m < e50_5m:
        reasons.append("EMA düzeni düşüşçü")

    max_spike = max(vol_spike_1m, vol_spike_5m)
    if max_spike > 1.8:
        cl_last = float(ohlcv_1m[-1, 3])
        cl_prev = float(ohlcv_1m[-2, 3])
        vol_dir = 1.0 if cl_last > cl_prev else -1.0
        signals.append((8, vol_dir))
        if vol_dir > 0:
            reasons.append(f"Hacim patlaması (×{max_spike:.1f}) yukarı yönlü")
        else:
            reasons.append(f"Hacim patlaması (×{max_spike:.1f}) aşağı yönlü")
    else:
        signals.append((8, 0.0))

    if funding is not None:
        funding_pct = funding * 100
        if funding_pct > 0.05:
            fval = max(-1.0, -funding_pct * 10)
            signals.append((8, fval))
            reasons.append(f"Funding yüksek ({funding_pct:.4f}%) — long baskısı")
        elif funding_pct < -0.01:
            fval = min(1.0, abs(funding_pct) * 15)
            signals.append((8, fval))
            reasons.append(f"Funding negatif ({funding_pct:.4f}%) — short baskısı")
        else:
            signals.append((8, 0.0))
            reasons.append(f"Funding normal ({funding_pct:.4f}%)")
    else:
        signals.append((8, 0.0))

    if oi_hist and len(oi_hist) >= 2:
        oi_change = (oi_hist[-1] - oi_hist[0]) / oi_hist[0] * 100 if oi_hist[0] else 0
        if oi_change > 3:
            signals.append((10, 0.8))
            reasons.append(f"OI artıyor (+{oi_change:.1f}%)")
        elif oi_change > 1:
            signals.append((10, 0.4))
            reasons.append("OI hafif artıyor")
        elif oi_change < -3:
            signals.append((10, -0.8))
            reasons.append(f"OI düşüyor ({oi_change:.1f}%)")
        elif oi_change < -1:
            signals.append((10, -0.4))
        else:
            signals.append((10, 0.0))
            reasons.append("OI yatay")
    else:
        signals.append((10, 0.0))

    if orderbook:
        ob_ratio = orderbook["ratio"]
        if ob_ratio > 0.65:
            signals.append((7, 1.0))
            reasons.append(f"Emir defteri alıcı ağırlıklı ({ob_ratio*100:.0f}%)")
        elif ob_ratio > 0.55:
            signals.append((7, 0.5))
        elif ob_ratio < 0.35:
            signals.append((7, -1.0))
            reasons.append(f"Emir defteri satıcı ağırlıklı ({(1-ob_ratio)*100:.0f}%)")
        elif ob_ratio < 0.45:
            signals.append((7, -0.5))
        else:
            signals.append((7, 0.0))
    else:
        signals.append((7, 0.0))

    pos = sr["position"]
    if pos < 0.15:
        signals.append((10, 1.0))
        reasons.append("Fiyat destekten tepki aldı")
    elif pos < 0.30:
        signals.append((10, 0.5))
        reasons.append("Fiyat destek bölgesinde")
    elif pos > 0.85:
        signals.append((10, -1.0))
        reasons.append("Fiyat direnç bölgesinde")
    elif pos > 0.70:
        signals.append((10, -0.5))
        reasons.append("Fiyat dirence yaklaşıyor")
    else:
        signals.append((10, 0.0))

    total_weight = sum(w for w, _ in signals)
    weighted_sum = sum(w * v for w, v in signals)
    normalized   = weighted_sum / total_weight
    score        = (normalized + 1) / 2 * 100

    if score >= 62:
        verdict = "LONG"
    elif score <= 38:
        verdict = "SHORT"
    else:
        verdict = "İŞLEM YOK"

    entry_low = entry_high = sl = tp1 = tp2 = None
    if verdict == "LONG":
        entry_low  = price - 0.1 * atr
        entry_high = price + 0.1 * atr
        sl  = price - 1.5 * atr
        tp1 = price + 1.5 * atr
        tp2 = price + 3.0 * atr
    elif verdict == "SHORT":
        entry_low  = price - 0.1 * atr
        entry_high = price + 0.1 * atr
        sl  = price + 1.5 * atr
        tp1 = price - 1.5 * atr
        tp2 = price - 3.0 * atr

    reasons = reasons[:6]

    return {
        "symbol":     symbol,
        "price":      price,
        "score":      score,
        "verdict":    verdict,
        "entry_low":  entry_low,
        "entry_high": entry_high,
        "sl":         sl,
        "tp1":        tp1,
        "tp2":        tp2,
        "reasons":    reasons,
        "btc_dir":    btc_dir,
        "rsi_1m":     rsi_1m,
        "rsi_5m":     rsi_5m,
        "rsi_15m":    rsi_15m,
        "funding":    funding,
        "sr":         sr,
    }
