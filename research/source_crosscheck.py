"""Independent source qualification using outer joins, including zero-attempt players."""
from pathlib import Path
import argparse
import json
import zipfile
import pandas as pd

HERE=Path(__file__).resolve().parent


def main():
    ap=argparse.ArgumentParser();ap.add_argument("--source",type=Path,required=True);args=ap.parse_args()
    with zipfile.ZipFile(args.source) as z:
        def load(suffix):
            name=next(n for n in z.namelist() if n.endswith(suffix))
            return pd.read_csv(z.open(name),low_memory=False)
        d=load("/original/wehoop_wnba_pbp.csv")
        players=load("/WNBA_player/wnba_player_box.csv")
        teams=load("/WNBA_Team/wnba_team_box.csv")
    s=d[d.shooting_play.eq(True)&~d.type_text.str.contains("free throw",case=False,na=False)].copy()
    a=s.groupby(["game_id","athlete_id_1"]).agg(event_fga=("scoring_play","size"),event_fgm=("scoring_play","sum"),event_points=("score_value","sum")).reset_index()
    p=players[players.season.eq(2025)].copy()
    for c in ["field_goals_attempted","field_goals_made","three_point_field_goals_made"]:
        p[c]=pd.to_numeric(p[c],errors="raise").fillna(0)
    p["fg_points"]=2*p.field_goals_made+p.three_point_field_goals_made
    p=p.rename(columns={"athlete_id":"athlete_id_1"})
    outer=p[["game_id","athlete_id_1","team_id","field_goals_attempted","field_goals_made","fg_points"]].merge(a,on=["game_id","athlete_id_1"],how="outer",validate="one_to_one",indicator=True)
    source_only=outer._merge.eq("right_only")
    assert not source_only.any(),"An event shooter has no matching player box"
    for c in ["event_fga","event_fgm","event_points"]:outer[c]=outer[c].fillna(0)
    outer["fga_difference"]=outer.event_fga-outer.field_goals_attempted
    outer["fgm_difference"]=outer.event_fgm-outer.field_goals_made
    outer["points_difference"]=outer.event_points-outer.fg_points
    bad=outer[["fga_difference","fgm_difference","points_difference"]].ne(0).any(axis=1)
    missing_shooters=outer._merge.eq("left_only")&outer.field_goals_attempted.gt(0)
    expected=pd.read_csv(HERE/"results"/"data1"/"excluded_games.csv")
    assert set(outer.loc[bad,"game_id"].astype(int))==set(expected.game_id.astype(int)),"The original exclusion list missed a discrepant game"
    assert not missing_shooters.any(),"A positive-attempt player was omitted by the event-to-box join"
    grouped=p.groupby(["game_id","team_id"])[["field_goals_attempted","field_goals_made","fg_points"]].sum().reset_index()
    t=teams[teams.season.eq(2025)].copy();t["fg_points"]=2*t.field_goals_made+t.three_point_field_goals_made
    t=grouped.merge(t[["game_id","team_id","field_goals_attempted","field_goals_made","fg_points"]],on=["game_id","team_id"],how="outer",validate="one_to_one",suffixes=("_players","_team"))
    identities={c:bool(t[c+"_players"].eq(t[c+"_team"]).all()) for c in ["field_goals_attempted","field_goals_made","fg_points"]}
    assert all(identities.values())
    past=players[players.season.between(2022,2024)&players.season_type.eq(2)].copy()
    assert not past.duplicated(["game_id","athlete_id"]).any()
    fga=pd.to_numeric(past.field_goals_attempted,errors="coerce").fillna(0)
    fgm=pd.to_numeric(past.field_goals_made,errors="coerce").fillna(0)
    assert fga.ge(0).all() and fgm.between(0,fga).all()
    result={"only_data_source":args.source.name,"source_events":len(d),"attempted_shooter_pairs":len(a),"all_player_boxes_including_zero_attempts":len(outer),
            "outer_join_finds_no_omitted_positive_attempt_player":True,"disagreeing_player_game_totals":int(bad.sum()),"excluded_game_list_complete":True,
            "player_box_sums_match_all_team_boxes":identities,"preseason_2022_2024_keys_unique":True,"preseason_counts_nonnegative_and_makes_le_attempts":True,
            "nonshot_coordinates_outside_court_bounds":int(((d.coordinate_x.abs()>47)|(d.coordinate_y.abs()>25)).sum()),
            "scope":"Independent source qualification. Final result and live-site verification run after the completed analysis and publication."}
    out=HERE/"results"/"data1"/"source_crosscheck.json"
    out.write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps(result,indent=2))


if __name__=="__main__":main()
