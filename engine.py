from datetime import datetime,timezone

class SignalEngine:
 def __init__(self,min_confidence=70):
  self.min_confidence=min_confidence
  self.last_signal="WAIT"

 def evaluate(self,ind):
  if not ind.get("ready"):
   self.last_signal="WAIT"
   return {"signal":"WAIT","confidence":0,"reason":ind.get("reason","Insufficient data"),"votes":[]}

  v=ind["values"]
  call=put=0.0
  votes=[]

  def vote(name,direction,weight):
   nonlocal call,put
   if direction=="CALL":
    call+=weight
   elif direction=="PUT":
    put+=weight
   votes.append({"name":name,"direction":direction,"weight":round(weight,1)})

  # ALUCARD V4 TEST SCORING:
  # 9 indicators = 100 weighted points.
  # Alligator receives the strongest trend influence, but its weight is
  # reduced when the lines are compressed. ATR confirms active movement
  # and only becomes directional when volatility is active.
  jaw=v.get("alligator_jaw")
  teeth=v.get("alligator_teeth")
  lips=v.get("alligator_lips")
  atr=v.get("atr") or 0
  if jaw is not None and teeth is not None and lips is not None:
   spread=max(abs(lips-jaw),abs(teeth-jaw),abs(lips-teeth))
   width_ratio=(spread/atr) if atr>0 else 0
   base="CALL" if lips>teeth>jaw else "PUT" if lips<teeth<jaw else "WAIT"
   if base!="WAIT":
    # Tight Alligator = weak trend. Wide, ordered lines = strong trend.
    factor=min(1.0,max(0.30,width_ratio/1.5))
    vote("Alligator",base,15.0*factor)
   else:
    vote("Alligator","WAIT",0)
  else:
   vote("Alligator","WAIT",0)

  ema_dir="CALL" if v["ema9"]>v["ema20"]>v["ema50"] else "PUT" if v["ema9"]<v["ema20"]<v["ema50"] else "WAIT"
  vote("EMA 9/20/50",ema_dir,15)

  fd="CALL" if v.get("fractal_down") and not v.get("fractal_up") else "PUT" if v.get("fractal_up") and not v.get("fractal_down") else "WAIT"
  vote("Fractal (2)",fd,10)

  vote("Parabolic SAR","CALL" if v["price"]>v["psar"] else "PUT" if v["price"]<v["psar"] else "WAIT",10)

  vote("MACD","CALL" if v["macd_hist"]>0 else "PUT" if v["macd_hist"]<0 else "WAIT",10)

  r=v.get("rsi")
  # 50 is the directional center; extreme readings don't automatically
  # reverse the signal because overbought/oversold can persist in trends.
  vote("RSI (14)","CALL" if r is not None and r>50 else "PUT" if r is not None and r<50 else "WAIT",10)

  cci=v.get("cci")
  vote("CCI (14)","CALL" if cci is not None and cci>0 else "PUT" if cci is not None and cci<0 else "WAIT",10)

  bp=v.get("bb_pct")
  bm=v.get("bb_mid")
  vote("Bollinger 20/2",
       "CALL" if bp is not None and bm is not None and bp>0.50 and v["price"]>=bm
       else "PUT" if bp is not None and bm is not None and bp<0.50 and v["price"]<=bm
       else "WAIT",10)

  av=v.get("atr")
  ab=v.get("atr_baseline")
  atr_active=av is not None and ab is not None and av>=ab
  atr_dir="CALL" if atr_active and v["price"]>v["ema9"] else "PUT" if atr_active and v["price"]<v["ema9"] else "WAIT"
  vote("ATR (14)",atr_dir,10)

  # Agreement percentage is strictly the number of directional indicators
  # pointing the same way out of the 9-indicator model.
  leader_direction="CALL" if call>put else "PUT" if put>call else "WAIT"
  directional_votes=sum(1 for x in votes if x["direction"]==leader_direction)
  confidence=round(directional_votes/9*100,1)

  leader=max(call,put)
  opposing=min(call,put)
  weighted_margin=leader-opposing

  # Strong-signal gate: agreement plus weighted confirmation plus active ATR.
  # This prevents a high agreement count from firing during a compressed,
  # low-volatility market.
  strong_margin=weighted_margin>=15
  if leader_direction!="WAIT" and confidence>=self.min_confidence and strong_margin and atr_active:
   signal=leader_direction
   reason=f"{signal} confirmation: {directional_votes}/9 indicators agree ({confidence:.0f}%), weighted score {leader:.1f}/100"
  else:
   signal="WAIT"
   if not atr_active:
    reason=f"WAIT: volatility filter is inactive; ATR is not above its baseline"
   elif leader_direction=="WAIT":
    reason="WAIT: indicators are evenly split"
   else:
    reason=f"WAIT: {directional_votes}/9 agree ({confidence:.0f}%); weighted margin {weighted_margin:.1f}; confirmation gate not met"

  self.last_signal=signal
  return {
   "signal":signal,
   "confidence":confidence,
   "agreement_count":directional_votes,
   "agreement_total":9,
   "call_score":round(call,1),
   "put_score":round(put,1),
   "max_score":100,
   "atr_active":atr_active,
   "votes":votes,
   "reason":reason,
   "timestamp":datetime.now(timezone.utc).isoformat()
  }
