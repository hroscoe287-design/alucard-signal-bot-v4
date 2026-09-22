import asyncio
import json
import logging
import struct
import time
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import websockets

log = logging.getLogger("alucard.feed")


class PocketOptionFeed:
    """Signal-only Pocket Option market feed."""

    def __init__(self, url, auth_json, on_tick, on_history=None, asset="EURUSD_otc", period=60):
        self.url = url
        self.auth_json = auth_json or ""
        self.on_tick = on_tick
        self.on_history = on_history
        self.asset = asset
        self.period = int(period)
        self.running = False
        self.connected = False
        self.authenticated = False
        self.last_tick = 0
        self.last_error = ""
        self.ws = None
        self._update_stream_samples = 0

    def _url(self):
        raw = self.url.strip()
        if not raw:
            raw = "wss://api-us-south.po.market/socket.io/?EIO=4&transport=websocket"
        p = urlparse(raw)
        q = parse_qs(p.query)
        q["EIO"] = ["4"]
        q["transport"] = ["websocket"]
        return urlunparse((p.scheme or "wss", p.netloc, p.path or "/socket.io/", "", urlencode(q, doseq=True), ""))

    def _auth_payload(self):
        if not self.auth_json.strip():
            return None
        raw = self.auth_json.strip()
        if raw.startswith("42"):
            try:
                packet = json.loads(raw[2:])
                if isinstance(packet, list) and len(packet) >= 2 and packet[0] == "auth":
                    return packet[1]
            except Exception:
                pass
        try:
            data = json.loads(raw)
        except Exception:
            data = {"session": raw}
        if isinstance(data, list):
            if len(data) >= 2 and data[0] == "auth":
                return data[1]
            return None
        if isinstance(data, dict) and "command" in data:
            return data.get("data") or {}
        return data if isinstance(data, dict) else None

    def auth_packet(self):
        payload = self._auth_payload()
        if payload is None:
            return None
        return "42" + json.dumps(["auth", payload], separators=(",", ":"))

    def _event_packet(self, event, payload):
        return "42" + json.dumps([event, payload], separators=(",", ":"))

    async def _subscribe(self, ws):
        await ws.send(self._event_packet("subscribeSymbol", {"asset": self.asset}))
        await ws.send(self._event_packet("changeSymbol", {
            "asset": self.asset,
            "period": self.period,
        }))
        await ws.send(self._event_packet("subfor", {"asset": self.asset}))

    async def change_subscription(self, asset, period):
        """Switch the live Pocket Option subscription without restarting the service."""
        try:
            period = int(period)
        except (TypeError, ValueError):
            raise ValueError("Invalid timeframe period")

        if not asset:
            raise ValueError("Asset is required")

        self.asset = str(asset)
        self.period = period

        if self.ws and self.connected and self.authenticated:
            await self._subscribe(self.ws)
            log.info(
                "Pocket Option subscription changed to %s/%ss",
                self.asset,
                self.period,
            )
            return True

        log.info(
            "Pocket Option subscription queued for reconnect: %s/%ss",
            self.asset,
            self.period,
        )
        return False

    async def _keepalive(self, ws):
        while self.running:
            try:
                await ws.send(self._event_packet("ps", {}))
                await asyncio.sleep(15)
            except asyncio.CancelledError:
                raise
            except Exception:
                return

    def _number(self, value):
        try:
            value = float(value)
            return value if value > 0 else None
        except (TypeError, ValueError):
            return None

    def _replace_placeholders(self, value, attachments):
        if isinstance(value, dict):
            if value.get("_placeholder") is True and isinstance(value.get("num"), int):
                idx = value["num"]
                if 0 <= idx < len(attachments):
                    return attachments[idx]
                return value
            return {k: self._replace_placeholders(v, attachments) for k, v in value.items()}
        if isinstance(value, list):
            return [self._replace_placeholders(v, attachments) for v in value]
        return value

    def _decode_socket_packet(self, msg):
        if isinstance(msg, bytes):
            return None
        if not isinstance(msg, str) or (not msg.startswith("42") and not msg.startswith("45")):
            return None
        raw = msg[2:]
        attachments = 0
        if msg.startswith("45"):
            dash = raw.find("-")
            if dash < 1:
                return None
            try:
                attachments = int(raw[:dash])
            except ValueError:
                return None
            raw = raw[dash + 1:]
        try:
            packet = json.loads(raw)
        except Exception:
            return None
        if not isinstance(packet, list) or len(packet) < 2:
            return None
        return str(packet[0]), packet[1], attachments

    async def _handshake(self, ws):
        first = await asyncio.wait_for(ws.recv(), timeout=15)
        if isinstance(first, bytes):
            first = first.decode("utf-8", "ignore")
        if not str(first).startswith("0"):
            raise RuntimeError(f"unexpected Engine.IO handshake: {str(first)[:120]}")
        await ws.send("40")

        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            msg = await asyncio.wait_for(ws.recv(), timeout=max(1, deadline - time.monotonic()))
            if isinstance(msg, bytes):
                continue
            if str(msg) == "40" or str(msg).startswith("40"):
                return
            if str(msg) == "2":
                await ws.send("3")

        raise RuntimeError("Socket.IO namespace handshake timed out")

    async def _authenticate(self, ws):
        packet = self.auth_packet()
        if packet is None:
            raise RuntimeError("PO_AUTH_JSON is not configured")
        await ws.send(packet)

        auth_deadline = time.monotonic() + 15
        while time.monotonic() < auth_deadline:
            msg = await asyncio.wait_for(ws.recv(), timeout=max(1, auth_deadline - time.monotonic()))
            if isinstance(msg, bytes):
                continue

            text_msg = str(msg)
            if text_msg == "2":
                await ws.send("3")
                continue
            if text_msg.startswith("41"):
                raise RuntimeError(f"Pocket Option authorization rejected: {text_msg[:200]}")

            decoded = self._decode_socket_packet(text_msg)
            if decoded is None:
                continue
            event, body, count = decoded

            if count:
                attachments = []
                for _ in range(count):
                    attachment = await asyncio.wait_for(
                        ws.recv(), timeout=max(1, auth_deadline - time.monotonic())
                    )
                    attachments.append(attachment)
                body = self._replace_placeholders(body, attachments)

            if event == "successauth":
                self.authenticated = True
                log.info("Pocket Option authorization accepted")
                return

        raise RuntimeError("Pocket Option authorization response not received")

    def _price_bounds(self):
        name = self.asset.upper()
        if "XAU" in name or "GOLD" in name:
            return 100.0, 10000.0
        if "XAG" in name or "SILVER" in name:
            return 5.0, 200.0
        if any(x in name for x in ("BTC", "ETH", "LTC", "XRP", "BCH", "DOGE", "ADA", "SOL", "DOT", "LINK", "AVAX", "BNB")):
            return 0.0000001, 1_000_000_000.0
        if any(x in name for x in ("US30", "NAS", "SPX", "DAX", "CAC", "FTSE")):
            return 10.0, 100_000.0
        return 0.00001, 10.0

    def _valid_price(self, value):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return False
        low, high = self._price_bounds()
        return low <= value <= high

    def _extract_binary_tick(self, data):
        """Decode the compact Pocket Option stream frame."""
        if not isinstance(data, (bytes, bytearray)) or len(data) < 36:
            return None

        raw = bytes(data)

        try:
            decoded = json.loads(raw.decode("utf-8"))
            if isinstance(decoded, list):
                for item in decoded:
                    if not isinstance(item, (list, tuple)) or len(item) < 3:
                        continue
                    asset = str(item[0]) if item[0] is not None else self.asset
                    try:
                        stamp = float(item[1])
                        price = float(item[2])
                    except (TypeError, ValueError):
                        continue
                    if self._valid_price(price) and (asset == self.asset or not asset):
                        if stamp > 10_000_000_000:
                            stamp /= 1000.0
                        return asset or self.asset, price, stamp
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            pass

        try:
            values = struct.unpack("<IdIfffff", raw[:36])
            if self._valid_price(values[1]):
                stamp = float(values[2])
                if stamp > 10_000_000_000:
                    stamp /= 1000.0
                return self.asset, float(values[1]), stamp
        except struct.error:
            pass

        for offset in range(1, min(17, len(raw) - 35)):
            try:
                values = struct.unpack("<IdIfffff", raw[offset:offset + 36])
            except struct.error:
                continue
            if not self._valid_price(values[1]):
                continue
            stamp = float(values[2])
            if stamp <= 0:
                continue
            if stamp > 10_000_000_000:
                stamp /= 1000.0
            return self.asset, float(values[1]), stamp

        return None

    def _extract_history(self, body):
        source = body
        if isinstance(source, (bytes, bytearray)):
            try:
                source = json.loads(bytes(source).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return []
        if not isinstance(source, dict):
            return []
        asset = str(source.get("asset") or source.get("symbol") or self.asset)
        raw = source.get("candles") or source.get("history") or []
        if isinstance(raw, dict):
            raw = raw.get("candles") or raw.get("history") or []
        out = []
        for row in raw if isinstance(raw, list) else []:
            if not isinstance(row, (list, tuple)) or len(row) < 5:
                continue
            try:
                ts = float(row[0])
                o, c, h, l = map(float, row[1:5])
            except (TypeError, ValueError):
                continue
            if ts > 10_000_000_000:
                ts /= 1000.0
            if asset == self.asset and min(o, c, h, l) > 0 and h >= max(o, c) and l <= min(o, c):
                out.append({"timestamp": ts, "open": o, "close": c, "high": h, "low": l})
        return out

    def _extract_event(self, event, body):
        candidates = []

        def walk(value, asset=None, timestamp=None):
            if isinstance(value, dict):
                current_asset = asset
                current_ts = timestamp
                for key, child in value.items():
                    lk = str(key).lower()
                    if lk in {"asset", "symbol", "pair", "active", "instrument"}:
                        current_asset = str(child)
                    elif lk in {"time", "timestamp", "ts", "at"}:
                        try:
                            current_ts = float(child)
                        except (TypeError, ValueError):
                            pass
                    elif lk in {"price", "rate", "quote", "close", "value", "bid", "ask", "close_value"}:
                        number = self._number(child)
                        if number is not None and self._valid_price(number):
                            candidates.append((current_asset, number, current_ts))
                    walk(child, current_asset, current_ts)
            elif isinstance(value, list):
                for child in value:
                    walk(child, asset, timestamp)
            elif isinstance(value, (bytes, bytearray)):
                parsed = self._extract_binary_tick(bytes(value))
                if parsed:
                    candidates.append(parsed)

        walk(body)
        preferred = [x for x in candidates if x[0] in (self.asset, None)]
        if event == "updateStream" and preferred:
            asset, price, ts = preferred[0]
            return asset or self.asset, price, ts
        for asset, price, ts in preferred:
            if asset == self.asset:
                return asset, price, ts
        return None

    async def run(self):
        self.running = True
        delay = 2

        while self.running:
            try:
                url = self._url()
                log.info("connecting to Pocket Option websocket")
                async with websockets.connect(
                    url,
                    ping_interval=20,
                    ping_timeout=20,
                    max_size=16 * 1024 * 1024,
                    additional_headers={
                        "Origin": "https://pocketoption.com",
                        "User-Agent": "Mozilla/5.0",
                    },
                ) as ws:
                    self.ws = ws
                    self.connected = True
                    self.authenticated = False
                    self.last_error = ""
                    self._update_stream_samples = 0
                    delay = 2

                    await self._handshake(ws)
                    await self._authenticate(ws)
                    await self._subscribe(ws)
                    log.info(
                        "Pocket Option feed authenticated; subscribed to %s/%ss",
                        self.asset,
                        self.period,
                    )

                    keepalive_task = asyncio.create_task(self._keepalive(ws))
                    try:
                        while self.running:
                            msg = await ws.recv()

                            if isinstance(msg, bytes):
                                parsed_binary = self._extract_binary_tick(msg)
                                if parsed_binary:
                                    asset, price, ts = parsed_binary
                                    self.last_tick = time.time()
                                    self.on_tick(asset, price, ts)
                                    log.info(
                                        "Pocket Option binary market tick received: %s %.8f",
                                        asset,
                                        price,
                                    )
                                else:
                                    log.info("Pocket Option binary frame received: %d bytes hex=%s", len(msg), msg[:32].hex())
                                continue

                            text_msg = str(msg)
                            if text_msg == "2":
                                await ws.send("3")
                                continue
                            if text_msg == "3":
                                continue
                            if text_msg.startswith("1"):
                                raise RuntimeError(
                                    f"Pocket Option websocket closed: {text_msg[:200]}"
                                )

                            decoded = self._decode_socket_packet(text_msg)
                            if decoded is None:
                                if text_msg:
                                    log.info("Pocket Option non-event message: %s", text_msg[:180])
                                continue

                            event, body, count = decoded

                            if count:
                                attachments = []
                                for _ in range(count):
                                    attachments.append(await ws.recv())
                                body = self._replace_placeholders(body, attachments)

                            if event == "updateStream" and self._update_stream_samples < 3:
                                self._update_stream_samples += 1
                                try:
                                    sample = json.dumps(body, separators=(",", ":"), default=str)
                                except Exception:
                                    sample = repr(body)
                                log.info(
                                    "Pocket Option updateStream sample %d: %s",
                                    self._update_stream_samples,
                                    sample[:2000],
                                )
                                if isinstance(body, (bytes, bytearray)):
                                    log.info(
                                        "Pocket Option updateStream binary attachment %d bytes hex=%s",
                                        len(body),
                                        bytes(body)[:64].hex(),
                                    )

                            log.info(
                                "Pocket Option event received: %s body_type=%s attachments=%d",
                                event,
                                type(body).__name__,
                                count,
                            )

                            if event == "updateHistoryNewFast" and self.on_history:
                                history = self._extract_history(body)
                                if history:
                                    self.on_history(history)
                                    log.info("Pocket Option historical candles loaded: %d", len(history))

                            parsed = self._extract_event(event, body)
                            if parsed:
                                asset, price, ts = parsed
                                stamp = float(ts) if ts else time.time()
                                if stamp > 10_000_000_000:
                                    stamp /= 1000.0
                                self.last_tick = time.time()
                                self.on_tick(asset, price, stamp)
                                log.info(
                                    "Pocket Option market tick received: %s %.8f",
                                    asset,
                                    price,
                                )
                            elif event in {"updateStream", "updateHistoryNewFast", "successauth"}:
                                log.info("Pocket Option market event had no valid price: %s", event)
                    finally:
                        keepalive_task.cancel()
                        try:
                            await keepalive_task
                        except asyncio.CancelledError:
                            pass

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.connected = False
                self.authenticated = False
                self.last_error = repr(exc)
                log.warning("feed disconnected: %s (%s)", exc, type(exc).__name__)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)
            finally:
                self.connected = False
                self.authenticated = False
                self.ws = None

    async def stop(self):
        self.running = False
        if self.ws:
            await self.ws.close()
