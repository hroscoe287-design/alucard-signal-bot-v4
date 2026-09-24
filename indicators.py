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
 tp=(df.high+df.low+df.close)/3
 ma=tp.rolling(n).mean()
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

def stochastic(df,k_period=14,d_period=3,smooth=3):
 close=df.close.astype(float)
 low=df.low.rolling(k_period).min()
 high=df.high.rolling(k_period).max()
 k=100*(close-low)/(high-low).replace(0,np.nan)
 k=k.rolling(smooth).mean()
 d=k.rolling(d_period).mean()
 return k,d

def adx_dmi(df,n=14):
 high=df.high.astype(float); low=df.low.astype(float); close=df.close.astype(float)
 up=high.diff()
 down=-low.diff()
 plus_dm=up.where((up>down)&(up>0),0.0)
 minus_dm=down.where((down>up)&(down>0),0.0)
 tr=pd.concat([(high-low),(high-close.shift()).abs(),(low-close.shift()).abs()],axis=1).max(axis=1)
 atr_w=tr.ewm(alpha=1/n,adjust=False).mean()
 plus_di=100*plus_dm.ewm(alpha=1/n,adjust=False).mean()/atr_w.replace(0,np.nan)
 minus_di=100*minus_dm.ewm(alpha=1/n,adjust=False).mean()/atr_w.replace(0,np.nan)
 dx=100*(plus_di-minus_di).abs()/(plus_di+minus_di).replace(0,np.nan)
 adx=dx.ewm(alpha=1/n,adjust=False).mean()
 return adx,plus_di,minus_di

def supertrend(df,period=10,multiplier=3.0):
 hl2=(df.high+df.low)/2.0
 a=atr(df,period)
 upper=hl2+multiplier*a
 lower=hl2-multiplier*a
 final_upper=upper.copy()
 final_lower=lower.copy()
 direction=pd.Series(1,index=df.index,dtype=int)
 st=pd.Series(np.nan,index=df.index,dtype=float)
 for i in range(1,len(df)):
  prev=i-1
  final_upper.iloc[i]=upper.iloc[i] if upper.iloc[i]<final_upper.iloc[prev] or df.close.iloc[prev]>final_upper.iloc[prev] else final_upper.iloc[prev]
  final_lower.iloc[i]=lower.iloc[i] if lower.iloc[i]>final_lower.iloc[prev] or df.close.iloc[prev]<final_lower.iloc[prev] else final_lower.iloc[prev]
  if pd.isna(a.iloc[i]):
   direction.iloc[i]=direction.iloc[prev]
  elif st.iloc[prev] == final_upper.iloc[prev]:
   direction.iloc[i]=1 if df.close.iloc[i]>final_upper.iloc[i] else -1
  else:
   direction.iloc[i]=-1 if df.close.iloc[i]<final_lower.iloc[i] else 1
  st.iloc[i]=final_lower.iloc[i] if direction.iloc[i]==1 else final_upper.iloc[i]
 st.iloc[0]=final_lower.iloc[0]
 return st,direction

def calculate(candles):
 if len(candles)<35:return {"ready":False,"reason":"Need at least 35 candles","values":{}}
 df=pd.DataFrame(candles); close=df.close.astype(float)
 e9,e20,e50=ema(close,9),ema(close,20),ema(close,50)
 m,ms,mh=macd(close); ps=psar(df); jaw,teeth,lips=alligator(df); fu,fd=fractal(df,2)
 bbmid,bbup,bblow,bbwidth,bbpct=bollinger(close,20,2.0)
 atr_series=atr(df)
 atr_base=atr_series.rolling(50,min_periods=14).mean()
 st,st_dir=supertrend(df,10,3.0)
 stoch_k,stoch_d=stochastic(df,14,3,3)
 adx_series,plus_di,minus_di=adx_dmi(df,14)
 cci_series=cci(df,14)
 last=lambda s:float(s.iloc[-1]) if pd.notna(s.iloc[-1]) else None
 return {"ready":True,"values":{
  "price":float(close.iloc[-1]),"ema9":last(e9),"ema20":last(e20),"ema50":last(e50),
  "macd":last(m),"macd_signal":last(ms),"macd_hist":last(mh),"rsi":last(rsi(close)),
  "cci":last(cci_series),"atr":last(atr_series),"atr_baseline":last(atr_base),"psar":last(ps),
  "alligator_jaw":last(jaw),"alligator_teeth":last(teeth),"alligator_lips":last(lips),
  "fractal_up":bool(fu.iloc[-3]),"fractal_down":bool(fd.iloc[-3]),
  "bb_mid":last(bbmid),"bb_upper":last(bbup),"bb_lower":last(bblow),
  "bb_width":last(bbwidth),"bb_pct":last(bbpct),
  "supertrend":last(st),"supertrend_direction":int(st_dir.iloc[-1]),
  "stoch_k":last(stoch_k),"stoch_d":last(stoch_d),
  "adx":last(adx_series),"plus_di":last(plus_di),"minus_di":last(minus_di),
  "momentum_1":float(close.iloc[-1]-close.iloc[-2]),
  "momentum_2":float(close.iloc[-2]-close.iloc[-3]),
  "momentum_3":float(close.iloc[-3]-close.iloc[-4])
 }}
