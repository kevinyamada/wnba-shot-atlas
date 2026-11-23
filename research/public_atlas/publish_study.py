"""Export the public research results and a readable report from audited tables."""
import json

import numpy as np
import pandas as pd
from sklearn.metrics import log_loss

from build import DERIVED, RESULTS, SHOT_TYPES, SITE, write_json
from fetch import manifest_digest


def read(path, **kwargs):
    return pd.read_csv(RESULTS / path, **kwargs)


def records(frame):
    return json.loads(frame.to_json(orient='records', double_precision=12))


def table(frame):
    columns = list(frame.columns)
    lines = ['| ' + ' | '.join(columns) + ' |', '| ' + ' | '.join(['---'] * len(columns)) + ' |']
    for row in frame.itertuples(index=False, name=None):
        values = [f'{value:.5f}' if isinstance(value, float) else str(value) for value in row]
        lines.append('| ' + ' | '.join(values) + ' |')
    return '\n'.join(lines)


def shot_type_results(selected):
    p = pd.read_csv(DERIVED / 'shot_predictions.csv.gz')
    identities = pd.concat([
        pd.read_csv(DERIVED / f'shots_{year}.csv.gz', usecols=['season', 'source_row', 'game_id', 'shot_type'])
        for year in p.season.unique()
    ])
    p = p.merge(identities, on=['season', 'source_row', 'game_id'], how='left', validate='one_to_one')
    assert p.shot_type.notna().all()
    rows = []
    for (split, category), a in p.groupby(['split', 'shot_type']):
        y = a.made.to_numpy()
        for name in dict.fromkeys(['Distance baseline', 'Five model average', selected, 'Matérn GP']):
            observed = a[name].to_numpy()
            rows.append(dict(split=split, shot_type=SHOT_TYPES[int(category)], model=name,
                             games=a.game_id.nunique(), attempts=len(a), makes=int(y.sum()),
                             brier=float(np.mean((y - observed) ** 2)), log_loss=log_loss(y, observed, labels=[0, 1])))
    return pd.DataFrame(rows)


def posterior():
    names = ('matern', 'spde')
    surfaces = {}
    for name in names:
        frame = read(f'shot_models/{name}_surface.csv')
        assert frame[['x', 'y']].duplicated().sum() == 0
        assert frame.lower.ge(0).all() and frame.upper.le(1).all() and frame.lower.le(frame.upper).all()
        surfaces[name] = frame.round(6).to_numpy().tolist()
    return surfaces


