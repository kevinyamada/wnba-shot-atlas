"""Methods lab: every spatial technique in the project on one question.

The question is the chance that a shot goes in from each court spot. Each
method learns from three regular seasons and is scored on the next one, for
2023 to 2026. The same methods then learn from 2024 to 2026 to draw a surface
for 2027. Diagnostics show the spatial structure the methods are built on.
"""
from itertools import product
import json

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.sparse import block_diag, coo_matrix, csc_matrix, diags, hstack, identity
from scipy.sparse.linalg import splu
from scipy.spatial import cKDTree
from scipy.special import expit, logit

from benchmark import paired_games
from build import RESULTS, SITE, write_json
from fetch import manifest_digest
from predict_surface import TARGET, choose, load, window
from shot_models import MaternLaplace
from spatial_methods import IDW, Kriging, aggregate

OUT = RESULTS / 'methods_lab'
FOLDS = (2023, 2024, 2025, 2026)
REPORTED = FOLDS[1:]
SEED = 20261124
METHODS = {
    'League rate': ('Baseline', 'Every spot gets the league make rate.'),
    'Distance curve': ('Baseline', 'A smooth curve of make rate against distance from the rim.'),
    'Inverse distance weighting': ('Interpolation', 'Each spot takes a weighted average of nearby cells, with closer cells counting more.'),
    'Ordinary kriging': ('Geostatistics', 'Best linear prediction from nearby cells, with weights set by a fitted variogram and a constant mean.'),
    'Universal kriging': ('Geostatistics', 'Kriging with a trend in distance, so the variogram only has to describe what distance misses.'),
    'Areal CAR model': ('Areal data', 'Court cells borrow strength from their neighbours through a conditional autoregressive prior. Bayesian, with a Laplace approximation.'),
    'Gaussian process': ('Bayesian field', 'A Matern Gaussian process on a spectral basis, with a Laplace approximation to the posterior.'),
    'SPDE mesh field': ('Bayesian field', 'A Matern field on a triangle mesh through the stochastic partial differential equation link.'),
    'SPDE mesh with trend': ('Bayesian field', 'The mesh field with a smooth curve in distance as its mean.'),
    'Simple average': ('Ensemble', 'The plain average of the spatial methods.'),
    'Stacked ensemble': ('Ensemble', 'A weighted average whose weights were fitted on the season before.'),
}
MEMBERS = ['Distance curve', 'Inverse distance weighting', 'Universal kriging', 'Areal CAR model', 'Gaussian process', 'SPDE mesh with trend']


class AreaCAR:
    """Binomial counts in 2 ft cells with a conditional autoregressive prior on the cell effects."""

    def __init__(self, tau, rho=.995, cell=2.0):
        self.cell, self.rows, self.cols = cell, int(48 / cell), int(52 / cell)
        index = np.arange(self.rows * self.cols).reshape(self.rows, self.cols)
        pairs = np.concatenate([np.column_stack([index[:-1].ravel(), index[1:].ravel()]), np.column_stack([index[:, :-1].ravel(), index[:, 1:].ravel()])])
        n = index.size
        W = coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(n, n))
        W = (W + W.T).tocsc()
        self.W = W
        self.Q = block_diag([csc_matrix([[.25]]), tau * (diags(np.asarray(W.sum(axis=1)).ravel()) - rho * W)], format='csc')

    def cells(self, frame):
        i = np.clip(np.floor((frame.x.to_numpy() + 6) / self.cell), 0, self.rows - 1).astype(int)
        j = np.clip(np.floor((frame.y.to_numpy() + 26) / self.cell), 0, self.cols - 1).astype(int)
        return i * self.cols + j

    def fit(self, shots):
        cell = self.cells(shots)
        size = self.rows * self.cols
        n, k = np.bincount(cell, minlength=size).astype(float), np.bincount(cell, weights=shots.made.to_numpy(), minlength=size)
        design = hstack([csc_matrix(np.ones((size, 1))), identity(size)], format='csc')
        theta = np.zeros(size + 1)
        theta[0] = logit(k.sum() / n.sum())
        for _ in range(60):
            p = expit(design @ theta)
            gradient = design.T @ (n * p - k) + self.Q @ theta
            hessian = (self.Q + design.T @ diags(n * p * (1 - p)) @ design).tocsc()
            step = splu(hessian).solve(np.asarray(gradient))
            theta -= step
            if np.abs(step).max() < 1e-7:
                break
        self.theta = theta
        return self

    def predict(self, frame):
        return expit(self.theta[0] + self.theta[1 + self.cells(frame)])


