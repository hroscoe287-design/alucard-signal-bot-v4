from datetime import datetime,timezone

class SignalEngine:
 def __init__(self,min_confidence=60):
  self.min_confidence=min_confidence
  self.last_signal="WAIT"

 def evaluate(self,ind):
  if not ind.get("ready"):
   self.last_signal="WAIT"
   return {"signal":"WAIT","confidence":0,"reason":ind.get("reason","Insufficient data"),"votes":[]}

  v=ind["values"]
  call=put=0
  votes=[]

  def vote(name,direction,w):
   nonlocal call,put
   if direction=="CALL":
    call+=w
   elif direction=="PUT":
    put+=w
   votes.append({"name":name,"direction":direction,"weight":w})

  # V4 baseline model restored to 100 points, plus Supertrend = 10.
  vote("Alligator",
       "CALL" if v["alligator_lips"]>v["alligator_teeth"]>v["alligator_jaw"]
       else "PUT" if v["alligator_lips"]<v["alligator_teeth"]<v["alligator_jaw"]
       else "WAIT",20)

  vote("EMA trend",
       "CALL" if v["ema9"]>v["ema20"]>v["ema50"]
       else "PUT" if v["ema9"]<v["ema20"]<v["ema50"]
       else "WAIT",15)

  fractal_direction="CALL" if v.get("fractal_down") and not v.get("fractal_up") else "PUT" if v.get("fractal_up") and not v.get("fractal_down") else "WAIT"
  vote("Fractal (2)",fractal_direction,15)

  vote("Parabolic SAR",
       "CALL" if v["price"]>v["psar"]
       else "PUT" if v["price"]<v["psar"]
       else "WAIT",10)

  vote("MACD",
       "CALL" if v["macd_hist"]>0
       else "PUT" if v["macd_hist"]<0
       else "WAIT",15)

  vote("RSI",
       "CALL" if 50<v["rsi"]<70
       else "PUT" if 30<v["rsi"]<50
       else "WAIT",10)

  vote("Bollinger Bands",
       "CALL" if v.get("bb_pct") is not None and v.get("bb_mid") is not None and v["bb_pct"]>0.50 and v["price"]>=v["bb_mid"]
       else "PUT" if v.get("bb_pct") is not None and v.get("bb_mid") is not None and v["bb_pct"]<0.50 and v["price"]<=v["bb_mid"]
       else "WAIT",10)

  atr_value=v.get("atr")
  atr_baseline=v.get("atr_baseline")
  if atr_value is not None and atr_baseline is not None and atr_value>=atr_baseline:
   atr_dir="CALL" if v["price"]>v["ema9"] else "PUT" if v["price"]<v["ema9"] else "WAIT"
  else:
   atr_dir="WAIT"
  vote("ATR volatility",atr_dir,5)

  vote("Supertrend",
       "CALL" if v.get("supertrend_direction")==1 and v["price"]>v.get("supertrend")
       else "PUT" if v.get("supertrend_direction")==-1 and v["price"]<v.get("supertrend")
       else "WAIT",10)

  total=110
  leader=max(call,put)
  confidence=round(leader/total*100,1)
  signal="CALL" if call>put and confidence>=self.min_confidence else "PUT" if put>call and confidence>=self.min_confidence else "WAIT"

  if signal=="WAIT":
   reason=f"Insufficient agreement: CALL {call}/{total}, PUT {put}/{total}"
  else:
   reason=f"{signal} confirmation: CALL {call}/{total}, PUT {put}/{total}"

  self.last_signal=signal
  return {"signal":signal,"confidence":confidence,"call_score":call,"put_score":put,
          "max_score":total,"votes":votes,"reason":reason,
          "timestamp":datetime.now(timezone.utc).isoformat()}
