"""H100 experiments with Data (1).zip as the sole data source.

Run with the user's configured Modal client. Credentials are never copied.
"""
from pathlib import Path
import hashlib
import json
import time
import modal

HERE = Path(__file__).resolve().parent
APP_NAME = "wnba-atlas-data1-20261115"
app = modal.App(APP_NAME, tags={"project":"wnba-shot-atlas","source":"data1","run":"20261115"})
volume = modal.Volume.from_name("wnba-atlas-data1-20261115",create_if_missing=True)
base_image = modal.Image.debian_slim(python_version="3.12").pip_install(
    "numpy==2.2.6","pandas==2.2.3","scipy==1.15.3","scikit-learn==1.6.1","matplotlib==3.10.3"
)
gpu_image = base_image.pip_install(
    "jax[cuda12]==0.6.2","numpyro==0.18.0","arviz==0.21.0","xgboost==2.1.4","catboost==1.2.8"
).env({"XLA_PYTHON_CLIENT_PREALLOCATE":"false","OMP_NUM_THREADS":"2"}).add_local_file(HERE/"gpu_models.py","/root/gpu_models.py")


@app.function(image=gpu_image,gpu="H100",cpu=4,memory=16384,timeout=1800,
              max_containers=4,scaledown_window=2,retries=0,volumes={"/work":volume})
def gpu_task(config):
    import sys
    import traceback
    import subprocess
    start=time.monotonic()
    volume.reload()
    try:
        # Keep native CUDA failures inside a child, so Modal cannot replay an
        # expensive full search after its container crashes.
        completed=subprocess.run([sys.executable,"/root/gpu_models.py","--work","/work","--config",json.dumps(config)],timeout=1700,check=False)
        if completed.returncode:
            raise RuntimeError(f"GPU worker exited with code {completed.returncode}; result is retained as failed, not retried")
        result=json.loads((Path("/work/experiments")/config["id"]/"task.json").read_text())
        result["status"]="complete"
    except Exception as exc:
        traceback.print_exc()
        result={"id":config["id"],"config":config,"status":"failed","error":f"{type(exc).__name__}: {exc}",
                "gpu_allocated_seconds_lower_bound":time.monotonic()-start,
                "gpu_cost_usd_lower_bound":(time.monotonic()-start)*.001097}
    dest=Path("/work/experiments")/config["id"]
    dest.mkdir(parents=True,exist_ok=True)
    (dest/"task.json").write_text(json.dumps(result,indent=2,default=str))
    volume.commit()
    return result