class CoxIntensity(AreaCAR):
    """Log Gaussian Cox process on the lattice: Poisson shot counts whose log intensity has the neighbour prior."""

    def fit(self, shots):
        size = self.rows * self.cols
        n = np.bincount(self.cells(shots), minlength=size).astype(float)
        design = hstack([csc_matrix(np.ones((size, 1))), identity(size)], format='csc')
        theta = np.zeros(size + 1)
        theta[0] = np.log(n.mean())
        for _ in range(80):
            rate = np.exp(np.clip(design @ theta, -20, 20))
            gradient = design.T @ (rate - n) + self.Q @ theta
            step = splu((self.Q + design.T @ diags(rate) @ design).tocsc()).solve(np.asarray(gradient))
            theta -= np.clip(step, -2, 2)
            if np.abs(step).max() < 1e-7:
                break
        rate = np.exp(design @ theta)
        self.share = rate / rate.sum()
        return self


def log_score(share, shots, model):
    """Average surprise per shot, in nats, when cell shares are used to predict where the next season's shots fall."""
    return float(-np.mean(np.log(share[model.cells(shots)])))


def intensity(scored):
    """Where shots come from: a Cox process against simply reusing past cell shares."""
    lattice = AreaCAR(1)
    size = lattice.rows * lattice.cols

    def raw(shots):
        counts = np.bincount(lattice.cells(shots), minlength=size) + .5
        return counts / counts.sum()

    def cox(train):
        last = train.season.max()
        early, late = train[train.season.lt(last)], train[train.season.eq(last)]
        tau = min((.25, 1, 4, 16), key=lambda t: log_score(CoxIntensity(t).fit(early).share, late, lattice))
        return CoxIntensity(tau).fit(train), tau

    rows = []
    for year in REPORTED:
        train, test = window(scored, year), scored[scored.season.eq(year)]
        model, tau = cox(train)
        rows.append(dict(season=year, shots=len(test), tau=tau, last_season=log_score(raw(train[train.season.eq(year - 1)]), test, lattice),
                         three_seasons=log_score(raw(train), test, lattice), cox_process=log_score(model.share, test, lattice)))
    final, tau = cox(window(scored, TARGET))
    grid = pd.DataFrame(list(product(range(-5, 42), range(-25, 26))), columns=['x', 'y'])
    return pd.DataFrame(rows), final.share[lattice.cells(grid)] / 4, tau


def car_model(train):
    """Choose the strength of the neighbour prior on the last training season, then refit on all three."""
    last = train.season.max()
    early, late = train[train.season.lt(last)], train[train.season.eq(last)]
    def loss(tau):
        p = AreaCAR(tau).fit(early).predict(late)
        return -np.mean(late.made * np.log(p) + (1 - late.made) * np.log(1 - p))
    tau = min((1, 4, 16, 64), key=loss)
    return AreaCAR(tau).fit(train), tau


def distance_curve(train):
    curve = train.assign(feet=np.rint(np.hypot(train.x, train.y)).clip(0, 40)).groupby('feet').made.agg(['sum', 'count'])
    curve = ((curve['sum'] + 4 * train.made.mean()) / (curve['count'] + 4)).reindex(range(41)).interpolate().bfill().ffill().to_numpy()
    def predict(frame):
        feet = np.rint(np.hypot(frame.x, frame.y)).clip(0, 40).astype(int)
        return curve[feet]
    return predict


def fit_all(scored, year):
    """Fit every method on the three seasons before `year` and return a prediction function for each."""
    train = window(scored, year)
    curve = distance_curve(train)
    rate = train.made.mean()
    ordinary, universal = Kriging(False).fit(train), Kriging(True).fit(train)
    car, tau = car_model(train)
    field, _, _ = choose(scored, year, 'field')
    trend, range_ft, sigma = choose(scored, year, 'trend')
    process = MaternLaplace(8, .5).fit(train)
    idw = IDW(3).fit(train)
    models = {'League rate': lambda f: np.full(len(f), rate),
              'Distance curve': curve,
              'Inverse distance weighting': idw.predict, 'Ordinary kriging': ordinary.predict, 'Universal kriging': universal.predict,
              'Areal CAR model': car.predict, 'Gaussian process': process.predict, 'SPDE mesh field': field.predict, 'SPDE mesh with trend': trend.predict}
    settings = dict(season=year, car_tau=tau, mesh_range_ft=range_ft, mesh_sigma=sigma, variogram_sill=float(universal.sill), variogram_range_ft=float(universal.scale))
    return models, settings, dict(train=train, ordinary=ordinary, universal=universal, trend=trend, curve=models['Distance curve'])


