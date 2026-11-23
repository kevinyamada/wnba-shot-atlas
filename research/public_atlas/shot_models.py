"""Repeat the spatial, make probability, and observed points comparisons on wehoop."""
import os

for variable in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[variable] = '3'

import argparse
import json
import sys
from itertools import product

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier
from scipy import sparse
from scipy.linalg import cho_factor, cho_solve
from scipy.special import expit, logit
from scipy.spatial import cKDTree
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.preprocessing import OneHotEncoder, SplineTransformer, StandardScaler
from xgboost import XGBClassifier

from benchmark import COHORTS, TEST, TRAIN, VALIDATION, paired_games, sample_split
from build import DERIVED, RESULTS, write_json
from fetch import manifest_digest

sys.path.insert(0, str(RESULTS.parents[1]))
from spatial_methods import IDW, Kriging, SPDE

OUT = RESULTS / 'shot_models'
BASELINE = 'Distance baseline'
CONTEXT = ['period_number', 'seconds', 'home', 'prior_rate', 'log_prior_n']
CATEGORICAL = ['player_id', 'team_id']
SPATIAL = ['x', 'y', 'distance', 'angle', 'line_offset_ft']
DISTANCE_BINS = [0, 4, 8, 12, 16, 20, 22.145833333333332, 24, 28, 100]
OUTCOMES = np.array([0, 2, 3])
SEEDS = (2026, 2027, 2028)


def dataset():
    frames = []
    for year in (*TRAIN, VALIDATION, TEST):
        shots = pd.read_csv(DERIVED / f'shots_{year}.csv.gz', low_memory=False)
        audit = pd.read_csv(DERIVED / f'player_game_audit_{year}.csv.gz')
        disputed = audit[audit.status.ne('matches') & (audit.attempts.gt(0) | audit.box_attempts.gt(0))]
        bad_ids = set(disputed.game_id) | set(shots.loc[shots.player_id.eq(0), 'game_id'])
        shots['player_audit_pass'] = ~shots.game_id.isin(bad_ids)
        frames.append(shots)
    s = pd.concat(frames, ignore_index=True)
    s['split'] = sample_split(s)
    s = s[s.split.isin(['train', *COHORTS])].copy()
    team_boxes = pd.read_csv(RESULTS / 'team_game_audit.csv')
    matched = team_boxes[team_boxes.status.eq('matches')].groupby('game_id').size()
    s['team_audit_pass'] = s.game_id.isin(matched[matched.eq(2)].index)
    clock = s.clock_display_value.str.extract(r'^(\d+):(\d+(?:\.\d+)?)$').astype(float)
    s['seconds'] = 60 * clock[0] + clock[1]
    s['home'] = s.team_id.eq(s.home_id).astype(int)
    s['date'] = pd.to_datetime(s.game_date, utc=True).dt.normalize()
    audited = s[s.player_audit_pass & s.team_audit_pass].copy()

    # Use the previous dates' attempts and makes, including attempts off the map.
    # Shots on the same date share a lagged value, so ordering that day's games
    # or plays cannot leak a result back into a prediction.
    history = (audited.groupby(['player_id', 'date']).made.agg(n='size', k='sum')
               .sort_index().reset_index())
    for key in ('n', 'k'):
        history['prior_' + key] = history.groupby('player_id')[key].cumsum() - history[key]
    audited = audited.merge(history[['player_id', 'date', 'prior_n', 'prior_k']],
                            on=['player_id', 'date'], validate='many_to_one')
    audited['prior_rate'] = (audited.prior_k + 22) / (audited.prior_n + 50)
    audited['log_prior_n'] = np.log1p(audited.prior_n)
    eligible = audited.cell.ge(0) & audited.seconds.between(0, np.where(audited.period_number.le(4), 600, 300))
    model = audited.loc[eligible].copy()

    def spatial_features(frame):
        frame = frame.rename(columns={'depth_ft': 'x', 'lateral_ft': 'y', 'distance_ft': 'distance'})
        frame['angle'] = np.arctan2(frame.y.abs(), frame.x)
        for key in CATEGORICAL:
            frame[key] = frame[key].astype(str)
        return frame

    model = spatial_features(model)
    assert np.isfinite(model[SPATIAL + CONTEXT].to_numpy()).all()
    assert model.groupby('game_id').split.nunique().eq(1).all()
    assert model[model.split.eq('train')].date.max() < model[model.split.eq('validation')].date.min()
    assert model[model.split.eq('validation')].date.max() < model[model.split.eq('test')].date.min()
    report = []
    for split, frame in s.groupby('split'):
        kept = model[model.split.eq(split)]
        report.append(dict(split=split, attempts=len(frame), games=frame.game_id.nunique(),
                           games_failing_team_boxes=frame.loc[~frame.team_audit_pass, 'game_id'].nunique(),
                           games_failing_player_check=frame.loc[~frame.player_audit_pass, 'game_id'].nunique(),
                           eligible=len(kept), eligible_games=kept.game_id.nunique(),
                           first_date=str(kept.date.min().date()), last_date=str(kept.date.max().date())))
    pd.DataFrame(report).to_csv(OUT / 'sample_coverage.csv', index=False)
    identity_free = spatial_features(s[s.team_audit_pass & s.cell.ge(0) & s.seconds.between(0, 600)].copy())
    return model, identity_free


