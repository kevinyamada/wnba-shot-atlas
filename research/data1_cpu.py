"""Reference models and descriptive summaries rebuilt exclusively from Data (1).zip."""
from __future__ import annotations
import os
for key in ["OMP_NUM_THREADS","OPENBLAS_NUM_THREADS","MKL_NUM_THREADS"]:
    os.environ[key]="4"
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from scipy.stats import beta
from sklearn.preprocessing import SplineTransformer, StandardScaler, OneHotEncoder
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss, brier_score_loss, roc_auc_score
from spatial_methods import IDW, Kriging, SPDE
from court_geometry import offset, R, JOIN

HERE=Path(__file__).resolve().parent
DATA=HERE/"data"/"data1"
OUT=HERE/"results"/"data1"/"cpu"
CONTEXT=["period_number","seconds","home","prior_rate","log_prior_n","preseason_rate","preseason_log_n"]


def score(y,p):
    p=np.clip(np.asarray(p,float),1e-12,1-1e-12)
    assert np.isfinite(p).all()
    return {"shots":len(y),"brier":float(brier_score_loss(y,p)),"log_loss":float(log_loss(y,p)),"auc":float(roc_auc_score(y,p)),"mean_prediction":float(p.mean()),"observed":float(np.mean(y))}


def distance_model(train,test):
    edges=[0,4,8,12,16,20,R,24,28,100]
    labels=np.digitize(train.distance,edges)-1
    a=train.assign(bin=labels).groupby("bin").made.agg(["sum","count"])
    posterior=(a["sum"]+1)/(a["count"]+2)
    return pd.Series(np.digitize(test.distance,edges)-1,index=test.index).map(posterior).fillna(train.made.mean()).to_numpy()


def design(train):
    spline=SplineTransformer(n_knots=5,degree=3,include_bias=False).fit(train[["x","y"]])
    scaler=StandardScaler().fit(train[CONTEXT])
    encoder=OneHotEncoder(handle_unknown="ignore",sparse_output=False).fit(train[["player_id","team_id"]])
    def transform(s,kind):
        b=spline.transform(s[["x","y"]]);n=b.shape[1]//2
        base=np.column_stack([b,np.einsum("ij,ik->ijk",b[:,:n],b[:,n:]).reshape(len(s),-1)])
        if kind=="context":
            return np.column_stack([base,scaler.transform(s[CONTEXT]),encoder.transform(s[["player_id","team_id"]])])
        return base
    return transform