def upload_inputs():
    source=HERE/"data"/"data1"
    audit=HERE/"results"/"data1"/"source_audit.json"
    metadata=json.loads(audit.read_text(encoding="utf-8"))
    assert metadata["only_data_source"]=="Data (1).zip"
    table=source/"model_shots.csv.gz"
    manifest={"source_archive_sha256":metadata["archive_sha256"],"only_data_source":"Data (1).zip",
              "model_table_sha256":hashlib.sha256(table.read_bytes()).hexdigest(),
              "gpu_code_sha256":hashlib.sha256((HERE/"gpu_models.py").read_bytes()).hexdigest(),
              "prepare_code_sha256":hashlib.sha256((HERE/"prepare_data1.py").read_bytes()).hexdigest()}
    (source/"input_manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    with volume.batch_upload(force=True) as upload:
        upload.put_file(table,"/input/model_shots.csv.gz")
        upload.put_file(audit,"/input/source_audit.json")
        upload.put_file(source/"input_manifest.json","/input/input_manifest.json")
    return manifest


def download_task(result):
    dest=HERE/"results"/"data1"/"experiments"/result["id"]
    dest.mkdir(parents=True,exist_ok=True)
    names=["task.json"]
    if result["status"]=="complete":
        names=result.get("files",["task.json","diagnostics.csv","surface.csv","predictions.csv.gz","predictive_check.csv"])
    for name in names:
        with (dest/name).open("wb") as output:
            for block in volume.read_file(f"experiments/{result['id']}/{name}"):
                output.write(block)


def configurations():
    jobs=[]
    def gp(name,**kw):
        jobs.append({"id":name,"basis":24,"players":True,"context":False,"draws":3000,"tune":3000,"seed":20261115,"fold":"main",**kw})
    gp("player24-main")
    gp("context24-main",context=True)
    gp("player32-main",basis=32)
    jobs.append({"id":"boost-main-2026-v214","kind":"boost","seed":2026,"fold":"main"})
    gp("location24-main",players=False)
    gp("player24-length1",min_length=1.)
    gp("player24-warped",warped=True)
    jobs.append({"id":"boost-main-2027-v214","kind":"boost","seed":2027,"fold":"main"})
    gp("player32-wide-domain",basis=32,domain=[48.,50.])
    gp("context32-main",basis=32,context=True)
    gp("player40-main",basis=40)
    jobs.append({"id":"boost-main-2028-v214","kind":"boost","seed":2028,"fold":"main"})
    for fold in ["july","august"]:
        gp(f"player24-{fold}",fold=fold)
        gp(f"context24-{fold}",fold=fold,context=True)
        jobs.append({"id":f"boost-{fold}-2026-v214","kind":"boost","seed":2026,"fold":fold})
    gp("player24-shrinkage025",player_prior=.25)
    gp("player24-shrinkage100",player_prior=1.)
    gp("player32-length1",basis=32,min_length=1.)
    gp("context32-warped",basis=32,context=True,warped=True)
    gp("player32-amplitude050",basis=32,amplitude_prior=.5)
    gp("player32-amplitude200",basis=32,amplitude_prior=2.)
    for basis in [24,32]:
        for buffer in [0,2,4]:
            for fold in range(4):
                gp(f"spatial{basis}-buffer{buffer}-fold{fold}",basis=basis,players=False,context=False,
                   fold="spatial",spatial_fold=fold,buffer=buffer,draws=2000,tune=2000)
    for seed in [20261116,20261117,20261118]:
        gp(f"player32-repeat-{seed}",basis=32,seed=seed,draws=6000,tune=4000)
        gp(f"context32-repeat-{seed}",basis=32,context=True,seed=seed,draws=6000,tune=4000)
    # Longer, independent posterior replications improve Monte Carlo precision
    # and stress the approximation if the first checks use less than the budget.
    for seed in range(20261210,20261231):
        gp(f"precision32-a99-{seed}",basis=32,context=bool(seed%2),seed=seed,draws=8000,tune=6000,domain=[48.,50.],target_accept=.99)
    return jobs


def prior_results():
    root=HERE/"results"/"data1"/"experiments"
    found={}
    if root.exists():
        for p in root.glob("*/task.json"):
            r=json.loads(p.read_text(encoding="utf-8"))
            found[r["id"]]=r
    return found


@app.local_entrypoint()
def main(stage:str="pilot"):
    if stage!="recover" and (HERE/"results"/"data1"/"compute_stop.json").exists():
        raise RuntimeError("Paid GPU work is halted by the user's later credit limit. Analyze saved results locally; do not start more GPU work without a new budget instruction.")
    upload_inputs()
    if stage not in ["pilot","full","smoke","recover","stabilize"]:
        raise ValueError(f"Stage not implemented: {stage}")
    for name in ["pilot-player16","player24-main","context24-main","player32-main"]:
        local=HERE/"results"/"data1"/"experiments"/name/"task.json"
        if not local.exists():
            try:
                result=json.loads(b"".join(volume.read_file(f"experiments/{name}/task.json")))
                download_task(result)
                print("RECOVERED",name,flush=True)
            except FileNotFoundError:
                pass
    if stage=="recover":
        return
    jobs=([{ "id":"pilot-player16","basis":16,"players":True,"context":False,"draws":500,"tune":500,"seed":20261115,"fold":"main"}]
          if stage=="pilot" else [{"id":"xgboost-gpu-smoke214","kind":"smoke","fold":"main"}] if stage=="smoke" else
          [{"id":f"stable32-wide-{'context' if context else 'player'}","basis":32,"players":True,"context":context,
            "draws":8000,"tune":6000,"seed":20261119+int(context),"fold":"main","domain":[48.,50.],"target_accept":.99}
           for context in [False,True]] if stage=="stabilize" else configurations())
    previous=prior_results()
    active=HERE/"data"/"data1"/"active_run.json"
    if active.exists():
        saved=json.loads(active.read_text(encoding="utf-8"))
        assert saved["app"]==APP_NAME
        # A coordinator restart never replays an already submitted fit. Recover
        # its actual call and result before scheduling any more paid work.
        for entry in saved.get("calls",[]):
            if entry["id"] in previous:continue
            print("RECOVERING_ACTIVE",entry["id"],flush=True)
            try:
                result=modal.FunctionCall.from_id(entry["call_id"]).get()
                download_task(result)
            except Exception as exc:
                try:
                    result=json.loads(b"".join(volume.read_file(f"experiments/{entry['id']}/task.json")))
                    download_task(result)
                except Exception:
                    result={"id":entry["id"],"config":entry["config"],"status":"unrecovered","error":str(exc),
                            "gpu_cost_usd_lower_bound":0.,"gpu_cost_guard_usd":4.1}
                    dest=HERE/"results"/"data1"/"experiments"/entry["id"]
                    dest.mkdir(parents=True,exist_ok=True)
                    (dest/"task.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
            previous[result["id"]]=result
            print("RECOVERED_ACTIVE",result["id"],result["status"],flush=True)
    required={j["id"] for j in jobs[:12]} if stage=="full" else set()
    target_gpu_dollars=22.
    hard_gpu_ceiling=32.  # Leaves room within the US$40 total ceiling for CPU/RAM/startup.
    while jobs:
        measured=sum(r.get("gpu_cost_usd_lower_bound",0) for r in previous.values())
        spent=sum(max(r.get("gpu_cost_usd_lower_bound",0),r.get("gpu_cost_guard_usd",0)) for r in previous.values())
        if stage=="full" and measured>=target_gpu_dollars and required.issubset(previous):
            break
        jobs=[j for j in jobs if j["id"] not in previous]
        if not jobs:
            break
        slots=min(4,len(jobs),int((hard_gpu_ceiling-spent)/2.1))
        if slots<1:
            print("BUDGET_STOP",spent,"completed GPU dollars; no new task can fit its full timeout reservation",flush=True)
            break
        batch,jobs=jobs[:slots],jobs[slots:]
        calls=[(config,gpu_task.spawn(config)) for config in batch]
        info={"app":APP_NAME,"stage":stage,"completed_gpu_dollars_lower_bound":spent,
              "calls":[{"id":config["id"],"call_id":call.object_id,"config":config} for config,call in calls]}
        (HERE/"data"/"data1"/"active_run.json").write_text(json.dumps(info,indent=2),encoding="utf-8")
        print("GPU_BATCH",json.dumps(info),flush=True)
        for config,call in calls:
            try:
                result=call.get()
                download_task(result)
            except Exception as exc:
                # Charge the full timeout reservation to the guard if a result
                # cannot be recovered; never assume an interrupted call was free.
                result={"id":config["id"],"config":config,"status":"unrecovered",
                        "error":str(exc),"gpu_cost_usd_lower_bound":0.,"gpu_cost_guard_usd":2.1}
                dest=HERE/"results"/"data1"/"experiments"/config["id"]
                dest.mkdir(parents=True,exist_ok=True)
                (dest/"task.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
            previous[result["id"]]=result
            ledger={"app":APP_NAME,"source":"Data (1).zip","target_gpu_usd":target_gpu_dollars,
                    "total_cost_ceiling_usd":40,"measured_gpu_usd_lower_bound":sum(r.get("gpu_cost_usd_lower_bound",0) for r in previous.values()),
                    "guard_gpu_usd":sum(max(r.get("gpu_cost_usd_lower_bound",0),r.get("gpu_cost_guard_usd",0)) for r in previous.values()),
                    "runs":list(previous.values())}
            (HERE/"results"/"data1"/"compute_ledger.json").write_text(json.dumps(ledger,indent=2,default=str),encoding="utf-8")
            print("GPU_RESULT",json.dumps(result,default=str),flush=True)
        # Unrecovered work remains reserved in future budget decisions.
        guarded=sum(max(r.get("gpu_cost_usd_lower_bound",0),r.get("gpu_cost_guard_usd",0)) for r in previous.values())
        if guarded>=hard_gpu_ceiling:
            break
    print("STUDY_STAGE_COMPLETE",stage,"completed",len(previous),"measured GPU dollars",sum(r.get("gpu_cost_usd_lower_bound",0) for r in previous.values()),flush=True)
