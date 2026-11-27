"""Check neighbouring shot forecast errors on three previously scored seasons."""
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from build import RESULTS, SITE, write_json
from fetch import manifest_digest
from methods_lab import REPORTED, distance_curve
from predict_surface import build, load, window
from court_geometry import zones

OUT = RESULTS / 'methods_lab'
MIN_SHOTS = 20
SHUFFLES = 9999
GAME_DRAWS = 2000
SEED = 20261126
MODELS = {'distance': 'Distance curve', 'mesh': 'SPDE mesh with trend'}


def moran(centres, values, permutations=None):
    pairs = cKDTree(centres).query_pairs(2.01, output_type='ndarray')
    left, right = pairs.T
    centred = values - values.mean()
    denominator = centred @ centred
    if not len(left) or denominator <= 0:
        raise ValueError('Moran statistic requires adjacent cells and variation in their errors.')
    multiplier = len(values) / (len(left) * denominator)
    index = multiplier * (centred[left] @ centred[right])
    result = dict(moransI=float(index))
    if permutations is not None:
        null = -1 / (len(values) - 1)
        threshold = abs(index - null)
        hits = 0
        for order in permutations:
            shuffled = centred[order]
            draw = multiplier * (shuffled[left] @ shuffled[right])
            hits += abs(draw - null) >= threshold
        result['pTwoSided'] = float((hits + 1) / (len(permutations) + 1))
    return result, len(left)


def forecast_cells(scored):
    settings = pd.read_csv(OUT / 'settings.csv').set_index('season')
    reference = pd.read_csv(OUT / 'scores_by_season.csv').set_index(['season','method']).brier
    frames, game_regions = [], []
    for year in REPORTED:
        train = window(scored, year)
        test = scored.loc[scored.season.eq(year), ['season','game_id','x','y','made']].copy()
        chosen = settings.loc[year]
        mesh = build('trend', chosen.mesh_range_ft, chosen.mesh_sigma).fit(train)
        predictors = {'distance': distance_curve(train), 'mesh': mesh.predict}
        for key, predict in predictors.items():
            probability = np.clip(predict(test), 1e-4, 1-1e-4)
            brier = np.mean((test.made - probability) ** 2)
            np.testing.assert_allclose(brier, reference.loc[year, MODELS[key]], rtol=0, atol=1e-10)
            test[key + '_expected'] = probability
            test[key + '_variance'] = probability * (1-probability)
        test['attempts'] = 1
        test['region'] = zones(test.x, test.y)
        game_regions.append(test.groupby(['season','game_id','region'], as_index=False)[['made','mesh_expected','attempts']].sum())
        test = test.drop(columns=['region','game_id'])
        test['x'] = 2 * np.floor(test.x / 2).astype(int) + 1
        test['y'] = 2 * np.floor(test.y / 2).astype(int) + 1
        frames.append(test.groupby(['season','x','y'], as_index=False).sum())
    return pd.concat(frames, ignore_index=True), pd.concat(game_regions, ignore_index=True)


def summary(cells, pooled=False):
    busy = cells[cells.attempts.ge(MIN_SHOTS)]
    centres = busy[['x','y']].to_numpy()
    perms = None
    if pooled:
        rng = np.random.default_rng(SEED)
        perms = np.array([rng.permutation(len(busy)) for _ in range(SHUFFLES)], dtype=np.int32)
    row = dict(season='pooled' if pooled else int(cells.season.iloc[0]), allShots=int(cells.attempts.sum()),
               usedShots=int(busy.attempts.sum()), cells=len(busy))
    for key in MODELS:
        residual = (busy.made - busy[key + '_expected']) / np.sqrt(busy[key + '_variance'])
        row[key], row['pairs'] = moran(centres, residual.to_numpy(), perms)
    return row


def calibration_rows(regions, totals, draws, joint=False):
    point = 100 * (totals[:, 1] - totals[:, 2]) / totals[:, 0]
    gaps = 100 * (draws[:, :, 1] - draws[:, :, 2]) / draws[:, :, 0]
    if not np.isfinite(gaps).all():
        raise ValueError('A regional bootstrap sample has no attempts.')
    limits = np.quantile(gaps, [.025, .975], axis=0)
    if joint:
        scale = gaps.std(axis=0, ddof=1)
        if (scale <= 0).any():
            raise ValueError('The joint band requires variation in every region.')
        maxima = np.max(np.abs(gaps - point) / scale, axis=1)
        half_width = np.quantile(maxima, .95) * scale
    rows = []
    for i, (attempts, made, expected) in enumerate(totals):
        row = dict(region=regions[i], attempts=int(attempts), makes=int(made), expectedMakes=float(expected),
                   gap=float(point[i]), low=float(limits[0, i]), high=float(limits[1, i]))
        if joint:
            row.update(jointLow=float(point[i] - half_width[i]), jointHigh=float(point[i] + half_width[i]))
        rows.append(row)
    return rows


def region_calibration(games):
    regions = sorted(games.region.unique())
    totals = np.zeros((len(regions), 3))
    draws = np.zeros((GAME_DRAWS, len(regions), 3))
    by_season = {}
    rng = np.random.default_rng(SEED + 1)
    for year, season in games.groupby('season'):
        ids = sorted(season.game_id.unique())
        index = pd.MultiIndex.from_product([ids, regions], names=['game_id', 'region'])
        values = season.set_index(['game_id', 'region'])[['attempts', 'made', 'mesh_expected']].reindex(index, fill_value=0)
        cube = values.to_numpy().reshape(len(ids), len(regions), 3)
        year_total = cube.sum(axis=0)
        weights = rng.multinomial(len(ids), np.full(len(ids), 1 / len(ids)), size=GAME_DRAWS)
        year_draws = (weights @ cube.reshape(len(ids), -1)).reshape(GAME_DRAWS, len(regions), 3)
        by_season[int(year)] = calibration_rows(regions, year_total, year_draws)
        totals += year_total
        draws += year_draws
    return calibration_rows(regions, totals, draws, joint=True), by_season


def main():
    scored, _ = load()
    cells, games = forecast_cells(scored)
    pooled = cells.drop(columns='season').groupby(['x','y'], as_index=False).sum()
    check = summary(pooled, pooled=True)
    seasons = [summary(year) for _, year in cells.groupby('season')]
    cells.to_csv(OUT / 'heldout_cells.csv', index=False, lineterminator='\n')
    regions, by_season = region_calibration(games)
    for row in seasons:
        row['regions'] = by_season[row['season']]
    games.sort_values(['season', 'game_id', 'region']).to_csv(OUT / 'heldout_game_regions.csv', index=False, lineterminator='\n')
    write_json(SITE / 'heldout-spatial.json', dict(manifestSha256=manifest_digest(), minShots=MIN_SHOTS,
               permutations=SHUFFLES, seed=SEED, pooled=check, seasons=seasons, regions=regions, games=int(games.game_id.nunique()), gameDraws=GAME_DRAWS))
    for row in regions:
        annual = [item['gap'] for year in REPORTED for item in by_season[year] if item['region'] == row['region']]
        print(row['region'], 'pooled', round(row['gap'], 2), 'joint range', round(row['jointLow'], 2), round(row['jointHigh'], 2), 'annual', [round(v, 2) for v in annual])
    print('HELDOUT_SPATIAL', check['allShots'], 'shots,', len(regions), 'regions,', len(seasons), 'seasons', flush=True)


if __name__ == '__main__':
    main()
