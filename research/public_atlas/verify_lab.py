"""Check the methods lab results with separately written arithmetic."""
import json

import numpy as np
import pandas as pd

from fetch import manifest_digest
from recount import RESULTS, ROOT, SITE

OUT = RESULTS / 'methods_lab'
DERIVED = ROOT / 'research/data/public_wnba/derived'
MEMBERS = ['Distance curve', 'Inverse distance weighting', 'Universal kriging', 'Areal CAR model', 'Gaussian process', 'SPDE mesh with trend']


def verify_heldout():
    from predict_surface import load
    from court_geometry import zones
    from scipy.sparse import csr_matrix

    data = json.loads((SITE / 'heldout-spatial.json').read_bytes())
    cells = pd.read_csv(OUT / 'heldout_cells.csv')
    assert data['manifestSha256'] == manifest_digest()
    scored, _ = load()
    scored = scored[scored.season.isin([2024, 2025, 2026])].copy()
    assert scored.game_id.nunique() == data['games']
    scored['region'] = zones(scored.x, scored.y)
    raw = scored.groupby('region').made.agg(['size','sum'])
    regions = pd.DataFrame(data['regions']).set_index('region')
    assert set(raw.index) == set(regions.index)
    for name, row in regions.iterrows():
        assert (row.attempts, row.makes) == tuple(raw.loc[name])
        assert np.isclose(100 * (row.makes - row.expectedMakes) / row.attempts, row.gap)
        assert row.low <= row.gap <= row.high
    assert np.isclose(regions.expectedMakes.sum(), cells.mesh_expected.sum())

    keys = ['season','x','y']
    for key in ['x','y']:
        scored[key] = 2 * np.floor_divide(scored[key], 2).astype(int) + 1
    original = scored.groupby(keys).made.agg(attempts='size', made='sum')
    pd.testing.assert_frame_equal(original, cells.set_index(keys)[['attempts','made']].sort_index(), check_dtype=False)
    for record in [*data['seasons'], data['pooled']]:
        pooled = record['season'] == 'pooled'
        part = cells if pooled else cells[cells.season.eq(record['season'])]
        grouped = part.groupby(['x','y']).sum(numeric_only=True)
        assert int(grouped.attempts.sum()) == record['allShots']
        kept = grouped[grouped.attempts >= data['minShots']]
        assert len(kept) == record['cells'] and int(kept.attempts.sum()) == record['usedShots']
        coords = kept.index.to_frame(index=False).to_numpy()
        delta = np.abs(coords[:,None] - coords[None,:]).sum(axis=2)
        adjacency = csr_matrix((delta == 2).astype(float))
        assert adjacency.nnz == 2 * record['pairs']
        for kind in ['distance','mesh']:
            residual = ((kept.made - kept[kind+'_expected']) / np.sqrt(kept[kind+'_variance'])).to_numpy()
            residual = residual - residual.mean()
            scale = len(kept) / (adjacency.nnz * (residual @ residual))
            value = scale * (residual @ (adjacency @ residual))
            np.testing.assert_allclose(value, record[kind]['moransI'], atol=1e-12)
            if pooled:
                rng = np.random.default_rng(data['seed'])
                null = -1 / (len(kept) - 1)
                extreme = 0
                for _ in range(data['permutations']):
                    permuted = rng.permutation(residual)
                    trial = scale * (permuted @ (adjacency @ permuted))
                    extreme += abs(trial - null) >= abs(value - null)
                assert (extreme + 1) / (data['permutations'] + 1) == record[kind]['pTwoSided']
    return data['pooled']['usedShots']


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
    heldout_shots = verify_heldout()
    certificate = dict(heldoutSpatialShots=heldout_shots, methods=len(scores), attempts=int(scores.attempts.iloc[0]), best=scores.index[0], league_brier=round(float(errors.mean()), 5), manifestSha256=manifest_digest())
    (OUT / 'verification.json').write_text(json.dumps(certificate, indent=2) + '\n', encoding='utf-8', newline='\n')
    print('METHODS_LAB_VERIFIED', certificate, flush=True)


if __name__ == '__main__':
    main()
