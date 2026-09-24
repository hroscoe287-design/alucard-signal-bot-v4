from datetime import datetime,timezone

class SignalEngine:
 def __init__(self,min_confidence=70):
  self.min_confidence=min_confidence
  self.last_signal="WAIT"
  self.developing_side="WAIT"
  self.developing_strength=0.0
  self.developing_since=0.0

 def evaluate(self,ind):
  now=datetime.now(timezone.utc).timestamp()
  if not ind.get("ready"):
   self.last_signal="WAIT"
   self.developing_side="WAIT"
   self.developing_strength=0.0
   self.developing_since=0.0
   return {"signal":"WAIT","confidence":0,"reason":ind.get("reason","Insufficient data"),"votes":[],"developing_signal":"WAIT","developing_strength":0}

  v=ind["values"]
  call=put=0.0
  votes=[]

  def vote(name,direction,weight):
   nonlocal call,put
   if direction=="CALL": call+=weight
   elif direction=="PUT": put+=weight
   votes.append({"name":name,"direction":direction,"weight":round(weight,1)})

  # ALUCARD V4: 10 independent indicator votes, 100 weighted points.
  # Confidence remains the simple agreement percentage.
  # Supertrend baseline: ATR 10 / multiplier 3.0.

  jaw=v.get("alligator_jaw"); teeth=v.get("alligator_teeth"); lips=v.get("alligator_lips")
  atr=v.get("atr") or 0
  if jaw is not None and teeth is not None and lips is not None:
   spread=max(abs(lips-jaw),abs(teeth-jaw),abs(lips-teeth))
   width_ratio=(spread/atr) if atr>0 else 0
   base="CALL" if lips>teeth>jaw else "PUT" if lips<teeth<jaw else "WAIT"
   alligator_dir=base
   if base!="WAIT":
    # Keep Alligator as a full directional vote; width is confirmation, not a reason to erase direction.
    vote("Alligator",base,15.0)
   else: vote("Alligator","WAIT",0)
  else:
   alligator_dir="WAIT"; vote("Alligator","WAIT",0)

  ema_dir="CALL" if v["ema9"]>v["ema20"]>v["ema50"] else "PUT" if v["ema9"]<v["ema20"]<v["ema50"] else "WAIT"
  vote("EMA 9/20/50",ema_dir,15)
  fd="CALL" if v.get("fractal_down") and not v.get("fractal_up") else "PUT" if v.get("fractal_up") and not v.get("fractal_down") else "WAIT"
  vote("Fractal (2)",fd,5)
  vote("Parabolic SAR","CALL" if v["price"]>v["psar"] else "PUT" if v["price"]<v["psar"] else "WAIT",10)
  vote("MACD 12/26/9","CALL" if v["macd_hist"]>0 else "PUT" if v["macd_hist"]<0 else "WAIT",10)

  r=v.get("rsi")
  vote("RSI (14)","CALL" if r is not None and r>50 else "PUT" if r is not None and r<50 else "WAIT",10)
  cci=v.get("cci")
  vote("CCI (14)","CALL" if cci is not None and cci>0 else "PUT" if cci is not None and cci<0 else "WAIT",10)

  bp=v.get("bb_pct"); bm=v.get("bb_mid")
  vote("Bollinger 20/2",
       "CALL" if bp is not None and bm is not None and bp>0.50 and v["price"]>=bm
       else "PUT" if bp is not None and bm is not None and bp<0.50 and v["price"]<=bm
       else "WAIT",10)

  av=v.get("atr"); ab=v.get("atr_baseline")
  atr_active=av is not None and ab is not None and av>=ab
  atr_dir="CALL" if atr_active and v["price"]>v["ema9"] else "PUT" if atr_active and v["price"]<v["ema9"] else "WAIT"
  vote("ATR (14)",atr_dir,5)

  st=v.get("supertrend"); st_dir=v.get("supertrend_direction")
  if st is not None and st_dir is not None:
   super_dir="CALL" if int(st_dir)==1 and v["price"]>st else "PUT" if int(st_dir)==-1 and v["price"]<st else "WAIT"
  else: super_dir="WAIT"
  vote("Supertrend 10/3",super_dir,10)

  leader_direction="CALL" if call>put else "PUT" if put>call else "WAIT"
  directional_votes=sum(1 for x in votes if x["direction"]==leader_direction)
  confidence=round(directional_votes/10*100,1)
  leader=max(call,put); opposing=min(call,put)
  weighted_margin=leader-opposing

  adx=v.get("adx"); plus_di=v.get("plus_di"); minus_di=v.get("minus_di")
  sk=v.get("stoch_k"); sd=v.get("stoch_d")
  adx_ready=adx is not None and plus_di is not None and minus_di is not None
  stoch_ready=sk is not None and sd is not None
  dmi_dir="CALL" if adx_ready and plus_di>minus_di else "PUT" if adx_ready and minus_di>plus_di else "WAIT"
  stoch_dir="CALL" if stoch_ready and sk>sd else "PUT" if stoch_ready and sk<sd else "WAIT"

  confirmation_bonus=0.0; conflict_penalty=0.0
  if leader_direction!="WAIT":
   if adx_ready and adx>=18:
    if dmi_dir==leader_direction: confirmation_bonus+=3.0
    elif dmi_dir in ("CALL","PUT"): conflict_penalty+=3.0
   if stoch_ready:
    if stoch_dir==leader_direction and ((leader_direction=="CALL" and sk<85) or (leader_direction=="PUT" and sk>15)):
     confirmation_bonus+=2.0
    elif stoch_dir in ("CALL","PUT") and ((leader_direction=="CALL" and sk>15) or (leader_direction=="PUT" and sk<85)):
     conflict_penalty+=2.0

  # REAL-TIME CANDLE MOMENTUM: gives the newest 2-3 candles limited early influence\n  # without changing the 10-indicator / 100-point model.\n  m1=v.get("momentum_1") or 0.0; m2=v.get("momentum_2") or 0.0; m3=v.get("momentum_3") or 0.0\n  momentum_side="CALL" if m1>0 and m2>0 and m3>0 else "PUT" if m1<0 and m2<0 and m3<0 else "WAIT"\n  momentum_strength=(abs(m1)+abs(m2)+abs(m3)) if momentum_side!="WAIT" else 0.0\n  momentum_same_count=sum(1 for x in (m1,m2,m3) if (x>0 if momentum_side=="CALL" else x<0)) if momentum_side!="WAIT" else 0\n  momentum_bonus=0.0\n  if leader_direction in ("CALL","PUT") and momentum_side==leader_direction and momentum_same_count>=2:\n   momentum_bonus=min(4.0, 1.5 + momentum_same_count*0.8)\n  adjusted_margin=weighted_margin+confirmation_bonus+momentum_bonus-conflict_penalty
  strong_margin=adjusted_margin>=13
  trend_votes=sum(1 for x in (alligator_dir,ema_dir,super_dir) if x==leader_direction)
  trend_aligned=trend_votes>=2

  reversal_conflict=(
   leader_direction!="WAIT" and adx_ready and adx>=18
   and dmi_dir in ("CALL","PUT") and dmi_dir!=leader_direction
   and stoch_ready and stoch_dir in ("CALL","PUT") and stoch_dir!=leader_direction
   and ((leader_direction=="CALL" and sk<85) or (leader_direction=="PUT" and sk>15))
  )
  effective_min_confidence=self.min_confidence+10 if reversal_conflict else self.min_confidence

  # SELECTIVE ANTICIPATION:
  # A directional candidate must persist instead of firing on one tick.
  raw_candidate=leader_direction if leader_direction in ("CALL","PUT") else "WAIT"
  if raw_candidate=="WAIT":
   self.developing_strength=max(0.0,self.developing_strength-0.10)
   if self.developing_strength<=0.05:
    self.developing_side="WAIT"; self.developing_since=0.0
  elif raw_candidate!=self.developing_side:
   self.developing_side=raw_candidate
   self.developing_strength=0.25
   self.developing_since=now
  else:
   self.developing_strength=min(1.0,self.developing_strength+0.10)

  developing_age=(now-self.developing_since) if self.developing_since else 0.0
  candidate_persistent=(self.developing_side==raw_candidate and developing_age>=1.5 and self.developing_strength>=0.52)

  # Early confirmation is close to the normal gate:
  # 8/10 agreement, 2/3 primary trend alignment, active ATR,
  # adjusted margin >=9, persistent candidate, no strong reversal conflict.
  early_ok=(
   raw_candidate!="WAIT" and candidate_persistent
   and confidence>=max(80.0,self.min_confidence-4)
   and trend_aligned and adjusted_margin>=8.0
   and not reversal_conflict
  )

  full_ok=(
   leader_direction!="WAIT" and confidence>=effective_min_confidence
   and strong_margin and trend_aligned
  )

  if full_ok or early_ok:
   signal=leader_direction
   reason=(
    f"{signal} confirmation: {directional_votes}/10 indicators agree ({confidence:.0f}%), "
    f"trend alignment {trend_votes}/3, weighted score {leader:.1f}/100"
    if full_ok else
    f"{signal} developing confirmation: {directional_votes}/10 agree ({confidence:.0f}%), "
    f"trend alignment {trend_votes}/3, persistent momentum build"
   )
  else:
   signal="WAIT"
   if not trend_aligned: reason=f"WAIT: {directional_votes}/10 agree ({confidence:.0f}%); primary trend is not aligned enough"
   elif leader_direction=="WAIT": reason="WAIT: indicators are evenly split"
   elif adjusted_margin < 8.0: reason=f"WAIT: {directional_votes}/10 agree ({confidence:.0f}%); directional margin {adjusted_margin:.1f} is too narrow"
   elif raw_candidate==self.developing_side and self.developing_strength>0:
    reason=f"WAIT: {directional_votes}/10 agree ({confidence:.0f}%); developing {raw_candidate} strength {self.developing_strength:.2f}"
   else: reason=f"WAIT: {directional_votes}/10 agree ({confidence:.0f}%); adjusted margin {adjusted_margin:.1f}; confirmation gate not met"

  self.last_signal=signal
  return {
   "signal":signal,"confidence":confidence,"agreement_count":directional_votes,"agreement_total":10,
   "call_score":round(call,1),"put_score":round(put,1),"max_score":100,"atr_active":atr_active,
   "adx":adx,"plus_di":plus_di,"minus_di":minus_di,"stoch_k":sk,"stoch_d":sd,
   "dmi_direction":dmi_dir,"stoch_direction":stoch_dir,
   "confirmation_bonus":round(confirmation_bonus,1),"momentum_bonus":round(momentum_bonus,1),"momentum_side":momentum_side,"momentum_same_count":momentum_same_count,\n   "conflict_penalty":round(conflict_penalty,1),
   "reversal_conflict":reversal_conflict,"effective_min_confidence":effective_min_confidence,
   "developing_signal":self.developing_side,"developing_strength":round(self.developing_strength,2),
   "developing_age":round(developing_age,1),"early_confirmation":early_ok,
   "votes":votes,"reason":reason,"timestamp":datetime.now(timezone.utc).isoformat()
  }
