import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from indicators import ema, cci, macd, psar

_MODEL_CACHE = {}

# Faithful feature set from VitalySvyatyuk/pocket_option_trading_bot/po_bot_ml.py:
# EMA(8/3 crossover), Awesome Oscillator, PSAR reversal, CCI, MACD.
FEATURES = ["ema_cross", "awesome_oscillator", "psar_reversal", "cci", "macd"]

def _frame(candles):
    df = pd.DataFrame(candles)
    if df.empty:
        return df
    for c in ("open","high","low","close"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.dropna(subset=["open","high","low","close"]).reset_index(drop=True)

def _psar_reversal(df):
    sar = psar(df)
    close = df["close"].astype(float)
    prev_close = close.shift(1)
    prev_sar = sar.shift(1)
    # Equivalent directional reversal event: price crosses the prior PSAR.
    return ((close > sar) & (prev_close <= prev_sar)) | ((close < sar) & (prev_close >= prev_sar))

def _features(candles):
    df = _frame(candles)
    if len(df) < 60:
        return pd.DataFrame(), df
    close = df["close"]
    fast = ema(close, 3)
    slow = ema(close, 8)
    median = (df["high"] + df["low"]) / 2.0
    ao = median.rolling(5).mean() - median.rolling(34).mean()
    psar_rev = _psar_reversal(df)
    cc = cci(df, 14)
    _, macd_signal, macd_hist = macd(close)

    out = pd.DataFrame(index=df.index)
    # Original bot encodes each feature as a binary 0/1.
    out["ema_cross"] = (
        (fast.shift(1) > slow.shift(1)) &
        (fast < slow) &
        (close < close.shift(1)) &
        (close.shift(1) < close.shift(2))
    ).astype(int)
    out["awesome_oscillator"] = (ao >= 0).astype(int)
    out["psar_reversal"] = psar_rev.astype(int)
    out["cci"] = (cc <= 0).astype(int)
    out["macd"] = (macd_hist >= 0).astype(int)
    return out, df

def _psar_strategy(candles):
    df = _frame(candles)
    if len(df) < 20:
        return {"signal":"WAIT","reason":"PSAR strategy needs more candle history"}
    sar = psar(df)
    close = df["close"]
    prev_close, prev_sar = close.iloc[-2], sar.iloc[-2]
    cur_close, cur_sar = close.iloc[-1], sar.iloc[-1]
    if cur_close > cur_sar and prev_close <= prev_sar:
        return {"signal":"CALL","reason":"PSAR bullish reversal"}
    if cur_close < cur_sar and prev_close >= prev_sar:
        return {"signal":"PUT","reason":"PSAR bearish reversal"}
    return {"signal":"WAIT","reason":"No PSAR reversal"}

def scan(candles, horizon=1, min_probability=0.60, cache_key=""):
    """
    Signal-only reproduction of the public bot's ML approach.
    It trains on the latest 200 candles, predicts the next horizon candle,
    and reports the Random Forest probability. It never places orders.
    """
    feats, df = _features(candles)
    psar_result = _psar_strategy(candles)
    if len(df) < 90:
        return {"ready":False,"signal":"WAIT","probability":0.0,"call_probability":0.0,
                "put_probability":0.0,"accuracy":None,"psar_signal":psar_result["signal"],
                "psar_reason":psar_result["reason"],"reason":"Need more candle history"}

    lookback = min(200, len(df))
    feats = feats.iloc[-lookback:].reset_index(drop=True)
    df = df.iloc[-lookback:].reset_index(drop=True)
    max_i = len(df) - horizon - 1
    if max_i < 40:
        return {"ready":False,"signal":"WAIT","probability":0.0,"call_probability":0.0,
                "put_probability":0.0,"accuracy":None,"psar_signal":psar_result["signal"],
                "psar_reason":psar_result["reason"],"reason":"Need more completed candles"}

    future = df["close"].shift(-horizon)
    y = (future > df["close"]).astype(int)
    data = feats.copy()
    data["profit"] = y
    data = data.iloc[:max_i + 1].dropna()

    if len(data) < 40 or data["profit"].nunique() < 2:
        return {"ready":False,"signal":"WAIT","probability":0.0,"call_probability":0.0,
                "put_probability":0.0,"accuracy":None,"psar_signal":psar_result["signal"],
                "psar_reason":psar_result["reason"],"reason":"Insufficient directional examples"}

    latest_completed = str(df.iloc[-2]["ts"]) if "ts" in df.columns and len(df) >= 2 else str(len(df))
    cache_id = (cache_key or "default", horizon, latest_completed, len(data))
    cached = _MODEL_CACHE.get(cache_id)
    if cached:
        model, accuracy = cached
    else:
        split = max(30, int(len(data) * 0.80))
        train_df, valid_df = data.iloc[:split], data.iloc[split:]
        model = RandomForestClassifier(n_estimators=400, random_state=42, n_jobs=1)
        model.fit(train_df[FEATURES], train_df["profit"])
        accuracy = float(model.score(valid_df[FEATURES], valid_df["profit"])) if len(valid_df) >= 5 else None
        _MODEL_CACHE[cache_id] = (model, accuracy)

    latest = feats.iloc[[-1]][FEATURES]
    if latest.isna().any(axis=None):
        return {"ready":False,"signal":"WAIT","probability":0.0,"call_probability":0.0,
                "put_probability":0.0,"accuracy":accuracy,"psar_signal":psar_result["signal"],
                "psar_reason":psar_result["reason"],"reason":"Current feature vector incomplete"}

    p = model.predict_proba(latest)[0]
    put_p = float(p[0]); call_p = float(p[1])
    signal = "PUT" if put_p > call_p else "CALL"
    probability = max(put_p, call_p)
    if probability < min_probability:
        signal = "WAIT"

    return {
        "ready":True,
        "signal":signal,
        "probability":round(probability*100,1),
        "call_probability":round(call_p*100,1),
        "put_probability":round(put_p*100,1),
        "accuracy":round(accuracy*100,1) if accuracy is not None else None,
        "training_rows":int(len(data)),
        "psar_signal":psar_result["signal"],
        "psar_reason":psar_result["reason"],
        "reason":f"Vitaly RF: {signal if signal != 'WAIT' else 'NO_TRADE'}; probability {probability*100:.1f}%"
    }
