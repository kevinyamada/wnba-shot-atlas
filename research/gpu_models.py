"""GPU experiments using only the prepared Data (1).zip table.

Experiments save individual keyed predictions. Final evaluation is separate.
Sampling checks never stand in for predictive validation.
"""
from __future__ import annotations
import hashlib
import json
import math
import os
import subprocess
import time
from pathlib import Path
import numpy as np
import pandas as pd

CONTEXT = ["period_number", "seconds", "home", "prior_rate", "log_prior_n", "preseason_rate", "preseason_log_n"]
NUMERIC = ["x", "y", "distance", "angle"] + CONTEXT
GPU_RATE = 0.001097  # USD per H100 SXM GPU second, Modal pricing checked 2026-11-15.


def metrics(y, p):
    from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
    p = np.clip(np.asarray(p, float), 1e-12, 1-1e-12)
    assert np.isfinite(p).all()
    return {"shots": len(y), "log_loss": float(log_loss(y,p)), "brier": float(brier_score_loss(y,p)),
            "auc": float(roc_auc_score(y,p)), "mean_prediction": float(p.mean()), "observed": float(np.mean(y))}


def load_data(work, config):
    root = Path(work)
    audit = json.loads((root / "input" / "source_audit.json").read_text())
    assert audit["only_data_source"] == "Data (1).zip"
    p = root / "input" / "model_shots.csv.gz"
    assert hashlib.sha256(p.read_bytes()).hexdigest() == json.loads((root / "input" / "input_manifest.json").read_text())["model_table_sha256"]
    s = pd.read_csv(p, dtype={"player_id":str,"team_id":str})
    if config.get("spatial_fold") is not None:
        from scipy.spatial import cKDTree
        base=s[s.split.eq("train")].copy()
        blocks=base.x.ge(16).astype(int)*2+base.y.ge(0).astype(int)
        validation=base[blocks.eq(int(config["spatial_fold"]))].copy()
        train=base[blocks.ne(int(config["spatial_fold"]))].copy()
        near=cKDTree(validation[["x","y"]].drop_duplicates()).query(train[["x","y"]],k=1)[0]
        train=train[near>float(config["buffer"])].copy()
        separation=cKDTree(validation[["x","y"]].drop_duplicates()).query(train[["x","y"]],k=1)[0].min()
        assert separation>float(config["buffer"]) and not set(train["loc"])&set(validation["loc"])
        assert not config.get("players") and not config.get("context"), "Spatial checks use location only, excluding histories that could cross the spatial split"
    elif config.get("fold", "main") == "main":
        train = s[s.split.eq("train")].copy()
        validation = s[s.split.eq("validation")].copy()
    else:
        cut, end = {"july": ("2025-07-01", "2025-07-21"), "august": ("2025-07-21", "2025-08-10")}[config["fold"]]
        train = s[s.scope.eq("regular") & s.date.lt(cut)].copy()
        validation = s[s.scope.eq("regular") & s.date.ge(cut) & s.date.lt(end)].copy()
    if config.get("spatial_fold") is None:
        assert train.date.max() < validation.date.min()
        assert not set(train.game_id) & set(validation.game_id)
    return s, train, validation, audit


def save_task(dest, record, start):
    record["gpu_allocated_seconds_lower_bound"] = time.monotonic() - start
    record["gpu_cost_usd_lower_bound"] = record["gpu_allocated_seconds_lower_bound"] * GPU_RATE
    record["cost_note"] = "Measured in-function allocation time times published H100 rate; excludes pre-function allocation, CPU, RAM, storage and credits. This is not an invoice."
    (dest / "task.json").write_text(json.dumps(record, indent=2, default=str))
    return record


