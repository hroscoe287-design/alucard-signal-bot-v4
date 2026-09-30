import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

from indicators import ema, rsi, atr, cci, macd, psar, alligator


FEATURES = [
    "ema_fast_slow",
    "ema_slope",
    "awesome_oscillator",
    "psar_gap",
    "cci",
    "macd_hist",
    "macd_slope",
    "rsi",
    "momentum_1",
    "momentum_3",
    "atr_pct",
    "alligator_spread",
]


def _frame(candles):
    df = pd.DataFrame(candles)
    if df.empty:
        return df
    for c in ("open", "high", "low", "close"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)


def _features(candles):
    df = _frame(candles)
    if len(df) < 60:
        return pd.DataFrame(), df

    close = df["close"]
    fast = ema(close, 8)
    slow = ema(close, 21)
    ao = (df["high"] + df["low"]) / 2.0
    ao = ao.rolling(5).mean() - ao.rolling(34).mean()
    ps = psar(df)
    cc = cci(df, 14)
    _, _, mh = macd(close)
    rr = rsi(close, 14)
    aa = atr(df, 14)
    jaw, teeth, lips = alligator(df)

    out = pd.DataFrame(index=df.index)
    out["ema_fast_slow"] = (fast - slow) / close.replace(0, np.nan)
    out["ema_slope"] = fast.diff(2) / close.replace(0, np.nan)
    out["awesome_oscillator"] = ao / close.replace(0, np.nan)
    out["psar_gap"] = (close - ps) / close.replace(0, np.nan)
    out["cci"] = cc.clip(-300, 300) / 300.0
    out["macd_hist"] = mh / close.replace(0, np.nan)
    out["macd_slope"] = mh.diff() / close.replace(0, np.nan)
    out["rsi"] = (rr - 50.0) / 50.0
    out["momentum_1"] = close.diff() / close.shift(1).replace(0, np.nan)
    out["momentum_3"] = close.diff(3) / close.shift(3).replace(0, np.nan)
    out["atr_pct"] = aa / close.replace(0, np.nan)
    out["alligator_spread"] = (lips - jaw) / close.replace(0, np.nan)
    return out.replace([np.inf, -np.inf], np.nan), df


def scan(candles, horizon=1, min_probability=0.60):
    """
    Research-only Random Forest confirmation inspired by the public
    Pocket Option ML example: EMA, oscillator/momentum, PSAR, CCI and MACD.
    It does not place orders and is deliberately kept separate from the
    ALUCARD weighted engine.
    """
    feats, df = _features(candles)
    if len(df) < 90:
        return {"ready": False, "signal": "WAIT", "probability": 0.0,
                "accuracy": None, "reason": "ML scanner needs more candle history"}

    # Never use the still-forming candle as a training label.
    max_i = len(df) - horizon - 1
    if max_i < 70:
        return {"ready": False, "signal": "WAIT", "probability": 0.0,
                "accuracy": None, "reason": "ML scanner needs more completed candles"}

    train = feats.iloc[:max_i + 1].copy()
    future = df["close"].shift(-horizon)
    y = (future > df["close"]).astype(int).iloc[:max_i + 1]
    data = train.copy()
    data["target"] = y.values
    data = data.dropna()

    if len(data) < 70 or data["target"].nunique() < 2:
        return {"ready": False, "signal": "WAIT", "probability": 0.0,
                "accuracy": None, "reason": "ML scanner has insufficient directional examples"}

    split = max(50, int(len(data) * 0.80))
    train_df = data.iloc[:split]
    valid_df = data.iloc[split:]

    model = RandomForestClassifier(
        n_estimators=300,
        max_depth=7,
        min_samples_leaf=3,
        random_state=42,
        class_weight="balanced_subsample",
        n_jobs=1,
    )
    model.fit(train_df[FEATURES], train_df["target"])

    accuracy = None
    if len(valid_df) >= 10:
        accuracy = float(model.score(valid_df[FEATURES], valid_df["target"]))

    latest = feats.iloc[[-1]][FEATURES]
    if latest.isna().any(axis=None):
        return {"ready": False, "signal": "WAIT", "probability": 0.0,
                "accuracy": accuracy, "reason": "Current ML feature vector is incomplete"}

    proba = model.predict_proba(latest)[0]
    put_p = float(proba[0])
    call_p = float(proba[1])
    if call_p >= put_p:
        signal, probability = "CALL", call_p
    else:
        signal, probability = "PUT", put_p

    if probability < min_probability:
        signal = "WAIT"

    return {
        "ready": True,
        "signal": signal,
        "probability": round(probability * 100.0, 1),
        "call_probability": round(call_p * 100.0, 1),
        "put_probability": round(put_p * 100.0, 1),
        "accuracy": round(accuracy * 100.0, 1) if accuracy is not None else None,
        "training_rows": int(len(data)),
        "reason": f"Random Forest: {signal if signal != 'WAIT' else 'NO_TRADE'}; "
                  f"model probability {probability * 100:.1f}%",
    }
