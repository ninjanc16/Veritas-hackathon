"""Can a random forest forecast farm-relevant drought ~1 year ahead?
Issue once a month (first USDM week of each month). Forward-chaining by year: to test year Y, train only on
issue dates whose 52-week label window ends before Jan 1 of Y. Test years 2008..2025 (out-of-sample, pooled).
Targets (next 52 weeks, t+1..t+52):
  lfp  = a run of >=8 consecutive D2+ weeks inside the window (LFP 1-payment trigger)
  d3   = any D3+ week in the window (bigger LFP payment)
  anom = share of weeks in D2+ exceeds the county's own long-run share to date ("worse-than-usual year")
Feature sets: S0 = original 26 history features; S1 = S0 + long memory (2-3 yr shares, expanding share, river mean);
  S2 = S1 + ENSO (ONI, lagged so only seasons that ended before the issue month are used).
Probabilities from an unweighted forest (roughly calibrated). Decision: warn if p >= 0.25 (cost 3:1 rule, no tuning).
Baseline 'climatology' = county's positive rate among that fold's training rows."""
import sys, json, numpy as np, pandas as pd
from numpy.lib.stride_tricks import sliding_window_view as sw
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score
DL=sys.argv[1]
import os; HERE=os.path.dirname(os.path.abspath(__file__)); src=open(os.path.join(HERE,"viability_test.py")).read().split("n,T=C.shape")[0]
sys.argv=["x",DL,"/tmp/u.json"]; exec(src)
n,T=C.shape; MISS=3
D2=(C>=3).astype(np.float32); cs=np.concatenate([np.zeros((n,1),np.float32),np.cumsum(D2,1)],1)
exp_share=cs[:,1:]/np.arange(1,T+1)
R=np.zeros_like(D2)
for t in range(T): R[:,t]=np.where(D2[:,t]>0,(R[:,t-1] if t else 0)+1,0)
def labels(H):
    lab={k:np.full((n,T),np.nan,np.float32) for k in("lfp","d3","anom")}
    idx=np.arange(T-H)
    Rw=sw(R,H,axis=1); lab["lfp"][:,idx]=(Rw[:,idx+1,7:].max(-1)>=8)
    Cw=sw(C,H,axis=1); lab["d3"][:,idx]=(Cw[:,idx+1].max(-1)>=4)
    nxt=(cs[:,idx+H+1]-cs[:,idx+1])/H; lab["anom"][:,idx]=(nxt>exp_share[:,idx])
    return lab
feat2=dict(feat)
feat2["share104"]=pd.DataFrame(D2.T).rolling(104,min_periods=104).mean().values.T
feat2["share156"]=pd.DataFrame(D2.T).rolling(156,min_periods=156).mean().values.T
feat2["share52"]=pd.DataFrame(D2.T).rolling(52,min_periods=52).mean().values.T
feat2["exp_share"]=exp_share
rv=river[sel]; rm=np.zeros_like(C)
for r in np.unique(rv): rm[rv==r]=C[rv==r].mean(0)
feat2["river_mean"]=rm
df=pd.DataFrame({k:v.ravel() for k,v in feat2.items()})
df["date"]=np.tile(dates,n); df["river"]=np.repeat(rv,T); df["fips"]=np.repeat(np.array(F)[sel],T)
woy=df.date.dt.isocalendar().week.astype(int); df["sin"]=np.sin(2*np.pi*woy/52); df["cos"]=np.cos(2*np.pi*woy/52)
df["lat"]=np.repeat(lat[sel],T); df["lon"]=np.repeat(lon[sel],T)
for H_ in (26,52):
    for k,v in labels(H_).items(): df[f"y_{k}_{H_}"]=v.ravel()
# ---- ENSO (ONI), seasons indexed by their end month; usable only if the season ended before the issue month
rows=[]
for line in open(os.path.join(HERE,"oni.txt")):
    if line.startswith("#"): continue
    p=line.split(); yr=int(p[0])
    for i,v in enumerate(p[1:]):
        end=pd.Period(year=yr,month=i+2,freq="M") if i<11 else pd.Period(year=yr+1,month=1,freq="M")
        rows.append((end,float(v)))
oni=pd.Series(dict(rows)).sort_index()
def oni_feats(d):
    a=oni[oni.index<pd.Period(d,"M")]
    return a.iloc[-1],a.iloc[-1]-a.iloc[-4],a.iloc[-12:].mean(),a.iloc[-12:].min(),a.iloc[-12:].max()
