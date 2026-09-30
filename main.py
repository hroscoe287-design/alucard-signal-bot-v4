import asyncio,logging,time
from fastapi import FastAPI,Request
from fastapi.responses import HTMLResponse
from config import APP_NAME,ASSETS,TIMEFRAMES,FOREX,settings
from candles import CandleBuilder
from indicators import calculate
from engine import SignalEngine
from pocket_feed import PocketOptionFeed
from pro_guards import apply_pro_guards
from backtest import run_backtest
logging.basicConfig(level=logging.INFO)
app=FastAPI(title=APP_NAME)
builder=CandleBuilder(TIMEFRAMES.get(settings.timeframe,60),settings.history_size)
engine=SignalEngine(settings.min_confidence)

# High-margin background scanner: separate feed so it never interrupts the user's selected pair.
SCAN_ASSETS=sorted(set(sum(ASSETS.values(),[])))
scanner_builders={}
scanner_engines={}
scanner_ticks={}
scanner_entry={}
scanner_candidates=[]
scanner_feed=None
scanner_task=None
scanner_loop_task=None

def scanner_history(asset, candles):
    asset=str(asset).lstrip("#")
    b=scanner_builders.setdefault(asset,CandleBuilder(TIMEFRAMES.get(state["timeframe"],60),settings.history_size))
    b.load_candles(candles)
    scanner_ticks.setdefault(asset,0.0)

def scanner_tick(asset, price, ts):
    asset=str(asset).lstrip("#")
    b=scanner_builders.setdefault(asset,CandleBuilder(TIMEFRAMES.get(state["timeframe"],60),settings.history_size))
    b.update(price,ts)
    scanner_ticks[asset]=time.time()

