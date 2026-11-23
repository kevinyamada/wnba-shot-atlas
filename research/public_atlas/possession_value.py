"""Score remaining points forecasts and the recovery checks on public event states."""
import sys
from itertools import product

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import PoissonRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, SplineTransformer, StandardScaler

from benchmark import COHORTS, TEST, TRAIN, VALIDATION, paired_games
from build import DERIVED, RESULTS, write_json
from fetch import manifest_digest

sys.path.insert(0, str(RESULTS.parents[1]))
from possession_models import CATEGORICAL, EDGES, FEATURES, NUMERIC, MarkovValue, StateMean, score
from possession_recovery import POLICIES

OUT = RESULTS / 'possession'
STAGES = ('entry', 'after_miss', 'after_offensive_rebound')
CLOCK = 'Clock average'
STAGE = 'Stage average'


def fit_clock(train, stage_mean):
    groups = train.assign(clock_bin=np.digitize(train.seconds_remaining, EDGES) - 1)
    sums = groups.groupby(['stage', 'clock_bin']).remaining_points.agg(['sum', 'size']).reset_index()
    lookup = {(r.stage, r.clock_bin): (r.sum + 50 * stage_mean[r.stage]) / (r.size + 50) for r in sums.itertuples()}
    return lambda a: np.array([lookup.get((stage, clock), stage_mean[stage])
                               for stage, clock in zip(a.stage, np.digitize(a.seconds_remaining, EDGES) - 1)])


def fit_models(train, validation=None, settings=None):
    means = train.groupby('stage').remaining_points.mean().to_dict()
    model = {STAGE: lambda a: a.stage.map(means).to_numpy(float), CLOCK: fit_clock(train, means)}
    selections = []

    def choose(name, spec, fit):
        if settings is not None:
            return fit(settings[name])
        candidates = []
        entry = validation[validation.stage.eq('entry')]
        for setting in spec:
            predict = fit(setting)
            mse = np.mean((entry.remaining_points.to_numpy() - predict(entry)) ** 2)
            candidates.append((mse, setting, predict))
            selections.append(dict(model=name, setting=str(setting), entry_mse=mse))
        return min(candidates, key=lambda candidate: candidate[0])[2]

    model['State mean'] = choose('State mean', (10., 50., 200.),
                                 lambda alpha: StateMean(alpha).fit(train).predict)
    model['Markov'] = choose('Markov', (1., 10., 50.),
                             lambda alpha: MarkovValue(alpha).fit(train).predict)
    clocks = ['seconds_remaining', 'elapsed_seconds']
    encoder = ColumnTransformer([
        ('time', SplineTransformer(n_knots=4, degree=3, include_bias=False), clocks),
        ('context', StandardScaler(), [c for c in NUMERIC if c not in clocks]),
        ('category', OneHotEncoder(handle_unknown='ignore', sparse_output=False), CATEGORICAL),
    ])
    if settings is None:
        def poisson(alpha):
            fit = make_pipeline(encoder, PoissonRegressor(alpha=alpha, max_iter=600))
            fit.fit(train[FEATURES], train.remaining_points)
            return lambda a: fit.predict(a[FEATURES])
        model['Poisson spline'] = choose('Poisson spline', (.1, 1.), poisson)
    levels = {name: sorted(train[name].unique()) for name in CATEGORICAL}

    def features(a):
        x = a[FEATURES].copy()
        for name in CATEGORICAL:
            x[name] = pd.Categorical(x[name].where(x[name].isin(levels[name])), categories=levels[name])
        return x

    xt = features(train)

    def boost(setting):
        depth, penalty = setting
        fit = HistGradientBoostingRegressor(loss='poisson', learning_rate=.04, max_iter=300,
                                            max_leaf_nodes=15, max_depth=depth, min_samples_leaf=100,
                                            l2_regularization=penalty, max_bins=63, early_stopping=False,
                                            random_state=2026, categorical_features='from_dtype')
        fit.fit(xt, train.remaining_points)
        return lambda a: fit.predict(features(a))

    model['Context boosting'] = choose('Context boosting', list(product((3, 5), (20., 100.))), boost)
    return model, selections


def recovery(states, models, settings):
    rows, coverage = [], []
    for policy in POLICIES:
        additions = pd.concat([pd.read_csv(DERIVED / f'{policy}_{year}.csv.gz',
                               dtype={'offense_team_id': str, 'defense_team_id': str})
                               for year in (*TRAIN, VALIDATION, TEST)], ignore_index=True)
        additions = additions[additions.split.isin(['train', *COHORTS])]
        coverage.append(dict(policy=policy, states=len(additions), entry_states=int(additions.stage.eq('entry').sum()),
                             games=additions.game_id.nunique(), periods=len(additions[['game_id', 'period_number']].drop_duplicates())))
        assert not set(additions.state_id) & set(states.state_id)
        expanded = pd.concat([states.assign(cohort='original'), additions.assign(cohort='recovered')])
        refits, _ = fit_models(expanded[expanded.split.eq('train')], settings=settings)
        for split in ('test', 'playoffs'):
            subset = expanded[expanded.split.eq(split)].copy()
            for name in (STAGE, CLOCK, 'Markov', 'Context boosting'):
                subset['original_fit'] = models[name](subset)
                subset['expanded_fit'] = refits[name](subset)
                for cohort in ('all', 'original', 'recovered'):
                    chosen = subset if cohort == 'all' else subset[subset.cohort.eq(cohort)]
                    for stage, a in chosen.groupby('stage'):
                        y, old, new = a.remaining_points, a.original_fit, a.expanded_fit
                        rows.append(dict(policy=policy, split=split, cohort=cohort, stage=stage,
                                         model=name, states=len(a), original_rmse=np.sqrt(np.mean((old - y) ** 2)),
                                         expanded_rmse=np.sqrt(np.mean((new - y) ** 2)),
                                         **paired_games(a.game_id, (new - y) ** 2 - (old - y) ** 2)))
        print('RECOVERY_FITS', policy, len(additions), flush=True)
    pd.DataFrame(rows).to_csv(OUT / 'recovery_metrics.csv', index=False)
    pd.DataFrame(coverage).to_csv(OUT / 'recovery_coverage.csv', index=False)


