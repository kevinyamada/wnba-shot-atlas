"""A Bayesian court surface for 2027: make chance by location from the SPDE mesh model.

The model puts a Gaussian field with Matern covariance on a triangle mesh over
the court and updates it with three regular seasons of shots. Its posterior
mean is the predicted make chance at each spot and its posterior spread gives
the credible range. Each past season is first predicted from the three before
it, to see how the surface and its ranges held up.
"""
from itertools import product
import json
import sys

import numpy as np
import pandas as pd
from scipy.sparse import block_diag, csc_matrix, hstack, identity
from sklearn.metrics import log_loss

from benchmark import paired_games
from build import DERIVED, RESULTS, ROOT, SITE, write_json
from fetch import manifest_digest

sys.path.insert(0, str(ROOT / 'research'))
from spatial_methods import SPDE  # noqa: E402

OUT = RESULTS / 'prediction_2027'
TARGET = 2027
FIRST_TEST = 2019
RANGES, SIGMAS, SPACING = (8, 16, 32), (.15, .3, .7), 3
MODELS = {'field': 'Mesh field only', 'trend': 'Distance trend plus mesh field'}


class TrendMesh(SPDE):
    """The mesh model with a smooth curve in distance from the rim as its mean, so the field only has to explain what distance misses."""

    def __init__(self, range_ft, sigma, spacing):
        super().__init__(range_ft, sigma, spacing)
        field = self.Q[1:, 1:]
        self.Q = block_diag([csc_matrix([[.25]]), .01 * identity(3), field], format='csc')

    def design(self, xy):
        base = super().design(xy).tocsc()
        distance = np.hypot(*np.asarray(xy, dtype=float).T)
        curve = np.column_stack([distance / 10, (distance / 10) ** 2, np.exp(-distance / 3)])
        return hstack([base[:, :1], csc_matrix(curve), base[:, 1:]], format='csc')


def build(kind, range_ft, sigma):
    return (TrendMesh if kind == 'trend' else SPDE)(range_ft, sigma, SPACING)


def load():
    """Eligible regular season shots with whole foot court positions and the distance forecast for the same shot."""
    shots = pd.read_csv(DERIVED / 'shot_form_predictions.csv.gz', usecols=['season', 'game_id', 'source_row', 'scope', 'made', 'p_distance'])
    shots = shots[shots.scope.eq('regular')]
    frames = []
    for year in range(2013, TARGET):
        place = pd.read_csv(DERIVED / f'shots_{year}.csv.gz', usecols=['source_row', 'depth_ft', 'lateral_ft', 'scope', 'cell'], low_memory=False)
        place = place[place.scope.eq('regular') & place.cell.ge(0)].rename(columns={'depth_ft': 'x', 'lateral_ft': 'y'}).assign(season=year)
        frames.append(place[['season', 'source_row', 'x', 'y']])
    places = pd.concat(frames)
    scored = shots.merge(places, on=['season', 'source_row'], validate='one_to_one')
    assert len(scored) == len(shots)
    return scored, places


def window(eligible, year, length=3):
    return eligible[eligible.season.between(year - length, year - 1)]


def choose(eligible, year, kind):
    """Pick the field range and spread on the last training season, then refit on all three."""
    early, late = window(eligible, year - 1, 2), eligible[eligible.season.eq(year - 1)]
    trials = []
    for range_ft, sigma in product(RANGES, SIGMAS):
        fit = build(kind, range_ft, sigma).fit(early)
        trials.append((log_loss(late.made, fit.predict(late)), range_ft, sigma))
    _, range_ft, sigma = min(trials)
    return build(kind, range_ft, sigma).fit(window(eligible, year)), range_ft, sigma


