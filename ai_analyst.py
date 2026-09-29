import math

class AIAnalyst:
    """Super AI-style classical analyst.

    Combines long candle-history similarity, multi-timeframe structure,
    trend/momentum/reversal evidence, support/resistance and the existing
    engine. It is deterministic and locally computed; its confidence is a
    model score, not a calibrated probability of winning.
    """
    def __init__(self, lookback=8, horizon=1, max_matches=240):
        self.lookback=lookback
        self.horizon=horizon
        self.max_matches=max_matches
        self._cache_key=None
        self._cache=None

    @staticmethod
    def _ret(a,b):
        return (b-a)/a if a else 0.0

    @staticmethod
    def _features(candles,i):
        c=candles[i]; rng=max(c["high"]-c["low"],1e-12)
        body=(c["close"]-c["open"])/rng
        upper=(c["high"]-max(c["open"],c["close"]))/rng
        lower=(min(c["open"],c["close"])-c["low"])/rng
        r1=math.tanh(AIAnalyst._ret(candles[max(0,i-1)]["close"],c["close"])*1000)
        r3=math.tanh(AIAnalyst._ret(candles[max(0,i-3)]["close"],c["close"])*1000)
        return [1.0 if c["close"]>=c["open"] else -1.0,body,upper,lower,r1,r3]

    def _pattern(self,candles,end):
        start=max(0,end-self.lookback+1)
        return [x for i in range(start,end+1) for x in self._features(candles,i)]

    @staticmethod
    def _distance(a,b):
        n=min(len(a),len(b))
        if not n:return 999.0
        return math.sqrt(sum((a[i]-b[i])**2 for i in range(n))/n)

    @staticmethod
    def _aggregate(candles,seconds):
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
        if len(candles)<self.lookback+self.horizon+12:
            return {"direction":"WAIT","confidence":0,"matches":0,"note":"Not enough historical candles"}
        target=self._pattern(candles,len(candles)-1)
        latest=len(candles)-1; scored=[]
        for i in range(self.lookback-1,latest-self.horizon):
            d=self._distance(target,self._pattern(candles,i))
            move=self._ret(candles[i]["close"],candles[i+self.horizon]["close"])
            if abs(move)>1e-12: scored.append((d,move))
        scored.sort(key=lambda x:x[0])
        chosen=scored[:self.max_matches]
        if not chosen:return {"direction":"WAIT","confidence":0,"matches":0,"note":"No comparable historical patterns"}
        call=put=0.0
        for d,move in chosen:
            w=1.0/(0.02+d)
            if move>0:call+=w
            else:put+=w
        total=call+put
        direction="CALL" if call>put else "PUT" if put>call else "WAIT"
        tendency=max(call,put)/total*100 if total else 0
        return {"direction":direction,"confidence":round(tendency,1),"matches":len(chosen),
                "best_distance":round(chosen[0][0],4),"note":"Long-history similar-pattern analysis"}

    @staticmethod
    def _indicator_vote(indicators):
        """Encode common professional TA workflow: trend first, momentum second,
        then volatility/structure and reversal protection."""
        scores={"CALL":0.0,"PUT":0.0}
        def add(direction,weight):
            if direction in scores:scores[direction]+=weight
        ema9,ema20,ema50=(indicators.get(k) for k in ("ema9","ema20","ema50"))
        if None not in (ema9,ema20,ema50):
            add("CALL",14 if ema9>ema20>ema50 else 0)
            add("PUT",14 if ema9<ema20<ema50 else 0)
        lips,teeth,jaw=(indicators.get(k) for k in ("alligator_lips","alligator_teeth","alligator_jaw"))
        if None not in (lips,teeth,jaw):
            add("CALL",20 if lips>teeth>jaw else 0)
            add("PUT",20 if lips<teeth<jaw else 0)
        macd=indicators.get("macd_hist")
        if macd is not None:
            add("CALL",14 if macd>0 else 0); add("PUT",14 if macd<0 else 0)
        cci=indicators.get("cci")
        if cci is not None:
            add("CALL",10 if 0<cci<100 else 5 if cci>=100 else 0)
            add("PUT",10 if -100<cci<0 else 5 if cci<=-100 else 0)
        adx=indicators.get("adx"); plus=indicators.get("plus_di"); minus=indicators.get("minus_di")
        if None not in (adx,plus,minus) and adx>=20:
            add("CALL",10 if plus>minus else 0); add("PUT",10 if minus>plus else 0)
        st=indicators.get("supertrend_direction")
        if st in ("CALL","PUT"):add(st,8)
        fcb=indicators.get("fcb_direction")
        if fcb in ("CALL","PUT"):add(fcb,5)
        rsi=indicators.get("rsi")
        if rsi is not None:
            add("CALL",4 if rsi<45 else 0); add("PUT",4 if rsi>55 else 0)
        return scores

    def _structure(self,candles):
        if len(candles)<12:return {"direction":"WAIT","score":0,"support":None,"resistance":None}
        recent=candles[-30:]
        support=min(c["low"] for c in recent); resistance=max(c["high"] for c in recent)
        last=candles[-1]["close"]; span=max(resistance-support,1e-12)
        pos=(last-support)/span
        # Avoid chasing into obvious extremes; favor a confirmed rejection.
        prev=candles[-2]
        bullish_reject=prev["low"]<=support+(span*.08) and last>prev["close"]
        bearish_reject=prev["high"]>=resistance-(span*.08) and last<prev["close"]
        if bullish_reject:return {"direction":"CALL","score":8,"support":support,"resistance":resistance}
        if bearish_reject:return {"direction":"PUT","score":8,"support":support,"resistance":resistance}
        if pos<.20:return {"direction":"CALL","score":3,"support":support,"resistance":resistance}
        if pos>.80:return {"direction":"PUT","score":3,"support":support,"resistance":resistance}
        return {"direction":"WAIT","score":0,"support":support,"resistance":resistance}

    def _mtf_score(self,candles):
        if len(candles)<6:return {"CALL":0.0,"PUT":0.0}
        base=max(1,int(candles[-1]["ts"]-candles[-2]["ts"]))
        scores={"CALL":0.0,"PUT":0.0}
        for mult,weight in ((1,7),(5,9),(15,9)):
            agg=self._aggregate(candles,max(base*mult,base))
            if len(agg)<4:continue
            move=self._ret(agg[-4]["close"],agg[-1]["close"])
            if move>0:add=weight;scores["CALL"]+=add
            elif move<0:scores["PUT"]+=weight
        return scores

    def analyze(self,asset,timeframe,engine_result,candles,indicators=None):
        candles=[c for c in (candles or []) if all(k in c for k in ("ts","open","high","low","close"))]
        indicators=indicators or {}
        cache_key=(asset,timeframe,candles[-1]["ts"] if candles else 0)
        if cache_key==self._cache_key and self._cache is not None:
            cached=dict(self._cache)
            cached["engine_signal"]=engine_result.get("signal","WAIT")
            cached["engine_agreement"]=cached.get("decision")==cached["engine_signal"] and cached.get("decision") in ("CALL","PUT")
            cached["engine_conflict"]=cached.get("decision") in ("CALL","PUT") and cached["engine_signal"] in ("CALL","PUT") and cached.get("decision")!=cached["engine_signal"]
            return cached
        hist=self._historical(candles)
        iv=self._indicator_vote(indicators)
        st=self._structure(candles)
        mtf=self._mtf_score(candles)
        totals={"CALL":iv["CALL"]+mtf["CALL"],"PUT":iv["PUT"]+mtf["PUT"]}
        if hist["direction"] in totals:totals[hist["direction"]]+=min(24.0,hist["confidence"]*.24)
        if st["direction"] in totals:totals[st["direction"]]+=st["score"]
        # Reversal protection: CCI extremes are not blindly treated as continuation.
        cci=indicators.get("cci")
        if cci is not None and cci>=100:totals["CALL"]*=0.72
        if cci is not None and cci<=-100:totals["PUT"]*=0.72
        direction="CALL" if totals["CALL"]>totals["PUT"] else "PUT" if totals["PUT"]>totals["CALL"] else "WAIT"
        total=totals["CALL"]+totals["PUT"]
        confidence=(max(totals.values())/total*100) if total else 0
        # Confidence is deliberately a decision-strength score, not a win-rate claim.
        confidence=round(min(100.0,confidence),1)
        engine_dir=engine_result.get("signal","WAIT")
        agreement=engine_dir==direction and direction in ("CALL","PUT")
        conflict=engine_dir in ("CALL","PUT") and direction in ("CALL","PUT") and engine_dir!=direction
        result={
            "enabled":True,"mode":"SUPER_AI_CLASSICAL","asset":asset,"timeframe":timeframe,
            "decision":direction,"confidence":confidence,"matches":hist["matches"],
            "best_distance":hist.get("best_distance"),"multi_timeframe":mtf,
            "engine_signal":engine_dir,"engine_agreement":agreement,"engine_conflict":conflict,
            "support":st.get("support"),"resistance":st.get("resistance"),
            "reason":"Super analysis: historical patterns + multi-timeframe trend + Alligator/MACD/CCI + ADX/DMI + structure/reversal checks",
            "warning":"Confidence is model agreement/decision strength, not a guaranteed win probability."
        }
        self._cache_key=cache_key
        self._cache=dict(result)
        return result
