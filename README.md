# ALUCARD SIGNAL BOT V4.0

Raw Engine.IO v3 WebSocket adapter, local tick-to-candle aggregation, technical indicators, and CALL/PUT/WAIT confluence dashboard.

Files:
main.py - FastAPI dashboard and API
pocket_feed.py - WebSocket transport and heartbeat
candles.py - tick-to-candle aggregation
indicators.py - EMA, Alligator, Fractal 2, PSAR, MACD, CCI, RSI, ATR
engine.py - confluence signal engine
config.py - assets, timeframes, environment settings

Authentication:
Pocket Option private WebSocket access requires a valid current session/auth payload. V4 does not hard-code credentials. Set PO_AUTH_JSON in Render to the current JSON auth payload. The adapter accepts a raw command/list or a plain auth dictionary and wraps it in an Engine.IO 42 packet.

Safety:
V4 is signal-only. It does not place orders or click the Pocket Option interface.

Local:
uvicorn main:app --host 0.0.0.0 --port 8000

Dashboard: /
Health: /api/health
State: /api/state
