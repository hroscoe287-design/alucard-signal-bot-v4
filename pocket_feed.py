import asyncio,json,logging,time
import websockets
log=logging.getLogger("alucard.feed")
class PocketOptionFeed:
 def __init__(self,url,auth_json,on_tick):
  self.url=url; self.auth_json=auth_json; self.on_tick=on_tick; self.running=False; self.connected=False; self.last_tick=0; self.last_error=""; self.ws=None
 def auth_packet(self):
  if not self.auth_json:return None
  raw=json.loads(self.auth_json)
  if isinstance(raw,list):return "42"+json.dumps(raw,separators=(",",":"))
  if isinstance(raw,dict) and "command" in raw:return "42"+json.dumps([raw["command"],raw.get("data",{})],separators=(",",":"))
  return "42"+json.dumps(["auth",raw],separators=(",",":"))
 def extract(self,msg):
  if isinstance(msg,bytes):msg=msg.decode("utf-8","ignore")
  if msg=="2":return "PONG"
  if not msg.startswith("42"):return None
  try:data=json.loads(msg[2:])
  except:return None
  if not isinstance(data,list) or len(data)<2:return None
  def walk(x,asset=None):
   if isinstance(x,dict):
    a=asset
    for k,v in x.items():
     if str(k).lower() in ("asset","symbol","pair","active","instrument"):a=str(v)
     if str(k).lower() in ("price","rate","quote","close","value","bid","ask"):
      try:yield a,float(v)
      except:pass
     yield from walk(v,a)
   elif isinstance(x,list):
    for z in x:yield from walk(z,asset)
  for a,p in walk(data[1]):
   if p>0:return a,p
  return None
 async def run(self):
  self.running=True; delay=2
  while self.running:
   try:
    async with websockets.connect(self.url,ping_interval=20,ping_timeout=20,max_size=8*1024*1024) as ws:
     self.ws=ws; self.connected=True; self.last_error=""; delay=2
     packet=self.auth_packet()
     if packet:await ws.send(packet)
     async for msg in ws:
      if msg=="2":await ws.send("3");continue
      parsed=self.extract(msg)
      if parsed:
       asset,price=parsed; self.last_tick=time.time(); self.on_tick(asset or "",price,self.last_tick)
   except asyncio.CancelledError:raise
   except Exception as e:
    self.connected=False; self.last_error=str(e); log.warning("feed disconnected: %s",e); await asyncio.sleep(delay); delay=min(delay*2,30)
   finally:self.connected=False; self.ws=None
 async def stop(self):
  self.running=False
  if self.ws:await self.ws.close()
