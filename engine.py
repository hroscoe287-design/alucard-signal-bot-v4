from datetime import datetime,timezone
class SignalEngine:
 def __init__(self,min_confidence=60): self.min_confidence=min_confidence
 def evaluate(self,ind):
  if not ind.get("ready"): return {"signal":"WAIT","confidence":0,"reason":ind.get("reason","Insufficient data"),"votes":[]}
  v=ind["values"]; call=put=0; votes=[]
  def vote(name,direction,w=1):
   nonlocal call,put
   if direction=="CALL":call+=w
   elif direction=="PUT":put+=w
   votes.append({"name":name,"direction":direction,"weight":w})
  vote("EMA trend","CALL" if v["ema9"]>v["ema20"]>v["ema50"] else "PUT" if v["ema9"]<v["ema20"]<v["ema50"] else "WAIT",2)
  vote("MACD","CALL" if v["macd_hist"]>0 else "PUT" if v["macd_hist"]<0 else "WAIT",2)
  vote("RSI","CALL" if 50<v["rsi"]<70 else "PUT" if 30<v["rsi"]<50 else "WAIT")
  vote("CCI","CALL" if v["cci"]>0 else "PUT" if v["cci"]<0 else "WAIT")
  vote("Parabolic SAR","CALL" if v["price"]>v["psar"] else "PUT" if v["price"]<v["psar"] else "WAIT")
  vote("Alligator","CALL" if v["alligator_lips"]>v["alligator_teeth"]>v["alligator_jaw"] else "PUT" if v["alligator_lips"]<v["alligator_teeth"]<v["alligator_jaw"] else "WAIT",2)
  total=9; confidence=round(max(call,put)/total*100,1)
  signal="CALL" if call>put and confidence>=self.min_confidence else "PUT" if put>call and confidence>=self.min_confidence else "WAIT"
  return {"signal":signal,"confidence":confidence,"call_score":call,"put_score":put,"votes":votes,"reason":f"CALL {call}/{total}, PUT {put}/{total}","timestamp":datetime.now(timezone.utc).isoformat()}
