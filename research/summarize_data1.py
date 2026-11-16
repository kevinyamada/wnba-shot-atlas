"""Freeze development choices, then evaluate keyed Data1 predictions.

Run after the experiment coordinator finishes. No later game result chooses a
model, prior, seed, calibration method, or ensemble weight.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.special import expit,logit
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss,brier_score_loss,roc_auc_score
from court_geometry import R

HERE=Path(__file__).resolve().parent
DATA=HERE/"data"/"data1"
OUT=HERE/"results"/"data1"
KEYS=["source_row","game_id","game_play_number","split"]


def score(y,p):
    p=np.clip(np.asarray(p,float),1e-12,1-1e-12)
    return {"shots":len(y),"brier":float(np.mean((np.asarray(y)-p)**2)),"log_loss":float(log_loss(y,p)),
            "auc":float(roc_auc_score(y,p)),"mean_prediction":float(p.mean()),"observed":float(np.mean(y))}


def aligned(path,truth):
    p=pd.read_csv(path)
    assert not p.duplicated(KEYS).any(),path
    q=truth[KEYS+["made","points"]].merge(p,on=KEYS,how="outer",validate="one_to_one",indicator=True,suffixes=("_truth",""))
    assert q._merge.eq("both").all(),f"Unmatched event keys: {path}"
    assert q.made.eq(q.made_truth).all() and q.points.eq(q.points_truth).all(),f"Outcome disagreement: {path}"
    return q.drop(columns=["made_truth","points_truth","_merge"]).set_index(KEYS).reindex(pd.MultiIndex.from_frame(truth[KEYS]))


def gp_key(config):
    return json.dumps({k:config.get(k,default) for k,default in [
        ("basis",24),("players",True),("context",False),("warped",False),("min_length",3.),
        ("player_prior",.5),("amplitude_prior",1.),("domain",[36.,38.])]},sort_keys=True)


def bootstrap(a,names,baseline,split):
    rng=np.random.default_rng(20261115)
    games=sorted(a.game_id.unique());rows=[]
    weights=rng.multinomial(len(games),np.full(len(games),1/len(games)),size=2000)
    for name in names:
        error=(a[name]-a.made)**2-(a[baseline]-a.made)**2
        g=pd.DataFrame({"game_id":a.game_id,"error":error}).groupby("game_id").error.agg(["sum","count"]).reindex(games)
        draws=(weights@g["sum"].to_numpy())/(weights@g["count"].to_numpy())
        rows.append({"split":split,"model":name,"baseline":baseline,"games":len(games),"shots":len(a),
                     "brier_difference":float(error.mean()),"lower":float(np.quantile(draws,.025)),"upper":float(np.quantile(draws,.975))})
    return rows


def main():
    ap=argparse.ArgumentParser();ap.add_argument("--allow-incomplete",action="store_true",help="Development inventory only; never scores later periods or freezes a release.");args=ap.parse_args()
    source=json.loads((OUT/"source_audit.json").read_text(encoding="utf-8"))
    assert source["only_data_source"]=="Data (1).zip"
    s=pd.read_csv(DATA/"model_shots.csv.gz",dtype={"player_id":str,"team_id":str})
    truth=s[s.split.ne("train")].sort_values(KEYS).reset_index(drop=True)
    valmask=truth.split.eq("validation").to_numpy()
    cpu=aligned(OUT/"cpu"/"predictions.csv.gz",truth)
    names=[c for c in cpu if c not in ["made","points"]]
    predictions=truth[KEYS+["made","points"]].copy()
    for name in names:predictions[name]=cpu[name].to_numpy()
    records=[]
    for file in sorted((OUT/"experiments").glob("*/task.json")):
        r=json.loads(file.read_text(encoding="utf-8"));r["directory"]=str(file.parent)
        if r.get("source_archive_sha256"):
            assert r["source_archive_sha256"]==source["archive_sha256"]
        records.append(r)
    diagnostic_rows=[];groups={};spatial_records=[]
    for r in records:
        if r.get("family")!="Bayesian HSGP":continue
        c=r["config"];d=r.get("diagnostics",{})
        diagnostic_rows.append({"id":r["id"],"fold":c.get("fold","main"),"basis":c.get("basis"),"draws_per_chain":c.get("draws"),"chains":4,**d,
                                "gpu_seconds":r.get("gpu_allocated_seconds_lower_bound"),"gpu_usd_lower_bound":r.get("gpu_cost_usd_lower_bound")})
        if c.get("spatial_fold") is not None:
            spatial_records.append(r);continue
        if r.get("status")=="complete" and c.get("fold","main")=="main" and d.get("sampling_checks_pass"):
            groups.setdefault(gp_key(c),[]).append(r)
    assert groups,"No eligible GP fit"
    gp_candidates=[];gp_predictions={};stability=[]
    for key,runs in groups.items():
        # Precision/diagnostics, never predictive performance, choose a seed.
        representative=max(runs,key=lambda r:(r["config"].get("draws",0),r["diagnostics"].get("minimum_bulk_ess",0),r["id"]))
        q=aligned(Path(representative["directory"])/"predictions.csv.gz",truth)
        p=q.prediction.to_numpy()
        assert np.isfinite(p).all() and ((p>=0)&(p<=1)).all()
        row={"id":representative["id"],"configuration":key,"replications":len(runs),**score(truth.loc[valmask,"made"],p[valmask])}
        gp_candidates.append(row);gp_predictions[representative["id"]]=p
        for other in runs:
            if other["id"]==representative["id"]:continue
            z=aligned(Path(other["directory"])/"predictions.csv.gz",truth).prediction.to_numpy()
            stability.append({"configuration":key,"reference":representative["id"],"replication":other["id"],"mean_absolute_prediction_change":float(abs(p-z).mean()),"maximum_prediction_change":float(abs(p-z).max())})
    gp_table=pd.DataFrame(gp_candidates).sort_values("log_loss")
    gp_table.to_csv(OUT/"gp_validation_selection.csv",index=False)
    pd.DataFrame(diagnostic_rows).to_csv(OUT/"gp_diagnostics.csv",index=False)
    pd.DataFrame(stability).to_csv(OUT/"gp_replication_stability.csv",index=False)
    selected_gp=gp_table.iloc[0]["id"]
    predictions["Bayesian GP"]=gp_predictions[selected_gp]
    names.append("Bayesian GP")
    joint_probabilities=[];boost_records=[]
    for seed in [2026,2027,2028]:
        r=next((r for r in records if r["id"]==f"boost-main-{seed}-v214" and r.get("status")=="complete"),None)
        if r:boost_records.append(r)
    if not args.allow_incomplete:assert len(boost_records)==3,"All three main seed comparisons must finish"
    for family in ["CatBoost spatial","CatBoost context","XGBoost spatial","XGBoost context","Joint 0/2/3 points"]:
        values=[]
        for r in boost_records:
            q=aligned(Path(r["directory"])/"predictions.csv.gz",truth)
            values.append(q[family].to_numpy())
            if family=="Joint 0/2/3 points":
                joint_probabilities.append(q[["p_zero","p_two","p_three"]].to_numpy())
        if values:
            predictions[family]=np.mean(values,axis=0);names.append(family)
    joint_cpu=aligned(OUT/"cpu"/"joint_predictions.csv.gz",truth)
    predictions["Joint outcome logistic"]=joint_cpu.prediction.to_numpy();names.append("Joint outcome logistic")
    components=["Distance baseline","SPDE","Bayesian GP","CatBoost context","XGBoost context"]
    if all(c in predictions for c in components):
        predictions["Equal-weight ensemble"]=predictions[components].mean(axis=1)
        names.append("Equal-weight ensemble")
    validation=pd.DataFrame([{"model":name,**score(predictions.loc[valmask,"made"],predictions.loc[valmask,name])} for name in names]).sort_values("log_loss")
    validation.to_csv(OUT/"validation_models.csv",index=False)
    if args.allow_incomplete:
        print("DEVELOPMENT_INVENTORY_ONLY",len(records),"runs",len(groups),"eligible GP configurations")
        print(validation.to_string(index=False));return
    ledger=json.loads((OUT/"compute_ledger.json").read_text(encoding="utf-8"))
    stopped=OUT/"compute_stop.json"
    stop=json.loads(stopped.read_text(encoding="utf-8")) if stopped.exists() else None
    assert ledger["measured_gpu_usd_lower_bound"]>=20 or (stop and stop.get("all_study_apps_stopped") and stop.get("remaining_credit_usd_reported_by_user")==1),"The requested GPU minimum has not been reached, and no later budget stop supersedes it"
    assert ledger["guard_gpu_usd"]<=32.01,"Review the budget guard before publication"
    log=(HERE/"data"/"modal_data1_full_v214.log").read_text(encoding="utf-16",errors="replace")
    assert "STUDY_STAGE_COMPLETE full" in log or (stop and stop.get("all_study_apps_stopped")),"The full experiment stage is still running"
    selected_model=str(validation.iloc[0].model)
    selected_record=next(r for r in records if r["id"]==selected_gp)
    receipt={"source_archive_sha256":source["archive_sha256"],"only_data_source":"Data (1).zip","selection_data":"August 10-26, 2025, eligible attempts only",
             "selected_gp_id":selected_gp,"selected_gp_configuration":selected_record["config"],"selected_model":selected_model,
             "gp_seed_rule":"Highest retained-draw count, then bulk ESS, within the same configuration; not the best-performing seed.",
             "tree_seed_rule":"Equal mean of the three validation-selected seed fits.","ensemble_components":components,"ensemble_weights":[1/len(components)]*len(components),
             "training_cutoff":"2025-08-09","calibration_cutoff":"2025-08-26","test_not_used_for_selection":True,
             "evaluation_limit":source["evaluation_limit"],"gp_diagnostics":selected_record["diagnostics"],
             "gpu_function_seconds":float(sum(r.get("gpu_allocated_seconds_lower_bound",0) for r in records)),
             "gpu_usd_lower_bound":float(ledger["measured_gpu_usd_lower_bound"]),"guard_gpu_usd":float(ledger["guard_gpu_usd"])}
    receipt["compute_stage"]="Stopped on the user's later credit limit; evaluate completed runs only." if stop else "Completed scheduled study"
    # Persist the choice before calculating any new later game scores.
    (OUT/"selection_receipt.json").write_text(json.dumps(receipt,indent=2,default=str),encoding="utf-8")
    calibration_x=logit(predictions.loc[valmask,"Equal-weight ensemble"].clip(1e-8,1-1e-8).to_numpy())[:,None]
    calibrator=LogisticRegression(C=1000,max_iter=2000).fit(calibration_x,predictions.loc[valmask,"made"])
    predictions["Validation-calibrated ensemble"]=calibrator.predict_proba(logit(predictions["Equal-weight ensemble"].clip(1e-8,1-1e-8).to_numpy())[:,None])[:,1]
    calibration_params={"intercept":float(calibrator.intercept_[0]),"slope":float(calibrator.coef_[0,0]),"fit_interval":"2025-08-10 through 2025-08-26","validation_score_is_in_sample":True}
    (OUT/"calibration_parameters.json").write_text(json.dumps(calibration_params,indent=2))
    all_names=names+["Validation-calibrated ensemble"]
    rows=[];calibration=[];boot=[]
    for split,a in predictions.groupby("split"):
        for name in all_names:
            if split=="validation" and name=="Validation-calibrated ensemble":continue
            rows.append({"split":split,"model":name,**score(a.made,a[name])})
            b=a.assign(bin=pd.cut(a[name],np.linspace(0,1,11),include_lowest=True))
            for key,g in b.groupby("bin",observed=True):
                calibration.append({"split":split,"model":name,"bin":str(key),"shots":len(g),"mean_prediction":float(g[name].mean()),"observed_rate":float(g.made.mean())})
        if split!="validation":boot.extend(bootstrap(a,all_names,"Distance baseline",split))
    pd.DataFrame(rows).to_csv(OUT/"metrics.csv",index=False)
    pd.DataFrame(calibration).to_csv(OUT/"calibration.csv",index=False)
    pd.DataFrame(boot).to_csv(OUT/"game_bootstrap.csv",index=False)
    predictions.to_csv(DATA/"comparison_predictions.csv.gz",index=False)
    # Score every GP specification as a secondary analysis after the frozen choice.
    gp_rows=[]
    for r in gp_candidates:
        p=gp_predictions[r["id"]]
        for split in ["validation","test","playoffs"]:
            mask=truth.split.eq(split).to_numpy()
            gp_rows.append({"id":r["id"],"configuration":r["configuration"],"split":split,**score(truth.loc[mask,"made"],p[mask])})
    pd.DataFrame(gp_rows).to_csv(OUT/"all_gp_benchmarks.csv",index=False)
    # Spatial GP tests have no history/player features and must cover all four folds.
    cv=pd.read_csv(OUT/"cpu"/"spatial_cv.csv").to_dict("records")
    for basis in [24,32]:
        for buffer in [0,2,4]:
            fits=[r for r in spatial_records if r["config"]["basis"]==basis and r["config"]["buffer"]==buffer]
            if len(fits)!=4 or not all(r.get("diagnostics",{}).get("sampling_checks_pass") for r in fits):continue
            for r in fits:
                cv.append({"buffer_ft":buffer,"fold":r["config"]["spatial_fold"],"model":f"Spatial GP ({basis})",**r["validation"]})
    pd.DataFrame(cv).to_csv(OUT/"spatial_cv.csv",index=False)
    # Points comparisons all use observed 0/2/3 outcomes from the same archive.
    train=s[s.split.eq("train")];edges=[0,4,8,12,16,20,R,24,28,100]
    groups=train.assign(bin=np.digitize(train.distance,edges)-1).groupby(["bin","points"]).size().unstack(fill_value=0).reindex(columns=[0,2,3],fill_value=0)
    post=(groups+1).div(groups.sum(axis=1)+3,axis=0)
    bins=pd.Series(np.digitize(truth.distance,edges)-1)
    distance_probs=post.reindex(bins).to_numpy(copy=True)
    fallback=(train.points.value_counts().reindex([0,2,3],fill_value=0).to_numpy()+1)/(len(train)+3)
    distance_probs[np.isnan(distance_probs).any(axis=1)]=fallback
    point_models={"Constant outcome baseline":np.repeat(fallback[None,:],len(truth),axis=0),"Distance outcome baseline":distance_probs,
                  "Joint outcome logistic":joint_cpu[["p_zero","p_two","p_three"]].to_numpy(),"Joint GPU outcome model":np.mean(joint_probabilities,axis=0)}
    point_rows=[];point_tables=[]
    for name,p in point_models.items():
        assert np.isfinite(p).all() and (p>=0).all() and (p<=1).all() and np.allclose(p.sum(axis=1),1)
        q=truth[KEYS+["made","points"]].copy();q["model"]=name
        q["p_zero"],q["p_two"],q["p_three"]=p[:,0],p[:,1],p[:,2]
        q["make_prediction"]=p[:,1]+p[:,2];q["expected_points"]=p@np.array([0.,2.,3.])
        for split,a in q.groupby("split"):
            point_rows.append({"split":split,"model":name,"shots":len(a),"rmse":float(np.sqrt(np.mean((a.expected_points-a.points)**2))),
                               "mae":float(np.mean(abs(a.expected_points-a.points))),"mean_expected":float(a.expected_points.mean()),"mean_observed":float(a.points.mean())})
        point_tables.append(q)
    pd.DataFrame(point_rows).to_csv(OUT/"points_metrics.csv",index=False)
    pd.concat(point_tables,ignore_index=True).to_csv(DATA/"points_comparison_predictions.csv.gz",index=False)
    point_boot=[]
    point_base=next(q for q in point_tables if q.model.iloc[0]=="Distance outcome baseline")
    for split in ["test","playoffs"]:
        mask=point_base.split.eq(split)
        base_error=(point_base.loc[mask,"expected_points"].to_numpy()-point_base.loc[mask,"points"].to_numpy())**2
        for q in point_tables:
            a=q[q.split.eq(split)].copy()
            difference=(a.expected_points-a.points).to_numpy()**2-base_error
            g=pd.DataFrame({"game":a.game_id,"difference":difference}).groupby("game").difference.agg(["sum","count"])
            rng=np.random.default_rng(20261116)
            w=rng.multinomial(len(g),np.full(len(g),1/len(g)),size=2000)
            draws=(w@g["sum"].to_numpy())/(w@g["count"].to_numpy())
            point_boot.append({"split":split,"model":q.model.iloc[0],"baseline":"Distance outcome baseline","mse_difference":float(difference.mean()),
                               "lower":float(np.quantile(draws,.025)),"upper":float(np.quantile(draws,.975)),"games":len(g),"shots":len(a)})
    pd.DataFrame(point_boot).to_csv(OUT/"points_game_bootstrap.csv",index=False)
    # Publish the exact saved posterior surface used by the selected configuration.
    surface=pd.read_csv(Path(selected_record["directory"])/"surface.csv")
    assert len(surface)==2397 and surface["mean"].between(0,1).all()
    surface.to_csv(OUT/"gp_surface.csv",index=False)
    clean_runs=[]
    for r in records:
        c=r.get("config",{})
        clean_runs.append({"id":r["id"],"family":r.get("family","GPU runtime failure"),"status":r.get("status"),"fold":c.get("fold"),"basis":c.get("basis"),
                           "draws_per_chain":c.get("draws"),"tune_per_chain":c.get("tune"),"candidate_models":r.get("candidates_fitted",0),
                           "gpu_seconds":r.get("gpu_allocated_seconds_lower_bound",0),"gpu_usd_lower_bound":r.get("gpu_cost_usd_lower_bound",0),
                           "budget_guard_usd":r.get("gpu_cost_guard_usd",0),"sampling_checks_pass":r.get("diagnostics",{}).get("sampling_checks_pass")})
    pd.DataFrame(clean_runs).to_csv(OUT/"gpu_experiments.csv",index=False)
    usage={"gpu_type":"H100 requested; completed results verified on NVIDIA H100 80GB. Later H200 workers were stopped before results completed.","source":"Data (1).zip","measured_gpu_usd_lower_bound":ledger["measured_gpu_usd_lower_bound"],
           "guarded_gpu_usd":ledger["guard_gpu_usd"],"total_budget_ceiling_usd":40,"successful_runs":sum(r.get("status")=="complete" for r in records),
           "boosting_candidates_fitted":sum(r.get("candidates_fitted",0) for r in records),
           "basis":"Measured completed in-function GPU allocation times times the H100 rate; interrupted work, CPU/RAM/startup and credits are reported separately from this lower bound.",
           "original_target_gpu_usd":20,"original_measured_gpu_target_met":ledger["measured_gpu_usd_lower_bound"]>=20,
           "budget_stop":stop}
    (OUT/"compute_usage.json").write_text(json.dumps(usage,indent=2))
    print("FROZEN_SELECTION",json.dumps(receipt,default=str),flush=True)
    print(pd.DataFrame(rows).query("split=='test'").sort_values("log_loss").to_string(index=False))


if __name__=="__main__":main()