def empirical(train, other, use_distance=True):
    base = train.points.value_counts().reindex(OUTCOMES, fill_value=0).to_numpy() + 1
    base = base / base.sum()
    if not use_distance:
        return np.tile(base, (len(other), 1))
    bins = np.digitize(train.distance, DISTANCE_BINS)
    histogram = pd.crosstab(bins, train.points).reindex(
        index=range(len(DISTANCE_BINS) + 1), columns=OUTCOMES, fill_value=0).to_numpy()
    probability = histogram + 2 * base
    probability /= probability.sum(axis=1, keepdims=True)
    return probability[np.digitize(other.distance, DISTANCE_BINS)]


class SplineDesign:
    def __init__(self, train):
        self.spline = SplineTransformer(n_knots=5, degree=3, include_bias=False).fit(train[['x', 'y']])
        self.scaler = StandardScaler().fit(train[CONTEXT])
        self.encoder = OneHotEncoder(handle_unknown='ignore').fit(train[CATEGORICAL])

    def transform(self, frame, context):
        basis = self.spline.transform(frame[['x', 'y']])
        n = basis.shape[1] // 2
        interaction = np.einsum('ij,ik->ijk', basis[:, :n], basis[:, n:]).reshape(len(frame), -1)
        base = np.column_stack([basis, interaction])
        if not context:
            return base
        return sparse.hstack((base, self.scaler.transform(frame[CONTEXT]),
                              self.encoder.transform(frame[CATEGORICAL])), format='csr')


def joint_logistic_fits(train, design):
    x = design.transform(train, True)
    for c in (.1, 1., 10.):
        model = LogisticRegression(C=c, solver='newton-cholesky', max_iter=100, tol=1e-7)
        model.fit(x, train.points)
        assert model.n_iter_.max() < model.max_iter
        assert np.array_equal(model.classes_, OUTCOMES)
        yield f'C={c}', lambda a, fit=model: fit.predict_proba(design.transform(a, True))


class MaternLaplace:
    """Finite spectral Matérn 5/2 binomial GP with a Gaussian Laplace posterior."""
    def __init__(self, length, scale):
        domain = np.array([36., 38.])
        modes = np.array(list(product(range(1, 17), repeat=2)))
        self.omega = np.pi * modes / (2 * domain)
        self.domain = domain
        self.spectral_weights = scale * np.sqrt(
            (4 * np.pi * 2.5 * 5 ** 2.5 * length ** 2) /
            (5 + np.sum((self.omega * length) ** 2, axis=1)) ** 3.5)

    def basis(self, xy):
        phase = (xy[:, None, :] - np.array([18., 0.]) + self.domain) * self.omega
        phi = np.prod(np.sin(phase) / np.sqrt(self.domain), axis=2)
        return np.column_stack([np.ones(len(xy)), phi * self.spectral_weights])

    def fit(self, train):
        grouped = train.groupby(['x', 'y']).made.agg(['sum', 'count']).reset_index()
        x = self.basis(grouped[['x', 'y']].to_numpy())
        k, n = grouped['sum'].to_numpy(), grouped['count'].to_numpy()
        eye = np.eye(x.shape[1])
        w = np.zeros(x.shape[1])
        w[0] = logit((k.sum() + 1) / (n.sum() + 2))

        def loss(v):
            z = x @ v
            return (n * np.logaddexp(0, z) - k * z).sum() + .5 * v @ v

        for _ in range(60):
            p = expit(x @ w)
            gradient = x.T @ (n * p - k) + w
            chol = cho_factor(eye + x.T @ ((n * p * (1 - p))[:, None] * x))
            step = cho_solve(chol, gradient)
            if np.max(np.abs(step)) < 1e-8:
                break
            rate, old = 1., loss(w)
            while loss(w - rate * step) > old + 1e-8:
                rate *= .5
                assert rate > 1e-8
            w -= rate * step
        self.gradient = float(abs(gradient).max())
        assert self.gradient < 1e-3
        self.w, self.chol = w, chol
        return self

    def predict(self, frame, interval=False):
        xy, ix = np.unique(frame[['x', 'y']], axis=0, return_inverse=True)
        x = self.basis(xy)
        mean = x @ self.w
        std = np.sqrt(np.maximum(0, np.sum(x * cho_solve(self.chol, x.T).T, axis=1)))
        nodes, weights = np.polynomial.hermite.hermgauss(15)
        p = expit(mean[:, None] + np.sqrt(2) * std[:, None] * nodes) @ weights / np.sqrt(np.pi)
        if interval:
            return p[ix], expit(mean - 1.96 * std)[ix], expit(mean + 1.96 * std)[ix]
        return p[ix]