def fit_gp(work, config):
    start = time.monotonic()
    os.environ["XLA_PYTHON_CLIENT_PREALLOCATE"] = "false"
    os.environ["OMP_NUM_THREADS"] = "2"
    import jax
    jax.config.update("jax_enable_x64", True)
    import jax.numpy as jnp
    import numpyro
    import numpyro.distributions as dist
    from numpyro.infer import MCMC, NUTS
    import arviz as az
    from scipy.special import expit
    assert any(d.platform == "gpu" for d in jax.devices()), "GPU sampling must not silently fall back to CPU"
    s, train, validation, audit = load_data(work, config)
    dest = Path(work) / "experiments" / config["id"]
    dest.mkdir(parents=True, exist_ok=True)
    grid = np.array([(x,y) for x in range(-5,42) for y in range(-25,26)], dtype=float)
    coordinates = grid.copy()
    if config.get("warped"):
        r = np.linalg.norm(coordinates, axis=1)
        factor = np.divide(20*np.arcsinh(r/20), r, out=np.ones_like(r), where=r>0)
        coordinates *= factor[:,None]
    centre = (coordinates.min(axis=0) + coordinates.max(axis=0))/2
    domain = np.array(config.get("domain", [36.,38.]), dtype=float)
    m = int(config.get("basis",24))
    a,b = np.meshgrid(np.arange(1,m+1),np.arange(1,m+1),indexing="ij")
    modes = np.column_stack([a.ravel(),b.ravel()])
    omega = np.pi*modes/(2*domain)
    phi = np.prod(np.sin((coordinates[:,None,:]-centre+domain)*omega[None,:,:])/np.sqrt(domain),axis=2)
    assert np.isfinite(phi).all() and np.all(abs(coordinates-centre) < domain)
    players = sorted(train.player_id.unique())
    mapping = {v:i for i,v in enumerate(players)}
    with_players = bool(config.get("players",True))
    with_context = bool(config.get("context",False))
    if with_context:
        a = train.copy()
        n = np.ones(len(a), dtype=int)
        k = a.made.to_numpy(int)
        means = train[CONTEXT].mean().to_numpy()
        scales = train[CONTEXT].std().clip(lower=1e-6).to_numpy()
        context = (a[CONTEXT].to_numpy()-means)/scales
    else:
        keys = ["loc","player_id"] if with_players else ["loc"]
        a = train.groupby(keys).made.agg(["sum","count"]).reset_index()
        n, k = a["count"].to_numpy(int), a["sum"].to_numpy(int)
        means,scales,context = np.zeros(len(CONTEXT)),np.ones(len(CONTEXT)),np.zeros((len(a),0))
    locations = a["loc"].to_numpy(int)
    pids = a.player_id.map(mapping).to_numpy(int) if with_players else np.zeros(len(a),int)
    phi_j, omega_j = jnp.asarray(phi), jnp.asarray(omega)
    loc_j,pids_j,n_j,k_j,ctx_j = map(jnp.asarray,[locations,pids,n,k,context])
    # Matérn-5/2 spectral density in two dimensions, with anisotropic lengths.
    spectral_constant = 4*np.pi*math.gamma(3.5)*(5**2.5)/math.gamma(2.5)
    low = float(config.get("min_length",3.))

    def model():
        intercept = numpyro.sample("intercept",dist.Normal(0,1))
        ell = numpyro.sample("ell",dist.TruncatedNormal(8,3,low=low,high=20).expand([2]).to_event(1))
        eta = numpyro.sample("eta",dist.HalfNormal(float(config.get("amplitude_prior",1.))))
        z = numpyro.sample("z",dist.Normal(0,1).expand([m*m]).to_event(1))
        psd = eta**2*spectral_constant*jnp.prod(ell)/(5+jnp.sum((omega_j*ell)**2,axis=1))**3.5
        spatial = phi_j@(z*jnp.sqrt(psd))
        logits = intercept+spatial[loc_j]
        if with_players:
            sigma = numpyro.sample("sigma_player",dist.HalfNormal(float(config.get("player_prior",.5))))
            z_player = numpyro.sample("z_player",dist.Normal(0,1).expand([len(players)]).to_event(1))
            alpha = sigma*(z_player-jnp.mean(z_player))*jnp.sqrt(len(players)/(len(players)-1))
            logits = logits+alpha[pids_j]
        if with_context:
            beta = numpyro.sample("beta",dist.Normal(0,.35).expand([len(CONTEXT)]).to_event(1))
            logits = logits+ctx_j@beta
        numpyro.sample("observed",dist.Binomial(total_count=n_j,logits=logits),obs=k_j)

    device_info = subprocess.check_output(["nvidia-smi","--query-gpu=name,uuid,memory.total","--format=csv,noheader"],text=True).strip()
    print("GP_START",config,"training",len(train),"likelihood_groups",len(a),"device",device_info,flush=True)
    sampler = NUTS(model,target_accept_prob=float(config.get("target_accept",.96)),max_tree_depth=11)
    mcmc = MCMC(sampler,num_warmup=int(config.get("tune",2500)),num_samples=int(config.get("draws",2500)),num_chains=4,chain_method="vectorized",progress_bar=False)
    mcmc.run(jax.random.PRNGKey(int(config.get("seed",20261115))),extra_fields=("diverging","num_steps","accept_prob"))
    posterior = mcmc.get_samples(group_by_chain=True)
    stats = mcmc.get_extra_fields(group_by_chain=True)
    trace = az.from_numpyro(mcmc,log_likelihood=False)
    diag = az.summary(trace,var_names=list(posterior),kind="diagnostics",round_to=6)
    diag.to_csv(dest/"diagnostics.csv")
    divergences = int(np.asarray(stats["diverging"]).sum())
    diagnostic = {"max_rhat":float(diag.r_hat.max()),"minimum_bulk_ess":float(diag.ess_bulk.min()),
                  "minimum_tail_ess":float(diag.ess_tail.min()),"divergences":divergences,
                  "mean_acceptance":float(np.asarray(stats["accept_prob"]).mean()),
                  "max_tree_depth_hits":int((np.asarray(stats["num_steps"])>=2047).sum())}
    diagnostic["sampling_checks_pass"] = bool(diagnostic["max_rhat"] < 1.01 and diagnostic["minimum_bulk_ess"] >= 400 and divergences == 0 and diagnostic["max_tree_depth_hits"] == 0)
    samples = {key:np.asarray(value).reshape((-1,)+np.asarray(value).shape[2:]) for key,value in posterior.items()}
    ell,eta = samples["ell"],samples["eta"]
    psd = eta[:,None]**2*spectral_constant*np.prod(ell,axis=1)[:,None]/(5+np.sum((omega[None,:,:]*ell[:,None,:])**2,axis=2))**3.5
    weights = samples["z"]*np.sqrt(psd)
    if with_players:
        zp = samples["z_player"]
        alpha = samples["sigma_player"][:,None]*(zp-zp.mean(axis=1,keepdims=True))*np.sqrt(len(players)/(len(players)-1))
    else:
        alpha = np.empty((len(weights),0))
    np.savez_compressed(dest/"posterior.npz",weights=weights,intercept=samples["intercept"],ell=ell,eta=eta,alpha=alpha,players=np.array(players),phi=phi,grid=grid,
                        sigma_player=samples.get("sigma_player",np.zeros(len(weights))),beta=samples.get("beta",np.empty((len(weights),0))),context_means=means,context_scales=scales)
    indices = np.linspace(0,len(weights)-1,min(3000,len(weights)),dtype=int)
    latent = samples["intercept"][indices,None]+weights[indices]@phi.T
    surface = expit(latent)
    pd.DataFrame({"x":grid[:,0],"y":grid[:,1],"mean":surface.mean(axis=0),"lower":np.quantile(surface,.025,axis=0),"upper":np.quantile(surface,.975,axis=0)}).to_csv(dest/"surface.csv",index=False)
    rng = np.random.default_rng(int(config.get("seed",20261115)))
    output = []
    sets = [("validation",validation)]
    if config.get("fold","main") == "main":
        sets += [(split,s[s.split.eq(split)]) for split in ["test","playoffs"]]
    for split,b in sets:
        probs=[]
        unknown={v:rng.normal(size=len(indices))*samples["sigma_player"][indices] for v in b.player_id.unique() if with_players and v not in mapping}
        for first in range(0,len(b),256):
            q=b.iloc[first:first+256]
            linear=latent[:,q["loc"].to_numpy(int)].copy()
            if with_players:
                for j,player in enumerate(q.player_id):
                    linear[:,j]+=alpha[indices,mapping[player]] if player in mapping else unknown[player]
            if with_context:
                linear+=samples["beta"][indices]@((q[CONTEXT].to_numpy()-means)/scales).T
            probs.extend(expit(linear).mean(axis=0))
        pred=b[["source_row","game_id","game_play_number","made","points"]].copy()
        pred["split"]=split
        pred["prediction"]=probs
        output.append(pred)
    predictions=pd.concat(output,ignore_index=True)
    predictions.to_csv(dest/"predictions.csv.gz",index=False)
    val=predictions[predictions.split.eq("validation")]
    # A small training posterior-predictive check, explicitly not validation.
    pick=indices[np.linspace(0,len(indices)-1,min(500,len(indices)),dtype=int)]
    base=samples["intercept"][pick,None]+weights[pick]@phi.T
    made_checks=[]
    for lo,hi in [(0,4),(4,8),(8,12),(12,16),(16,20),(20,24),(24,28),(28,100)]:
        b=train[train.distance.ge(lo)&train.distance.lt(hi)]
        if not len(b):continue
        lin=base[:,b["loc"].to_numpy(int)].copy()
        if with_players:
            lin+=alpha[pick][:,[mapping[v] for v in b.player_id]]
        if with_context:
            lin+=samples["beta"][pick]@((b[CONTEXT].to_numpy()-means)/scales).T
        totals=rng.binomial(1,expit(lin)).sum(axis=1)
        made_checks.append({"distance_lower":lo,"distance_upper":hi,"attempts":len(b),"observed_makes":int(b.made.sum()),"simulated_lower":float(np.quantile(totals,.025)),"simulated_upper":float(np.quantile(totals,.975))})
    pd.DataFrame(made_checks).to_csv(dest/"predictive_check.csv",index=False)
    record={"id":config["id"],"family":"Bayesian HSGP","config":config,"source_archive_sha256":audit["archive_sha256"],"training_shots":len(train),"training_games":int(train.game_id.nunique()),
            "training_last_date":train.date.max(),"validation_first_date":validation.date.min(),"validation":metrics(val.made,val.prediction),"diagnostics":diagnostic,"gpu":device_info,
            "jax_version":jax.__version__,"numpyro_version":numpyro.__version__,"surface_reference":"Player effect zero; context at the training column means when used.",
            "predictions_note":"Posterior mean of transformed probabilities. Unknown players integrated over the player distribution. All four chains contribute equally."}
    record=save_task(dest,record,start)
    print("GP_COMPLETE",json.dumps(record,default=str),flush=True)
    return record