def main():
    frames = [pd.read_csv(DERIVED / f'states_{year}.csv.gz', dtype={'offense_team_id': str, 'defense_team_id': str})
              for year in (*TRAIN, VALIDATION, TEST)]
    states = pd.concat(frames, ignore_index=True)
    states = states[states.split.isin(['train', *COHORTS])]
    assert states.state_id.is_unique and states.groupby('game_id').split.nunique().eq(1).all()
    train = states[states.split.eq('train')]
    validation = states[states.split.eq('validation')]
    models, selection = fit_models(train, validation)
    candidates = pd.DataFrame(selection).sort_values('entry_mse')
    candidates.to_csv(OUT / 'validation_selection.csv', index=False)
    import ast
    settings = {name: ast.literal_eval(a.setting.iloc[0]) for name, a in candidates.groupby('model')}
    entry = validation[validation.stage.eq('entry')]
    selected = min(models, key=lambda name: np.mean((entry.remaining_points - models[name](entry)) ** 2))
    markov = models['Markov'].__self__
    write_json(OUT / 'design.json', dict(input_manifest_sha256=manifest_digest(), train=list(TRAIN),
               validation=VALIDATION, test=TEST, selected=selected, settings=settings, features=FEATURES,
               markov_bellman_residual=markov.residual, markov_spectral_radius=markov.radius))
    value_rows = pd.DataFrame({'state': markov.labels, 'visits': markov.counts, 'value': markov.V,
                               'immediate_reward': markov.r, 'absorption_probability': 1 - markov.P.sum(axis=1)})
    value_rows.to_csv(OUT / 'markov_values.csv', index=False)
    i, j = np.nonzero(markov.P)
    pd.DataFrame({'from': np.array(markov.labels)[i], 'to': np.array(markov.labels)[j],
                  'probability': markov.P[i, j]}).to_csv(OUT / 'markov_transitions.csv', index=False)
    metrics, comparisons, calibration, pair_outputs = [], [], [], []
    for split in COHORTS:
        subset = states[states.split.eq(split)].copy()
        for name, predict in models.items():
            subset[name] = predict(subset)
        pair_outputs.append(subset[['season', 'state_id', 'episode_id', 'source_row', 'game_id', 'split', 'stage',
                                    'remaining_points', *models.keys()]])
        for stage, a in [('all', subset), *subset.groupby('stage')]:
            y = a.remaining_points
            for name in models:
                p = a[name]
                metrics.append(dict(split=split, stage=stage, model=name, games=a.game_id.nunique(), **score(y, p)))
                for baseline in [STAGE, CLOCK]:
                    difference = (p - y) ** 2 - (a[baseline] - y) ** 2
                    comparisons.append(dict(split=split, stage=stage, model=name, baseline=baseline,
                                            **paired_games(a.game_id, difference)))
                bins = np.minimum(11, np.floor(p * 4).astype(int))
                for bucket, b in a.groupby(bins):
                    calibration.append(dict(split=split, stage=stage, model=name, bin=bucket, states=len(b),
                                            predicted=b[name].mean(), observed=b.remaining_points.mean()))
    pd.DataFrame(metrics).to_csv(OUT / 'metrics.csv', index=False)
    pd.DataFrame(comparisons).to_csv(OUT / 'paired_game_intervals.csv', index=False)
    pd.DataFrame(calibration).to_csv(OUT / 'calibration.csv', index=False)
    pd.concat(pair_outputs).to_csv(DERIVED / 'possession_predictions.csv.gz', index=False)
    print('POSSESSION_MODELS_SCORED', selected, flush=True)

    flows = []
    for year in (VALIDATION, TEST):
        misses = pd.read_csv(DERIVED / f'miss_flow_{year}.csv.gz')
        for split, a in misses[misses.split.isin(COHORTS)].groupby('split'):
            for retained, b in a.groupby('retained_by_rebound'):
                flows.append(dict(year=year, split=split, rebound=bool(retained), misses=len(b),
                                  later_points=int(b.remaining_points.sum()),
                                  scored_after=int(b.remaining_points.gt(0).sum())))
    pd.DataFrame(flows).to_csv(OUT / 'miss_flow.csv', index=False)
    summary = states.groupby(['split', 'stage']).remaining_points.agg(states='size', points='sum', mean='mean').reset_index()
    summary.to_csv(OUT / 'state_summary.csv', index=False)
    recovery(states, models, settings)
    print('POSSESSION_STUDY_COMPLETE', flush=True)


if __name__ == '__main__':
    main()
