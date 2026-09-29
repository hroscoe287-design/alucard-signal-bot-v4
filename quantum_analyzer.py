"""Quantum-inspired market analyzer for ALUCARD V4.

This is classical software, not a physical quantum computer.  It uses a
quantum-inspired state representation to model interactions between the
existing independent signals without adding network latency or requiring a
quantum-cloud API.

The output is intentionally a confirmation/veto layer; it never claims a
statistical win rate or a guaranteed outcome.
"""

from __future__ import annotations

import math


DIRECTIONS = ("CALL", "PUT")


def _clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _sign(x: float | None) -> float:
    if x is None:
        return 0.0
    return 1.0 if x > 0 else -1.0 if x < 0 else 0.0


def analyze(values: dict) -> dict:
    """Return a quantum-inspired state score from ALUCARD's live indicators.

    The model maps directional evidence into normalized amplitudes, applies
    pairwise interference between independent families, and measures the
    resulting CALL/PUT state. It is deterministic and runs locally.
    """

    price = values.get("price")
    ema9, ema20, ema50 = values.get("ema9"), values.get("ema20"), values.get("ema50")
    jaw, teeth, lips = (
        values.get("alligator_jaw"),
        values.get("alligator_teeth"),
        values.get("alligator_lips"),
    )
    macd, macd_prev = values.get("macd_hist"), values.get("macd_hist_prev")
    cci, cci_prev = values.get("cci"), values.get("cci_prev")
    psar = values.get("psar")
    st_dir = values.get("supertrend_direction")
    fcb_mid = values.get("fcb_mid")
    adx, plus_di, minus_di = values.get("adx"), values.get("plus_di"), values.get("minus_di")
    ut_fast, ut_slow = values.get("ut_fast_direction"), values.get("ut_slow_direction")

    features = {}

    if None not in (ema9, ema20, ema50):
        features["EMA"] = _sign((ema9 - ema20) + (ema20 - ema50))

    if None not in (jaw, teeth, lips):
        features["ALLIGATOR"] = _sign((lips - teeth) + (teeth - jaw))

    if macd is not None:
        features["MACD"] = _sign(macd)
        if macd_prev is not None:
            features["MACD_SLOPE"] = _sign(macd - macd_prev)

    if cci is not None:
        features["CCI"] = _sign(cci)
        if cci_prev is not None:
            features["CCI_SLOPE"] = _sign(cci - cci_prev)

    if price is not None and psar is not None:
        features["PSAR"] = _sign(price - psar)

    if st_dir in (-1, 1):
        features["SUPERTREND"] = float(st_dir)

    if price is not None and fcb_mid is not None:
        features["FCB"] = _sign(price - fcb_mid)

    if adx is not None and plus_di is not None and minus_di is not None and adx >= 18:
        features["DMI"] = _sign(plus_di - minus_di)

    if ut_fast in (-1, 1) and ut_slow in (-1, 1) and ut_fast == ut_slow:
        features["UT"] = float(ut_fast)

    # Primary families get more amplitude. Alligator/MACD/CCI are deliberately
    # emphasized because they are ALUCARD V4's directional leaders.
    weights = {
        "ALLIGATOR": 1.30,
        "MACD": 1.20,
        "CCI": 1.15,
        "EMA": 1.00,
        "SUPERTREND": 0.90,
        "DMI": 0.85,
        "PSAR": 0.75,
        "FCB": 0.70,
        "MACD_SLOPE": 0.65,
        "CCI_SLOPE": 0.65,
        "UT": 0.55,
    }

    call_amp = 0.0
    put_amp = 0.0
    for name, direction in features.items():
        a = weights.get(name, 0.5)
        if direction > 0:
            call_amp += a
        elif direction < 0:
            put_amp += a

    # Interference: agreement among independent families reinforces the state;
    # disagreement creates destructive interference instead of being ignored.
    pairs = (
        ("ALLIGATOR", "MACD", 0.35),
        ("ALLIGATOR", "CCI", 0.30),
        ("MACD", "CCI", 0.30),
        ("EMA", "SUPERTREND", 0.22),
        ("DMI", "SUPERTREND", 0.20),
        ("FCB", "DMI", 0.16),
    )
    interference = 0.0
    for a, b, strength in pairs:
        if a in features and b in features:
            if features[a] == features[b]:
                interference += strength * features[a]
            else:
                interference -= strength * features[a]

    net = call_amp - put_amp + interference
    total = call_amp + put_amp + abs(interference)
    state_strength = 0.0 if total <= 0 else min(1.0, abs(net) / total)
    direction = "CALL" if net > 0 else "PUT" if net < 0 else "WAIT"

    # A quantum-inspired state is useful only when the strongest directional
    # families agree. This prevents the new layer from overpowering V4.
    leaders = [features.get(k, 0.0) for k in ("ALLIGATOR", "MACD", "CCI")]
    leader_agreement = sum(1 for x in leaders if x != 0 and x == (1 if direction == "CALL" else -1))
    leader_conflict = sum(1 for x in leaders if x != 0 and direction in DIRECTIONS and x != (1 if direction == "CALL" else -1))

    confidence = round(50.0 + 50.0 * state_strength, 1)
    veto = direction in DIRECTIONS and leader_conflict >= 2

    return {
        "direction": direction,
        "confidence": confidence,
        "state_strength": round(state_strength, 3),
        "call_amplitude": round(call_amp, 3),
        "put_amplitude": round(put_amp, 3),
        "interference": round(interference, 3),
        "leader_agreement": leader_agreement,
        "leader_conflict": leader_conflict,
        "veto": veto,
        "features": features,
        "mode": "QUANTUM_INSPIRED_CLASSICAL",
    }