def fit_boost(work, config):
    """Compare spatial and contextual GPU trees, plus a joint 0/2/3 model."""
    start=time.monotonic()
    from catboost import CatBoostClassifier
    from xgboost import XGBClassifier
    from sklearn.metrics import log_loss
    s,train,validation,audit=load_data(work,config)
    dest=Path(work)/"experiments"/config["id"]
    dest.mkdir(parents=True,exist_ok=True)
    seed=int(config.get("seed",20261115))
    candidates=[]
    winners={}
    device_info=subprocess.check_output(["nvidia-smi","--query-gpu=name,memory.total","--format=csv,noheader"],text=True).strip()
    assert "H100" in device_info or "H200" in device_info
    print("BOOST_START",config,"training",len(train),"device",device_info,flush=True)

    def inputs(a,cols,family):
        x=a[cols].copy()
        if family=="xgboost":
            for col in ["player_id","team_id"]:
                if col in cols:
                    levels=list(train[col].unique())+["__unknown__"]
                    x[col]=pd.Categorical(x[col].where(x[col].isin(levels),"__unknown__"),categories=levels)
        return x

    for family in ["catboost","xgboost"]:
        for contextual in [False,True]:
            cols=NUMERIC+["player_id","team_id"] if contextual else ["x","y","distance","angle"]
            label=("CatBoost" if family=="catboost" else "XGBoost")+(" context" if contextual else " spatial")
            xt,xv=inputs(train,cols,family),inputs(validation,cols,family)
            best=None
            for depth in ([4,6,8] if family=="catboost" else [3,5,7]):
                for penalty in [3.,10.,30.]:
                    began=time.monotonic()
                    if family=="catboost":
                        model=CatBoostClassifier(iterations=2500,depth=depth,learning_rate=.035,l2_leaf_reg=penalty,
                             loss_function="Logloss",task_type="GPU",devices="0",thread_count=4,random_seed=seed,
                             verbose=False,allow_writing_files=False,early_stopping_rounds=150)
                        model.fit(xt,train.made,cat_features=[c for c in ["player_id","team_id"] if c in cols],eval_set=(xv,validation.made),use_best_model=True)
                        ntrees=int(model.tree_count_)
                    else:
                        model=XGBClassifier(n_estimators=2500,max_depth=depth,learning_rate=.035,reg_lambda=penalty,
                             min_child_weight=30,subsample=.85,colsample_bytree=.9,tree_method="hist",device="cuda",
                             enable_categorical=True,max_cat_to_onehot=10,objective="binary:logistic",eval_metric="logloss",
                             n_jobs=4,random_state=seed,early_stopping_rounds=150)
                        model.fit(xt,train.made,eval_set=[(xv,validation.made)],verbose=False)
                        ntrees=int(model.best_iteration+1)
                        assert '"device":"cuda' in model.get_booster().save_config()
                    p=model.predict_proba(xv)[:,1]
                    row={"family":label,"depth":depth,"penalty":penalty,"trees":ntrees,"seconds":time.monotonic()-began,**metrics(validation.made,p)}
                    candidates.append(row)
                    if best is None or row["log_loss"]<best[0]["log_loss"]:
                        best=(row,model,cols,family)
                    print("BOOST_CANDIDATE",config["id"],label,depth,penalty,row["log_loss"],flush=True)
            winners[label]=best
    # Joint outcome probabilities preserve P(make)=P(2)+P(3) without inventing miss labels.
    cols=NUMERIC+["player_id","team_id"]
    best=None
    for depth in [4,6,8]:
        for penalty in [3.,10.,30.]:
            model=CatBoostClassifier(iterations=2500,depth=depth,learning_rate=.035,l2_leaf_reg=penalty,
                  loss_function="MultiClass",task_type="GPU",devices="0",thread_count=4,random_seed=seed,
                  verbose=False,allow_writing_files=False,early_stopping_rounds=150)
            model.fit(train[cols],train.points,cat_features=["player_id","team_id"],eval_set=(validation[cols],validation.points),use_best_model=True)
            p=model.predict_proba(validation[cols])
            loss=float(log_loss(validation.points,p,labels=model.classes_))
            row={"family":"Joint 0/2/3 points","depth":depth,"penalty":penalty,"trees":int(model.tree_count_),"joint_log_loss":loss,**metrics(validation.made,p[:,1]+p[:,2])}
            candidates.append(row)
            if best is None or loss<best[0]["joint_log_loss"]:
                best=(row,model,cols,"catboost")
            print("JOINT_CANDIDATE",config["id"],depth,penalty,loss,flush=True)
    winners["Joint 0/2/3 points"]=best
    sets=[("validation",validation)]
    if config.get("fold","main")=="main":
        sets += [(split,s[s.split.eq(split)]) for split in ["test","playoffs"]]
    predictions=[]
    for split,b in sets:
        q=b[["source_row","game_id","game_play_number","made","points"]].copy()
        q["split"]=split
        for name,(row,model,cols,family) in winners.items():
            p=model.predict_proba(inputs(b,cols,family))
            assert np.isfinite(p).all() and np.allclose(p.sum(axis=1),1)
            if name=="Joint 0/2/3 points":
                assert list(model.classes_)==[0,2,3]
                q[name]=p[:,1]+p[:,2]
                q["expected_points"]=2*p[:,1]+3*p[:,2]
                q["p_zero"],q["p_two"],q["p_three"]=p[:,0],p[:,1],p[:,2]
            else:
                q[name]=p[:,1]
        predictions.append(q)
    pd.concat(predictions,ignore_index=True).to_csv(dest/"predictions.csv.gz",index=False)
    pd.DataFrame(candidates).to_csv(dest/"candidate_validation.csv",index=False)
    for name,(row,model,cols,family) in winners.items():
        slug=name.lower().replace(" ","_").replace("/","_")
        model.save_model(str(dest/(slug+(".cbm" if family=="catboost" else ".json"))))
    record={"id":config["id"],"family":"GPU tree comparison","config":config,"source_archive_sha256":audit["archive_sha256"],
            "training_shots":len(train),"training_last_date":train.date.max(),"validation_first_date":validation.date.min(),"candidates_fitted":len(candidates),
            "selected":{name:item[0] for name,item in winners.items()},"gpu":device_info,
            "files":["task.json","predictions.csv.gz","candidate_validation.csv"],
            "selection":"Validation log loss for binary models; validation multiclass log loss for the joint points model. No later-game metrics enter selection."}
    record=save_task(dest,record,start)
    print("BOOST_COMPLETE",json.dumps(record,default=str),flush=True)
    return record


