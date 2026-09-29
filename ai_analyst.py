import math
from collections import defaultdict

class AIAnalyst:
    """Local, deterministic shadow analyst for ALUCARD V4.

    It is not a trained neural network and does not claim to predict markets.
    It searches the supplied candle history for similar normalized patterns,
    checks several aggregated timeframes, and reports the historical tendency.
    """
    def __init__(self, lookback=6, horizon=1, max_matches=80):
        self.lookback=lookback
        self.horizon=horizon
        self.max_matches=max_matches

    @staticmethod
    def _ret(a,b):
        return (b-a)/a if a else 0.0

    @staticmethod
    def _features(candles, i):
        c=candles[i]
        base=max(abs(c["close"]-c["open"]),1e-12)
        rng=max(c["high"]-c["low"],1e-12)
        return [
            1.0 if c["close"]>=c["open"] else -1.0,
            (c["close"]-c["open"])/rng,
            (c["high"]-max(c["open"],c["close"]))/rng,
            (min(c["open"],c["close"])-c["low"])/rng,
            math.tanh(self._ret(candles[max(0,i-1)]["close"],c["close"])*1000),
            math.tanh(self._ret(candles[max(0,i-3)]["close"],c["close"])*1000),
        ]

    def _pattern(self,candles,end):
        start=max(0,end-self.lookback+1)
        return [x for i in range(start,end+1) for x in self._features(candles,i)]

    @staticmethod
    def _distance(a,b):
        if not a or not b:return 999.0
        n=min(len(a),len(b))
        return math.sqrt(sum((a[i]-b[i])**2 for i in range(n))/n)

    @staticmethod
    def _aggregate(candles, seconds):
        if not candles:return []
        out=[]; bucket=None
        for c in candles:
            b=int(c["ts"]//seconds)*seconds
            if bucket!=b:
                out.append({"ts":b,"open":c["open"],"high":c["high"],"low":c["low"],"close":c["close"]})
                bucket=b
            else:
                x=out[-1]; x["high"]=max(x["high"],c["high"]); x["low"]=min(x["low"],c["low"]); x["close"]=c["close"]
        return out

    def _historical(self,candles):
        if len(candles)<self.lookback+self.horizon+8:
            return {"direction":"WAIT","confidence":0,"matches":0,"note":"Not enough candle history"}
        target=self._pattern(candles,len(candles)-1)
        scored=[]
        latest=len(candles)-1
        for i in range(self.lookback-1,latest-self.horizon):
            p=self._pattern(candles,i)
            d=self._distance(target,p)
            future=candles[i+self.horizon]["close"]
            now=candles[i]["close"]
            move=self._ret(now,future)
            if abs(move)<1e-12: continue
            scored.append((d,move))
        scored.sort(key=lambda x:x[0])
        chosen=scored[:self.max_matches]
        if not chosen:return {"direction":"WAIT","confidence":0,"matches":0,"note":"No comparable historical patterns"}
        weighted_call=weighted_put=0.0
        for d,move in chosen:
            w=1.0/(0.03+d)
            if move>0:weighted_call+=w
            else:weighted_put+=w
        total=weighted_call+weighted_put
        direction="CALL" if weighted_call>weighted_put else "PUT" if weighted_put>weighted_call else "WAIT"
        agreement=max(weighted_call,weighted_put)/total*100 if total else 0
        return {"direction":direction,"confidence":round(agreement,1),"matches":len(chosen),"best_distance":round(chosen[0][0],4),"note":"Historical tendency from similar candle sequences"}

    def _mtf(self,candles):
        base=max(1,int(candles[-1]["ts"]-candles[-2]["ts"])) if len(candles)>1 else 60
        frames=[base,max(base*5,300),max(base*15,900)]
        out={}
        for sec in dict.fromkeys(frames):
            agg=self._aggregate(candles,sec)
            if len(agg)>=3:
                a,b,c=agg[-3:]
                score=(c["close"]-a["close"])/max(a["close"],1e-12)
                out[str(sec)] = "CALL" if score>0 else "PUT" if score<0 else "WAIT"
        return out

    def analyze(self,asset,timeframe,engine_result,candles,indicators=None):
        candles=[c for c in (candles or []) if all(k in c for k in ("ts","open","high","low","close"))]
        hist=self._historical(candles)
        mtf=self._mtf(candles)
        leaders=[]
        for key in ("alligator_lips","alligator_teeth","alligator_jaw"):
            if indicators and indicators.get(key) is not None: leaders.append(indicators[key])
        leader_dir="WAIT"
        if len(leaders)==3:
            leader_dir="CALL" if leaders[0]>leaders[1]>leaders[2] else "PUT" if leaders[0]<leaders[1]<leaders[2] else "WAIT"
        engine_dir=engine_result.get("signal","WAIT")
        agreement=engine_dir==hist["direction"] and engine_dir in ("CALL","PUT")
        conflict=engine_dir in ("CALL","PUT") and hist["direction"] in ("CALL","PUT") and engine_dir!=hist["direction"]
        return {"enabled":True,"mode":"SHADOW","asset":asset,"timeframe":timeframe,"decision":hist["direction"],"confidence":hist["confidence"],"matches":hist["matches"],"best_distance":hist.get("best_distance"),"multi_timeframe":mtf,"engine_signal":engine_dir,"engine_agreement":agreement,"engine_conflict":conflict,"alligator_direction":leader_dir,"reason":hist["note"],"warning":"Historical tendency is not a calibrated win probability and does not guarantee the next candle."}