def stack(frame):
    """Weights that are not negative and add to one, chosen to minimise squared error."""
    P, y = frame[MEMBERS].to_numpy(), frame.made.to_numpy()
    start = np.full(len(MEMBERS), 1 / len(MEMBERS))
    scale = 1e4 / len(y)
    best = minimize(lambda w: scale * np.sum((P @ w - y) ** 2), start, jac=lambda w: 2 * scale * P.T @ (P @ w - y), method='SLSQP', bounds=[(0, 1)] * len(MEMBERS),
                    constraints={'type': 'eq', 'fun': lambda w: w.sum() - 1, 'jac': lambda w: np.ones(len(w))}, options={'ftol': 1e-12, 'maxiter': 500})
    return np.clip(best.x, 0, None) / np.clip(best.x, 0, None).sum()


def morans_i(cells, residual, rng):
    """Moran's I for cell residuals with neighbours one cell apart, and a permutation test."""
    tree = cKDTree(cells)
    pairs = tree.query_pairs(2.01, output_type='ndarray')
    def statistic(values):
        centred = values - values.mean()
        return len(values) / (2 * len(pairs)) * 2 * np.sum(centred[pairs[:, 0]] * centred[pairs[:, 1]]) / np.sum(centred ** 2)
    observed = statistic(residual)
    shuffled = np.array([statistic(rng.permutation(residual)) for _ in range(999)])
    return float(observed), float((1 + np.sum(shuffled >= observed)) / 1000), int(len(pairs))


