from dataclasses import dataclass,asdict
import time
@dataclass
class Candle:
 ts:int; open:float; high:float; low:float; close:float; volume:float=0.0
 def as_dict(self): return asdict(self)
class CandleBuilder:
 def __init__(self,timeframe_seconds,max_candles=250): self.timeframe=timeframe_seconds; self.max_candles=max_candles; self.candles=[]
 def update(self,price,ts=None,volume=0.0):
  ts=time.time() if ts is None else ts; bucket=int(ts//self.timeframe)*self.timeframe
  if not self.candles or self.candles[-1].ts!=bucket:
   self.candles.append(Candle(bucket,price,price,price,price,volume)); self.candles=self.candles[-self.max_candles:]
  else:
   c=self.candles[-1]; c.high=max(c.high,price); c.low=min(c.low,price); c.close=price; c.volume+=volume
  return self.candles[-1]
 def snapshot(self): return [c.as_dict() for c in self.candles]