def binary_metrics(y, p):
    return dict(brier=brier_score_loss(y, p), log_loss=log_loss(y, p, labels=[0, 1]),
                auc=roc_auc_score(y, p), mean_prediction=float(np.mean(p)), observed=float(np.mean(y)))


def cat_features(frame, context):
    columns = SPATIAL + CONTEXT + CATEGORICAL if context else SPATIAL
    return frame[columns]


def xgb_features(frame, context, fitted_encoder):
    if not context:
        return frame[SPATIAL].to_numpy()
    return sparse.hstack((frame[SPATIAL + CONTEXT].to_numpy(),
                          fitted_encoder.transform(frame[CATEGORICAL])), format='csr')


def comparisons(data, identity_free):
    train = data[data.split.eq('train')]
    val = data[data.split.eq('validation')]
    design = SplineDesign(train)
    candidates, predictions = [], {}

    def pick(name, trials, response='made'):
        best = None
        for label, predict in trials:
            p = predict(val)
            loss = log_loss(val[response], p, labels=OUTCOMES if response == 'points' else [0, 1])
            candidates.append(dict(model=name, settings=label, validation_log_loss=float(loss)))
            if best is None or loss < best[0]:
                best = loss, predict, label
        print('SELECTED', name, best[2], f'{best[0]:.6f}', flush=True)
        return best[1], best[2]

    predictions['Constant baseline'] = lambda a: empirical(train, a, False)[:, 1:].sum(axis=1)
    predictions[BASELINE] = lambda a: empirical(train, a)[:, 1:].sum(axis=1)
    for context in (False, True):
        name = 'Context logistic' if context else 'Spatial logistic'
        xt = design.transform(train, context)

        def logistic_trials():
            for c in (.1, 1., 10.):
                fit = LogisticRegression(C=c, max_iter=2500, tol=1e-6).fit(xt, train.made)
                yield f'C={c}', lambda a, m=fit, ctx=context: m.predict_proba(design.transform(a, ctx))[:, 1]

        predictions[name], _ = pick(name, logistic_trials())

    def spatial_trials(variants):
        for label, model in variants:
            fit = model.fit(train)
            yield label, fit.predict

    predictions['IDW'], _ = pick('IDW', spatial_trials((f'power={p}', IDW(p)) for p in (1, 2, 3)))
    for name, drift in [('Ordinary kriging', False), ('Universal kriging', True)]:
        model = Kriging(drift).fit(train)
        predictions[name] = model.predict
        pd.DataFrame(model.variogram, columns=['distance_ft', 'semivariance', 'pairs']).to_csv(
            OUT / f"{name.lower().replace(' ', '_')}_variogram.csv", index=False)
    predictions['SPDE'], _ = pick('SPDE', spatial_trials(
        (f'range={r}, sigma={s}, spacing=3', SPDE(r, s, 3)) for r, s in product((4, 8, 16), (.3, .7, 1.5))))
    predictions['Matérn GP'], _ = pick('Matérn GP', spatial_trials(
        (f'length={l}, scale={s}, basis=16×16', MaternLaplace(l, s)) for l, s in product((4, 8, 16), (.5, 1.))))

    def tree_fit(family, context, depth, seed, joint=False, fitted_train=train):
        if family == 'CatBoost':
            xt = cat_features(fitted_train, context)
            fit = CatBoostClassifier(iterations=400, depth=depth, learning_rate=.05, l2_leaf_reg=5,
                                     cat_features=CATEGORICAL if context else [], random_seed=seed,
                                     thread_count=3, verbose=False, allow_writing_files=False)
            fit.fit(xt, fitted_train.points if joint else fitted_train.made)
            classes = OUTCOMES if joint else np.array([0, 1])
            assert np.array_equal(fit.classes_, classes)
            return lambda a: fit.predict_proba(cat_features(a, context))
        fit = XGBClassifier(n_estimators=400, max_depth=depth, learning_rate=.05, min_child_weight=12,
                            reg_lambda=4, tree_method='hist', random_state=seed, n_jobs=3)
        fit.fit(xgb_features(fitted_train, context, design.encoder),
                np.searchsorted(OUTCOMES, fitted_train.points) if joint else fitted_train.made)
        return lambda a: fit.predict_proba(xgb_features(a, context, design.encoder))

    for family, context in product(('CatBoost', 'XGBoost'), (False, True)):
        name = f"{family} {'context' if context else 'spatial'}"

        def tree_trials():
            for depth in (4, 6):
                m = tree_fit(family, context, depth, SEEDS[0])
                yield f'depth={depth}', lambda a, f=m: f(a)[:, 1]

        _, setting = pick(name, tree_trials())
        depth = int(setting.split('=')[1])
        fits = [tree_fit(family, context, depth, seed) for seed in SEEDS]
        predictions[name] = lambda a, members=fits: np.mean([m(a)[:, 1] for m in members], axis=0)

    member_names = ['CatBoost context', 'XGBoost context', 'Matérn GP', 'SPDE', 'Universal kriging']
    predictions['Five model average'] = lambda a: np.mean([predictions[name](a) for name in member_names], axis=0)
    calibrate_input = lambda a: logit(np.clip(predictions['Five model average'](a), 1e-6, 1 - 1e-6)).reshape(-1, 1)
    calibration = LogisticRegression(C=1000).fit(calibrate_input(val), val.made)
    predictions['Calibrated average'] = lambda a: calibration.predict_proba(calibrate_input(a))[:, 1]

    joint_logistic, _ = pick('Joint logistic', joint_logistic_fits(train, design), response='points')


    def joint_tree_trials():
        for family, depth in product(('CatBoost', 'XGBoost'), (4, 6)):
            yield f'{family} depth={depth}', tree_fit(family, True, depth, SEEDS[0], joint=True)

    _, joint_setting = pick('Joint boosted', joint_tree_trials(), response='points')
    family, depth = joint_setting.split(' depth=')
    joint_members = [tree_fit(family, True, int(depth), seed, joint=True) for seed in SEEDS]
    joint_boosted = lambda a: np.mean([predict(a) for predict in joint_members], axis=0)
    points = {'Constant outcomes': lambda a: empirical(train, a, False),
              'Distance outcomes': lambda a: empirical(train, a),
              'Joint logistic': joint_logistic, 'Joint boosted': joint_boosted}
    predictions['Joint boosted make probability'] = lambda a: joint_boosted(a)[:, 1:].sum(axis=1)
    predictions['Joint logistic make probability'] = lambda a: joint_logistic(a)[:, 1:].sum(axis=1)
    validation_scores = {name: binary_metrics(val.made, m(val))['log_loss']
                         for name, m in predictions.items() if name != 'Calibrated average'}
    selected = min(validation_scores, key=validation_scores.get)
    pd.DataFrame(candidates).to_csv(OUT / 'validation_selection.csv', index=False)
    write_json(OUT / 'design.json', dict(input_manifest_sha256=manifest_digest(), train=list(TRAIN),
               validation=VALIDATION, test=TEST, playoff_season=TEST, test_and_playoffs_scored_after_selection=True,
               ensemble_members=member_names, seeds=list(SEEDS), selected=selected,
               validation_model_scores=validation_scores,
               features=SPATIAL + CONTEXT + CATEGORICAL,
               inference='CPU, conditional Laplace posterior for GP and SPDE.'))
    tables, point_tables, comparisons, bins, saved = [], [], [], [], []
    for split in COHORTS:
        a = data[data.split.eq(split)]
        observed = a.made.to_numpy()
        actual_points = a.points.to_numpy()
        q = a[['season', 'source_row', 'game_id', 'split', 'made', 'points']].copy()
        baseline = (predictions[BASELINE](a) - observed) ** 2
        for name, predict in predictions.items():
            if name == 'Calibrated average' and split == 'validation':
                continue
            p = np.asarray(predict(a))
            assert np.isfinite(p).all() and ((0 <= p) & (p <= 1)).all()
            tables.append(dict(split=split, model=name, attempts=len(a), **binary_metrics(observed, p)))
            difference = (p - observed) ** 2 - baseline
            comparisons.append(dict(split=split, model=name, metric='Brier', **paired_games(a.game_id, difference)))
            bin_data = pd.DataFrame({'p': p, 'made': observed, 'bin': np.minimum(9, (p * 10).astype(int))})
            for bin_id, group in bin_data.groupby('bin'):
                bins.append(dict(split=split, model=name, bin=int(bin_id), attempts=len(group),
                                 predicted=group.p.mean(), observed=group.made.mean()))
            q[name] = p
        baseline_points = (points['Distance outcomes'](a) @ OUTCOMES - actual_points) ** 2
        for name, predict in points.items():
            p = predict(a)
            assert np.isfinite(p).all() and (p >= 0).all() and np.allclose(p.sum(axis=1), 1)
            expected = p @ OUTCOMES
            error = expected - actual_points
            point_tables.append(dict(split=split, model=name, attempts=len(a), rmse=np.sqrt(np.mean(error ** 2)),
                                 mae=np.mean(abs(error)), joint_log_loss=log_loss(actual_points, p, labels=OUTCOMES)))
            comparisons.append(dict(split=split, model=name, metric='Points MSE',
                                    **paired_games(a.game_id, error ** 2 - baseline_points)))
            q['points ' + name] = expected
            for j, outcome in enumerate(OUTCOMES):
                q[f'Pr({outcome}) {name}'] = p[:, j]
        saved.append(q)
    pd.DataFrame(tables).to_csv(OUT / 'make_metrics.csv', index=False)
    pd.DataFrame(point_tables).to_csv(OUT / 'point_metrics.csv', index=False)
    pd.DataFrame(comparisons).to_csv(OUT / 'paired_game_intervals.csv', index=False)
    pd.DataFrame(bins).to_csv(OUT / 'calibration.csv', index=False)
    pd.concat(saved).to_csv(DERIVED / 'shot_predictions.csv.gz', index=False)
    print('SHOT_MODELS_SCORED', selected, flush=True)

    # Diagnostic refits are separate from the fixed chronological benchmark.
    refit = data[data.split.isin(['train', 'validation'])]
    cat_setting = next(r for r in sorted(candidates, key=lambda r: r['validation_log_loss'])
                       if r['model'] == 'CatBoost context')
    depth = int(cat_setting['settings'].split('=')[1])
    columns = SPATIAL + ['seconds', 'period_number', 'home']
    matched_ids = set(train.game_id)
    clean = identity_free[identity_free.game_id.isin(matched_ids)]
    expanded = identity_free[identity_free.split.eq('train')]
    hgb = [HistGradientBoostingClassifier(max_iter=300, l2_regularization=10,
                                          max_leaf_nodes=15, random_state=2026)
           .fit(frame[columns], frame.made) for frame in (clean, expanded)]
    outcomes = []
    for split in ('test', 'playoffs'):
        a = data[data.split.eq(split)]
        cases = [
            ('CatBoost extra season', tree_fit('CatBoost', True, depth, SEEDS[0], fitted_train=refit)(a)[:, 1],
             tree_fit('CatBoost', True, depth, SEEDS[0])(a)[:, 1]),
            ('Distance extra season', empirical(refit, a)[:, 1:].sum(axis=1), predictions[BASELINE](a)),
            ('Identity free with disputed games', hgb[1].predict_proba(a[columns])[:, 1], hgb[0].predict_proba(a[columns])[:, 1])
        ]
        for name, expanded_p, fixed_p in cases:
            y = a.made.to_numpy()
            outcomes.append(dict(split=split, comparison=name, attempts=len(a),
                                 expanded_brier=brier_score_loss(y, expanded_p), reference_brier=brier_score_loss(y, fixed_p),
                                 **paired_games(a.game_id, (expanded_p - y) ** 2 - (fixed_p - y) ** 2)))
    pd.DataFrame(outcomes).to_csv(OUT / 'refit_sensitivity.csv', index=False)

    mesh = predictions['SPDE'].__self__
    cases = []
    previous = None
    grid = pd.DataFrame(list(product(range(-5, 42), range(-25, 26))), columns=['x', 'y'])
    for spacing in (3, 2, 1.5):
        fit = mesh if spacing == 3 else SPDE(mesh.range_ft, mesh.sigma, spacing).fit(train)
        p = fit.predict(val)
        cases.append(dict(spacing_ft=spacing, nodes=len(fit.nodes), validation_log_loss=log_loss(val.made, p),
                          mean_change=None if previous is None else abs(p - previous).mean(),
                          max_change=None if previous is None else abs(p - previous).max(), gradient=fit.gradient_max))
        previous = p
    pd.DataFrame(cases).to_csv(OUT / 'mesh_sensitivity.csv', index=False)
    for name, model in [('spde', mesh), ('matern', predictions['Matérn GP'].__self__)]:
        p, lower, upper = (model.predict(grid, uncertainty=True) if name == 'spde'
                           else model.predict(grid, interval=True))
        grid.assign(probability=p, lower=lower, upper=upper).to_csv(OUT / f'{name}_surface.csv', index=False)


