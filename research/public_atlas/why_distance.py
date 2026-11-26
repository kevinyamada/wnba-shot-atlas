"""Measure what each kind of recorded information adds to a distance only shot forecast.

Every step uses the benchmark sample: fit on 2022 to 2024 regular seasons,
choose the number of boosting rounds on 2025, score 2026 once. Each step keeps
the features of the step before it and adds one more group.
"""
import json

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import log_loss

from benchmark import paired_games
from build import DERIVED, RESULTS, SITE, write_json
from fetch import RAW, manifest_digest

OUT = RESULTS / 'why_distance'
SEED = 20261123
ROUNDS = 600
STEPS = [('Distance', ['distance']),
         ('Court position', ['x', 'y', 'angle', 'line_offset_ft']),
         ('Recorded shot type', ['shot_label']),
         ('Period, clock and score', ['period_number', 'seconds', 'home', 'margin']),
         ('Previous event', ['previous_event', 'previous_same_team', 'seconds_since_previous']),
         ('Shooter record so far', ['prior_rate', 'log_prior_n'])]
CATEGORIES = ['shot_label', 'previous_event']
KEY = ['game_id', 'period_number', 'clock_display_value', 'athlete_id_1', 'type_text', 'score_value', 'coordinate_x_raw', 'coordinate_y_raw']
TARGETS = (.02, .05, .10, .20)


def event_group(plays):
    kind = plays.type_text.fillna('').str.lower().str.replace('\n', ' ')
    text = plays.text.fillna('').str.lower()
    made = plays.shooting_play.eq(True) & plays.scoring_play.eq(True)
    return np.select(
        [kind.str.contains('free throw'), plays.shooting_play.eq(True) & made, plays.shooting_play.eq(True),
         kind.str.contains('offensive rebound'), kind.str.contains('rebound'),
         kind.str.contains('turnover|traveling') & text.str.contains('steal'), kind.str.contains('turnover|traveling|violation'),
         kind.str.contains('timeout'), kind.str.contains('foul'), kind.str.contains('jumpball|jump ball')],
        ['Free throw', 'Made shot', 'Missed shot', 'Offensive rebound', 'Defensive rebound', 'Steal', 'Other turnover',
         'Timeout', 'Foul', 'Jump ball'], default='Other')


def play_context(year):
    """For each shot in the play by play, describe the event recorded just before it."""
    use = ['game_id', 'sequence_number', 'type_text', 'text', 'period_number', 'clock_display_value', 'scoring_play', 'score_value',
           'team_id', 'athlete_id_1', 'shooting_play', 'coordinate_x_raw', 'coordinate_y_raw', 'home_score', 'away_score',
           'home_team_id', 'start_quarter_seconds_remaining']
    plays = pd.read_csv(RAW / f'play_by_play_{year}.csv', usecols=use, low_memory=False)
    plays = plays[~plays.type_text.fillna('').str.contains('Substitution')].sort_values(['game_id', 'sequence_number'])
    plays['group'] = event_group(plays)
    earlier = plays.groupby(['game_id', 'period_number'])[['group', 'team_id', 'start_quarter_seconds_remaining', 'home_score', 'away_score']].shift()
    plays['previous_event'] = earlier.group.fillna('Start of period')
    plays['previous_same_team'] = earlier.team_id.eq(plays.team_id).astype(float).where(earlier.team_id.notna())
    plays['seconds_since_previous'] = (earlier.start_quarter_seconds_remaining - plays.start_quarter_seconds_remaining).clip(0, 40)
    lead = (earlier.home_score - earlier.away_score).fillna(0)
    plays['margin'] = np.where(plays.team_id.eq(plays.home_team_id), lead, -lead)
    shots = plays[plays.shooting_play.eq(True) & ~plays.type_text.fillna('').str.contains('Free Throw')].copy()
    shots['repeat'] = shots.groupby(KEY, dropna=False).cumcount()
    return shots[KEY + ['repeat', 'previous_event', 'previous_same_team', 'seconds_since_previous', 'margin']].assign(season=year)


