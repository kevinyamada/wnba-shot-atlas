"""Build the 2027 prediction court for the explorer's Compare with list.

Where shots come from is taken from the 2026 regular season, because repeating
the last season was the best simple rule for shot mix. How often they go in
comes from the Bayesian mesh surface. Points use the points per make seen in
each court area from 2024 to 2026.
"""
import json

import numpy as np
import pandas as pd

from build import DERIVED, RESULTS, SITE, write_json
from fetch import manifest_digest

OUT = RESULTS / 'prediction_2027'
BASE = 2026
COLUMNS = ['phase', 'team_id', 'player_id', 'cell', 'zone', 'attempts', 'made', 'points', 'shot_type']
OTHER = 6


def main():
    surface = pd.read_csv(OUT / 'surface_2027.csv').set_index(['x', 'y']).probability
    use = ['scope', 'cell', 'zone', 'depth_ft', 'lateral_ft', 'made', 'points']
    recent = pd.concat([pd.read_csv(DERIVED / f'shots_{year}.csv.gz', usecols=use, low_memory=False).assign(season=year) for year in (BASE - 2, BASE - 1, BASE)])
    recent = recent[recent.scope.eq('regular')]
    mapped = recent[recent.cell.ge(0)]
    value = mapped[mapped.made.eq(1)].groupby('zone').points.mean()
    shots = recent[recent.season.eq(BASE)].copy()
    on_court = shots.cell.ge(0)
    spot = pd.MultiIndex.from_arrays([shots.loc[on_court, 'depth_ft'].round().astype(int), shots.loc[on_court, 'lateral_ft'].round().astype(int)])
    chance = surface.reindex(spot).to_numpy()
    assert np.isfinite(chance).all(), 'every mapped shot needs a spot on the surface'
    shots['expected_makes'] = shots.made.astype(float)
    shots['expected_points'] = shots.points.astype(float)
    shots.loc[on_court, 'expected_makes'] = chance
    shots.loc[on_court, 'expected_points'] = chance * shots.loc[on_court, 'zone'].map(value).to_numpy()
    groups = shots.groupby(['cell', 'zone']).agg(attempts=('made', 'size'), made=('expected_makes', 'sum'), points=('expected_points', 'sum')).reset_index()
    groups['phase'], groups['team_id'], groups['player_id'], groups['shot_type'] = 0, 0, 0, OTHER
    rows = [[int(r.phase), 0, 0, int(r.cell), int(r.zone), int(r.attempts), round(float(r.made), 3), round(float(r.points), 3), OTHER] for r in groups.itertuples()]
    summary = dict(attempts=int(groups.attempts.sum()), predicted_makes=round(float(groups.made.sum()), 1), predicted_points=round(float(groups.points.sum()), 1),
                   make_rate_2026=round(float(shots.made.mean()), 4), predicted_make_rate=round(float(groups.made.sum() / groups.attempts.sum()), 4),
                   points_per_shot_2026=round(float(shots.points.mean()), 4), predicted_points_per_shot=round(float(groups.points.sum() / groups.attempts.sum()), 4))
    index = json.loads((SITE / 'index.json').read_bytes())
    pack = dict(season='prediction', label='2027 prediction', prediction=True, court=index['court']['eras'][-1]['id'], basis=BASE, manifestSha256=manifest_digest(),
                summary=summary, teams={'0': 'Whole league'}, players={}, rows=rows)
    write_json(SITE / 'prediction.json', pack)
    pd.DataFrame(rows, columns=COLUMNS).to_csv(OUT / 'court_2027.csv', index=False)
    print('PREDICTION_COURT', summary, flush=True)


if __name__ == '__main__':
    main()
