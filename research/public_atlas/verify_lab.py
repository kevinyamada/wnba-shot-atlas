"""Check the methods lab results with separately written arithmetic."""
import json

import numpy as np
import pandas as pd

from fetch import manifest_digest
from recount import RESULTS, ROOT, SITE

OUT = RESULTS / 'methods_lab'
DERIVED = ROOT / 'research/data/public_wnba/derived'
MEMBERS = ['Distance curve', 'Inverse distance weighting', 'Universal kriging', 'Areal CAR model', 'Gaussian process', 'SPDE mesh with trend']


def main():
    scores = pd.read_csv(OUT / 'scores.csv').set_index('method')
    shots = pd.read_csv(DERIVED / 'shot_form_predictions.csv.gz', usecols=['season', 'scope', 'made'])
    shots = shots[shots.scope.eq('regular')]
    errors = []
    for year in (2024, 2025, 2026):
        rate = shots[shots.season.between(year - 3, year - 1)].made.mean()
        errors.append((shots[shots.season.eq(year)].made - rate) ** 2)
    errors = pd.concat(errors)
    assert len(errors) == scores.attempts.iloc[0] and np.isclose(errors.mean(), scores.loc['League rate', 'brier'])
    assert scores.brier.is_monotonic_increasing and np.isclose(scores.loc['Distance curve', 'drop_vs_distance_pct'], 0)
    assert (scores.low_pct <= scores.drop_vs_distance_pct + 1e-9).all() and (scores.drop_vs_distance_pct <= scores.high_pct + 1e-9).all()
    assert np.allclose(scores.drop_vs_distance_pct, 100 * (1 - scores.brier / scores.loc['Distance curve', 'brier']), atol=1e-6)
    surfaces = pd.read_csv(OUT / 'surfaces_2027.csv')
    weights = pd.read_csv(OUT / 'stacking_weights.csv').set_index('season')
    assert np.allclose(weights.sum(axis=1), 1) and (weights >= -1e-9).all().all()
    assert np.allclose(surfaces['Simple average'], surfaces[MEMBERS].mean(axis=1))
    assert np.allclose(surfaces['Stacked ensemble'], surfaces[MEMBERS].to_numpy() @ weights.loc[2027, MEMBERS].to_numpy())
    assert ((surfaces.drop(columns=['x', 'y']) > 0) & (surfaces.drop(columns=['x', 'y']) < 1)).all().all() and len(surfaces) == 47 * 51
    rim, far = surfaces[(surfaces.x.eq(1)) & surfaces.y.eq(0)].iloc[0], surfaces[(surfaces.x.eq(24)) & surfaces.y.eq(0)].iloc[0]
    assert all(rim[name] > far[name] for name in scores.index if name != 'League rate'), 'every spatial method should rate the rim above a long three'
    moran = pd.read_csv(OUT / 'morans_i.csv')
    assert moran.morans_i.iloc[0] > moran.morans_i.iloc[1] > moran.morans_i.iloc[2] and moran.p_value.between(0, 1).all()
    k = pd.read_csv(OUT / 'k_function.csv')
    assert np.allclose(k.random_expected, np.pi * k.radius_ft ** 2) and (k.random_low <= k.random_expected * 1.1).all() and (k.observed > k.random_high).all()
    density = pd.read_csv(OUT / 'intensity_2027.csv')
    assert (density.share > 0).all() and .97 < density.share.sum() <= 1.0001, density.share.sum()
    assert density.loc[density.x.eq(1) & density.y.eq(0), 'share'].iloc[0] > 20 * density.share.median(), 'the rim should be far busier than a typical spot'
    points = pd.read_csv(OUT / 'intensity_scores.csv')
    assert (points.cox_process <= points.three_seasons + 1e-3).all() and len(points) == 3 and points[['last_season', 'three_seasons', 'cox_process']].gt(0).all().all()

    site = json.loads((SITE / 'methods-lab.json').read_bytes())
    assert site['manifestSha256'] == manifest_digest() and [row['method'] for row in site['methods']] == list(scores.index)
    for name in scores.index:
        assert np.allclose(site['surfaces'][name], surfaces[name], atol=1e-4)
    certificate = dict(methods=len(scores), attempts=int(scores.attempts.iloc[0]), best=scores.index[0], league_brier=round(float(errors.mean()), 5), manifestSha256=manifest_digest())
    (OUT / 'verification.json').write_text(json.dumps(certificate, indent=2) + '\n', encoding='utf-8', newline='\n')
    print('METHODS_LAB_VERIFIED', certificate, flush=True)


if __name__ == '__main__':
    main()
