import math
from statistics import mean

class SuperAIAnalyzer:
    """Independent, deterministic market-analysis layer for ALUCARD V4.

    Uses the full candle snapshot supplied by the feed plus the calculated
    indicator state. It is intentionally independent of external AI APIs so
    testing does not depend on an API key or network round-trip.
    """

    def __init__(self, history_limit=500):
        self.history_limit = history_limit

    @staticmethod
    def _sign(x, eps=0.0):
        if x is None:
            return 0
        return 1 if x > eps else -1 if x < -eps else 0

    @staticmethod
    def _trend(candles, n):
        c = [float(x.get("close")) for x in candles[-n:] if x.get("close") is not None]
        if len(c) < max(8, n // 3):
            return 0.0
        # Least-squares slope, normalized by price so different assets are comparable.
        m = len(c)
        xbar = (m - 1) / 2.0
        ybar = mean(c)
        den = sum((i - xbar) ** 2 for i in range(m)) or 1.0
        slope = sum((i - xbar) * (y - ybar) for i, y in enumerate(c)) / den
        return slope / (abs(ybar) or 1.0) * 1000.0

    @staticmethod
    def _returns(candles, n):
        c = [float(x.get("close")) for x in candles[-(n + 1):] if x.get("close") is not None]
        if len(c) < n + 1:
            return []
        return [(c[i] - c[i - 1]) / (abs(c[i - 1]) or 1.0) for i in range(1, len(c))]

    def analyze(self, candles, indicators, engine_result):
        candles = list(candles or [])[-self.history_limit:]
        v = indicators or {}
        if len(candles) < 35:
            return {"enabled": True, "decision": "WAIT", "confidence": 0,
                    "reason": "Super AI needs more candle history", "history_used": len(candles)}

        scores = {"CALL": 0.0, "PUT": 0.0}
        evidence = []

        def add(name, direction, weight):
            if direction in ("CALL", "PUT"):
                scores[direction] += weight
                evidence.append((name, direction, weight))

        # 1) Multi-horizon price trend: recent + medium + long context.
        t20, t50, t100 = self._trend(candles, 20), self._trend(candles, 50), self._trend(candles, min(100, len(candles)))
        add("20-candle trend", "CALL" if t20 > 0.10 else "PUT" if t20 < -0.10 else "WAIT", 10)
        add("50-candle trend", "CALL" if t50 > 0.05 else "PUT" if t50 < -0.05 else "WAIT", 8)
        add("100-candle trend", "CALL" if t100 > 0.03 else "PUT" if t100 < -0.03 else "WAIT", 5)

        # 2) Core indicator alignment.
        price = v.get("price")
        ema9, ema20, ema50 = v.get("ema9"), v.get("ema20"), v.get("ema50")
        if None not in (ema9, ema20, ema50):
            add("EMA stack", "CALL" if ema9 > ema20 > ema50 else "PUT" if ema9 < ema20 < ema50 else "WAIT", 8)

        lips, teeth, jaw = v.get("alligator_lips"), v.get("alligator_teeth"), v.get("alligator_jaw")
        if None not in (lips, teeth, jaw):
            add("Alligator", "CALL" if lips > teeth > jaw else "PUT" if lips < teeth < jaw else "WAIT", 12)

        macd = v.get("macd_hist")
        macd_prev = v.get("macd_hist_prev")
        if macd is not None:
            macd_dir = "CALL" if macd > 0 else "PUT" if macd < 0 else "WAIT"
            # A strengthening histogram gets extra directional evidence.
            if macd_prev is not None and self._sign(macd - macd_prev) == self._sign(macd):
                add("MACD momentum", macd_dir, 8)
            else:
                add("MACD", macd_dir, 5)

        cci = v.get("cci")
        cci_prev = v.get("cci_prev")
        if cci is not None:
            cci_dir = "CALL" if cci > 0 else "PUT" if cci < 0 else "WAIT"
            add("CCI", cci_dir, 6)
            if cci_prev is not None and self._sign(cci - cci_prev) == self._sign(cci):
                add("CCI slope", cci_dir, 3)

        psar = v.get("psar")
        if price is not None and psar is not None:
            add("PSAR", "CALL" if price > psar else "PUT" if price < psar else "WAIT", 4)

        st = v.get("supertrend")
        st_dir = v.get("supertrend_direction")
        if price is not None and st is not None:
            add("Supertrend", "CALL" if st_dir == 1 and price > st else "PUT" if st_dir == -1 and price < st else "WAIT", 5)

        # 3) Market structure and FCB.
        structure = v.get("market_structure")
        structure_break = v.get("market_structure_break")
        add("Market structure", structure if structure in ("CALL", "PUT") else "WAIT", 7)
        add("Structure break", structure_break if structure_break in ("CALL", "PUT") else "WAIT", 5)

        fcb_mid = v.get("fcb_mid")
        fcb_prev = v.get("fcb_mid_prev")
        if price is not None and fcb_mid is not None:
            fcb_slope = (fcb_mid - fcb_prev) if fcb_prev is not None else 0
            add("FCB structure", "CALL" if price >= fcb_mid and fcb_slope > 0 else "PUT" if price <= fcb_mid and fcb_slope < 0 else "WAIT", 5)

        # 4) DMI/ADX confirms direction only when trend strength is meaningful.
        adx, plus_di, minus_di = v.get("adx"), v.get("plus_di"), v.get("minus_di")
        if None not in (adx, plus_di, minus_di):
            if adx >= 18:
                add("ADX/DMI", "CALL" if plus_di > minus_di else "PUT" if minus_di > plus_di else "WAIT", 6)

        # 5) Short-term momentum and candle quality.
        rs = self._returns(candles, 6)
        if rs:
            mom = sum(rs)
            add("6-candle momentum", "CALL" if mom > 0.00005 else "PUT" if mom < -0.00005 else "WAIT", 7)

        last = candles[-1]
        o, h, l, c = [float(last.get(k, 0) or 0) for k in ("open", "high", "low", "close")]
        rng = max(h - l, 0.0)
        body = abs(c - o)
        body_ratio = body / rng if rng else 0.0
        if body_ratio >= 0.55:
            add("Latest candle", "CALL" if c > o else "PUT" if c < o else "WAIT", 4)

        # 6) Reversal/exhaustion penalty. Extreme momentum without structure
        # support is treated as lower-quality continuation evidence.
        rsi = v.get("rsi")
        exhaustion = bool(v.get("spike_exhaustion", False))
        if exhaustion:
            leader = "CALL" if sum(x > 0 for x in rs[-3:]) >= 2 else "PUT" if sum(x < 0 for x in rs[-3:]) >= 2 else "WAIT"
            if leader in scores:
                scores[leader] -= 8
                evidence.append(("exhaustion penalty", leader, -8))

        if rsi is not None:
            if rsi > 78:
                scores["CALL"] -= 4
            elif rsi < 22:
                scores["PUT"] -= 4

        total = max(scores["CALL"] + scores["PUT"], 1.0)
        leader = "CALL" if scores["CALL"] > scores["PUT"] else "PUT" if scores["PUT"] > scores["CALL"] else "WAIT"
        margin = abs(scores["CALL"] - scores["PUT"])
        confidence = min(100.0, max(0.0, 50.0 + (margin / total) * 50.0))

        # Require both broad agreement and a meaningful margin for a decision.
        # This keeps the analyzer from forcing a direction on mixed conditions.
        if leader == "WAIT" or confidence < 62:
            decision = "WAIT"
        else:
            decision = leader

        top = sorted(evidence, key=lambda x: abs(x[2]), reverse=True)[:4]
        reason_parts = [f"{name}={direction}" for name, direction, _ in top]
        reason = ("History %d candles; " % len(candles)) + "; ".join(reason_parts)
        return {
            "enabled": True,
            "decision": decision,
            "confidence": round(confidence, 1),
            "call_score": round(scores["CALL"], 1),
            "put_score": round(scores["PUT"], 1),
            "history_used": len(candles),
            "reason": reason[:500],
            "model": "ALUCARD V4 Super AI (multi-horizon ensemble)"
        }