def compare(s):
    OUT.mkdir(parents=True,exist_ok=True)
    train=s[s.split.eq("train")].copy();val=s[s.split.eq("validation")].copy()
    assert train.date.max()<val.date.min() and not set(train.game_id)&set(val.game_id)
    transform=design(train)
    candidates=[];models={}
    for kind,label in [("spatial","Spatial logistic"),("context","Context logistic")]:
        best=None
        for c in [.1,1.,10.]:
            m=LogisticRegression(C=c,max_iter=3000).fit(transform(train,kind),train.made)
            loss=log_loss(val.made,m.predict_proba(transform(val,kind))[:,1])
            candidates.append({"family":label,"setting":str(c),"validation_log_loss":loss})
            if best is None or loss<best[0]:best=(loss,m,kind)
        models[label]=("logistic",best[1],best[2])
    best=None
    for power in [1,2,3]:
        m=IDW(power).fit(train);loss=log_loss(val.made,m.predict(val))
        candidates.append({"family":"IDW","setting":str(power),"validation_log_loss":loss})
        if best is None or loss<best[0]:best=(loss,m)
    models["IDW"]=("spatial",best[1],None)
    for universal,label in [(False,"Ordinary kriging"),(True,"Universal kriging")]:
        m=Kriging(universal).fit(train);models[label]=("spatial",m,None)
        pd.DataFrame(m.variogram,columns=["distance","semivariance","pairs"]).to_csv(OUT/(label.replace(" ","_")+"_variogram.csv"),index=False)
    best=None
    for length in [4,8,16]:
        for sigma in [.3,.7,1.5]:
            m=SPDE(length,sigma,3).fit(train);loss=log_loss(val.made,m.predict(val))
            candidates.append({"family":"SPDE","setting":f"range={length};sigma={sigma};spacing=3","validation_log_loss":loss})
            if best is None or loss<best[0]:best=(loss,m)
    models["SPDE"]=("spatial",best[1],None)
    predictions=[];rows=[]
    for split,b in s[s.split.ne("train")].groupby("split"):
        q=b[["source_row","game_id","game_play_number","made","points"]].copy();q["split"]=split
        q["Constant baseline"]=train.made.mean()
        q["Distance baseline"]=distance_model(train,b)
        for name,(family,m,kind) in models.items():
            q[name]=m.predict_proba(transform(b,kind))[:,1] if family=="logistic" else m.predict(b)
        for name in ["Constant baseline","Distance baseline"]+list(models):
            rows.append({"split":split,"model":name,**score(b.made,q[name])})
        predictions.append(q)
    pd.concat(predictions,ignore_index=True).to_csv(OUT/"predictions.csv.gz",index=False)
    pd.DataFrame(rows).to_csv(OUT/"metrics.csv",index=False)
    # Interim expected FG points: model observed outcomes, without guessed miss values.
    joint=[]
    for c in [.1,1.,10.]:
        m=LogisticRegression(C=c,max_iter=3000).fit(transform(train,"context"),train.points)
        loss=log_loss(val.points,m.predict_proba(transform(val,"context")),labels=m.classes_)
        joint.append((loss,c,m))
    loss,c,m=min(joint,key=lambda q:q[0]);point_predictions=[]
    for split,b in s[s.split.ne("train")].groupby("split"):
        p=m.predict_proba(transform(b,"context"));assert list(m.classes_)==[0,2,3]
        q=b[["source_row","game_id","game_play_number","made","points"]].copy();q["split"]=split
        q["p_zero"],q["p_two"],q["p_three"]=p[:,0],p[:,1],p[:,2]
        q["prediction"]=p[:,1]+p[:,2];q["expected_points"]=p@np.array([0,2,3])
        point_predictions.append(q)
    pd.concat(point_predictions).to_csv(OUT/"joint_predictions.csv.gz",index=False)
    candidates.append({"family":"Joint outcome logistic","setting":str(c),"validation_joint_log_loss":loss})
    pd.DataFrame(candidates).to_csv(OUT/"validation_selection.csv",index=False)
    mesh=models["SPDE"][1]
    (OUT/"mesh.json").write_text(json.dumps({"nodes":mesh.nodes.tolist(),"triangles":mesh.mesh.simplices.tolist(),"range_ft":mesh.range_ft,"sigma":mesh.sigma,"spacing":mesh.spacing,"gradient_max":mesh.gradient_max,"inference":"Conditional Gaussian Laplace approximation; hyperparameters fixed using validation, not INLA or full hyperparameter integration."}))
    params={name:{"sill":float(models[name][1].sill),"scale":float(models[name][1].scale)} for name in ["Ordinary kriging","Universal kriging"]}
    (OUT/"model_parameters.json").write_text(json.dumps(params,indent=2))
    refinement=[];previous=None
    for spacing in [3,2,1.5]:
        m=mesh if spacing==3 else SPDE(mesh.range_ft,mesh.sigma,spacing).fit(train)
        p=m.predict(val)
        refinement.append({"spacing_ft":spacing,"nodes":len(m.nodes),"validation_log_loss":float(log_loss(val.made,p)),"mean_prediction_change":None if previous is None else float(abs(p-previous).mean()),"maximum_prediction_change":None if previous is None else float(abs(p-previous).max())})
        previous=p
    pd.DataFrame(refinement).to_csv(OUT/"mesh_refinement.csv",index=False)
    print("CPU_MODEL_COMPARISON_COMPLETE",flush=True)


def spatial_cv(s):
    train=s[s.split.eq("train")].copy();rows=[];folds=[]
    blocks=(train.x.ge(16).astype(int)*2+train.y.ge(0).astype(int))
    for buffer in [0,2,4]:
        for fold in range(4):
            te=train[blocks.eq(fold)].copy();tr=train[blocks.ne(fold)].copy()
            distance=cKDTree(te[["x","y"]].drop_duplicates()).query(tr[["x","y"]],k=1)[0]
            tr=tr[distance>buffer].copy()
            separation=cKDTree(te[["x","y"]].drop_duplicates()).query(tr[["x","y"]],k=1)[0].min()
            assert separation>buffer and not set(tr["loc"])&set(te["loc"])
            folds.append({"buffer_ft":buffer,"fold":fold,"train_shots":len(tr),"test_shots":len(te),"minimum_separation_ft":float(separation)})
            predictions={"Distance baseline":distance_model(tr,te)}
            for name,model in [("IDW",IDW(2)),("Ordinary kriging",Kriging(False)),("Universal kriging",Kriging(True)),("SPDE",SPDE(8,.7,3))]:
                predictions[name]=model.fit(tr).predict(te)
            trans=design(tr)
            m=LogisticRegression(C=1,max_iter=3000).fit(trans(tr,"spatial"),tr.made)
            predictions["Spatial logistic"]=m.predict_proba(trans(te,"spatial"))[:,1]
            for name,p in predictions.items():rows.append({"buffer_ft":buffer,"fold":fold,"model":name,**score(te.made,p)})
            print("CPU_SPATIAL_FOLD",buffer,fold,"complete",flush=True)
    pd.DataFrame(rows).to_csv(OUT/"spatial_cv.csv",index=False)
    pd.DataFrame(folds).to_csv(OUT/"spatial_folds.csv",index=False)


