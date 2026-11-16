"""Data (1).zip is the only source. No downloads or inferred attempt values.

Field goal outcomes are observed makes/misses and actual 0/2/3 points.
Conflicting score sequences are audited and never enter the predictors.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import zipfile
from pathlib import Path
import numpy as np
import pandas as pd
from court_geometry import offset, zones

HERE = Path(__file__).resolve().parent
NUMERIC = ["x", "y", "distance", "angle", "period_number", "seconds", "home", "prior_rate", "log_prior_n", "preseason_rate", "preseason_log_n"]
CATEGORICAL = ["player_id", "team_id"]
SPECIAL = [401781604, 401736430]


def member(z, suffix):
    matches = [n for n in z.namelist() if n.endswith(suffix)]
    assert len(matches) == 1, (suffix, matches)
    raw = z.read(matches[0])
    import io
    return pd.read_csv(io.BytesIO(raw), low_memory=False), {"member": matches[0], "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, required=True)
    args = ap.parse_args()
    source = args.source.resolve(strict=True)
    existing = json.loads((HERE / "results" / "archive_audit.json").read_text(encoding="utf-8"))
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    assert source.name == "Data (1).zip" and digest.hexdigest() == existing["source_sha256"], "Source differs from the inventoried Data (1).zip"
    out = HERE / "results" / "data1"
    data = HERE / "data" / "data1"
    out.mkdir(parents=True, exist_ok=True)
    data.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source) as z:
        d, pbp_info = member(z, "/original/wehoop_wnba_pbp.csv")
        box, box_info = member(z, "/WNBA_Team/wnba_team_box.csv")
        players, player_info = member(z, "/WNBA_player/wnba_player_box.csv")
    assert set(d.season.unique()) == {2025}
    assert not d.duplicated(["game_id", "game_play_number"]).any()
    d["source_row"] = np.arange(len(d)) + 2
    d = d.sort_values(["game_id", "game_play_number"], kind="stable").reset_index(drop=True)
    for c in ["home_score", "away_score"]:
        d["before_" + c] = d.groupby("game_id")[c].shift().fillna(0)
    s = d[d.shooting_play.eq(True) & ~d.type_text.str.contains("free throw", case=False, na=False)].copy()
    s["made"] = s.scoring_play.astype(int)
    s["points"] = pd.to_numeric(s.score_value).astype(int)
    assert s.points.isin([0, 2, 3]).all() and s.points.gt(0).eq(s.made.eq(1)).all()
    assert not s[["coordinate_x", "coordinate_y", "athlete_id_1"]].isna().any().any()
    assert s.coordinate_x.abs().le(47).all() and s.coordinate_y.abs().le(25).all()
    for c in ["game_id", "game_play_number", "athlete_id_1", "team_id"]:
        s[c] = pd.to_numeric(s[c]).astype("int64")
    s["home"] = s.team_id.eq(s.home_team_id).astype(int)
    sign = np.where(s.home.eq(1), 1, -1)
    s["x"] = 41.75 - s.coordinate_x * sign
    s["y"] = s.coordinate_y * sign
    s["distance"] = np.hypot(s.x, s.y)
    s["angle"] = np.arctan2(s.y.abs(), s.x)
    clock = s.clock_display_value.str.split(":", expand=True).astype(float)
    s["seconds"] = clock[0] * 60 + clock[1]
    assert s.seconds.between(0, 600).all()
    s["date_time"] = pd.to_datetime(s.game_date_time, utc=True)
    s["date"] = pd.to_datetime(s.game_date, utc=True).dt.strftime("%Y-%m-%d")
    s["scope"] = np.where(s.game_id.isin(SPECIAL), "special", np.where(s.season_type.eq(3), "playoffs", "regular"))
    s["arc_offset_exact"] = offset(s.x, s.y)
    s["region"] = zones(s.x, s.y)
    check = s.groupby(["game_id", "team_id"]).agg(fga=("made", "size"), fgm=("made", "sum"), fg_points=("points", "sum")).reset_index()
    b = box[box.season.eq(2025)]
    assert not b.duplicated(["game_id", "team_id"]).any()
    check = check.merge(b[["game_id", "team_id", "field_goals_attempted", "field_goals_made", "three_point_field_goals_made"]], on=["game_id", "team_id"], how="outer", validate="one_to_one", indicator=True)
    check["attempts_difference"] = check.fga - check.field_goals_attempted
    check["makes_difference"] = check.fgm - check.field_goals_made
    check["points_difference"] = check.fg_points - 2 * check.field_goals_made - check.three_point_field_goals_made
    assert len(check) == 624 and check._merge.eq("both").all()
    assert check[["attempts_difference", "makes_difference", "points_difference"]].eq(0).all().all()
    check.to_csv(out / "team_box_reconciliation.csv", index=False)
    # Names and prior season features come from the same archive, using ESPN IDs.
    names = players[players.season.eq(2025)][["game_id", "athlete_id", "athlete_display_name"]].drop_duplicates()
    assert not names.duplicated(["game_id", "athlete_id"]).any()
    s = s.merge(names, left_on=["game_id", "athlete_id_1"], right_on=["game_id", "athlete_id"], how="left", validate="many_to_one")
    assert s.athlete_display_name.notna().all()
    s["player"] = s.athlete_display_name
    pc = s.groupby(["game_id", "athlete_id_1"]).agg(fga=("made", "size"), fgm=("made", "sum"), points=("points", "sum")).reset_index()
    pb = players[players.season.eq(2025)].copy()
    pb["fg_points"] = 2 * pd.to_numeric(pb.field_goals_made) + pd.to_numeric(pb.three_point_field_goals_made)
    pc = pc.merge(pb[["game_id", "athlete_id", "field_goals_attempted", "field_goals_made", "fg_points"]], left_on=["game_id", "athlete_id_1"], right_on=["game_id", "athlete_id"], validate="one_to_one")
    pc["attempts_difference"] = pc.fga - pc.field_goals_attempted
    pc["makes_difference"] = pc.fgm - pc.field_goals_made
    pc["points_difference"] = pc.points - pc.fg_points
    pc.to_csv(out / "player_box_reconciliation.csv", index=False)
    bad_players = pc[["attempts_difference", "makes_difference", "points_difference"]].ne(0).any(axis=1)
    bad_games = set(pc.loc[bad_players, "game_id"])
    excluded = s[s.game_id.isin(bad_games)].groupby(["game_id", "date", "scope"]).agg(attempts=("made", "size"), makes=("made", "sum")).reset_index()
    excluded["reason"] = "Player field-goal-attempt attribution disagrees between event and box-score files; neither is silently corrected."
    excluded.to_csv(out / "excluded_games.csv", index=False)
    retained = pc[~pc.game_id.isin(bad_games)]
    assert retained[["attempts_difference", "makes_difference", "points_difference"]].eq(0).all().all()
    p = players[players.season.between(2022, 2024) & players.season_type.eq(2)].copy()
    for c in ["field_goals_attempted", "field_goals_made"]:
        p[c] = pd.to_numeric(p[c], errors="coerce").fillna(0)
    prior = p.groupby("athlete_id").agg(n=("field_goals_attempted", "sum"), k=("field_goals_made", "sum"))
    assert prior.k.between(0, prior.n).all()
    s["preseason_n"] = s.athlete_id_1.map(prior.n).fillna(0)
    s["preseason_k"] = s.athlete_id_1.map(prior.k).fillna(0)
    s["preseason_rate"] = (s.preseason_k + 22) / (s.preseason_n + 50)
    s["preseason_log_n"] = np.log1p(s.preseason_n)
    r = s[s.scope.eq("regular") & ~s.game_id.isin(bad_games)]
    history = r.groupby(["date_time", "game_id", "athlete_id_1"]).agg(n=("made", "size"), k=("made", "sum")).reset_index().sort_values(["date_time", "game_id"], kind="stable")
    history["prior_n"] = history.groupby("athlete_id_1").n.cumsum() - history.n
    history["prior_k"] = history.groupby("athlete_id_1").k.cumsum() - history.k
    history["history_latest_time"] = history.groupby("athlete_id_1").date_time.shift()
    assert (history.history_latest_time.isna() | history.history_latest_time.lt(history.date_time)).all()
    s = s.merge(history[["game_id", "athlete_id_1", "prior_n", "prior_k", "history_latest_time"]], on=["game_id", "athlete_id_1"], how="left", validate="many_to_one")
    totals = r.groupby("athlete_id_1").agg(n=("made", "size"), k=("made", "sum"))
    playoff = s.scope.eq("playoffs")
    for target, origin in [("prior_n", "n"), ("prior_k", "k")]:
        s.loc[playoff, target] = s.loc[playoff, "athlete_id_1"].map(totals[origin]).fillna(0)
    s["prior_rate"] = (s.prior_k + 22) / (s.prior_n + 50)
    s["log_prior_n"] = np.log1p(s.prior_n)
    s["player_id"] = s.athlete_id_1.astype(str)
    s["team_id"] = s.team_id.astype(str)
    s["split"] = np.select([s.scope.eq("playoffs"), s.scope.eq("special"), s.date.lt("2025-08-10"), s.date.lt("2025-08-27")], ["playoffs", "special", "train", "validation"], default="test")
    r = s[s.scope.eq("regular")]
    assert len(r) == 38535 and r.made.sum() == 16926 and r.points.sum() == 38533
    model = s[s.scope.isin(["regular", "playoffs"]) & s.x.between(-5.25, 41.75) & ~s.game_id.isin(bad_games)].copy()
    assert np.isfinite(model[NUMERIC].to_numpy(float)).all()
    assert np.allclose(model.x, model.x.round()) and np.allclose(model.y, model.y.round())
    assert model.groupby(["game_id", "player_id"]).prior_rate.nunique().max() == 1
    model["loc"] = ((model.x + 5) * 51 + model.y + 25).astype(int)
    assert model["loc"].between(0, 47 * 51 - 1).all()
    conflicts = s[~np.isclose(s.home_score - s.before_home_score + s.away_score - s.before_away_score, s.points)]
    conflicts[["game_id", "game_play_number", "scope", "source_row", "points", "home_score", "away_score", "before_home_score", "before_away_score"]].to_csv(out / "score_sequence_conflicts.csv", index=False)
    s.to_csv(data / "all_shots.csv.gz", index=False)
    keep = ["source_row", "game_id", "game_play_number", "split", "scope", "date", "date_time", "made", "points", "player", "loc"] + NUMERIC + CATEGORICAL
    model[list(dict.fromkeys(keep))].to_csv(data / "model_shots.csv.gz", index=False)
    splits = {k: {"shots": len(a), "games": int(a.game_id.nunique()), "start": a.date.min(), "end": a.date.max()} for k,a in model.groupby("split")}
    for left in splits:
        for right in splits:
            if left != right:
                assert not set(model.loc[model.split.eq(left), "game_id"]) & set(model.loc[model.split.eq(right), "game_id"])
    audit = {"source_filename": source.name, "archive_sha256": existing["source_sha256"], "archive_bytes": source.stat().st_size,
             "only_data_source": "Data (1).zip", "inputs": [pbp_info, box_info, player_info], "source_rows": len(d), "all_attempts": len(s),
             "regular_attempts": len(r), "regular_games": int(r.game_id.nunique()), "regular_makes": int(r.made.sum()), "regular_points": int(r.points.sum()),
             "all_game_team_boxes_reconcile": True, "all_shooter_boxes_reconcile": not bool(bad_games), "retained_model_shooter_boxes_reconcile": True,
             "excluded_games_for_shooter_disagreement": len(bad_games), "mismatched_player_game_totals": int(bad_players.sum()), "game_team_checks": len(check), "player_game_checks": len(pc),
             "score_update_conflicts": len(conflicts), "regular_games_with_score_conflicts": int(conflicts.loc[conflicts.scope.eq("regular"), "game_id"].nunique()),
             "splits": splits, "numeric_features": NUMERIC, "categorical_features": CATEGORICAL,
             "prior_season_feature_window": "2022-2024 regular-season-coded box scores in the supplied archive only, fixed before 2025",
             "history_rule": "Only completed earlier regular-season games; constant within game; frozen at regular-season end for playoffs.",
             "excluded_features": ["outcome descriptions", "made", "points", "score_value", "scoring_play", "current-game box scores", "future-season totals", "assists", "conflicting score margin", "inferred two/three attempt values", "college records", "salary"],
             "evaluation_limit": "The 2025 evaluation periods have already been examined. They are reused benchmarks, not an untouched final season.",
             "expected_points_target": "Observed 0/2/3 field-goal outcome mix; missed-shot attempt values are not authoritatively supplied."}
    (out / "source_audit.json").write_text(json.dumps(audit, indent=2, default=str), encoding="utf-8")
    print(json.dumps(audit, indent=2, default=str), flush=True)


if __name__ == "__main__":
    main()
