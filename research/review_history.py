"""Check the supplied pre 2025 count features against supplied team totals."""
from pathlib import Path
import argparse
import json
import zipfile
import pandas as pd

HERE=Path(__file__).resolve().parent


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--source',type=Path,required=True);args=ap.parse_args()
    with zipfile.ZipFile(args.source) as z:
        def read(suffix):return pd.read_csv(z.open(next(n for n in z.namelist() if n.endswith(suffix))),low_memory=False)
        players=read('/WNBA_player/wnba_player_box.csv');teams=read('/WNBA_Team/wnba_team_box.csv')
    p=players[players.season.between(2022,2024)&players.season_type.eq(2)].copy()
    t=teams[teams.season.between(2022,2024)&teams.season_type.eq(2)].copy()
    fields=['field_goals_attempted','field_goals_made','three_point_field_goals_made']
    for c in fields:p[c]=pd.to_numeric(p[c],errors='coerce').fillna(0)
    a=p.groupby(['season','game_id','team_id'])[fields].sum().reset_index()
    joined=a.merge(t[['season','game_id','team_id']+fields],on=['season','game_id','team_id'],how='outer',validate='one_to_one',suffixes=('_players','_team'),indicator=True)
    for c in fields:joined[c+'_difference']=joined[c+'_players']-joined[c+'_team']
    joined.to_csv(HERE/'results/data1/preseason_box_reconciliation.csv',index=False)
    disagreements=joined[[c+'_difference' for c in fields]].ne(0).any(axis=1)
    result={'only_data_source':'Data (1).zip','window':'2022-2024 season_type=2','player_game_rows':len(p),'game_team_rows':len(joined),
            'all_game_teams_present_in_both':bool(joined._merge.eq('both').all()),'disagreeing_game_team_rows':int(disagreements.sum()),
            'counts':joined.groupby('season').size().to_dict(),
            'feature_definition':'Player sums are used as fixed recorded preseason counts; no source values are repaired. Any disagreements here are a limitation of those supplied historical records.'}
    (HERE/'results/data1/preseason_history_audit.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