def diagnostics(parts, scored):
    """Variograms, Moran's I and a point pattern summary for the seasons behind the 2027 surface."""
    rng = np.random.default_rng(SEED)
    train = parts['train']
    variogram = pd.concat([pd.DataFrame(model.variogram, columns=['distance_ft', 'semivariance', 'pairs']).assign(
        kind=kind, fitted=model.sill * (1 - np.exp(-model.variogram[:, 0] / model.scale)), sill=model.sill, range_ft=model.scale)
        for kind, model in [('Make rate on the logit scale', parts['ordinary']), ('After removing the distance trend', parts['universal'])]])
    cells = aggregate(train, 2)
    cells = cells[cells['count'].ge(20)].rename(columns={'cx': 'x', 'cy': 'y'})
    centres = cells[['x', 'y']].to_numpy()
    moran = []
    for name, expected in [('Observed make rate', np.full(len(cells), train.made.mean())), ('After the distance curve', parts['curve'](cells)),
                           ('After the mesh model with trend', parts['trend'].predict(cells))]:
        value, p, pairs = morans_i(centres, (cells['sum'] / cells['count'] - expected).to_numpy(), rng)
        moran.append(dict(residual=name, morans_i=value, p_value=p, cells=len(cells), neighbour_pairs=pairs))
    shots = scored[scored.season.eq(TARGET - 1)]
    quadrat = shots.assign(qx=np.floor((shots.x + 6) / 6), qy=np.floor((shots.y + 26) / 6.5)).groupby(['qx', 'qy']).size().reindex(
        pd.MultiIndex.from_product([range(8), range(8)]), fill_value=0)
    chi2 = float(((quadrat - quadrat.mean()) ** 2 / quadrat.mean()).sum())
    sample = shots.sample(4000, random_state=SEED)[['x', 'y']].to_numpy() + rng.uniform(-.5, .5, size=(4000, 2))
    area = 48 * 52
    def k_function(points):
        tree = cKDTree(points)
        values = []
        for r in range(1, 9):
            inside = (points[:, 0] > -6 + r) & (points[:, 0] < 42 - r) & (np.abs(points[:, 1]) < 26 - r)
            counts = tree.query_ball_point(points[inside], r, return_length=True) - 1
            values.append(area * counts.mean() / len(points))
        return np.array(values)
    observed = k_function(sample)
    random = np.array([k_function(np.column_stack([rng.uniform(-6, 42, 4000), rng.uniform(-26, 26, 4000)])) for _ in range(39)])
    k = pd.DataFrame({'radius_ft': range(1, 9), 'observed': observed, 'random_low': random.min(axis=0), 'random_high': random.max(axis=0),
                      'random_expected': np.pi * np.arange(1, 9) ** 2})
    pattern = dict(shots=int(len(shots)), quadrats=int(len(quadrat)), chi_square=chi2, degrees_of_freedom=int(len(quadrat) - 1),
                   variance_to_mean=float(quadrat.var() / quadrat.mean()), sample=4000, simulations=39)
    return variogram, pd.DataFrame(moran), k, pattern


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    scored, _ = load()
    tests, settings, weights, previous = [], [], [], None
    for year in FOLDS:
        models, setting, _ = fit_all(scored, year)
        test = scored[scored.season.eq(year)][['season', 'game_id', 'x', 'y', 'made']].copy()
        for name, model in models.items():
            test[name] = np.clip(model(test), 1e-4, 1 - 1e-4)
        test['Simple average'] = test[MEMBERS].mean(axis=1)
        if previous is not None:
            w = stack(previous)
            test['Stacked ensemble'] = test[MEMBERS].to_numpy() @ w
            weights.append(dict(season=year, **dict(zip(MEMBERS, w))))
        previous = test
        tests.append(test)
        settings.append(setting)
        print(year, {name: round(float(np.mean((test[name] - test.made) ** 2)), 5) for name in METHODS if name in test}, flush=True)
    reported = pd.concat([test for test in tests if test.season.iloc[0] in REPORTED], ignore_index=True)
    base = (reported['Distance curve'] - reported.made) ** 2
    scores = []
    for name, (family, text) in METHODS.items():
        error = (reported[name] - reported.made) ** 2
        gap = paired_games(reported.game_id, error - base)
        scores.append(dict(method=name, family=family, description=text, attempts=len(reported), games=reported.game_id.nunique(), brier=float(error.mean()),
                           drop_vs_distance_pct=-100 * gap['difference'] / base.mean(), low_pct=-100 * gap['upper'] / base.mean(), high_pct=-100 * gap['lower'] / base.mean()))
    scores = pd.DataFrame(scores).sort_values('brier').reset_index(drop=True)
    by_fold = pd.DataFrame([dict(season=int(test.season.iloc[0]), method=name, brier=float(np.mean((test[name] - test.made) ** 2)))
                            for test in tests for name in METHODS if name in test])

    models, setting, parts = fit_all(scored, TARGET)
    grid = pd.DataFrame(list(product(range(-5, 42), range(-25, 26))), columns=['x', 'y'])
    surfaces = {name: np.clip(model(grid), 1e-4, 1 - 1e-4) for name, model in models.items()}
    surfaces['Simple average'] = np.mean([surfaces[name] for name in MEMBERS], axis=0)
    final_weights = stack(previous)
    surfaces['Stacked ensemble'] = np.column_stack([surfaces[name] for name in MEMBERS]) @ final_weights
    weights.append(dict(season=TARGET, **dict(zip(MEMBERS, final_weights))))
    variogram, moran, k, pattern = diagnostics(parts, scored)
    density_scores, density, density_tau = intensity(scored)
    density_scores.to_csv(OUT / 'intensity_scores.csv', index=False)
    grid.assign(share=density).to_csv(OUT / 'intensity_2027.csv', index=False)
    weight = density_scores.shots / density_scores.shots.sum()
    pooled_density = {name: float((density_scores[name] * weight).sum()) for name in ('last_season', 'three_seasons', 'cox_process')}
    scores.to_csv(OUT / 'scores.csv', index=False)
    by_fold.to_csv(OUT / 'scores_by_season.csv', index=False)
    pd.DataFrame(weights).to_csv(OUT / 'stacking_weights.csv', index=False)
    pd.DataFrame(settings + [setting]).to_csv(OUT / 'settings.csv', index=False)
    variogram.to_csv(OUT / 'variogram.csv', index=False)
    moran.to_csv(OUT / 'morans_i.csv', index=False)
    k.to_csv(OUT / 'k_function.csv', index=False)
    grid.assign(**{name: surfaces[name] for name in METHODS}).to_csv(OUT / 'surfaces_2027.csv', index=False)
    (OUT / 'point_pattern.json').write_text(json.dumps(pattern, indent=2) + '\n', encoding='utf-8', newline='\n')

    best, distance = scores.iloc[0], scores[scores.method.eq('Distance curve')].iloc[0]
    lines = ['# Methods lab', '',
             f"Eleven methods answer one question: the chance a shot goes in from each court spot. Each learns from three regular seasons and is scored on the next. Across {len(reported):,} shots from {REPORTED[0]} to {REPORTED[-1]}, "
             f"the lowest error belongs to {best.method.lower()} at {best.brier:.5f}. The distance curve scores {distance.brier:.5f}.", '',
             '| Method | Family | Brier error | Change from the distance curve | 95% game interval |', '| --- | --- | ---: | ---: | --- |']
    lines += [f"| {r.method} | {r.family} | {r.brier:.5f} | {r.drop_vs_distance_pct:+.2f}% | {r.low_pct:+.2f}% to {r.high_pct:+.2f}% |" for r in scores.itertuples()]
    lines += ['', '## Where shots come from', '',
              'A log Gaussian Cox process treats shot locations as a point pattern whose intensity varies smoothly over the court. It is fitted to counts in 2 ft cells with a Poisson likelihood and a neighbour prior on the log intensity. '
              f"Predicting where the next season's shots fall, its average log score per shot is {pooled_density['cox_process']:.4f}, against {pooled_density['three_seasons']:.4f} for reusing the cell shares of the three seasons "
              f"and {pooled_density['last_season']:.4f} for reusing the last season alone. Lower is better. "
              f"The best of the three is {min(pooled_density, key=pooled_density.get).replace('_', ' ')}, so smoothing the pattern adds little once a full season of shots is available.", '',
              '| Season | Shots | Last season shares | Three season shares | Cox process |', '| --- | ---: | ---: | ---: | ---: |']
    lines += [f'| {r.season} | {r.shots:,} | {r.last_season:.4f} | {r.three_seasons:.4f} | {r.cox_process:.4f} |' for r in density_scores.itertuples()]
    lines += ['', 'A positive change means lower error than the distance curve. The stacked ensemble uses weights fitted on the season before each test, so it never sees the season it is scored on.', '',
              '## Spatial structure', '',
              f"The variogram of cell make rates on the logit scale rises with distance, with a fitted sill of {parts['ordinary'].sill:.2f} and a range of {parts['ordinary'].scale:.1f} ft. "
              f"After a trend in distance is removed the sill falls to {parts['universal'].sill:.3f}, so little spatial structure is left.", '',
              "| Cell values | Moran's I | Permutation p value |", '| --- | ---: | ---: |']
    lines += [f'| {r.residual} | {r.morans_i:.3f} | {r.p_value:.3f} |' for r in moran.itertuples()]
    lines += ['', f"Shots are far from evenly spread. A quadrat test on {pattern['shots']:,} shots from {TARGET - 1} gives a variance to mean ratio of {pattern['variance_to_mean']:.0f} "
              f"where complete spatial randomness would give about 1, and Ripley's K at 2 ft is {k.observed.iloc[1]:.0f} against {k.random_expected.iloc[1]:.0f} for random points.", '',
              '## Notes', '',
              'Kriging and inverse distance weighting work on 2 ft cells. The areal model uses the same cells with a conditional autoregressive prior and a binomial likelihood. '
              'The Gaussian process and the mesh models use exact shot locations. Bayesian models use a Laplace approximation at the posterior mode. '
              'Kriging, the Gaussian process and inverse distance weighting use the settings chosen in the earlier benchmark. The areal and mesh models choose theirs on the last training season. '
              "Moran's I uses cells with at least 20 shots and neighbours one cell apart, with 999 permutations. Ripley's K uses 4,000 sampled shots moved by up to half a foot, a border correction and 39 random patterns.", '',
              "[Held-out forecast errors and regional calibration](https://kevinyamada.github.io/wnba-shot-atlas/lab/#forecast-errors) · [Held-out cell totals](heldout_cells.csv) · [Scores](scores.csv) · [Scores by season](scores_by_season.csv) · [Stacking weights](stacking_weights.csv) · [Settings](settings.csv) · [Variograms](variogram.csv) · [Moran's I](morans_i.csv) · [K function](k_function.csv) · [Surfaces for 2027](surfaces_2027.csv) · [Shot density scores](intensity_scores.csv) · [Shot density for 2027](intensity_2027.csv)", '']
    (OUT / 'README.md').write_text('\n'.join(lines), encoding='utf-8', newline='\n')
    write_json(SITE / 'methods-lab.json', dict(
        manifestSha256=manifest_digest(), season=TARGET, tested=list(REPORTED), attempts=len(reported),
        methods=json.loads(scores.to_json(orient='records')), weights=[dict(method=name, weight=round(float(w), 4)) for name, w in zip(MEMBERS, final_weights)],
        variogram=json.loads(variogram.round(5).to_json(orient='records')), moran=json.loads(moran.to_json(orient='records')),
        kFunction=json.loads(k.round(3).to_json(orient='records')), pattern=pattern,
        intensity=dict(scores=pooled_density, bySeason=json.loads(density_scores.to_json(orient='records')), surface=np.round(density, 7).tolist()),
        grid=dict(rows=47, cols=51), surfaces={name: np.round(surfaces[name], 4).tolist() for name in METHODS}))
    print(scores[['method', 'brier', 'drop_vs_distance_pct']].round(5).to_string(index=False), flush=True)
    print('METHODS_LAB', len(METHODS), 'methods', len(reported), 'shots', flush=True)


if __name__ == '__main__':
    main()
