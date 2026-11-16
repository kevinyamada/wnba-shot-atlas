"""Build the website from the completed, frozen Data1 analysis only."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import zipfile
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

HERE=Path(__file__).resolve().parent
OUT=HERE/'results'/'data1'
CPU=OUT/'cpu'


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--source',type=Path,required=True);ap.add_argument('--preview',action='store_true',help='Private UI preview using provisional validation summaries; never a release.');args=ap.parse_args()
    source=json.loads((OUT/'source_audit.json').read_text(encoding='utf-8'))
    if args.preview:
        gp_id=pd.read_csv(OUT/'gp_validation_selection.csv').iloc[0]['id']
        selection={'source_archive_sha256':source['archive_sha256'],'selected_gp_id':gp_id,
                   'selected_model':pd.read_csv(OUT/'validation_models.csv').iloc[0]['model'],'preview_only':True}
        gp_path=OUT/'experiments'/gp_id/'surface.csv'
        metrics=pd.read_csv(CPU/'metrics.csv').to_dict('records')
        points_metrics=[];points_bootstrap=[];bootstrap=[];spatial_path=CPU/'spatial_cv.csv'
        ledger=json.loads((OUT/'compute_ledger.json').read_text())
        compute={'successful_runs':sum(r.get('status')=='complete' for r in ledger['runs']),
                 'boosting_candidates_fitted':sum(r.get('candidates_fitted',0) for r in ledger['runs']),
                 'measured_gpu_usd_lower_bound':ledger['measured_gpu_usd_lower_bound']}
    else:
        selection=json.loads((OUT/'selection_receipt.json').read_text(encoding='utf-8'))
        gp_path=OUT/'gp_surface.csv';metrics=pd.read_csv(OUT/'metrics.csv').to_dict('records')
        points_metrics=pd.read_csv(OUT/'points_metrics.csv').to_dict('records');points_bootstrap=pd.read_csv(OUT/'points_game_bootstrap.csv').to_dict('records')
        bootstrap=pd.read_csv(OUT/'game_bootstrap.csv').to_dict('records');spatial_path=OUT/'spatial_cv.csv'
        compute=json.loads((OUT/'compute_usage.json').read_text())
    assert selection['source_archive_sha256']==source['archive_sha256']
    s=pd.read_csv(HERE/'data/data1/all_shots.csv.gz',low_memory=False)
    regular=s[s.scope.eq('regular')]
    a=pd.read_csv(CPU/'site_cells.csv.gz')
    names=regular.groupby('athlete_id_1').player.first()
    with zipfile.ZipFile(args.source) as z:
        name=next(n for n in z.namelist() if n.endswith('/WNBA_Team/wnba_team_box.csv'))
        teams=pd.read_csv(z.open(name),low_memory=False)
    teams=teams[teams.season.eq(2025)&teams.team_id.isin(regular.team_id)].groupby('team_id').team_display_name.first()
    gp=pd.read_csv(gp_path).sort_values(['x','y'])
    cv=pd.read_csv(spatial_path)
    cvsum=[]
    for (buffer,model),b in cv.groupby(['buffer_ft','model']):
        assert len(b)==4 and b.shots.sum()==25751
        cvsum.append({'buffer':int(buffer),'model':model,'brier':float(np.average(b.brier,weights=b.shots)),'log_loss':float(np.average(b.log_loss,weights=b.shots))})
    data={'cells':a[['x','y','team_id','athlete_id_1','n','k','points']].astype(int).values.tolist(),
          'players':{str(int(k)):v for k,v in names.items()},'teams':{str(int(k)):v for k,v in teams.items()},
          'gp':np.round(gp[['x','y','mean','lower','upper']].to_numpy(),6).tolist(),
          'arc':json.loads((CPU/'arc_review.json').read_text()),
          'arcBins':pd.read_csv(CPU/'arc_density.csv').query("region == 'All locations'").to_dict('records'),
          'metrics':metrics,'spatialCV':cvsum,
          'folds':pd.read_csv(CPU/'spatial_folds.csv').to_dict('records'),
          'bootstrap':bootstrap,
          'mesh':json.loads((CPU/'mesh.json').read_text()),
          'variogram':pd.read_csv(CPU/'Universal_kriging_variogram.csv').to_dict('records'),
          'kriging':json.loads((CPU/'model_parameters.json').read_text())['Universal kriging'],
          'source':source,'selection':selection,'compute':compute,
          'pointsMetrics':points_metrics,'pointsBootstrap':points_bootstrap}
    followup=OUT/'followup'
    if (followup/'local_metrics.csv').exists() and not args.preview:
        receipt=json.loads((followup/'local_model_receipt.json').read_text(encoding='utf-8'))
        assert receipt['archive_sha256']==source['archive_sha256'] and receipt['no_cloud_gpu_used']
        data['localFollowup']={'metrics':pd.read_csv(followup/'local_metrics.csv').to_dict('records'),
                              'paired':pd.read_csv(followup/'local_game_bootstrap.csv').to_dict('records'),
                              'receipt':receipt,'sourceInvestigation':json.loads((followup/'archive_investigation.json').read_text(encoding='utf-8'))}
    possession=OUT/'possession'
    if (possession/'metrics.csv').exists() and not args.preview:
        receipt=json.loads((possession/'model_selection_receipt.json').read_text(encoding='utf-8'))
        assert receipt['archive_sha256']==source['archive_sha256'] and receipt['runtime']=='desktop CPU only'
        data['possessionValue']={'audit':json.loads((possession/'reconstruction_audit.json').read_text(encoding='utf-8')),
            'selection':receipt,'metrics':pd.read_csv(possession/'metrics.csv').to_dict('records'),
            'bootstrap':pd.read_csv(possession/'game_bootstrap.csv').to_dict('records'),
            'summary':pd.read_csv(possession/'value_summary.csv').to_dict('records'),
            'calibration':pd.read_csv(possession/'calibration.csv').to_dict('records'),
            'markov':json.loads((possession/'markov_diagnostics.json').read_text(encoding='utf-8'))}
    train=pd.read_csv(HERE/'data/data1/model_shots.csv.gz').query("split == 'train'")[['x','y']].drop_duplicates().copy()
    train['fold']=train.x.ge(16).astype(int)*2+train.y.ge(0).astype(int)
    train['nearest']=cKDTree(train[train.fold.eq(0)][['x','y']]).query(train[['x','y']])[0]
    data['trainingLocations']=np.round(train.to_numpy(),6).tolist()
    assert len(data['teams'])==13 and len(gp)==2397
    assert sum(r[4] for r in data['cells'])==38441
    if args.preview:
        root=HERE/'data/site_preview';(root/'assets').mkdir(parents=True,exist_ok=True)
        for name in ['index.html','app.js','style.css']:shutil.copyfile(HERE.parent/name,root/name)
    else:root=HERE.parent
    output=root/'assets/data.json'
    output.write_text(json.dumps(data,separators=(',',':'),allow_nan=False),encoding='utf-8')
    receipt={'only_data_source':'Data (1).zip','archive_sha256':source['archive_sha256'],
             'site_data_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
             'cell_player_team_groups':len(a),'surface_locations':len(gp),'selected_model':selection['selected_model'],
             'public_data_path':'assets/data.json'}
    if not args.preview:(OUT/'publication_receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    print(json.dumps(receipt,indent=2))


if __name__=='__main__':main()