def _scanner_entry_window(asset, direction, confidence, candle_ts, tf):
    now=time.time()
    key=scanner_entry.get(asset)
    bucket=int((candle_ts or now)//tf)*tf
    candle_close=bucket+tf
    if key and key["direction"]==direction and key["bucket"]==bucket and key["until"]>now:
        return key["until"]
    strength=max(0.0,min(1.0,(float(confidence or 0)-settings.min_confidence)/max(1.0,100.0-settings.min_confidence)))
    window=max(5.0,min(tf*0.40,tf*(0.15+0.25*strength)))
    until=min(candle_close,now+window)
    scanner_entry[asset]={"direction":direction,"bucket":bucket,"until":until}
    return until

def refresh_scanner():
    global scanner_candidates
    ranked=[]
    tf=TIMEFRAMES.get(state["timeframe"],60)
    now=time.time()
    for asset,b in list(scanner_builders.items()):
        if len(b.candles)<30:
            continue
        result=calculate(b.snapshot())
        eng=scanner_engines.setdefault(asset,SignalEngine(settings.min_confidence))
        sig=eng.evaluate(result)
        age=now-scanner_ticks.get(asset,0) if scanner_ticks.get(asset) else 9999
        direction=sig.get("signal","WAIT")
        margin=float(sig.get("adjusted_margin",0) or 0)
        confidence=float(sig.get("confidence",0) or 0)
        if age<=settings.stale_seconds and direction in ("CALL","PUT") and 90 <= margin <= 120:
            candle_ts=b.candles[-1].ts
            until=_scanner_entry_window(asset,direction,confidence,candle_ts,tf)
            remaining=max(0.0,until-now)
            if remaining>0:
                ranked.append({"asset":asset,"signal":direction,"margin":round(margin,1),"confidence":round(confidence,1),"setup_probability":round(float(sig.get("setup_probability",0) or 0),1),"core_trend":direction,"core_agreement":sig.get("core_agreement",0),"age":round(age,2),"entry_remaining":round(remaining,1),"entry_open":True,"reason":sig.get("reason","")})
        else:
            scanner_entry.pop(asset,None)
    ranked.sort(key=lambda x:(105 <= x["margin"] <= 115,x["margin"],x["setup_probability"],x["confidence"]),reverse=True)
    scanner_candidates=ranked[:10]
    return scanner_candidates

async def scanner_loop():
    while True:
        try:
            refresh_scanner()
            await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception("High-margin scanner cycle failed")
            await asyncio.sleep(1.0)

state={"asset":settings.asset,"timeframe":settings.timeframe,"price":None,"last_tick":0.0,"signal":{"signal":"WAIT","confidence":0,"reason":"Waiting for market data"},"indicators":{},"entry_until":0.0,"entry_signal":"WAIT"}
feed=None
feed_task=None
signal_task=None
signal_generation=0
def refresh_entry_window(signal, candle_ts=None):
 now=time.time()
 direction=signal.get("signal","WAIT")
 confidence=float(signal.get("confidence",0) or 0)
 tf=TIMEFRAMES.get(state["timeframe"],60)
 if direction in ("CALL","PUT") and confidence >= settings.min_confidence:
  bucket=int((candle_ts or now)//tf)*tf
  candle_close=bucket+tf
  # Timeframe-aware entry window: no fixed 12-second lock.
  # Stronger signals receive more of the available candle, but never
  # beyond the current candle close.
  strength=max(0.0,min(1.0,(confidence-settings.min_confidence)/max(1.0,100.0-settings.min_confidence)))
  window=max(5.0,min(tf*0.40,tf*(0.15+0.25*strength)))
  proposed=min(candle_close,now+window)
  if state["entry_signal"] != direction or state["entry_until"] <= now:
   state["entry_until"]=proposed
   state["entry_signal"]=direction
 else:
  state["entry_until"]=0.0
  state["entry_signal"]="WAIT"


def on_history(candles):
 loaded=builder.load_candles(candles)
 if loaded:
  result=calculate(builder.snapshot())
  state["indicators"]=result.get("values",{})
  state["signal"]=engine.evaluate(result)
  state["signal"]=apply_pro_guards(state["signal"],state["indicators"],last_tick=state["last_tick"],timeframe_seconds=builder.timeframe,candle_ts=builder.candles[-1].ts if builder.candles else None)
  refresh_entry_window(state["signal"], builder.candles[-1].ts if builder.candles else None)

async def process_latest_ticks():
 global signal_task
 try:
  while True:
   generation=signal_generation
   snapshot=builder.snapshot()
   result=await asyncio.to_thread(calculate,snapshot)
   if generation!=signal_generation:
    continue
   state["indicators"]=result.get("values",{})
   state["signal"]=engine.evaluate(result)
   state["signal"]=apply_pro_guards(state["signal"],state["indicators"],last_tick=state["last_tick"],timeframe_seconds=builder.timeframe,candle_ts=builder.candles[-1].ts if builder.candles else None)
   refresh_entry_window(state["signal"],snapshot[-1]["ts"] if snapshot else None)
   if generation==signal_generation:
    break
 finally:
  signal_task=None

def on_tick(asset,price,ts):
 global signal_task,signal_generation
 if asset and asset.lower()!=state["asset"].lower():return
 state["price"]=price
 state["last_tick"]=time.time()
 builder.update(price,ts)
 signal_generation+=1
 if signal_task is None or signal_task.done():
  signal_task=asyncio.create_task(process_latest_ticks())
@app.on_event("startup")
async def startup():
 global feed,feed_task,scanner_feed,scanner_task,scanner_loop_task
 feed=PocketOptionFeed(settings.ws_url,settings.auth_json,on_tick,on_history,asset=state["asset"],period=TIMEFRAMES.get(state["timeframe"],60))
 feed_task=asyncio.create_task(feed.run())
 scanner_feed=PocketOptionFeed(settings.ws_url,settings.auth_json,scanner_tick,asset=SCAN_ASSETS[0],period=TIMEFRAMES.get(settings.timeframe,60),assets=SCAN_ASSETS,on_history_asset=scanner_history)
 scanner_task=asyncio.create_task(scanner_feed.run())
 scanner_loop_task=asyncio.create_task(scanner_loop())
 logging.info("%s started; auth configured=%s; background scanner assets=%d",APP_NAME,bool(settings.auth_json),len(SCAN_ASSETS))
@app.on_event("shutdown")
async def shutdown():
 if feed:await feed.stop()
 if scanner_feed:await scanner_feed.stop()
 if feed_task:feed_task.cancel()
 if scanner_task:scanner_task.cancel()
 if scanner_loop_task:scanner_loop_task.cancel()
@app.get("/api/health")
async def health():
 age=time.time()-state["last_tick"] if state["last_tick"] else None
 live=bool(feed and feed.connected and age is not None and age<=settings.stale_seconds)
 return {"service":APP_NAME,"feed":"LIVE" if live else "WAITING","engine":"READY" if builder.candles else "WAITING_FOR_FEED","last_tick_age":age,"feed_tick_latency_ms":feed.last_tick_latency_ms if feed else None,"feed_tick_source":feed.last_tick_source if feed else "","auth_configured":bool(settings.auth_json),"error":feed.last_error if feed else ""}
@app.get("/api/scanner")
async def api_scanner():
 return {"threshold":90,"max_margin":120,"priority_band":[105,115],"candidates":scanner_candidates}

@app.get("/api/state")
async def api_state():
 age=time.time()-state["last_tick"] if state["last_tick"] else None
 entry_remaining=max(0.0,state["entry_until"]-time.time()) if state["entry_until"] else 0.0
 if state["entry_until"] and (state["entry_signal"] != state["signal"].get("signal") or state["signal"].get("signal") not in ("CALL","PUT")):
  state["entry_until"]=0.0; state["entry_signal"]="WAIT"; entry_remaining=0.0
 return {"app":APP_NAME,"asset":state["asset"],"timeframe":state["timeframe"],"payout":settings.payout,"expiry":settings.expiry_minutes,"price":state["price"],"last_tick_age":age,"feed_tick_latency_ms":feed.last_tick_latency_ms if feed else None,"feed_tick_source":feed.last_tick_source if feed else "","feed_connected":bool(feed and feed.connected),"candles":builder.snapshot()[-120:],"indicators":state["indicators"],"signal":state["signal"],"scanner":{"threshold":90,"max_margin":120,"priority_band":[105,115],"candidates":scanner_candidates},"entry_remaining":round(entry_remaining,1),"entry_open":entry_remaining>0}
@app.get("/api/backtest")
async def api_backtest():
 return run_backtest(builder.snapshot(),settings.min_confidence,150)
@app.get("/api/assets")
async def assets():return {"assets":ASSETS,"timeframes":list(TIMEFRAMES)}
@app.post("/api/config")
async def config(request:Request):
 global builder
 body=await request.json()
 new_asset=body.get("asset") if body.get("asset") in sum(ASSETS.values(),[]) else state["asset"]
 new_tf=body.get("timeframe") if body.get("timeframe") in TIMEFRAMES else state["timeframe"]
 changed_asset=new_asset!=state["asset"]
 changed_tf=new_tf!=state["timeframe"]
 state["asset"]=new_asset
 state["timeframe"]=new_tf
 builder=CandleBuilder(TIMEFRAMES[new_tf],settings.history_size)
 state["price"]=None
 state["last_tick"]=0.0
 state["indicators"]={}
 state["entry_until"]=0.0
 state["entry_signal"]="WAIT"
 state["signal"]={"signal":"WAIT","confidence":0,"reason":"Loading selected market data","votes":[]}
 state["ai_review"]={"enabled":False,"decision":"NO_REVIEW","reason":"AI confirmation not configured"}
 if feed:
  try:
   await feed.change_subscription(new_asset,TIMEFRAMES[new_tf])
  except Exception as exc:
   logging.exception("configuration change failed")
   return {"ok":False,"asset":new_asset,"timeframe":new_tf,"error":str(exc)}
 return {"ok":True,"asset":new_asset,"timeframe":new_tf,"changed_asset":changed_asset,"changed_timeframe":changed_tf}
HTML='''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>ALUCARD V4</title><style>
*{box-sizing:border-box}body{margin:0;background:#08090d;color:#e9e9ee;font-family:system-ui,sans-serif}header{padding:18px 22px;border-bottom:1px solid #262833;background:#0d0e14}h1{margin:0;font-size:22px;letter-spacing:2px}.wrap{max-width:1200px;margin:auto;padding:18px}small,.label,.foot{color:#858b9b}.tabs,.controls{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}.tab,select,button,.status{background:#151823;color:#eee;border:1px solid #343846;border-radius:8px;padding:9px 12px}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.card{background:#11131b;border:1px solid #252834;border-radius:12px;padding:15px;margin-top:12px}.label{font-size:11px;text-transform:uppercase}.value{font-size:23px;margin-top:7px;font-weight:700}.signal{font-size:32px;letter-spacing:2px}.call{color:#56e39f}.put{color:#ff6577}.wait{color:#f1c75b}.chart{height:280px;display:flex;align-items:flex-end;gap:3px;overflow:hidden}.bar{width:7px;min-height:4px}.up{background:#56e39f}.down{background:#ff6577}.matrix{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.matrix div{padding:10px;background:#171923;border-radius:7px;font-size:12px}.foot{font-size:12px;margin-top:18px}@media(max-width:800px){.grid{grid-template-columns:1fr 1fr}.matrix{grid-template-columns:1fr 1fr}}@media(max-width:500px){.value{font-size:18px}.signal{font-size:27px}}
</style></head><body><header><div class="wrap"><h1>☠ ALUCARD SIGNAL BOT V4.0</h1><small>GOTHIC MARKET INTELLIGENCE • LIVE SIGNAL ENGINE</small></div></header><main class="wrap"><div class="tabs"><div class="tab">Signals</div><div class="tab">Trades</div><div class="tab">Performance</div><div class="tab">Settings</div></div><div class="controls"><select id="asset"></select><select id="tf"></select><button onclick="applyCfg()">APPLY</button><span id="feed" class="status">FEED: WAITING</span><span id="feedAge" class="status">AGE: —</span><span id="eng" class="status">ENGINE: WAITING</span></div><div class="grid"><div class="card"><div class="label">Signal</div><div id="sig" class="value signal wait">WAIT</div></div><div class="card"><div class="label">Entry Window</div><div id="count" class="value">—</div><small id="entryStatus">WAITING FOR SIGNAL</small></div><div class="card"><div class="label">LIVE CLOCK</div><div id="clock" class="value">--:--:--</div><small>LOCAL TIME • RUNNING</small></div><div class="card"><div class="label">Confidence</div><div id="conf" class="value">0%</div></div><div class="card"><div class="label">Asset</div><div id="as" class="value">EURUSD_otc</div></div><div class="card"><div class="label">Price</div><div id="price" class="value">—</div></div></div><div class="card"><div class="label">Market candles</div><div id="chart" class="chart"></div></div><div class="card"><div class="label">Indicator matrix</div><div id="matrix" class="matrix"></div></div><div class="card"><div class="label">Engine reason</div><div id="reason" style="margin-top:8px">Waiting for live market data.</div></div><div class="card"><div class="label">HIGH-MARGIN SETUPS — LIVE</div><div id="scanner">SCANNING FEED…</div><small>90–120% margin • 105–115% priority</small></div><div class="foot">Signal-only architecture. No order execution is enabled. Entry window is dynamic and closes early if confirmation is lost.</div></main><script>
const $=x=>document.getElementById(x);
async function init(){const a=await fetch('/api/assets').then(r=>r.json());for(const[g,items]of Object.entries(a.assets)){const o=document.createElement('optgroup');o.label=g;items.forEach(v=>{const q=document.createElement('option');q.value=v;q.textContent=v;o.appendChild(q)});$('asset').appendChild(o)}$('asset').value='EURUSD_otc';a.timeframes.forEach(v=>{const q=document.createElement('option');q.value=v;q.textContent=v;$('tf').appendChild(q)});$('tf').value='1m';poll()}
async function applyCfg(){const r=await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({asset:$('asset').value,timeframe:$('tf').value})});const d=await r.json();if(!d.ok)alert(d.error||'Configuration change failed')}
function draw(c){$('chart').innerHTML=c.map(x=>'<div class="bar '+(x.close>=x.open?'up':'down')+'" style="height:'+Math.max(6,Math.min(100,Math.abs(x.close-x.open)/(x.high-x.low||1)*100))+'%"></div>').join('')}
function updateClock(){const d=new Date();$('clock').textContent=d.toLocaleTimeString([], {hour12:false,hour:'2-digit',minute:'2-digit',second:'2-digit'});}
setInterval(updateClock,250);updateClock();
async function poll(){try{const[s,h]=await Promise.all([fetch('/api/state').then(r=>r.json()),fetch('/api/health').then(r=>r.json())]);$('as').textContent=s.asset;$('price').textContent=s.price??'—';$('feed').textContent='FEED: '+h.feed;$('feedAge').textContent='AGE: '+(h.last_tick_age==null?'—':h.last_tick_age.toFixed(2)+'s')+' • NET '+(h.feed_tick_latency_ms==null?'—':h.feed_tick_latency_ms.toFixed(0)+'ms');$('eng').textContent='ENGINE: '+h.engine;const z=s.signal||{};$('sig').textContent=z.signal||'WAIT';const rem=Math.max(0,s.entry_remaining||0);$('count').textContent=(z.signal==='CALL'||z.signal==='PUT')&&rem>0?('00:'+String(Math.ceil(rem)).padStart(2,'0')):'00:00';$('entryStatus').textContent=(z.signal==='CALL'||z.signal==='PUT')&&rem>0?'ENTRY OPEN — VALIDATION ACTIVE':'ENTRY CLOSED — WAIT FOR NEXT SIGNAL';$('sig').className='value signal '+(z.signal||'WAIT').toLowerCase();$('conf').textContent=(z.confidence||0)+'%';$('reason').textContent=z.reason||'';const sc=(s.scanner||{}).candidates||[];
$('scanner').innerHTML=sc.length?sc.slice(0,5).map((x,i)=>'<div style="margin:8px 0;padding:8px;background:#171923;border-radius:7px"><b>#'+(i+1)+' '+x.asset+'</b> • <span class="'+x.signal.toLowerCase()+'">'+x.signal+'</span><br><small>CORE TREND: '+x.core_trend+' • MARGIN: <b>'+x.margin.toFixed(1)+'%</b>'+(x.margin>=105&&x.margin<=115?' 🔥':'')+' • CONF: '+x.confidence.toFixed(0)+'%</small><br><b>ENTRY: <span id="scan-'+i+'">00:'+String(Math.ceil(x.entry_remaining)).padStart(2,'0')+'</span></b> • '+(x.entry_open?'ENTRY OPEN':'ENTRY CLOSED')+'</div>').join(''):'NO HIGH-MARGIN SETUP';draw(s.candles||[]);const v=s.indicators||{};const rows=[['EMA 9 / 20 / 50',v.ema9?[v.ema9,v.ema20,v.ema50].map(x=>x.toFixed(5)).join(' / '):'—'],['Alligator',v.alligator_lips?[v.alligator_lips,v.alligator_teeth,v.alligator_jaw].map(x=>x.toFixed(5)).join(' / '):'—'],['Parabolic SAR',v.psar?.toFixed(5)||'—'],['MACD histogram',v.macd_hist?.toFixed(5)||'—'],['RSI',v.rsi?.toFixed(2)||'—'],['CCI',v.cci?.toFixed(2)||'—'],['Bollinger 20/2',v.bb_pct!=null?('%B '+v.bb_pct.toFixed(2)+' • W '+v.bb_width.toFixed(4)):'—'],['ADX / DMI',v.adx!=null?('ADX '+v.adx.toFixed(1)+' • +DI '+v.plus_di.toFixed(1)+' • -DI '+v.minus_di.toFixed(1)):'—'],['Fractal Chaos Bands',v.fcb_mid!=null?((v.fcb_direction||'WAIT')+' • mid '+v.fcb_mid.toFixed(5)):'—'],['Stochastic',v.stoch_k!=null?('%K '+v.stoch_k.toFixed(1)+' • %D '+v.stoch_d.toFixed(1)):'—']];$('matrix').innerHTML=rows.map(r=>'<div><b>'+r[0]+'</b><br>'+r[1]+'</div>').join('')}catch(e){}setTimeout(poll,250)}init()
</script></body></html>'''
@app.get("/",response_class=HTMLResponse)
async def home():return HTML