def smoke_gpu(work,config):
    start=time.monotonic()
    import xgboost
    from xgboost import XGBClassifier
    _,train,validation,audit=load_data(work,config)
    cols=["x","y","distance","angle"]
    m=XGBClassifier(n_estimators=10,max_depth=2,device="cuda",tree_method="hist",n_jobs=2)
    m.fit(train[cols].iloc[:2000],train.made.iloc[:2000])
    assert '"device":"cuda' in m.get_booster().save_config()
    p=m.predict_proba(validation[cols].iloc[:100])[:,1]
    assert np.isfinite(p).all() and ((p>=0)&(p<=1)).all()
    dest=Path(work)/"experiments"/config["id"]
    dest.mkdir(parents=True,exist_ok=True)
    return save_task(dest,{"id":config["id"],"family":"GPU compatibility check","config":config,"xgboost_version":xgboost.__version__,
                          "source_archive_sha256":audit["archive_sha256"],"gpu_device_verified":True,"files":["task.json"]},start)


if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("--work",default="/work")
    parser.add_argument("--config",required=True)
    args=parser.parse_args()
    cfg=json.loads(args.config)
    worker=smoke_gpu if cfg.get("kind")=="smoke" else fit_boost if cfg.get("kind")=="boost" else fit_gp
    result=worker(args.work,cfg)
    print("WORKER_COMPLETE",cfg["id"],flush=True)
