from datetime import datetime,timezone

class SignalEngine:
 def __init__(self,min_confidence=60):
  self.min_confidence=min_confidence
  self.last_signal="WAIT"

 def evaluate(self,ind):
  if not ind.get("ready"):
   self.last_signal="WAIT"
   return {"signal":"WAIT","confidence":0,"reason":ind.get("reason","Insufficient data"),"votes":[]}
  v=ind["values"]; call=put=0; votes=[]
  def vote(name,direction,w):
   nonlocal call,put
   if direction=="CALL": call+=w
   elif direction=="PUT": put+=w
   votes.append({"name":name,"direction":direction,"weight":w})

  # 100-point model. Alligator receives 25 points and its effective
  # contribution adapts to line separation relative to ATR.
  jaw=v["alligator_jaw"]; teeth=v["alligator_teeth"]; lips=v["alligator_lips"]; atr=v.get("atr") or 0
  spread=max(abs(lips-jaw),abs(teeth-jaw),abs(lips-teeth))
  width_ratio=(spread/atr) if atr>0 else 0
  base="CALL" if lips>teeth>jaw else "PUT" if lips<teeth<jaw else "WAIT"
  if base!="WAIT":
   width_factor=min(1.0,max(0.25,width_ratio/1.5))
   vote("Alligator",base,round(25*width_factor,1))
  else: vote("Alligator","WAIT",0)

  vote("EMA trend","CALL" if v["ema9"]>v["ema20"]>v["ema50"] else "PUT" if v["ema9"]<v["ema20"]<v["ema50"] else "WAIT",15)
  fd="CALL" if v.get("fractal_down") and not v.get("fractal_up") else "PUT" if v.get("fractal_up") and not v.get("fractal_down") else "WAIT"
  vote("Fractal (2)",fd,10)
  vote("Parabolic SAR","CALL" if v["price"]>v["psar"] else "PUT" if v["price"]<v["psar"] else "WAIT",10)
  vote("MACD","CALL" if v["macd_hist"]>0 else "PUT" if v["macd_hist"]<0 else "WAIT",15)
  vote("RSI","CALL" if 50<v["rsi"]<70 else "PUT" if 30<v["rsi"]<50 else "WAIT",10)
  vote("Bollinger Bands","CALL" if v.get("bb_pct") is not None and v.get("bb_mid") is not None and v["bb_pct"]>0.50 and v["price"]>=v["bb_mid"] else "PUT" if v.get("bb_pct") is not None and v.get("bb_mid") is not None and v["bb_pct"]<0.50 and v["price"]<=v["bb_mid"] else "WAIT",5)
  av=v.get("atr"); ab=v.get("atr_baseline")
  ad="CALL" if av is not None and ab is not None and av>=ab and v["price"]>v["ema9"] else "PUT" if av is not None and ab is not None and av>=ab and v["price"]<v["ema9"] else "WAIT"
  vote("ATR volatility",ad,5)
  vote("Supertrend","CALL" if v.get("supertrend_direction")==1 and v.get("supertrend") is not None and v["price"]>v["supertrend"] else "PUT" if v.get("supertrend_direction")==-1 and v.get("supertrend") is not None and v["price"]<v["supertrend"] else "WAIT",5)

  total=100; leader=max(call,put); confidence=round(leader/total*100,1)
  signal="CALL" if call>put and confidence>=self.min_confidence else "PUT" if put>call and confidence>=self.min_confidence else "WAIT"
  reason=f"Insufficient agreement: CALL {call:.1f}/{total}, PUT {put:.1f}/{total}" if signal=="WAIT" else f"{signal} confirmation: CALL {call:.1f}/{total}, PUT {put:.1f}/{total}"
  self.last_signal=signal
  return {"signal":signal,"confidence":confidence,"call_score":round(call,1),"put_score":round(put,1),"max_score":total,"votes":votes,"reason":reason,"timestamp":datetime.now(timezone.utc).isoformat()}
