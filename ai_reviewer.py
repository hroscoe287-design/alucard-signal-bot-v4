import json
import os
import time
import urllib.request

class AIReviewer:
 def __init__(self):
  self.api_key=os.getenv("OPENAI_API_KEY","").strip()
  self.model=os.getenv("OPENAI_MODEL","gpt-5.6-luna")
  self.enabled=os.getenv("AI_CONFIRMATION_ENABLED","true").lower() not in ("0","false","no")
  self.timeout=float(os.getenv("AI_CONFIRMATION_TIMEOUT","3.5"))

 def review(self, asset, timeframe, engine_result, indicators, candles):
  if not self.enabled or not self.api_key:
   return {"enabled":False,"decision":"NO_REVIEW","reason":"AI confirmation is not configured"}
  candidate=engine_result.get("signal","WAIT")
  if candidate not in ("CALL","PUT"):
   return {"enabled":True,"decision":"WAIT","reason":"ALUCARD did not produce a CALL/PUT candidate"}
  compact={k:indicators.get(k) for k in (
   "price","ema9","ema20","ema50","alligator_jaw","alligator_teeth","alligator_lips",
   "psar","macd_hist","rsi","cci","bb_pct","bb_width","adx","plus_di","minus_di",
   "stoch_k","stoch_d","atr","atr_baseline","supertrend","supertrend_direction",
   "momentum_1","momentum_2","momentum_3")}
  recent=[]
  for c in (candles or [])[-8:]:
   recent.append({k:c.get(k) for k in ("ts","open","high","low","close") if k in c})
  payload={
   "model":self.model,
   "input":[
    {"role":"system","content":"You are the independent confirmation layer for ALUCARD V4. Review only the supplied market/engine snapshot. Do not invent missing data. Return JSON with decision CALL, PUT, or WAIT. Be conservative: confirm the candidate only when the directional evidence is coherent and not obviously stale, overextended, or internally conflicted. If evidence is insufficient or conflicting, return WAIT. This is signal analysis, not order execution."},
    {"role":"user","content":json.dumps({
      "asset":asset,"timeframe":timeframe,"engine_candidate":candidate,
      "engine":engine_result,"indicators":compact,"recent_candles":recent
    },separators=(",",":"))}
   ],
   "max_output_tokens":120
  }
  req=urllib.request.Request(
   "https://api.openai.com/v1/responses",
   data=json.dumps(payload).encode(),
   headers={"Authorization":"Bearer "+self.api_key,"Content-Type":"application/json"},
   method="POST")
  try:
   with urllib.request.urlopen(req,timeout=self.timeout) as resp:
    data=json.loads(resp.read().decode())
   text=""
   for item in data.get("output",[]):
    for part in item.get("content",[]):
     if part.get("type")=="output_text":
      text+=part.get("text","")
   parsed=json.loads(text)
   decision=str(parsed.get("decision","WAIT")).upper()
   if decision not in ("CALL","PUT","WAIT"): decision="WAIT"
   return {"enabled":True,"decision":decision,"reason":str(parsed.get("reason","AI confirmation complete"))[:300],"model":self.model}
  except Exception as exc:
   return {"enabled":True,"decision":"WAIT","reason":"AI review unavailable: "+str(exc)[:180],"model":self.model}
