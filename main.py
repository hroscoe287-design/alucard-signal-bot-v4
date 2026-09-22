import asyncio,logging,time
from fastapi import FastAPI,Request
from fastapi.responses import HTMLResponse
from config import APP_NAME,ASSETS,TIMEFRAMES,settings
from candles import CandleBuilder
from indicators import calculate
from engine import SignalEngine
from pocket_feed import PocketOptionFeed
logging.basicConfig(level=logging.INFO)
app=FastAPI(title=APP_NAME)
builder=CandleBuilder(TIMEFRAMES.get(settings.timeframe,60),settings.history_size)
engine=SignalEngine(settings.min_confidence)
state={"asset":settings.asset,"price":None,"last_tick":0.0,"signal":{"signal":"WAIT","confidence":0,"reason":"Waiting for market data"},"indicators":{}}
feed=None
feed_task=None
def on_history(candles):
 loaded=builder.load_candles(candles)
 if loaded:
  result=calculate(builder.snapshot());state["indicators"]=result.get("values",{});state["signal"]=engine.evaluate(result)

def on_tick(asset,price,ts):
 if asset and asset.lower()!=state["asset"].lower():return
 state["price"]=price;state["last_tick"]=ts;builder.update(price,ts)
 result=calculate(builder.snapshot());state["indicators"]=result.get("values",{});state["signal"]=engine.evaluate(result)
@app.on_event("startup")
async def startup():
 global feed,feed_task
 feed=PocketOptionFeed(settings.ws_url,settings.auth_json,on_tick,on_history);feed_task=asyncio.create_task(feed.run())
 logging.info("%s started; auth configured=%s",APP_NAME,bool(settings.auth_json))
@app.on_event("shutdown")
async def shutdown():
 if feed:await feed.stop()
 if feed_task:feed_task.cancel()
@app.get("/api/health")
async def health():
 age=time.time()-state["last_tick"] if state["last_tick"] else None
 live=bool(feed and feed.connected and age is not None and age<=settings.stale_seconds)
 return {"service":APP_NAME,"feed":"LIVE" if live else "WAITING","engine":"READY" if builder.candles else "WAITING_FOR_FEED","last_tick_age":age,"auth_configured":bool(settings.auth_json),"error":feed.last_error if feed else ""}
@app.get("/api/state")
async def api_state():
 age=time.time()-state["last_tick"] if state["last_tick"] else None
 return {"app":APP_NAME,"asset":state["asset"],"timeframe":settings.timeframe,"payout":settings.payout,"expiry":settings.expiry_minutes,"price":state["price"],"last_tick_age":age,"feed_connected":bool(feed and feed.connected),"candles":builder.snapshot()[-120:],"indicators":state["indicators"],"signal":state["signal"]}
@app.get("/api/assets")
async def assets():return {"assets":ASSETS,"timeframes":list(TIMEFRAMES)}
@app.post("/api/config")
async def config(request:Request):
 global builder
 body=await request.json()
 if body.get("asset") in sum(ASSETS.values(),[]):state["asset"]=body["asset"]
 tf=body.get("timeframe")
 if tf in TIMEFRAMES:builder=CandleBuilder(TIMEFRAMES[tf],settings.history_size)
 return {"ok":True,"asset":state["asset"],"timeframe":tf or settings.timeframe}
