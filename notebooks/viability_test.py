"""Go/no-go: can a random forest beat simple rules at warning of severe drought (D2+)
4 weeks ahead, for counties along five rivers? Drought-history features only."""
import json, sys, math, numpy as np, pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
DL=sys.argv[1]; OUT=sys.argv[2]
H=4; BUF_KM=50; NB_KM=150; MISS=3
RIVERS=["Rio Grande","Mississippi","Missouri","Colorado","Ohio"]

# ---- rivers -> points
r=json.load(open(f"{DL}/ne_10m_rivers_lake_centerlines.geojson"))
rp={k:[] for k in RIVERS}
for f in r["features"]:
    n=f["properties"].get("name")
    if n in RIVERS:
        g=f["geometry"]; lines=[g["coordinates"]] if g["type"]=="LineString" else g["coordinates"]
        for l in lines:
            for i,(x,y) in enumerate(l):
                if y<25 or x<-125 or x>-66: continue   # drops Argentina's Colorado
                rp[n].append((x,y))
                if i+1<len(l):                           # densify long segments
                    x2,y2=l[i+1]; m=int(max(abs(x2-x),abs(y2-y))/0.1)
                    for k in range(1,m): rp[n].append((x+(x2-x)*k/m,y+(y2-y)*k/m))
rp={k:np.array(v) for k,v in rp.items()}
# ---- county centroids
cj=json.load(open(f"{DL}/geojson-counties-fips.json")); cen={}
for f in cj["features"]:
    g=f["geometry"]; polys=[g["coordinates"]] if g["type"]=="Polygon" else g["coordinates"]
    pts=np.array([p for poly in polys for p in poly[0]]); cen[f["id"]]=(pts[:,0].mean(),pts[:,1].mean())
def km(lon1,lat1,lon2,lat2):
    p=np.pi/180; a=np.sin((lat2-lat1)*p/2)**2+np.cos(lat1*p)*np.cos(lat2*p)*np.sin((lon2-lon1)*p/2)**2
    return 12742*np.arcsin(np.sqrt(a))
u=json.load(open(f"{DL}/usdm-counties.json"))
fips=u["counties"]; week0=pd.Timestamp(u["week0"]); W=u["weeks"]
dates=pd.date_range(week0,periods=W,freq="7D")
arr=np.full((len(fips),W),np.nan,dtype=np.float32)
for i,s in enumerate(u["series"]):
    a=np.frombuffer(s.encode(),dtype="S1"); ok=a!=b"."; arr[i,ok]=a[ok].astype(np.int8)
names={f:(c,s) for f,c,s in zip(fips,u["county_names"],u["state_names"])}
full=[i for i,f in enumerate(fips) if f in cen and not np.isnan(arr[i]).any()]
lon=np.array([cen[fips[i]][0] for i in full]); lat=np.array([cen[fips[i]][1] for i in full])
A=arr[full]; F=[fips[i] for i in full]
# river membership
dist={k:np.array([km(lon[j],lat[j],v[:,0],v[:,1]).min() for j in range(len(F))]) for k,v in rp.items()}
D=pd.DataFrame(dist); river=D.idxmin(axis=1).values; dmin=D.min(axis=1).values
sel=np.where(dmin<=BUF_KM)[0]
print("counties with full history:",len(F),"| river counties:",len(sel))
print(pd.Series(river[sel]).value_counts().to_dict())
# neighbors among ALL counties (drought spreads from anywhere)
nb=[np.where((km(lon[j],lat[j],lon,lat)<=NB_KM))[0] for j in sel]
nb=[n[n!=j] for n,j in zip(nb,sel)]
nb_mean=np.stack([A[n].mean(0) for n in nb]); nb_max=np.stack([A[n].max(0) for n in nb])
nb_d2=np.stack([(A[n]>=3).mean(0) for n in nb])
C=A[sel]                                   # counties x weeks
def lagm(M,k):
    o=np.full_like(M,np.nan); o[:,k:]=M[:,:-k]; return o
def rollmax(M,k): return pd.DataFrame(M.T).rolling(k,min_periods=k).max().values.T
def rollmean(M,k): return pd.DataFrame(M.T).rolling(k,min_periods=k).mean().values.T
fut=np.stack([np.concatenate([C[:,h:],np.full((C.shape[0],h),np.nan)],1) for h in range(1,H+1)])
y_any=(fut.max(0)>=3).astype(float); y_any[np.isnan(fut).any(0)]=np.nan
# run length at current class, weeks since last D2+
run=np.ones_like(C); since=np.full_like(C,999.)
for t in range(1,W):
    run[:,t]=np.where(C[:,t]==C[:,t-1],run[:,t-1]+1,1)
    since[:,t]=np.where(C[:,t]>=3,0,np.minimum(since[:,t-1]+1,999))