def sample(shots=None):
    """Add the play context and coded categories to benchmark shots. Category levels always come from the training seasons."""
    if shots is None:
        from shot_models import dataset
        shots, _ = dataset()
    shots['repeat'] = shots.groupby(['season'] + KEY, dropna=False).cumcount()
    context = pd.concat([play_context(year) for year in sorted(shots.season.unique())])
    joined = shots.merge(context, on=['season', 'repeat'] + KEY, how='left', validate='one_to_one')
    joined['matched_play'] = joined.previous_event.notna()
    joined['shot_label'] = joined.type_text.fillna('').str.lower().str.replace(r'[^a-z ]', '', regex=True).str.strip()
    train = joined[joined.split.eq('train')]
    for name in CATEGORIES:
        common = train[name].value_counts()
        levels = common[common.ge(50)].index
        joined[name] = pd.Categorical(joined[name].where(joined[name].isin(levels)), categories=sorted(levels)).codes.astype(float)
        joined.loc[joined[name].lt(0), name] = np.nan
    return joined


def fit_step(data, features):
    """Boosted trees with rounds chosen on 2025. Returns predictions for every scored split."""
    train, pick = data[data.split.eq('train')], data[data.split.eq('validation')]
    model = HistGradientBoostingClassifier(max_depth=3, learning_rate=.05, max_iter=ROUNDS, min_samples_leaf=200, l2_regularization=1.0,
                                           categorical_features=[f in CATEGORIES for f in features], early_stopping=False, random_state=SEED)
    model.fit(train[features], train.made)
    losses = [log_loss(pick.made, p[:, 1]) for p in model.staged_predict_proba(pick[features])]
    best = int(np.argmin(losses))
    scored = data[data.split.ne('train')]
    for i, p in enumerate(model.staged_predict_proba(scored[features])):
        if i == best:
            return model, best + 1, pd.Series(p[:, 1], index=scored.index)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    data = sample()
    match = data.groupby('split').matched_play.mean()
    print('Shots matched to a play by play row:', match.round(4).to_dict(), flush=True)
    train = data[data.split.eq('train')]
    scored = data[data.split.ne('train')][['season', 'game_id', 'source_row', 'split', 'made']].copy()
    scored['League rate'] = train.made.mean()
    features, rows, models = [], [], {}
    for name, added in STEPS:
        features = features + added
        model, rounds, prediction = fit_step(data, features)
        scored[name] = prediction
        models[name] = dict(model=model, rounds=rounds, features=list(features))
        print(name, 'rounds', rounds, flush=True)
    names = ['League rate'] + [name for name, _ in STEPS]
    for split in ('validation', 'test', 'playoffs'):
        part = scored[scored.split.eq(split)]
        y = part.made.to_numpy()
        errors = {name: (part[name] - y) ** 2 for name in names}
        for i, name in enumerate(names):
            row = dict(split=split, step=name, attempts=len(part), games=part.game_id.nunique(), brier=float(errors[name].mean()),
                       log_loss=float(log_loss(y, part[name])), mean_prediction=float(part[name].mean()), observed=float(y.mean()),
                       spread=float(part[name].std()))
            if i >= 1:
                for label, other in [('distance', 'Distance'), ('previous_step', names[i - 1])]:
                    gap = paired_games(part.game_id, errors[name] - errors[other])
                    base = errors[other].mean()
                    row.update({f'drop_vs_{label}_pct': -100 * gap['difference'] / base,
                                f'drop_vs_{label}_low': -100 * gap['upper'] / base, f'drop_vs_{label}_high': -100 * gap['lower'] / base})
            rows.append(row)
    ladder = pd.DataFrame(rows)
    test = scored[scored.split.eq('test')]
    best = names[-1]
    league = float(ladder[(ladder.split.eq('test')) & ladder.step.eq('League rate')].brier.iloc[0])
    distance = float(ladder[(ladder.split.eq('test')) & ladder.step.eq('Distance')].brier.iloc[0])
    full = float(ladder[(ladder.split.eq('test')) & ladder.step.eq(best)].brier.iloc[0])
    noise = float((test[best] * (1 - test[best])).mean())
    ceiling = [dict(target_drop_pct=100 * t, brier_needed=distance * (1 - t),
                    spread_needed=float(np.sqrt(league - distance * (1 - t)))) for t in TARGETS]
    ceiling = pd.DataFrame(ceiling)
    summary = dict(league_brier=league, distance_brier=distance, full_brier=full, full_drop_pct=100 * (1 - full / distance),
                   distance_spread=float(test.Distance.std()), full_spread=float(test[best].std()),
                   error_left_if_full_model_were_exact=noise, share_of_error_that_is_chance=noise / full,
                   matched_play_share=float(match['test']))
    ladder.to_csv(OUT / 'ladder.csv', index=False)
    ceiling.to_csv(OUT / 'what_it_would_take.csv', index=False)
    scored.to_csv(DERIVED / 'why_distance_predictions.csv.gz', index=False)
    joblib.dump(models, DERIVED / 'why_distance_models.joblib')

    shown = ladder[ladder.split.eq('test')]
    lines = ['# Why is distance so hard to beat?', '',
             f"On {int(shown.attempts.iloc[0]):,} shots from the 2026 regular season, a forecast that gives every shot the league make rate has a Brier error of {league:.4f}. "
             f"Using distance alone brings it to {distance:.4f}. Adding court position, the recorded shot type, the period, clock and score, the previous event and the shooter's record so far brings it to {full:.4f}, "
             f"a further drop of {100 * (1 - full / distance):.1f}%.", '',
             f"If the fitted make probabilities were exact, the expected squared error would be {noise:.4f}, "
             f"against the {full:.4f} it actually has. The contribution of unobserved shot difficulty is unknown. "
             f"Distance already spreads them with a standard deviation of {100 * test.Distance.std():.1f} percentage points and everything else widens that to {100 * test[best].std():.1f}.", '',
             '| Added information | Brier error | Drop from distance | 95% interval | Drop from previous step | 95% interval |', '| --- | ---: | ---: | --- | ---: | --- |']
    for row in shown.itertuples():
        if row.step == 'League rate':
            lines.append(f'| League make rate only | {row.brier:.5f} | | | | |')
        elif row.step == 'Distance':
            lines.append(f'| Distance | {row.brier:.5f} | | | {row.drop_vs_previous_step_pct:.2f}% | {row.drop_vs_previous_step_low:.2f}% to {row.drop_vs_previous_step_high:.2f}% |')
        else:
            lines.append(f'| {row.step} | {row.brier:.5f} | {row.drop_vs_distance_pct:.2f}% | {row.drop_vs_distance_low:.2f}% to {row.drop_vs_distance_high:.2f}% | '
                         f'{row.drop_vs_previous_step_pct:.2f}% | {row.drop_vs_previous_step_low:.2f}% to {row.drop_vs_previous_step_high:.2f}% |')
    lines += ['', '## What a larger gain would take', '',
              'For a well calibrated forecast, Brier error equals the error of the league rate minus the variance of the predicted chances. The table gives the spread of predicted chances needed to beat distance by each amount.', '',
              '| Drop from distance | Brier error needed | Spread of predicted chances needed |', '| ---: | ---: | ---: |']
    lines += [f'| {row.target_drop_pct:.0f}% | {row.brier_needed:.4f} | {100 * row.spread_needed:.1f} points |' for row in ceiling.itertuples()]
    lines += ['', '## What this can and cannot say', '',
              'The recorded shot type and the previous event are the closest things in these files to how a shot came about. They help a little. '
              'The files have no defender positions, no passes and no movement, so the gain from tracking data cannot be measured here. '
              'The spread table shows the size of the task: tracking would have to separate shots far more sharply than everything recorded today.', '',
              f"Each step is a boosted tree model with depth 3 and a learning rate of 0.05. The number of rounds is chosen by log loss on the 2025 regular season and the 2026 scores are computed once. "
              f"The previous event and the score come from the ESPN play by play and use only rows recorded before the shot. {100 * match['test']:.1f}% of test shots matched a play by play row. "
              'Unmatched shots keep missing values for those features. Intervals resample whole games.', '',
              '[Scores for every split](ladder.csv) · [Spread needed](what_it_would_take.csv)', '']
    (OUT / 'README.md').write_text('\n'.join(lines), encoding='utf-8', newline='\n')
    write_json(SITE / 'model-ladder.json', dict(manifestSha256=manifest_digest(), summary=summary,
                                                steps=json.loads(shown.to_json(orient='records')),
                                                ceiling=json.loads(ceiling.to_json(orient='records'))))
    print('WHY_DISTANCE', {key: round(value, 5) for key, value in summary.items()}, flush=True)


if __name__ == '__main__':
    main()
