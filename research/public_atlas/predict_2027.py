"""Predictions for the 2027 season, written before it is played.

Each prediction is last season's pooled estimate multiplied by how much such
estimates have carried over to the following season. Every rule is first
tested on past seasons using only what was known before each of them.
"""
import json

import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar

from build import RESULTS, SITE, write_json
from fetch import manifest_digest
from shooters import pool, talent_variance

OUT = RESULTS / 'prediction_2027'
TARGET = 2027
FIRST_TEST = 2019
SEED = 20261124
MEASURES = {'offence_quality': 'Shot quality taken', 'offence_making': 'Shot making', 'defence_quality': 'Shot quality allowed',
            'defence_making': 'Shot making allowed', 'net': 'Net'}
SHOOTER_MINIMUM = 100


def spread_of(values, noise):
    return minimize_scalar(lambda t: float(np.sum(np.log(t + noise) + values ** 2 / (t + noise))), bounds=(0, 100), method='bounded').x


def carry(x, y, weight=None):
    """Slope through the origin: how much of last season's estimate shows up next season."""
    weight = np.ones(len(x)) if weight is None else weight
    return float(np.sum(weight * x * y) / np.sum(weight * x * x))


def team_pairs(table, known_before):
    """Pooled estimate in one season paired with the observed value in the next, pooling with seasons before `known_before` only."""
    past = table[table.season.lt(known_before)]
    frames = []
    for name in MEASURES:
        tau2 = spread_of(past[f'{name}_observed'].to_numpy(), past[f'{name}_noise'].to_numpy())
        weight = tau2 / (tau2 + table[f'{name}_noise'])
        now = table.assign(estimate=weight * table[f'{name}_observed'])[['season', 'team_id', 'team', 'estimate']]
        later = table.assign(season=table.season - 1)[['season', 'team_id', f'{name}_observed']].rename(columns={f'{name}_observed': 'next'})
        frames.append(now.merge(later, on=['season', 'team_id'], how='left').assign(measure=name))
    return pd.concat(frames, ignore_index=True)


def score(rows, weight=None):
    """Root mean squared error of the carry over rule and two simple alternatives, with a paired interval against the league average."""
    weight = np.ones(len(rows)) if weight is None else weight
    errors = {name: (rows[name] - rows.actual) ** 2 for name in ('league', 'same', 'carried')}
    rng = np.random.default_rng(SEED)
    picks = rng.integers(0, len(rows), size=(2000, len(rows)))
    gap = (errors['carried'] - errors['league']).to_numpy() * weight
    draws = gap[picks].sum(axis=1) / weight[picks].sum(axis=1)
    result = {f'rmse_{name}': float(np.sqrt(np.average(error, weights=weight))) for name, error in errors.items()}
    result.update(predictions=len(rows), squared_error_change_low=float(np.quantile(draws, .025)), squared_error_change_high=float(np.quantile(draws, .975)))
    return result


def teams():
    table = pd.read_csv(RESULTS / 'teams/team_seasons.csv')
    table['net_observed'] = table.offence_quality_observed + table.offence_making_observed - table.defence_quality_observed - table.defence_making_observed
    table['net_noise'] = table[[f'{name}_noise' for name in list(MEASURES)[:4]]].sum(axis=1)
    tests = []
    for year in range(FIRST_TEST, TARGET):
        pairs = team_pairs(table, year)
        for name, part in pairs.groupby('measure'):
            train = part[part.season.lt(year - 1) & part.next.notna()]
            test = part[part.season.eq(year - 1) & part.next.notna()]
            slope = carry(train.estimate.to_numpy(), train.next.to_numpy())
            tests.append(pd.DataFrame({'measure': name, 'season': year, 'team': test.team, 'actual': test.next, 'league': 0.0,
                                       'same': test.estimate, 'carried': slope * test.estimate}))
    tests = pd.concat(tests, ignore_index=True)
    backtest = pd.DataFrame([dict(measure=name, label=MEASURES[name], **score(part)) for name, part in tests.groupby('measure', sort=False)])
    pairs = team_pairs(table, TARGET)
    rows = []
    for name, part in pairs.groupby('measure', sort=False):
        train = part[part.next.notna()]
        slope = carry(train.estimate.to_numpy(), train.next.to_numpy())
        error = float(backtest.loc[backtest.measure.eq(name), 'rmse_carried'].iloc[0])
        last = part[part.season.eq(TARGET - 1)]
        rows.append(pd.DataFrame({'measure': name, 'team_id': last.team_id, 'team': last.team, 'estimate_2026': last.estimate, 'carry_over': slope,
                                  'prediction': slope * last.estimate, 'low': slope * last.estimate - 1.96 * error, 'high': slope * last.estimate + 1.96 * error}))
    return pd.concat(rows, ignore_index=True), backtest, tests


