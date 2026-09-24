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

  # ALUCARD V4: 10 independent indicator votes, 100 weighted points.
  # Confidence is agreement count, not weighted score:
  # 10/10 = 100%, 9/10 = 90%, 8/10 = 80%, etc.
  #
  # Supertrend uses the widely used ATR 10 / multiplier 3.0 configuration.
  # There is no universally best setting; 10/3 is the standard baseline
  # used by major charting platforms and technical references.

  # 1) Williams Alligator — strongest trend influence.
  # Tight/compressed lines automatically reduce its weight.
  jaw=v.get("alligator_jaw")
  teeth=v.get("alligator_teeth")
  lips=v.get("alligator_lips")
  atr=v.get("atr") or 0
  if jaw is not None and teeth is not None and lips is not None:
   spread=max(abs(lips-jaw),abs(teeth-jaw),abs(lips-teeth))
   width_ratio=(spread/atr) if atr>0 else 0
   base="CALL" if lips>teeth>jaw else "PUT" if lips<teeth<jaw else "WAIT"
   alligator_dir=base
   if base!="WAIT":
    factor=min(1.0,max(0.30,width_ratio/1.5))
    vote("Alligator",base,15.0*factor)
   else:
    vote("Alligator","WAIT",0)
  else:
   alligator_dir="WAIT"
   vote("Alligator","WAIT",0)

  # 2) EMA 9/20/50 — trend confirmation.
  ema_dir="CALL" if v["ema9"]>v["ema20"]>v["ema50"] else "PUT" if v["ema9"]<v["ema20"]<v["ema50"] else "WAIT"
  vote("EMA 9/20/50",ema_dir,15)

  # 3) Fractal period 2 — swing confirmation.
  fd="CALL" if v.get("fractal_down") and not v.get("fractal_up") else "PUT" if v.get("fractal_up") and not v.get("fractal_down") else "WAIT"
  vote("Fractal (2)",fd,5)

  # 4) Parabolic SAR — direction confirmation.
  vote("Parabolic SAR","CALL" if v["price"]>v["psar"] else "PUT" if v["price"]<v["psar"] else "WAIT",10)

  # 5) MACD 12/26/9 — momentum.
  vote("MACD 12/26/9","CALL" if v["macd_hist"]>0 else "PUT" if v["macd_hist"]<0 else "WAIT",10)

  # 6) RSI 14 — directional momentum.
  r=v.get("rsi")
  vote("RSI (14)","CALL" if r is not None and r>50 else "PUT" if r is not None and r<50 else "WAIT",10)

  # 7) CCI 14 — momentum confirmation.
  cci=v.get("cci")
  vote("CCI (14)","CALL" if cci is not None and cci>0 else "PUT" if cci is not None and cci<0 else "WAIT",10)

  # 8) Bollinger Bands 20/2 — price-position confirmation.
  bp=v.get("bb_pct")
  bm=v.get("bb_mid")
  vote("Bollinger 20/2",
       "CALL" if bp is not None and bm is not None and bp>0.50 and v["price"]>=bm
       else "PUT" if bp is not None and bm is not None and bp<0.50 and v["price"]<=bm
       else "WAIT",10)

  # 9) ATR 14 — volatility filter + directional confirmation.
  av=v.get("atr")
  ab=v.get("atr_baseline")
  atr_active=av is not None and ab is not None and av>=ab
  atr_dir="CALL" if atr_active and v["price"]>v["ema9"] else "PUT" if atr_active and v["price"]<v["ema9"] else "WAIT"
  vote("ATR (14)",atr_dir,5)

  # 10) Supertrend — ATR 10 / multiplier 3.0.
  # direction +1 is bullish and -1 is bearish in our implementation.
  st=v.get("supertrend")
  st_dir=v.get("supertrend_direction")
  if st is not None and st_dir is not None:
   super_dir="CALL" if int(st_dir)==1 and v["price"]>st else "PUT" if int(st_dir)==-1 and v["price"]<st else "WAIT"
  else:
   super_dir="WAIT"
  vote("Supertrend 10/3",super_dir,10)

  leader_direction="CALL" if call>put else "PUT" if put>call else "WAIT"

  # Every indicator has exactly one vote. Confidence is the percentage
  # of the 10 indicators agreeing with the leading direction.
  directional_votes=sum(1 for x in votes if x["direction"]==leader_direction)
  confidence=round(directional_votes/10*100,1)

  leader=max(call,put)
  opposing=min(call,put)
  weighted_margin=leader-opposing

  # V4.1 confirmation layer: ADX/DMI + Stochastic are supporting filters,
  # not extra votes. This preserves the 10-indicator / 100-point model.
  adx=v.get("adx")
  plus_di=v.get("plus_di")
  minus_di=v.get("minus_di")
  sk=v.get("stoch_k")
  sd=v.get("stoch_d")
  adx_ready=adx is not None and plus_di is not None and minus_di is not None
  stoch_ready=sk is not None and sd is not None

  dmi_dir="CALL" if adx_ready and plus_di>minus_di else "PUT" if adx_ready and minus_di>plus_di else "WAIT"
  stoch_dir="CALL" if stoch_ready and sk>sd else "PUT" if stoch_ready and sk<sd else "WAIT"

  confirmation_bonus=0.0
  conflict_penalty=0.0
  if leader_direction!="WAIT":
   if adx_ready and adx>=18:
    if dmi_dir==leader_direction:
     confirmation_bonus+=3.0
    elif dmi_dir in ("CALL","PUT"):
     conflict_penalty+=3.0
   # Stochastic confirms momentum but is deliberately ignored as a reversal
   # signal when it is merely overbought/oversold.
   if stoch_ready:
    if stoch_dir==leader_direction and ((leader_direction=="CALL" and sk<85) or (leader_direction=="PUT" and sk>15)):
     confirmation_bonus+=2.0
    elif stoch_dir in ("CALL","PUT") and ((leader_direction=="CALL" and sk>15) or (leader_direction=="PUT" and sk<85)):
     conflict_penalty+=2.0

  adjusted_margin=weighted_margin+confirmation_bonus-conflict_penalty
  strong_margin=adjusted_margin>=13

  # Small V4 confirmation improvement: require at least 2 of the 3
  # primary trend indicators (Alligator, EMA, Supertrend) to agree with
  # the leading direction. This does not add points, so max_score stays 100
  # and confidence remains the simple 10-indicator agreement percentage.
  trend_votes=sum(1 for x in (alligator_dir,ema_dir,super_dir) if x==leader_direction)
  trend_aligned=trend_votes>=2

  # Only a strong multi-source reversal warning tightens the confidence gate.
  # This prevents WAIT from taking over during ordinary oscillator pullbacks.
  reversal_conflict = (
   leader_direction!="WAIT"
   and adx_ready and adx>=18
   and dmi_dir in ("CALL","PUT") and dmi_dir!=leader_direction
   and stoch_ready and stoch_dir in ("CALL","PUT") and stoch_dir!=leader_direction
   and ((leader_direction=="CALL" and sk<85) or (leader_direction=="PUT" and sk>15))
  )
  effective_min_confidence=self.min_confidence+10 if reversal_conflict else self.min_confidence

  # ATR must be active so high agreement does not fire in dead volatility.
  if leader_direction!="WAIT" and confidence>=effective_min_confidence and strong_margin and atr_active and trend_aligned:
   signal=leader_direction
   reason=f"{signal} confirmation: {directional_votes}/10 indicators agree ({confidence:.0f}%), trend alignment {trend_votes}/3, weighted score {leader:.1f}/100"
  else:
   signal="WAIT"
   if not atr_active:
    reason="WAIT: volatility filter is inactive; ATR is not above its baseline"
   elif leader_direction=="WAIT":
    reason="WAIT: indicators are evenly split"
   elif not trend_aligned:
    reason=f"WAIT: {directional_votes}/10 agree ({confidence:.0f}%); only {trend_votes}/3 primary trend indicators agree; trend alignment gate not met"
   else:
    reason=f"WAIT: {directional_votes}/10 agree ({confidence:.0f}%); adjusted margin {adjusted_margin:.1f}; confirmation gate not met"

  self.last_signal=signal
  return {
   "signal":signal,
   "confidence":confidence,
   "agreement_count":directional_votes,
   "agreement_total":10,
   "call_score":round(call,1),
   "put_score":round(put,1),
   "max_score":100,
   "atr_active":atr_active,
   "adx":adx,
   "plus_di":plus_di,
   "minus_di":minus_di,
   "stoch_k":sk,
   "stoch_d":sd,
   "dmi_direction":dmi_dir,
   "stoch_direction":stoch_dir,
   "confirmation_bonus":round(confirmation_bonus,1),
   "conflict_penalty":round(conflict_penalty,1),
   "reversal_conflict":reversal_conflict,
   "effective_min_confidence":effective_min_confidence,
   "votes":votes,
   "reason":reason,
   "timestamp":datetime.now(timezone.utc).isoformat()
  }