since[:,0]=np.where(C[:,0]>=3,0,999)
feat={"cls":C,"l1":lagm(C,1),"l2":lagm(C,2),"l4":lagm(C,4),"l8":lagm(C,8),"l12":lagm(C,12),"l26":lagm(C,26),"l52":lagm(C,52),
 "chg4":C-lagm(C,4),"chg8":C-lagm(C,8),"max12":rollmax(C,12),"max26":rollmax(C,26),"max52":rollmax(C,52),
 "mean12":rollmean(C,12),"mean26":rollmean(C,26),"run":run,"since_d2":np.minimum(since,104),
 "nb_mean":nb_mean,"nb_max":nb_max,"nb_d2":nb_d2,"nb_chg4":nb_mean-lagm(nb_mean,4),"nb_minus_self":nb_mean-C}
n,T=C.shape
df=pd.DataFrame({k:v.ravel() for k,v in feat.items()})
df["y"]=y_any.ravel(); df["fips"]=np.repeat(np.array(F)[sel],T); df["river"]=np.repeat(river[sel],T)
df["date"]=np.tile(dates,n); df["lat"]=np.repeat(lat[sel],T); df["lon"]=np.repeat(lon[sel],T)
woy=df.date.dt.isocalendar().week.astype(int); df["sin"]=np.sin(2*np.pi*woy/52); df["cos"]=np.cos(2*np.pi*woy/52); df["woy"]=woy
df["year"]=df.date.dt.year
df=df.dropna().reset_index(drop=True)
FE=[c for c in df.columns if c not in("y","fips","river","date","year","woy")]
tr=df[df.year<=2014]; va=df[(df.year>=2015)&(df.year<=2018)]; te=df[df.year>=2019]
print("rows train/val/test:",len(tr),len(va),len(te),"| positives test:",int(te.y.sum()),
      "| onset rows test (not D2 now):",int((te.cls<3).sum()),"positives among them:",int(te[te.cls<3].y.sum()))
def tally(d,alarm):
    alarm=np.asarray(alarm,bool); yv=d.y.values==1
    c=int((alarm&yv).sum()); m=int((~alarm&yv).sum()); fa=int((alarm&~yv).sum())
    return dict(cost=MISS*m+fa,alarms=int(alarm.sum()),caught=c,missed=m,false_alarms=fa,
                precision=round(c/max(alarm.sum(),1),3),recall=round(c/max(yv.sum(),1),3))
def best_thr(p,d):
    ths=np.linspace(0.02,0.9,45); return ths[int(np.argmin([tally(d,p>=t)["cost"] for t in ths]))]
# calendar baseline: per river x week-of-year rate from train, threshold on val
rate=tr.groupby(["river","woy"]).y.mean().rename("r")
def cal(d): return d.join(rate,on=["river","woy"]).r.fillna(0).values
tc=best_thr(cal(va),va)
BASE={"Persistence (D2+ now)":lambda d:d.cls>=3,"D1 or worse now":lambda d:d.cls>=2,
      "D1+ now and worsening (4 wk)":lambda d:(d.cls>=3)|((d.cls>=2)&(d.chg4>0)),
      "Calendar":lambda d:cal(d)>=tc}
res={}
rf=RandomForestClassifier(n_estimators=200,max_depth=12,min_samples_leaf=50,max_features="sqrt",
                          class_weight="balanced_subsample",n_jobs=2,random_state=0)
sub=tr.sample(min(len(tr),250000),random_state=0)
rf.fit(sub[FE],sub.y); pv=rf.predict_proba(va[FE])[:,1]; pt=rf.predict_proba(te[FE])[:,1]; th=best_thr(pv,va)
lr=LogisticRegression(max_iter=300,C=0.5,class_weight="balanced")
mu,sd=sub[FE].mean(),sub[FE].std()+1e-9
lr.fit((sub[FE]-mu)/sd,sub.y); lv=lr.predict_proba((va[FE]-mu)/sd)[:,1]; lt=lr.predict_proba((te[FE]-mu)/sd)[:,1]; tl=best_thr(lv,va)
def block(d,title,extra):
    rows={k:tally(d,f(d)) for k,f in BASE.items()}; rows.update(extra)
    t=pd.DataFrame(rows).T.sort_values("cost"); print("\n=== "+title+" ==="); print(t.to_string()); return t
allv=block(va,"VALIDATION 2015-2018, all rows",{"Random forest":tally(va,pv>=th),"Logistic":tally(va,lv>=tl)})
allt=block(te,"TEST 2019-2026, all rows",{"Random forest":tally(te,pt>=th),"Logistic":tally(te,lt>=tl)})
print("AUC test RF %.3f LR %.3f"%(roc_auc_score(te.y,pt),roc_auc_score(te.y,lt)))
# ---- onset: rows not yet in D2+. Separate forest + threshold, chosen on validation
tro,vao,teo=sub[sub.cls<3],va[va.cls<3],te[te.cls<3]
rfo=RandomForestClassifier(n_estimators=200,max_depth=12,min_samples_leaf=50,max_features="sqrt",
                           class_weight="balanced_subsample",n_jobs=2,random_state=0).fit(tro[FE],tro.y)