def shooters():
    seasons = pd.read_csv(RESULTS / 'shooters/player_seasons.csv')
    noise = lambda frame: frame.chance_variance / frame.attempts ** 2
    excess = lambda frame: (frame.makes - frame.expected) / frame.attempts

    def pairs(known_before):
        past = seasons[seasons.season.lt(known_before)]
        now = pool(seasons, talent_variance(excess(past).to_numpy(), noise(past).to_numpy()))
        later = seasons.assign(season=seasons.season - 1)[['season', 'player_id', 'raw_per_100', 'attempts', 'chance_variance']]
        later = later.rename(columns={'raw_per_100': 'next', 'attempts': 'next_attempts', 'chance_variance': 'next_variance'})
        return now[['season', 'player_id', 'name', 'team_id', 'attempts', 'chance_variance', 'per_100']].merge(later, on=['season', 'player_id'], how='left')

    tests = []
    for year in range(FIRST_TEST, TARGET):
        part = pairs(year)
        train = part[part.season.lt(year - 1) & part.next.notna()]
        test = part[part.season.eq(year - 1) & part.next.notna()]
        slope = carry(train.per_100.to_numpy(), train.next.to_numpy(), train.next_attempts.to_numpy())
        tests.append(pd.DataFrame({'season': year, 'name': test.name, 'actual': test.next, 'league': 0.0, 'same': test.per_100, 'carried': slope * test.per_100,
                                   'weight': test.next_attempts, 'chance': 1e4 * test.next_variance / test.next_attempts ** 2}))
    tests = pd.concat(tests, ignore_index=True)
    backtest = dict(measure='shooter', label='Shooter makes above expected', **score(tests, tests.weight.to_numpy()))
    skill_left = max(float(np.average((tests.carried - tests.actual) ** 2 - tests.chance, weights=tests.weight)), 0.0)
    part = pairs(TARGET)
    train = part[part.next.notna()]
    slope = carry(train.per_100.to_numpy(), train.next.to_numpy(), train.next_attempts.to_numpy())
    last = part[part.season.eq(TARGET - 1) & part.attempts.ge(SHOOTER_MINIMUM)].copy()
    last['prediction'] = slope * last.per_100
    chance = 1e4 * last.chance_variance / last.attempts ** 2
    last['low'] = last.prediction - 1.96 * np.sqrt(skill_left + chance)
    last['high'] = last.prediction + 1.96 * np.sqrt(skill_left + chance)
    last['carry_over'] = slope
    keep = ['player_id', 'name', 'team_id', 'attempts', 'per_100', 'carry_over', 'prediction', 'low', 'high']
    return last[keep].rename(columns={'attempts': 'attempts_2026', 'per_100': 'estimate_2026'}).sort_values('prediction', ascending=False), backtest