def descriptive():
    s=pd.read_csv(DATA/"all_shots.csv.gz",dtype={"team_id":str,"player_id":str})
    r=s[s.scope.eq("regular")].copy();half=r[r.x.between(-5.25,41.75)]
    cell=half.groupby(["x","y","team_id","athlete_id_1"]).agg(n=("made","size"),k=("made","sum"),points=("points","sum")).reset_index()
    assert cell.n.sum()==38441 and cell.k.sum()==16926 and cell.points.sum()==38533
    cell.to_csv(OUT/"site_cells.csv.gz",index=False)
    for name,keys in [("team_summary",["team_id"]),("player_summary",["athlete_id_1","player"]),("player_regions",["athlete_id_1","player","region"]),("team_regions",["team_id","region"]),("league_regions",["region"])]:
        a=r.groupby(keys).agg(attempts=("made","size"),makes=("made","sum"),points=("points","sum"),games=("game_id","nunique")).reset_index()
        a["make_rate"]=a.makes/a.attempts;a["points_per_attempt"]=a.points/a.attempts
        a.to_csv(OUT/(name+".csv"),index=False)
    d=offset(r.x,r.y)
    gx,gy=np.meshgrid(np.arange(-5.225,41.75,.05),np.arange(-24.975,25,.05));gd=offset(gx,gy)
    rows=[]
    for label,mask,gmask in [("All locations",np.ones(len(r),bool),np.ones(gx.shape,bool)),("Curved arc region",r.x.to_numpy()>JOIN,gx>JOIN),("Corner region",r.x.to_numpy()<=JOIN,gx<=JOIN)]:
        edges=np.arange(-4,4,1);counts=np.histogram(d[mask],edges)[0];areas=np.histogram(gd[gmask],edges)[0]*.0025
        for lo,hi,c,a in zip(edges[:-1],edges[1:],counts,areas):rows.append({"region":label,"offset_lower":int(lo),"offset_upper":int(hi),"attempts":int(c),"area_sqft":float(a),"attempts_per_sqft":float(c/a)})
    pd.DataFrame(rows).to_csv(OUT/"arc_density.csv",index=False)
    inside_area=float(((gd>=-2)&(gd<0)).sum()*.0025);outside_area=float(((gd>0)&(gd<=2)).sum()*.0025)
    g=r.assign(inside=(d>=-2)&(d<0),outside=(d>0)&(d<=2)).groupby("game_id")[["inside","outside"]].sum()
    rng=np.random.default_rng(2026);w=rng.multinomial(len(g),np.full(len(g),1/len(g)),size=2000)
    ratios=(w@g.outside.to_numpy()/outside_area)/(w@g.inside.to_numpy()/inside_area)
    jitter=[]
    for _ in range(100):
        jd=offset(np.clip(r.x+rng.uniform(-.5,.5,len(r)),-5.25,88.75),np.clip(r.y+rng.uniform(-.5,.5,len(r)),-25,25))
        jitter.append((((jd>0)&(jd<=2)).sum()/outside_area)/(((jd>=-2)&(jd<0)).sum()/inside_area))
    arc={"half_court_shots_shown":len(half),"shots_outside_view":len(r)-len(half),"inside_2ft_attempts":int(g.inside.sum()),"outside_2ft_attempts":int(g.outside.sum()),
         "exactly_on_line_attempts_excluded_from_ratio":int(np.isclose(d,0).sum()),"inside_2ft_area":inside_area,"outside_2ft_area":outside_area,
         "outside_inside_density_ratio":float((g.outside.sum()/outside_area)/(g.inside.sum()/inside_area)),"game_bootstrap_95_interval":np.quantile(ratios,[.025,.975]).tolist(),
         "coordinate_sensitivity_ratio_range":[float(min(jitter)),float(max(jitter))],"sensitivity_note":"Artificial coordinate perturbations; a sensitivity check, not observed movement or a confidence interval."}
    (OUT/"arc_review.json").write_text(json.dumps(arc,indent=2))
    print("DATA1_DESCRIPTIVE_COMPLETE",json.dumps(arc),flush=True)


def main():
    p=argparse.ArgumentParser();p.add_argument("--stage",choices=["all","models","spatial","descriptive"],default="all");args=p.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    s=pd.read_csv(DATA/"model_shots.csv.gz",dtype={"player_id":str,"team_id":str})
    if args.stage in ["all","models"]:compare(s)
    if args.stage in ["all","spatial"]:spatial_cv(s)
    if args.stage in ["all","descriptive"]:descriptive()


if __name__=="__main__":main()