pvo=rfo.predict_proba(vao[FE])[:,1]; pto=rfo.predict_proba(teo[FE])[:,1]; tho=best_thr(pvo,vao)
OB={k:v for k,v in BASE.items() if k!="Persistence (D2+ now)"}
def oblock(d,p,title):
    rows={k:tally(d,f(d)) for k,f in OB.items()}; rows["Never warn"]=tally(d,np.zeros(len(d),bool)); rows["Onset forest"]=tally(d,p>=tho)
    t=pd.DataFrame(rows).T.sort_values("cost"); print("\n=== "+title+" ==="); print(t.to_string()); return t
ov=oblock(vao,pvo,"VALIDATION onset rows (not in D2+ today)")
ot=oblock(teo,pto,"TEST onset rows (not in D2+ today)")
auc_o=roc_auc_score(teo.y,pto); print("Onset AUC test: %.3f"%auc_o)
# matched alarms vs 'D1 or worse now' on test onset rows
k=int((teo.cls>=2).sum()); topk=np.zeros(len(teo),bool); topk[np.argsort(-pto)[:k]]=True
ma=dict(alarms=k,forest_caught=int((topk&(teo.y.values==1)).sum()),rule_caught=int(((teo.cls>=2)&(teo.y==1)).sum()))
print("Matched alarms (same count as 'D1 or worse now'):",ma)
# hybrid system on all test rows: D2+ now -> warn; else onset forest
hyb=np.where(te.cls.values>=3,True,rfo.predict_proba(te[FE])[:,1]>=tho); hv=np.where(va.cls.values>=3,True,rfo.predict_proba(va[FE])[:,1]>=tho)
print("\nHybrid (persistence + onset forest) cost  val:",tally(va,hv)["cost"]," test:",tally(te,hyb))
# shuffled-label check on onset model
aucs=[]
for s in range(3):
    ys=tro.y.sample(frac=1,random_state=s).values
    m=RandomForestClassifier(n_estimators=60,max_depth=12,min_samples_leaf=50,n_jobs=2,random_state=s).fit(tro[FE],ys)
    aucs.append(roc_auc_score(teo.y,m.predict_proba(teo[FE])[:,1]))
print("Shuffled-label onset AUC (should be ~0.5): %.3f"%np.mean(aucs))
# per river and per year (onset rows, test)
teo=teo.assign(p=pto,al=pto>=tho)
pr=[]
for rv,g in teo.groupby("river"):
    pr.append(dict(river=rv,counties=g.fips.nunique(),positives=int(g.y.sum()),forest_cost=tally(g,g.al)["cost"],
                   d1_rule_cost=tally(g,g.cls>=2)["cost"],never_cost=MISS*int(g.y.sum()),auc=round(roc_auc_score(g.y,g.p),3)))
print("\nPer river, test onset rows:"); print(pd.DataFrame(pr).to_string(index=False))
py=[]
for yr,g in teo.groupby("year"):
    py.append(dict(year=yr,positives=int(g.y.sum()),forest_cost=tally(g,g.al)["cost"],d1_rule_cost=tally(g,g.cls>=2)["cost"]))
print("\nPer year, test onset rows:"); print(pd.DataFrame(py).to_string(index=False))
imp=pd.Series(rfo.feature_importances_,FE).sort_values(ascending=False).round(3)
print("\nTop features (onset forest):"); print(imp.head(10).to_string())
# event-level: first week a county enters D2+ after >=8 weeks out of it; was there a warning in the prior 4 weeks?
te2=te.assign(al=hyb).sort_values(["fips","date"])
ev=warn=0; lead=[]
for f,g in te2.groupby("fips"):
    c=g.cls.values; al=g.al.values
    for i in range(8,len(c)):
        if c[i]>=3 and (c[i-8:i]<3).all():
            ev+=1; w=[j for j in range(1,5) if al[i-j]]
            if w: warn+=1; lead.append(max(w))
print("\nD2 onset events in test: %d | warned in the prior 4 weeks: %d (%.0f%%) | median lead %s weeks"%(ev,warn,100*warn/max(ev,1),np.median(lead) if lead else "n/a"))
json.dump(dict(n_counties=int(len(sel)),by_river=pd.Series(river[sel]).value_counts().to_dict(),rows=dict(train=len(tr),val=len(va),test=len(te)),
  all_test=allt.to_dict("index"),onset_val=ov.to_dict("index"),onset_test=ot.to_dict("index"),onset_auc=float(auc_o),matched=ma,
  hybrid_test=tally(te,hyb),hybrid_val_cost=tally(va,hv)["cost"],shuffled_auc=float(np.mean(aucs)),per_river=pr,per_year=py,
  events=dict(n=ev,warned=warn),top_features=imp.head(10).to_dict(),last_week=str(dates[-1].date())),open(OUT,"w"),indent=1,default=float)