def league():
    series = pd.read_csv(RESULTS / 'shot_mix/by_season.csv')
    rows = []
    for column, label, scale in [('share Three point area', 'Share of shots from the three point area', 100), ('actual', 'Field goal points per shot', 1)]:
        values = (scale * series.set_index('season')[column])
        errors = {'last': [], 'trend': []}
        guess = {}
        for year in range(2017, TARGET + 1):
            window = values.loc[year - 5:year - 1]
            fit = np.polyfit(window.index, window.to_numpy(), 1)
            guess = {'last': float(window.iloc[-1]), 'trend': float(np.polyval(fit, year))}
            if year < TARGET:
                for name in errors:
                    errors[name].append(guess[name] - values.loc[year])
        rmse = {name: float(np.sqrt(np.mean(np.square(e)))) for name, e in errors.items()}
        rule = min(rmse, key=rmse.get)
        rows.append(dict(measure=label, value_2026=float(values.loc[TARGET - 1]), rule='Five season trend' if rule == 'trend' else 'Same as last season',
                         prediction=guess[rule], low=guess[rule] - 1.96 * rmse[rule], high=guess[rule] + 1.96 * rmse[rule],
                         rmse_trend=rmse['trend'], rmse_same_as_last=rmse['last'], seasons_tested=len(errors['last'])))
    return pd.DataFrame(rows)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    team_table, team_tests, team_rows = teams()
    shooter_table, shooter_test = shooters()
    league_table = league()
    backtest = pd.concat([team_tests, pd.DataFrame([shooter_test])], ignore_index=True)
    team_table.to_csv(OUT / 'teams.csv', index=False)
    shooter_table.to_csv(OUT / 'shooters.csv', index=False)
    league_table.to_csv(OUT / 'league.csv', index=False)
    backtest.to_csv(OUT / 'backtest.csv', index=False)
    team_rows.to_csv(OUT / 'team_backtest_rows.csv', index=False)

    net = team_table[team_table.measure.eq('net')].sort_values('prediction', ascending=False)
    lines = ['# Predictions for 2027', '', 'Written on 24 November 2026, before any 2027 game. They will be scored once against the 2027 season under the rules in the prospective test plan.', '',
             '## League', '', '| Measure | 2026 | Predicted 2027 | 95% range | Rule |', '| --- | ---: | ---: | --- | --- |']
    lines += [f'| {r.measure} | {r.value_2026:.2f} | {r.prediction:.2f} | {r.low:.2f} to {r.high:.2f} | {r.rule} |' for r in league_table.itertuples()]
    lines += ['', '## Teams', '', 'Net is points per 100 shots against the league from field goals, adding shot quality and shot making on offence and subtracting what is allowed on defence.', '',
              '| Team | 2026 estimate | Predicted 2027 | 95% range |', '| --- | ---: | ---: | --- |']
    lines += [f'| {r.team} | {r.estimate_2026:+.1f} | {r.prediction:+.1f} | {r.low:+.1f} to {r.high:+.1f} |' for r in net.itertuples()]
    lines += ['', '## Shooters', '', f'Makes per 100 shots above the league expectation, for players with at least {SHOOTER_MINIMUM} eligible attempts in 2026. The range is for a season with the same number of attempts.', '',
              '| Player | 2026 estimate | Predicted 2027 | 95% range |', '| --- | ---: | ---: | --- |']
    lines += [f'| {r.name} | {r.estimate_2026:+.1f} | {r.prediction:+.1f} | {r.low:+.1f} to {r.high:+.1f} |' for r in shooter_table.head(10).itertuples()]
    lines += ['', '## How well the rule worked on past seasons', '',
              f'Each season from {FIRST_TEST} to 2026 was predicted from the season before, using only earlier seasons to set the pooling and the carry over. Error is the root mean squared error against what was then observed.', '',
              '| Measure | Predictions | League average | Same as last season | Carry over rule |', '| --- | ---: | ---: | ---: | ---: |']
    lines += [f'| {r.label} | {r.predictions:,} | {r.rmse_league:.2f} | {r.rmse_same:.2f} | {r.rmse_carried:.2f} |' for r in backtest.itertuples()]
    lines += ['', '## Method and limits', '',
              'A team or player prediction is the pooled 2026 estimate times a carry over factor. The factor is the slope, through zero, of the next season on the pooled estimate across all earlier pairs of seasons. '
              'Team ranges are 1.96 times the past error of the rule. Shooter ranges add the chance in a season of the same length. League values use whichever of two simple rules had the lower past error: the last value, or a straight line through the last five seasons.', '',
              'The rule knows nothing about trades, injuries, coaching changes, the draft or new teams. A team that changes its roster can move well outside its range. Players and teams with no 2026 record have no prediction.', '',
              '[Teams](teams.csv) · [Shooters](shooters.csv) · [League](league.csv) · [Past error](backtest.csv) · [Each past team prediction](team_backtest_rows.csv)', '']
    (OUT / 'README.md').write_text('\n'.join(lines), encoding='utf-8', newline='\n')

    def team_record(team_id, part):
        row = dict(id=int(team_id), name=part.team.iloc[0])
        for r in part.itertuples():
            row[r.measure] = dict(last=round(float(r.estimate_2026), 2), prediction=round(float(r.prediction), 2), low=round(float(r.low), 2), high=round(float(r.high), 2))
        return row
    site = dict(manifestSha256=manifest_digest(), season=TARGET, written='24 November 2026', measures=MEASURES,
                league=json.loads(league_table.to_json(orient='records')), backtest=json.loads(backtest.to_json(orient='records')),
                teams=sorted([team_record(team, part) for team, part in team_table.groupby('team_id')], key=lambda row: -row['net']['prediction']),
                shooters=[dict(id=int(r.player_id), name=r.name, team=int(r.team_id), attempts=int(r.attempts_2026), last=round(float(r.estimate_2026), 2),
                               estimate=round(float(r.prediction), 2), low=round(float(r.low), 2), high=round(float(r.high), 2)) for r in shooter_table.itertuples()])
    write_json(SITE / 'prediction-2027.json', site)
    print(backtest[['label', 'predictions', 'rmse_league', 'rmse_same', 'rmse_carried']].round(3).to_string(index=False), flush=True)
    print(league_table[['measure', 'value_2026', 'prediction', 'low', 'high', 'rule']].round(3).to_string(index=False), flush=True)
    print('PREDICTIONS_WRITTEN', len(net), 'teams', len(shooter_table), 'shooters', flush=True)


if __name__ == '__main__':
    main()