def coverage(model, test):
    """Share of court spots whose next season makes fall inside the model's 95% range for that many shots."""
    spots = test.groupby(['x', 'y']).made.agg(makes='sum', shots='count').reset_index()
    p, low, high = model.predict(spots, uncertainty=True)
    spread = (high - low) / 3.92
    limit = 1.96 * np.sqrt(spots.shots * p * (1 - p) + (spots.shots * spread) ** 2)
    inside = (spots.makes - spots.shots * p).abs().le(limit)
    busy = spots.shots.ge(20)
    return dict(spots=int(busy.sum()), inside=int((inside & busy).sum()))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    scored, _ = load()
    rows, tests = [], []
    for year in range(FIRST_TEST, TARGET):
        test = scored[scored.season.eq(year)].copy()
        train = window(scored, year)
        test['league'] = train.made.mean()
        row = dict(season=year, training_shots=len(train), test_shots=len(test), league_brier=float(np.mean((test.league - test.made) ** 2)),
                   distance_brier=float(np.mean((test.p_distance - test.made) ** 2)))
        for kind in MODELS:
            model, range_ft, sigma = choose(scored, year, kind)
            test[kind] = model.predict(test)
            held = coverage(model, test)
            row.update({f'{kind}_brier': float(np.mean((test[kind] - test.made) ** 2)), f'{kind}_range_ft': range_ft, f'{kind}_sigma': sigma,
                        f'{kind}_spots': held['spots'], f'{kind}_inside': held['inside']})
        tests.append(test)
        rows.append(row)
        print(row, flush=True)
    seasons = pd.DataFrame(rows)
    tests = pd.concat(tests, ignore_index=True)
    errors = {name: (tests[name] - tests.made) ** 2 for name in ('league', 'p_distance', *MODELS)}
    best = min(MODELS, key=lambda kind: errors[kind].mean())
    tests['mesh'], errors['mesh'] = tests[best], errors[best]
    seasons = seasons.assign(mesh_brier=seasons[f'{best}_brier'], range_ft=seasons[f'{best}_range_ft'], sigma=seasons[f'{best}_sigma'],
                             spots=seasons[f'{best}_spots'], inside=seasons[f'{best}_inside'])
    pooled = []
    for name, other in [('p_distance', 'league'), ('field', 'p_distance'), ('trend', 'p_distance'), ('mesh', 'league'), ('mesh', 'p_distance')]:
        gap = paired_games(tests.game_id, errors[name] - errors[other])
        base = float(errors[other].mean())
        pooled.append(dict(forecast=name, compared_with=other, attempts=len(tests), games=tests.game_id.nunique(), brier=float(errors[name].mean()), brier_compared=base,
                           drop_pct=-100 * gap['difference'] / base, low_pct=-100 * gap['upper'] / base, high_pct=-100 * gap['lower'] / base))
    pooled = pd.DataFrame(pooled)

    model, range_ft, sigma = choose(scored, TARGET, best)
    grid = pd.DataFrame(list(product(range(-5, 42), range(-25, 26))), columns=['x', 'y'])
    p, low, high = model.predict(grid, uncertainty=True)
    surface = grid.assign(probability=p, lower=low, upper=high)
    surface.to_csv(OUT / 'surface_2027.csv', index=False)
    seasons.to_csv(OUT / 'surface_backtest_by_season.csv', index=False)
    pooled.to_csv(OUT / 'surface_backtest.csv', index=False)

    head = pooled.set_index(['forecast', 'compared_with'])
    held = seasons.inside.sum() / seasons.spots.sum()
    rim, corner, top = (surface[(surface.x.eq(x)) & surface.y.eq(y)].iloc[0] for x, y in [(1, 0), (0, 23), (24, 0)])
    lines = ['# A Bayesian court surface for 2027', '',
             f"Two versions of the mesh model were tested on past seasons: {MODELS['field'].lower()}, and {MODELS['trend'].lower()}. The surface below uses the one with the lower past error, {MODELS[best].lower()}.", '',
             f"The mesh model was fitted to the {len(window(scored, TARGET)):,} eligible shots of the 2024 to 2026 regular seasons. Its predicted make chance is "
             f"{100 * rim.probability:.1f}% one foot in front of the rim (95% credible range {100 * rim.lower:.1f}% to {100 * rim.upper:.1f}%), "
             f"{100 * corner.probability:.1f}% in the corner at 23 ft ({100 * corner.lower:.1f}% to {100 * corner.upper:.1f}%) and "
             f"{100 * top.probability:.1f}% straight on at 24 ft ({100 * top.lower:.1f}% to {100 * top.upper:.1f}%).", '',
             '## How it did on past seasons', '',
             f"Each regular season from {FIRST_TEST} to 2026 was predicted from the three before it. Across {len(tests):,} shots the mesh surface lowered Brier error by "
             f"{head.loc[('mesh', 'league'), 'drop_pct']:.2f}% against the league make rate and changed it by {head.loc[('mesh', 'p_distance'), 'drop_pct']:.2f}% against the distance curve "
             f"(95% game interval {head.loc[('mesh', 'p_distance'), 'low_pct']:.2f}% to {head.loc[('mesh', 'p_distance'), 'high_pct']:.2f}%). "
             f"The field alone changed it by {head.loc[('field', 'p_distance'), 'drop_pct']:.2f}% and the trend plus field by {head.loc[('trend', 'p_distance'), 'drop_pct']:.2f}%. "
             f"Among court spots with at least 20 shots in the predicted season, the makes fell inside the model's 95% range for {100 * held:.1f}% of spots "
             f"({seasons.inside.sum():,} of {seasons.spots.sum():,}).", '',
             '| Season | Shots | Field range (ft) | Field spread | League Brier | Distance Brier | Mesh Brier | Spots inside the 95% range |', '| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |']
    lines += [f'| {r.season} | {r.test_shots:,} | {r.range_ft} | {r.sigma} | {r.league_brier:.5f} | {r.distance_brier:.5f} | {r.mesh_brier:.5f} | {r.inside} of {r.spots} |' for r in seasons.itertuples()]
    lines += ['', '## Method', '',
              'The make chance at a location is the logistic transform of a mean plus a Gaussian random field. The mean is an intercept, or an intercept with a smooth curve in distance from the rim (linear, squared and a short range term near the basket) under a weak normal prior. The field has a Matern covariance with smoothness one, represented on a triangle mesh with nodes every 3 ft through the stochastic partial differential equation link. '
              'The posterior is a Laplace approximation at the mode, given the chosen range and spread of the field. Those two settings are chosen from nine combinations by log loss on the last training season, then the model is refitted on all three seasons. '
              'The credible range for a spot comes from the posterior variance of the field there. The range for a count of makes adds the binomial chance in that many shots.', '',
              'The surface uses location only. It does not know the shooter, the shot type or the defence, and it assumes 2027 will look like the three seasons before it.', '',
              '[Surface](surface_2027.csv) · [Past seasons](surface_backtest_by_season.csv) · [Pooled comparison](surface_backtest.csv)', '']
    (OUT / 'SURFACE.md').write_text('\n'.join(lines), encoding='utf-8', newline='\n')
    write_json(SITE / 'prediction-surface.json', dict(manifestSha256=manifest_digest(), season=TARGET, model=MODELS[best], range_ft=range_ft, sigma=sigma, spacing=SPACING,
                                                       nodes=int(len(model.nodes)), training_shots=int(len(window(scored, TARGET))), coverage=round(float(held), 4),
                                                       backtest=json.loads(pooled.to_json(orient='records')),
                                                       surface=surface.round(6).to_numpy().tolist()))
    print(pooled[['forecast', 'compared_with', 'brier', 'drop_pct', 'low_pct', 'high_pct']].round(4).to_string(index=False), flush=True)
    print('SURFACE_WRITTEN', dict(model=MODELS[best], range_ft=range_ft, sigma=sigma, coverage=round(float(held), 3)), flush=True)


if __name__ == '__main__':
    main()