def main():
    shot = 'shot_models/'
    pos = 'possession/'
    make = read(shot + 'make_metrics.csv')
    points = read(shot + 'point_metrics.csv')
    spatial = read(shot + 'spatial_metrics.csv')
    comparison = read(shot + 'paired_game_intervals.csv')
    refits = read(shot + 'refit_sensitivity.csv')
    values = read(pos + 'metrics.csv')
    entry = values[values.stage.eq('entry')]
    recovery = read(pos + 'recovery_coverage.csv')
    recovery_metrics = read(pos + 'recovery_metrics.csv')
    flow = read(pos + 'miss_flow.csv')
    state_counts = read(pos + 'state_summary.csv')
    state_checks = read(pos + 'paired_game_intervals.csv')
    shot_design = json.loads((RESULTS / shot / 'design.json').read_bytes())
    pos_design = json.loads((RESULTS / pos / 'design.json').read_bytes())
    reconstruction = json.loads((RESULTS / pos / 'reconstruction.json').read_bytes())
    typed = shot_type_results(shot_design['selected'])
    typed.to_csv(RESULTS / shot / 'shot_type_metrics.csv', index=False)
    shots_type_summary = []
    for path in sorted(SITE.glob('[12][0-9][0-9][0-9].json')):
        pack = json.loads(path.read_bytes())
        for phase in range(2):
            sums = np.zeros((len(SHOT_TYPES), 3), dtype='int64')
            for row in pack['rows']:
                if row[0] == phase:
                    sums[row[8]] += row[5:8]
            for label, (n, k, points_total) in zip(SHOT_TYPES, sums):
                shots_type_summary.append(dict(season=pack['season'], phase=('regular', 'playoffs')[phase],
                                               shot_type=label, attempts=n, makes=k, points=points_total,
                                               make_rate=k / n if n else None, points_per_shot=points_total / n if n else None))
    pd.DataFrame(shots_type_summary).to_csv(RESULTS / 'shot_types.csv', index=False)
    write_json(SITE / 'bayesian.json', posterior())
    source = manifest_digest()
    assert shot_design['input_manifest_sha256'] == pos_design['input_manifest_sha256'] == source
    write_json(SITE / 'study.json', dict(
        manifestSha256=source, shotSelected=shot_design['selected'], possessionSelected=pos_design['selected'],
        shots=records(make), shotTypeMetrics=records(typed), pointModels=records(points), shotIntervals=records(comparison),
        refits=records(refits), spatial=records(spatial), possession=records(values),
        possessionIntervals=records(state_checks[state_checks.baseline.eq('Stage average')]),
        flow=records(flow), stateCounts=records(state_counts), recovery=records(recovery),
        recoveryMetrics=records(recovery_metrics[recovery_metrics.stage.eq('entry')]),
        seasonReconstruction=reconstruction))
    holdout = make[make.split.ne('validation')].sort_values(['split', 'brier'])
    result = f"""# What the public WNBA data show

[Season by season data review](eda.md)

## Shot predictions across seasons

Regular season games in 2022 through 2024 train the models. The 2025 regular season chooses model settings by log loss. The 2026 regular season and the 2026 playoffs are scored separately with settings fixed. Earlier games on the same date cannot affect a shooter's history. Models use the same mapped attempts with usable clocks and reconciled team and player counts. The data have already been used for descriptive work, and the final season is an out of time comparison.

The model with the lowest 2025 log loss is **{shot_design['selected']}**. Results include Brier score, log loss and calibration. Smaller errors are better. Paired intervals resample whole games with all their attempts.

{table(holdout[['split', 'model', 'attempts', 'brier', 'log_loss', 'auc']])}

The field goal points comparison predicts the probabilities of 0, 2 or 3 points, then multiplies those probabilities by their values. A missed shot always contributes zero points. Court geometry is not used to assign an official attempt value to a miss.

{table(points[['split', 'model', 'attempts', 'rmse', 'mae']])}

The shot type tables from the same runs score models on jump shots, layups and other recorded types. Those categories were used for evaluation. They were not supplied as predictors in the benchmark.

## Prediction in unfamiliar court areas

The four regions divide the court at 16 feet forward and down its centre. Each region is held out once. Training points are removed within 0, 2 or 4 feet of observed test locations. The same attempts are tested with every buffer.

{table(spatial.sort_values(['buffer_ft', 'brier']))}

The spatial methods reuse inverse distance weighting, ordinary and universal kriging, and the finite element SPDE model. The Matérn model uses a finite spectral basis and a conditional Laplace approximation on CPU. The SPDE report checks finer meshes with the fitted range and variance fixed. The refit checks add 2025 training games or include games with disputed shooter counts in a model that does not use shooter identity.

## What happens after a miss

The sequence reconstruction uses public play by play and checks the scoreboard, team boxes, play order and control changes. The sample covers clean sequences from 2022 to 2026. The rebound flow counts a miss followed by an offensive rebound as the next relevant event within the same sequence.

{table(flow[['year', 'split', 'rebound', 'misses', 'later_points', 'scored_after']])}

The possession models predict points remaining in a recorded sequence. The model selected on 2025 entry states is **{pos_design['selected']}**. The simplest forecasts use means by stage or remaining time. The Markov model estimates state transitions and rewards. The other models fit clock splines or boosted trees.

{table(entry[['split', 'model', 'states', 'rmse', 'mae']])}

The recovery comparison uses confirmed defensive rebounds to restart eligible tails after a special sequence or overturned play. A stricter policy waits for a second such restart. Hard score and clock exclusions remain in force. The original and expanded fits are compared on the same states.

{table(recovery)}

The public releases used here support shot analysis and event based remaining points. Estimating the value of choosing a pass or movement would require action locations and a suitable comparison design.

## Files

- [Source checks and reproduction](../../public_atlas/README.md)
- [Shot prediction results](shot_models/)
- [Possession results and score audits](possession/)
"""
    (RESULTS / 'study.md').write_text(result, encoding='utf-8', newline='')
    print('PUBLIC_STUDY_EXPORTED', len(make), 'shot model rows', len(values), 'possession model rows', flush=True)


if __name__ == '__main__':
    main()