HTML='''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>ALUCARD V4</title><style>
*{box-sizing:border-box}body{margin:0;background:#08090d;color:#e9e9ee;font-family:system-ui,sans-serif}header{padding:18px 22px;border-bottom:1px solid #262833;background:#0d0e14}h1{margin:0;font-size:22px;letter-spacing:2px}.wrap{max-width:1200px;margin:auto;padding:18px}small,.label,.foot{color:#858b9b}.tabs,.controls{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}.tab,select,button,.status{background:#151823;color:#eee;border:1px solid #343846;border-radius:8px;padding:9px 12px}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.card{background:#11131b;border:1px solid #252834;border-radius:12px;padding:15px;margin-top:12px}.label{font-size:11px;text-transform:uppercase}.value{font-size:23px;margin-top:7px;font-weight:700}.signal{font-size:32px;letter-spacing:2px}.call{color:#56e39f}.put{color:#ff6577}.wait{color:#f1c75b}.chart{height:280px;display:flex;align-items:flex-end;gap:3px;overflow:hidden}.bar{width:7px;min-height:4px}.up{background:#56e39f}.down{background:#ff6577}.matrix{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.matrix div{padding:10px;background:#171923;border-radius:7px;font-size:12px}.foot{font-size:12px;margin-top:18px}@media(max-width:800px){.grid{grid-template-columns:1fr 1fr}.matrix{grid-template-columns:1fr 1fr}}@media(max-width:500px){.value{font-size:18px}.signal{font-size:27px}}
</style></head><body><header><div class="wrap"><h1>☠ ALUCARD SIGNAL BOT V4.0</h1><small>GOTHIC MARKET INTELLIGENCE • LIVE SIGNAL ENGINE</small></div></header><main class="wrap"><div class="tabs"><div class="tab">Signals</div><div class="tab">Trades</div><div class="tab">Performance</div><div class="tab">Settings</div></div><div class="controls"><select id="asset"></select><select id="tf"></select><button onclick="applyCfg()">APPLY</button><span id="feed" class="status">FEED: WAITING</span><span id="eng" class="status">ENGINE: WAITING</span></div><div class="grid"><div class="card"><div class="label">Signal</div><div id="sig" class="value signal wait">WAIT</div></div><div class="card"><div class="label">Confidence</div><div id="conf" class="value">0%</div></div><div class="card"><div class="label">Asset</div><div id="as" class="value">EURUSD_otc</div></div><div class="card"><div class="label">Price</div><div id="price" class="value">—</div></div></div><div class="card"><div class="label">Market candles</div><div id="chart" class="chart"></div></div><div class="card"><div class="label">Indicator matrix</div><div id="matrix" class="matrix"></div></div><div class="card"><div class="label">Engine reason</div><div id="reason" style="margin-top:8px">Waiting for live market data.</div></div><div class="foot">Signal-only architecture. No order execution is enabled.</div></main><script>
const $=x=>document.getElementById(x);
async function init(){const a=await fetch('/api/assets').then(r=>r.json());for(const[g,items]of Object.entries(a.assets)){const o=document.createElement('optgroup');o.label=g;items.forEach(v=>{const q=document.createElement('option');q.value=v;q.textContent=v;o.appendChild(q)});$('asset').appendChild(o)}$('asset').value='EURUSD_otc';a.timeframes.forEach(v=>{const q=document.createElement('option');q.value=v;q.textContent=v;$('tf').appendChild(q)});$('tf').value='1m';poll()}
async function applyCfg(){await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({asset:$('asset').value,timeframe:$('tf').value})})}
function draw(c){$('chart').innerHTML=c.map(x=>'<div class="bar '+(x.close>=x.open?'up':'down')+'" style="height:'+Math.max(6,Math.min(100,Math.abs(x.close-x.open)/(x.high-x.low||1)*100))+'%"></div>').join('')}
async function poll(){try{const[s,h]=await Promise.all([fetch('/api/state').then(r=>r.json()),fetch('/api/health').then(r=>r.json())]);$('as').textContent=s.asset;$('price').textContent=s.price??'—';$('feed').textContent='FEED: '+h.feed;$('eng').textContent='ENGINE: '+h.engine;const z=s.signal||{};$('sig').textContent=z.signal||'WAIT';$('sig').className='value signal '+(z.signal||'WAIT').toLowerCase();$('conf').textContent=(z.confidence||0)+'%';$('reason').textContent=z.reason||'';draw(s.candles||[]);const v=s.indicators||{};const rows=[['EMA 9 / 20 / 50',v.ema9?[v.ema9,v.ema20,v.ema50].map(x=>x.toFixed(5)).join(' / '):'—'],['Alligator',v.alligator_lips?[v.alligator_lips,v.alligator_teeth,v.alligator_jaw].map(x=>x.toFixed(5)).join(' / '):'—'],['Parabolic SAR',v.psar?.toFixed(5)||'—'],['MACD histogram',v.macd_hist?.toFixed(5)||'—'],['RSI',v.rsi?.toFixed(2)||'—'],['CCI',v.cci?.toFixed(2)||'—']];$('matrix').innerHTML=rows.map(r=>'<div><b>'+r[0]+'</b><br>'+r[1]+'</div>').join('')}catch(e){}setTimeout(poll,1000)}init()
</script></body></html>'''
@app.get("/",response_class=HTMLResponse)
async def home():return HTML
