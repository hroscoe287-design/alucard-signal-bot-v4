import numpy as np
import pandas as pd

def ema(s,n): return s.ewm(span=n,adjust=False).mean()

def rsi(s,n=14):
 d=s.diff(); up=d.clip(lower=0); dn=-d.clip(upper=0)
 rs=up.ewm(alpha=1/n,adjust=False).mean()/dn.ewm(alpha=1/n,adjust=False).mean().replace(0,np.nan)
 return 100-100/(1+rs)

def atr(df,n=14):
 pc=df.close.shift()
 tr=pd.concat([df.high-df.low,(df.high-pc).abs(),(df.low-pc).abs()],axis=1).max(axis=1)
 return tr.ewm(alpha=1/n,adjust=False).mean()

def cci(df,n=14):
 tp=(df.high+df.low+df.close)/3; ma=tp.rolling(n).mean()
 md=tp.rolling(n).apply(lambda x:np.mean(np.abs(x-x.mean())),raw=True)
 return (tp-ma)/(0.015*md.replace(0,np.nan))

def macd(s):
 m=ema(s,12)-ema(s,26); sig=ema(m,9); return m,sig,m-sig

def psar(df,step=.02,max_af=.2):
 h=df.high.to_numpy(); l=df.low.to_numpy(); out=np.zeros(len(df))
 if not len(df): return pd.Series(dtype=float)
 bull=True; af=step; ep=h[0]; sar=l[0]; out[0]=sar
 for i in range(1,len(df)):
  sar=sar+af*(ep-sar)
  if bull:
   sar=min(sar,l[i-1],l[i-2] if i>1 else l[i-1])
   if l[i]<sar: bull=False; sar=ep; ep=l[i]; af=step
   elif h[i]>ep: ep=h[i]; af=min(max_af,af+step)
  else:
   sar=max(sar,h[i-1],h[i-2] if i>1 else h[i-1])
   if h[i]>sar: bull=True; sar=ep; ep=h[i]; af=step
   elif l[i]<ep: ep=l[i]; af=min(max_af,af+step)
  out[i]=sar
 return pd.Series(out,index=df.index)

def alligator(df): return ema(df.close,13),ema(df.close,8),ema(df.close,5)

def fractal(df,span=2):
 return df.high.rolling(2*span+1,center=True).max().eq(df.high),df.low.rolling(2*span+1,center=True).min().eq(df.low)

def bollinger(s,n=20,stds=2.0):
 mid=s.rolling(n).mean()
 dev=s.rolling(n).std(ddof=0)
 upper=mid+stds*dev; lower=mid-stds*dev
 width=(upper-lower)/mid.replace(0,np.nan)
 pct=(s-lower)/(upper-lower).replace(0,np.nan)
 return mid,upper,lower,width,pct

def calculate(candles):
 if len(candles)<35:return {"ready":False,"reason":"Need at least 35 candles","values":{}}
 df=pd.DataFrame(candles); close=df.close.astype(float)
 e9,e20,e50=ema(close,9),ema(close,20),ema(close,50)
 m,ms,mh=macd(close); ps=psar(df); jaw,teeth,lips=alligator(df); fu,fd=fractal(df,2)
 bbmid,bbup,bblow,bbwidth,bbpct=bollinger(close,20,2.0)
 last=lambda s:float(s.iloc[-1]) if pd.notna(s.iloc[-1]) else None
 return {"ready":True,"values":{
  "price":float(close.iloc[-1]),"ema9":last(e9),"ema20":last(e20),"ema50":last(e50),
  "macd":last(m),"macd_signal":last(ms),"macd_hist":last(mh),"rsi":last(rsi(close)),
  "cci":last(cci(df)),"atr":last(atr(df)),"psar":last(ps),
  "alligator_jaw":last(jaw),"alligator_teeth":last(teeth),"alligator_lips":last(lips),
  "fractal_up":bool(fu.iloc[-3]),"fractal_down":bool(fd.iloc[-3]),
  "bb_mid":last(bbmid),"bb_upper":last(bbup),"bb_lower":last(bblow),
  "bb_width":last(bbwidth),"bb_pct":last(bbpct)
 }}