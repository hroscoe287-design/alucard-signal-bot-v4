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
  active_vote_count=0

  def vote(name,direction,weight):
   nonlocal call,put
   if direction=="CALL": call+=weight
   elif direction=="PUT": put+=weight
   if direction in ("CALL","PUT"): active_vote_count += 1
   votes.append({"name":name,"direction":direction,"weight":round(weight,2)})

  # ALUCARD V4 GROUPED DIRECTIONAL VOTING: related indicators have equal weight within each group.
  # Trend 30: Alligator/EMA/Supertrend; Momentum 24: MACD/OSMA/CCI;
  # Direction 21: RSI/DeMarker+WMA/Ichimoku; Price Action 15: PSAR/Bollinger/Stochastic;
  # Strength 10: DMI/ADX. Total directional weight = 100. ATR remains a volatility filter.
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
    vote("Alligator",base,10.0)
   else: vote("Alligator","WAIT",0)
  else:
   alligator_dir="WAIT"; vote("Alligator","WAIT",0)

  ema_dir="CALL" if v["ema9"]>v["ema20"]>v["ema50"] else "PUT" if v["ema9"]<v["ema20"]<v["ema50"] else "WAIT"
  vote("EMA 9/20/50",ema_dir,10)
  fd="CALL" if v.get("fractal_down") and not v.get("fractal_up") else "PUT" if v.get("fractal_up") and not v.get("fractal_down") else "WAIT"
  vote("Fractal (2)",fd,5)
  vote("Parabolic SAR","CALL" if v["price"]>v["psar"] else "PUT" if v["price"]<v["psar"] else "WAIT",5)
  vote("MACD 12/26/9","CALL" if v["macd_hist"]>0 else "PUT" if v["macd_hist"]<0 else "WAIT",8)

  r=v.get("rsi")
  vote("RSI (14)","CALL" if r is not None and r>50 else "PUT" if r is not None and r<50 else "WAIT",7)
  cci=v.get("cci")
  vote("CCI (14)","CALL" if cci is not None and cci>0 else "PUT" if cci is not None and cci<0 else "WAIT",8)

  bp=v.get("bb_pct"); bm=v.get("bb_mid")
  vote("Bollinger 20/2",
       "CALL" if bp is not None and bm is not None and bp>0.50 and v["price"]>=bm
       else "PUT" if bp is not None and bm is not None and bp<0.50 and v["price"]<=bm
       else "WAIT",5)

  av=v.get("atr"); ab=v.get("atr_baseline")
  # ATR is now a soft volatility filter instead of a hard signal gate.
  # Normal/low volatility can still participate when directional evidence agrees.
  # Only very low volatility suppresses the ATR vote itself.
  atr_ratio=(av/ab) if av is not None and ab not in (None,0) else None
  atr_active=atr_ratio is not None and atr_ratio>=0.80
  # Only severe compression blocks the ATR contribution. 0.60-0.80 is a
  # soft-volatility regime and can still produce a signal when direction agrees.
  atr_very_low=atr_ratio is not None and atr_ratio<0.60
  atr_dir="CALL" if not atr_very_low and v["price"]>v["ema9"] else "PUT" if not atr_very_low and v["price"]<v["ema9"] else "WAIT"
  # ATR remains a volatility filter, not a directional vote.

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

  # OSMA 10/20/24: independent momentum vote, equal to MACD/CCI.
  osma_hist=v.get("osma_hist")
  osma_signal=v.get("osma_signal")
  osma_dir="CALL" if osma_hist is not None and osma_hist>0 else "PUT" if osma_hist is not None and osma_hist<0 else "WAIT"

  # Ichimoku 9/26/52: independent direction/location vote.
  tenkan=v.get("ichimoku_tenkan"); kijun=v.get("ichimoku_kijun")
  span_a=v.get("ichimoku_span_a"); span_b=v.get("ichimoku_span_b")
  ichimoku_ready=all(x is not None for x in (tenkan,kijun,span_a,span_b))
  if ichimoku_ready:
   cloud_top=max(span_a,span_b); cloud_bottom=min(span_a,span_b)
   if v["price"]>cloud_top and tenkan>kijun: ichimoku_dir="CALL"
   elif v["price"]<cloud_bottom and tenkan<kijun: ichimoku_dir="PUT"
   else: ichimoku_dir="WAIT"
  else:
   ichimoku_dir="WAIT"

  # Add the newer directional voters before selecting the leader.
  vote("OSMA 10/20/24",osma_dir,8)
  vote("Ichimoku 9/26/52",ichimoku_dir,7)
  vote("DeMarker 9 + WMA 9",demarker_wma_dir,7)
  vote("Stochastic 14/3/3",stoch_dir,5)
  vote("DMI/ADX 14",dmi_dir,10)

  leader_direction="CALL" if call>put else "PUT" if put>call else "WAIT"
  directional_votes=sum(1 for x in votes if x["direction"]==leader_direction)
  confidence=round(directional_votes/active_vote_count*100,1) if active_vote_count else 0.0
  leader=max(call,put); opposing=min(call,put)
  weighted_margin=leader-opposing

  confirmation_bonus=0.0; conflict_penalty=0.0
  candle_direction=v.get("candle_direction","WAIT")
  candle_body_ratio=float(v.get("candle_body_ratio") or 0.0)
  candle_confirmed=bool(v.get("candle_confirmed",False))
  support=v.get("support"); resistance=v.get("resistance")
  near_support=bool(v.get("near_support",False)); near_resistance=bool(v.get("near_resistance",False))
  support_break=bool(v.get("support_break",False)); resistance_break=bool(v.get("resistance_break",False))
  sr_confirmation="WAIT"
  if leader_direction!="WAIT":
   if leader_direction=="CALL" and (support_break or resistance_break): sr_confirmation="CALL" if resistance_break else "WAIT"
   elif leader_direction=="PUT" and (support_break or resistance_break): sr_confirmation="PUT" if support_break else "WAIT"
   # Near support favors a bounce CALL; near resistance favors a rejection PUT.
   if leader_direction=="CALL" and near_support: confirmation_bonus+=2.0; sr_confirmation="CALL"
   elif leader_direction=="PUT" and near_resistance: confirmation_bonus+=2.0; sr_confirmation="PUT"
   elif leader_direction=="CALL" and near_resistance: conflict_penalty+=2.0; sr_confirmation="CONFLICT"
   elif leader_direction=="PUT" and near_support: conflict_penalty+=2.0; sr_confirmation="CONFLICT"
  candle_confirmation="WAIT"
  if leader_direction!="WAIT":
   if candle_confirmed and candle_direction==leader_direction:
    confirmation_bonus+=3.0
    candle_confirmation=leader_direction
   elif candle_confirmed and candle_direction in ("CALL","PUT") and candle_direction!=leader_direction:
    conflict_penalty+=3.0
    candle_confirmation="CONFLICT"

   if adx_ready and adx>=18:
    if dmi_dir==leader_direction: confirmation_bonus+=3.0
    elif dmi_dir in ("CALL","PUT"): conflict_penalty+=3.0
   if stoch_ready:
    if stoch_dir==leader_direction and ((leader_direction=="CALL" and sk<85) or (leader_direction=="PUT" and sk>15)):
     confirmation_bonus+=2.0
    elif stoch_dir in ("CALL","PUT") and ((leader_direction=="CALL" and sk>15) or (leader_direction=="PUT" and sk<85)):
     conflict_penalty+=2.0

   # Additional confirmation layers: small influence, never replacement votes.
   # OSMA confirms momentum; Ichimoku confirms broader trend/location.
   if osma_dir==leader_direction:
    confirmation_bonus+=2.0
   elif osma_dir in ("CALL","PUT"):
    conflict_penalty+=2.0

   if ichimoku_dir==leader_direction:
    confirmation_bonus+=2.0
   elif ichimoku_dir in ("CALL","PUT"):
    conflict_penalty+=2.0

   # DeMarker 9 + WMA 9: confirmation only; never a new weighted vote.
   dem=v.get("demarker"); dem_prev=v.get("demarker_prev")
   wma9=v.get("wma9"); wma9_prev=v.get("wma9_prev")
   demarker_wma_dir="WAIT"
   if all(x is not None for x in (dem,dem_prev,wma9,wma9_prev)):
    if dem>0.50 and dem>=dem_prev and v["price"]>wma9 and wma9>=wma9_prev:
     demarker_wma_dir="CALL"
    elif dem<0.50 and dem<=dem_prev and v["price"]<wma9 and wma9<=wma9_prev:
     demarker_wma_dir="PUT"
   if leader_direction!="WAIT":
    if demarker_wma_dir==leader_direction: confirmation_bonus+=3.0
    elif demarker_wma_dir in ("CALL","PUT"): conflict_penalty+=3.0

  # REAL-TIME CANDLE MOMENTUM: gives the newest 2-3 candles limited early influence
  # without changing the 10-indicator / 100-point model.
  m1=v.get("momentum_1") or 0.0; m2=v.get("momentum_2") or 0.0; m3=v.get("momentum_3") or 0.0
  momentum_side="CALL" if m1>0 and m2>0 and m3>0 else "PUT" if m1<0 and m2<0 and m3<0 else "WAIT"
  momentum_strength=(abs(m1)+abs(m2)+abs(m3)) if momentum_side!="WAIT" else 0.0
  momentum_same_count=sum(1 for x in (m1,m2,m3) if (x>0 if momentum_side=="CALL" else x<0)) if momentum_side!="WAIT" else 0
  momentum_bonus=0.0
  if leader_direction in ("CALL","PUT") and momentum_side==leader_direction and momentum_same_count>=2:
   momentum_bonus=min(4.0, 1.5 + momentum_same_count*0.8)
  adjusted_margin=weighted_margin+confirmation_bonus+momentum_bonus-conflict_penalty
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
   and confidence>=max(70.0,self.min_confidence-8)
   and trend_aligned and adjusted_margin>=6.0
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
   elif adjusted_margin < 6.0: reason=f"WAIT: {directional_votes}/10 agree ({confidence:.0f}%); directional margin {adjusted_margin:.1f} is too narrow"
   elif raw_candidate==self.developing_side and self.developing_strength>0:
    reason=f"WAIT: {directional_votes}/10 agree ({confidence:.0f}%); developing {raw_candidate} strength {self.developing_strength:.2f}"
   else: reason=f"WAIT: {directional_votes}/10 agree ({confidence:.0f}%); adjusted margin {adjusted_margin:.1f}; confirmation gate not met"

  self.last_signal=signal
  return {
   "signal":signal,"confidence":confidence,"agreement_count":directional_votes,"agreement_total":active_vote_count,
   "call_score":round(call,1),"put_score":round(put,1),"max_score":100,
   "atr_active":atr_active,"atr_ratio":round(atr_ratio,2) if atr_ratio is not None else None,
   "atr_very_low":atr_very_low,
   "adx":adx,"plus_di":plus_di,"minus_di":minus_di,"stoch_k":sk,"stoch_d":sd,
   "dmi_direction":dmi_dir,"stoch_direction":stoch_dir,"osma_direction":osma_dir,"osma_hist":osma_hist,"ichimoku_direction":ichimoku_dir,"demarker":dem,"wma9":wma9,"demarker_wma_direction":demarker_wma_dir,
   "confirmation_bonus":round(confirmation_bonus,1),"candle_confirmation":candle_confirmation,"support":support,"resistance":resistance,"near_support":near_support,"near_resistance":near_resistance,"support_break":support_break,"resistance_break":resistance_break,"sr_confirmation":sr_confirmation,"candle_direction":candle_direction,"candle_body_ratio":round(candle_body_ratio,3),"candle_confirmed":candle_confirmed,
   "momentum_bonus":round(momentum_bonus,1),"momentum_side":momentum_side,"momentum_same_count":momentum_same_count,
   "conflict_penalty":round(conflict_penalty,1),
   "reversal_conflict":reversal_conflict,"effective_min_confidence":effective_min_confidence,
   "developing_signal":self.developing_side,"developing_strength":round(self.developing_strength,2),
   "developing_age":round(developing_age,1),"early_confirmation":early_ok,
   "votes":votes,"reason":reason,"timestamp":datetime.now(timezone.utc).isoformat()
  }