def spatial_cv(data):
    train = data[data.split.eq('train')].copy()
    blocks = 2 * train.x.ge(16).astype(int) + train.y.ge(0).astype(int)
    scores, folds = [], []
    for buffer, fold in product((0, 2, 4), range(4)):
        heldout = train[blocks.eq(fold)]
        fit = train[blocks.ne(fold)]
        locations = cKDTree(heldout[['x', 'y']].drop_duplicates())
        nearest = locations.query(fit[['x', 'y']])[0]
        fit = fit.iloc[np.flatnonzero(nearest > buffer)]
        assert len(fit) > 0 and nearest[nearest > buffer].min() > buffer
        folds.append(dict(buffer_ft=buffer, fold=fold, train_attempts=len(fit), test_attempts=len(heldout),
                          minimum_distance_ft=nearest[nearest > buffer].min()))
        design = SplineDesign(fit)
        logistic = LogisticRegression(C=1, max_iter=2500).fit(design.transform(fit, False), fit.made)
        models = {'Distance baseline': empirical(fit, heldout)[:, 1:].sum(axis=1),
                  'Spatial logistic': logistic.predict_proba(design.transform(heldout, False))[:, 1]}
        for name, model in [('IDW', IDW(2)), ('Ordinary kriging', Kriging(False)),
                            ('Universal kriging', Kriging(True)), ('SPDE', SPDE(8, .7, 3)),
                            ('Matérn GP', MaternLaplace(8, 1))]:
            models[name] = model.fit(fit).predict(heldout)
        for name, p in models.items():
            scores.append(dict(buffer_ft=buffer, fold=fold, model=name, attempts=len(heldout),
                               **binary_metrics(heldout.made, p)))
        print('SPATIAL_FOLD', buffer, fold, len(heldout), flush=True)
    pd.DataFrame(scores).to_csv(OUT / 'spatial_folds.csv', index=False)
    pd.DataFrame(folds).to_csv(OUT / 'spatial_separation.csv', index=False)
    table = pd.DataFrame(scores)
    for key in ('brier', 'log_loss'):
        table[key] *= table.attempts
    pooled = table.groupby(['buffer_ft', 'model'], as_index=False)[['attempts', 'brier', 'log_loss']].sum()
    for key in ('brier', 'log_loss'):
        pooled[key] /= pooled.attempts
    assert pooled.attempts.nunique() == 1 and pooled.attempts.iloc[0] == len(train)
    pooled.to_csv(OUT / 'spatial_metrics.csv', index=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=['all', 'chronological', 'spatial'], default='all')
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    data, uncorrected = dataset()
    if args.stage != 'spatial':
        comparisons(data, uncorrected)
    if args.stage != 'chronological':
        spatial_cv(data)
