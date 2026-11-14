"""A) Does skill last longer on snow-fed western rivers? (per-river decision-level skill by horizon, one forest trained on all rivers)
B) Transfer: train on Rio Grande counties only (no lat/lon), test on every other river vs own-river model and all-river model.
Thresholds chosen on validation only (2015-2018, labels end by 2018-12-31); test = windows starting 2019+. Cost = 3*miss + false alarm."""
import sys, numpy as np, pandas as pd
from sklearn.ensemble import RandomForestClassifier
DL=sys.argv[1]
import os; HERE=os.path.dirname(os.path.abspath(__file__)); src=open(os.path.join(HERE,"viability_test.py")).read().split("n,T=C.shape")[0]
sys.argv=["x",DL,"/tmp/unused.json"]; exec(src)
n,T=C.shape; MISS=3
D2=(C>=3).astype(np.float32); cs=np.concatenate([np.zeros((n,1),np.float32),np.cumsum(D2,1)],1)
def fut_any(h):
    o=np.full((n,T),np.nan,np.float32); idx=np.arange(T-h-1); o[:,idx]=(cs[:,idx+h+1]-cs[:,idx+1]>0); return o
base=pd.DataFrame({k:v.ravel() for k,v in feat.items()})
base["river"]=np.repeat(river[sel],T); base["date"]=np.tile(dates,n)
woy=base.date.dt.isocalendar().week.astype(int); base["sin"]=np.sin(2*np.pi*woy/52); base["cos"]=np.cos(2*np.pi*woy/52)
base["lat"]=np.repeat(lat[sel],T); base["lon"]=np.repeat(lon[sel],T)
FE=list(base.columns.drop(["river","date"])); FEnl=[c for c in FE if c not in("lat","lon")]
ok=base[FE].notna().all(axis=1).values
c14=pd.Timestamp("2014-12-31"); c18=pd.Timestamp("2018-12-31")
def tally(y,al):
    al=np.asarray(al,bool); y=np.asarray(y)==1
    return MISS*int((~al&y).sum())+int((al&~y).sum())
def best(p,y):
    ths=np.unique(np.quantile(p,np.linspace(0.3,0.995,70))); return ths[int(np.argmin([tally(y,p>=t) for t in ths]))]
def mk(): return RandomForestClassifier(n_estimators=100,max_depth=12,min_samples_leaf=100,max_features="sqrt",class_weight="balanced_subsample",n_jobs=2,random_state=0)
def fit(X,y,cap=150000):
    rs=np.random.RandomState(0); i=np.arange(len(X)); i=rs.choice(i,min(len(i),cap),replace=False); return mk().fit(X.iloc[i],y[i])
RV=["Rio Grande","Colorado","Missouri","Mississippi","Ohio"]
A=[];B=[]
for h in (4,13,26,52):
    y=fut_any(h).ravel(); end=base.date+pd.to_timedelta(7*h,unit="D"); m=ok&~np.isnan(y)
    tr=m&(end<=c14).values; va=m&(base.date>c14).values&(end<=c18).values; te=m&(base.date>c18).values
    # ---- A: one forest, all rivers, pooled threshold
    rf=fit(base.loc[tr,FE],y[tr]); pv=rf.predict_proba(base.loc[va,FE])[:,1]; th=best(pv,y[va]); pt=rf.predict_proba(base.loc[te,FE])[:,1]
    Te=base[te]; yt=y[te]
    for r in RV:
        mt=(Te.river.values==r); cls=Te.cls.values[mt]; yy=yt[mt]
        rules={"never":tally(yy,np.zeros(mt.sum(),bool)),"D1+ now":tally(yy,cls>=2),"D2+ now":tally(yy,cls>=3)}
        bk=min(rules,key=rules.get); f=tally(yy,pt[mt]>=th)
        A.append(dict(h=h,river=r,counties=int(Te.loc[mt].shape[0]>0),pos_rate=round(float(yy.mean()),3),forest=f,best_rule=bk,best_cost=rules[bk],saving_pct=round(100*(1-f/rules[bk]),1)))
    # ---- B: transfer from Rio Grande (h = 4, 26 only)
    if h in (4,26):
        rg_tr=tr&(base.river.values=="Rio Grande"); rg_va=va&(base.river.values=="Rio Grande")
        mRG=fit(base.loc[rg_tr,FEnl],y[rg_tr]); thRG=best(mRG.predict_proba(base.loc[rg_va,FEnl])[:,1],y[rg_va])
        mALL=fit(base.loc[tr,FEnl],y[tr]); thALL=best(mALL.predict_proba(base.loc[va,FEnl])[:,1],y[va])
        for r in RV:
            rt=(Te.river.values==r); cls=Te.cls.values[rt]; yy=yt[rt]; Xt=Te.loc[rt,FEnl]
            rules={"never":tally(yy,np.zeros(rt.sum(),bool)),"D1+ now":tally(yy,cls>=2),"D2+ now":tally(yy,cls>=3)}; bk=min(rules,key=rules.get)
            own_tr=tr&(base.river.values==r); own_va=va&(base.river.values==r)
            mOWN=fit(base.loc[own_tr,FEnl],y[own_tr]); thO=best(mOWN.predict_proba(base.loc[own_va,FEnl])[:,1],y[own_va])
            c_rg=tally(yy,mRG.predict_proba(Xt)[:,1]>=thRG); c_all=tally(yy,mALL.predict_proba(Xt)[:,1]>=thALL); c_own=tally(yy,mOWN.predict_proba(Xt)[:,1]>=thO)
            s=lambda c:round(100*(1-c/rules[bk]),1)
            B.append(dict(h=h,target=r,best_rule=bk,rule_cost=rules[bk],RGonly_cost=c_rg,RGonly_save=s(c_rg),own_cost=c_own,own_save=s(c_own),allriv_cost=c_all,allriv_save=s(c_all)))
    print("done h",h,flush=True)
a=pd.DataFrame(A).drop(columns="counties"); b=pd.DataFrame(B)
print("\nA) one forest on all rivers, per-river test (saving vs best simple rule; + = forest cheaper)"); print(a.to_string(index=False))
print("\nB) trained on Rio Grande only (no lat/lon) -> tested on each river"); print(b.to_string(index=False))
a.to_csv("horizons3_A.csv",index=False); b.to_csv("horizons3_B.csv",index=False)
