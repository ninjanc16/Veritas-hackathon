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
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
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
    idx=np.arange(T-H_); a=np.full((n,T),np.nan,np.float32); a[:,idx]=cs[:,idx+H_+1]-cs[:,idx+1]; df[f"y_wk_{H_}"]=a.ravel()
    b=np.full((n,T),np.nan,np.float32); b[:,H_-1:]=cs[:,H_:]-cs[:,:T-H_+1]; df[f"trail_{H_}"]=b.ravel()
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
S1nl=[c for c in S1 if c not in("lat","lon")]
def mk(leaf=100): return RandomForestRegressor(n_estimators=80,max_depth=10,min_samples_leaf=leaf,max_features="sqrt",n_jobs=2,random_state=0)
out={}
for H in (26,52):
    end=df.date+pd.to_timedelta(7*H,unit="D"); col=f"y_wk_{H}"; y=df[col]; meta=[]; P={k:[] for k in("S1","S2","RG-only S1")}
    for Y in range(2008,2026):
        start=pd.Timestamp(f"{Y}-01-01"); tr=ok&y.notna()&(end<start); te=ok&y.notna()&(df.date>=start)&(df.date<pd.Timestamp(f"{Y+1}-01-01"))
        if te.sum()==0: continue
        clim=df[tr].groupby("fips")[col].mean()
        meta.append(df[te][["date","river","fips","cls",f"trail_{H}"]].assign(y=y[te].values,clim=df[te].fips.map(clim).values,year=Y))
        P["S1"].append(mk().fit(df.loc[tr,S1],y[tr]).predict(df.loc[te,S1])); P["S2"].append(mk().fit(df.loc[tr,S2],y[tr]).predict(df.loc[te,S2]))
        rg=tr&(df.river=="Rio Grande"); P["RG-only S1"].append(mk(20).fit(df.loc[rg,S1nl],y[rg]).predict(df.loc[te,S1nl]))
    M=pd.concat(meta,ignore_index=True)
    for k in P: M[k]=np.concatenate(P[k])
    M["persist_trailing"]=M[f"trail_{H}"]; M["persist_state"]=np.where(M.cls>=3,H,0)
    M.to_pickle(f"ya_wk_{H}.pkl")
    cols=["S1","S2","RG-only S1","persist_trailing","persist_state","clim"]
    res={}
    for r,g in list(M.groupby("river"))+[("ALL",M)]:
        d={"rows":len(g),"mean_weeks":round(float(g.y.mean()),1)}
        for c in cols: d[c]=round(float((g[c]-g.y).abs().mean()),2)
        d["yrs_S1_beats_trailing"]=f"{sum(int((gg.S1-gg.y).abs().mean()<(gg.persist_trailing-gg.y).abs().mean()) for _,gg in g.groupby('year'))}/{g.year.nunique()}"
        d["yrs_S1_beats_clim"]=f"{sum(int((gg.S1-gg.y).abs().mean()<(gg.clim-gg.y).abs().mean()) for _,gg in g.groupby('year'))}/{g.year.nunique()}"
        d["yrs_RG_beats_trailing"]=f"{sum(int((gg['RG-only S1']-gg.y).abs().mean()<(gg.persist_trailing-gg.y).abs().mean()) for _,gg in g.groupby('year'))}/{g.year.nunique()}"
        res[r]=d
    out[H]=res; print("\nH",H); print(pd.DataFrame(res).T.to_string(),flush=True)
json.dump(out,open("year_ahead_weeks.json","w"),indent=1)