ud=pd.Series(df.date.unique())
O=pd.DataFrame([oni_feats(d) for d in ud],columns=["oni","oni_chg3","oni_mean12","oni_min12","oni_max12"]); O["date"]=ud.values
df=df.merge(O,on="date",how="left")
# monthly issue rows only
df=df[df.date.dt.day<=7].reset_index(drop=True)
S0=list(feat.keys())+["sin","cos","lat","lon"]
S1=S0+["share52","share104","share156","exp_share","river_mean"]
S2=S1+["oni","oni_chg3","oni_mean12","oni_min12","oni_max12"]
SETS={"S0 history":S0,"S1 +long memory":S1,"S2 +long memory +ENSO":S2}
ok=df[S2].notna().all(axis=1)
S2nl=[c for c in S2 if c not in("lat","lon")]
def mk(leaf=100): return RandomForestClassifier(n_estimators=80,max_depth=10,min_samples_leaf=leaf,max_features="sqrt",n_jobs=2,random_state=0)
KEYS=list(SETS)+["RG-only S2"]
def cost(yv,al): al=np.asarray(al,bool); yv=np.asarray(yv)==1; return MISS*int((~al&yv).sum())+int((al&~yv).sum())
out={}
for H in (26,52):
  end=df.date+pd.to_timedelta(7*H,unit="D")
  for tg in ("lfp","d3","anom"):
    col=f"y_{tg}_{H}"; y=df[col]; preds={k:[] for k in KEYS}; meta=[]
    for Y in range(2008,2026):
        start=pd.Timestamp(f"{Y}-01-01")
        tr=ok&y.notna()&(end<start); te=ok&y.notna()&(df.date>=start)&(df.date<pd.Timestamp(f"{Y+1}-01-01"))
        if te.sum()==0: continue
        clim=df[tr].groupby("fips")[col].mean()
        meta.append(df[te][["date","river","fips","cls"]].assign(y=y[te].values,clim=df[te].fips.map(clim).fillna(y[tr].mean()).values,year=Y))
        for k,FE in SETS.items():
            preds[k].append(mk().fit(df.loc[tr,FE],y[tr]).predict_proba(df.loc[te,FE])[:,1])
        rg=tr&(df.river=="Rio Grande")
        m=mk(20).fit(df.loc[rg,S2nl],y[rg]); p=m.predict_proba(df.loc[te,S2nl]); preds["RG-only S2"].append(p[:,1] if p.shape[1]>1 else np.full(len(p),float(m.classes_[0])))
    M=pd.concat(meta,ignore_index=True)
    for k in KEYS: M[k]=np.concatenate(preds[k])
    M.to_pickle(f"ya_{tg}_{H}.pkl")
    def summ(g):
        yv=g.y.values; bc=((g.clim-yv)**2).mean(); r={"rows":len(g),"base_rate":round(float(yv.mean()),3)}
        base={"never":cost(yv,np.zeros(len(g))),"always":cost(yv,np.ones(len(g))),"persistence D2+ now":cost(yv,g.cls>=3),"D1+ now":cost(yv,g.cls>=2),"climatology":cost(yv,g.clim>=0.25)}
        bk=min(base,key=base.get); r["best_rule"]=bk; r["best_rule_cost"]=base[bk]; r["persistence_cost"]=base["persistence D2+ now"]; r["climatology_cost"]=base["climatology"]
        two=0<yv.mean()<1
        r["auc_clim"]=round(roc_auc_score(yv,g.clim),3) if two else None
        r["auc_persist"]=round(roc_auc_score(yv,g.cls),3) if two else None
        for k in KEYS:
            p=g[k].values; al=p>=0.25; c=cost(yv,al); tp=int((al&(yv==1)).sum())
            r[k]=dict(auc=round(roc_auc_score(yv,p),3) if two else None,bss=round(1-((p-yv)**2).mean()/max(bc,1e-9),3),cost=c,
                      save_vs_best_rule_pct=round(100*(1-c/max(base[bk],1)),1),precision=round(tp/max(al.sum(),1),3),recall=round(tp/max((yv==1).sum(),1),3))
        return r
    res={"ALL":summ(M)}
    for r_,g in M.groupby("river"): res[r_]=summ(g)
    wins={}
    for k in KEYS:
        wins[k]={rr:f"{sum(int(((g[k]-g.y)**2).mean()<((g.clim-g.y)**2).mean()) for Y,g in gg.groupby('year'))}/{gg.year.nunique()}" for rr,gg in list(M.groupby("river"))+[("ALL",M)]}
    res["years_beating_climatology_brier"]=wins
    out[f"{tg}_{H}"]=res
    json.dump(out,open("year_ahead.json","w"),indent=1,default=str)
    print("finished",tg,H,flush=True)
print("DONE")
