"""Predictions for the 2027 season, written before it is played.

Teams and shooters are predicted with a Bayesian season model. Each one has a
true level that drifts from season to season. A normal belief about that level
is updated on every past season and carried forward to 2027. A simpler rule,
last season's pooled estimate times a carry over factor, is kept for
comparison. Every rule is tested on past seasons using only what was known
before each of them.
"""
import json

import numpy as np
import pandas as pd
from scipy.optimize import minimize, minimize_scalar

from build import RESULTS, SITE, write_json
from fetch import manifest_digest

OUT = RESULTS / 'prediction_2027'
TARGET = 2027
FIRST_TEST = 2019
SEED = 20261124
MEASURES = {'offence_quality': 'Shot quality taken', 'offence_making': 'Shot making', 'defence_quality': 'Shot quality allowed',
            'defence_making': 'Shot making allowed', 'net': 'Net'}
SHOOTER_MINIMUM = 100
RULES = ('league', 'same', 'carried', 'bayes')


def spread_of(values, noise):
    return minimize_scalar(lambda t: float(np.sum(np.log(t + noise) + values ** 2 / (t + noise))), bounds=(0, 400), method='bounded').x


def walk(seasons, values, noise, rho, tau2, until):
    """Update a normal belief about one level through its seasons, then carry it forward to the season `until`."""
    mean, var, loglik, last = 0.0, tau2, 0.0, None
    for season, value, v in zip(seasons, values, noise):
        if last is not None:
            keep = rho ** (2 * (season - last))
            mean, var = rho ** (season - last) * mean, keep * var + (1 - keep) * tau2
        total = var + v
        loglik -= .5 * (np.log(total) + (value - mean) ** 2 / total)
        gain = var / total
        mean, var, last = mean + gain * (value - mean), (1 - gain) * var, season
    keep = rho ** (2 * (until - last))
    return rho ** (until - last) * mean, keep * var + (1 - keep) * tau2, loglik


def season_model(history, until):
    """Fit how far levels spread and how strongly they persist, then forecast every entity for the season `until`."""
    groups = [(key, part.season.to_numpy(), part.observed.to_numpy(), part.noise.to_numpy())
              for key, part in history.sort_values('season').groupby('entity')]

    def loss(params):
        rho, tau2 = 1 / (1 + np.exp(-params[0])), np.exp(params[1])
        return -sum(walk(seasons, values, noise, rho, tau2, until)[2] for _, seasons, values, noise in groups)

    start = [1.0, np.log(max(history.observed.var() - history.noise.mean(), 1e-3))]
    best = minimize(loss, start, method='Nelder-Mead', options={'xatol': 1e-4, 'fatol': 1e-6, 'maxiter': 400})
    rho, tau2 = 1 / (1 + np.exp(-best.x[0])), np.exp(best.x[1])
    forecast = {key: walk(seasons, values, noise, rho, tau2, until)[:2] for key, seasons, values, noise in groups}
    return forecast, float(rho), float(tau2)


def carry(x, y, weight):
    return float(np.sum(weight * x * y) / np.sum(weight * x * x))


def predict(history, until, minimum_weight=0):
    """All four rules for the season `until`, for entities that played the season before it."""
    past = history[history.season.lt(until)]
    forecast, rho, tau2 = season_model(past, until)
    spread = spread_of(past.observed.to_numpy(), past.noise.to_numpy())
    pooled = past.assign(pooled=spread / (spread + past.noise) * past.observed)
    later = past.assign(season=past.season - 1)[['entity', 'season', 'observed', 'weight']].rename(columns={'observed': 'next', 'weight': 'next_weight'})
    pairs = pooled.merge(later, on=['entity', 'season'])
    slope = carry(pairs.pooled.to_numpy(), pairs.next.to_numpy(), pairs.next_weight.to_numpy())
    last = pooled[pooled.season.eq(until - 1) & pooled.weight.ge(minimum_weight)].copy()
    last['league'], last['same'], last['carried'] = 0.0, last.pooled, slope * last.pooled
    last['bayes'] = [forecast[key][0] for key in last.entity]
    last['bayes_variance'] = [forecast[key][1] for key in last.entity]
    return last, dict(persistence=rho, spread=float(np.sqrt(tau2)), carry_over=slope)


def backtest(history, label, minimum_weight=0):
    """Predict each past season from earlier ones and compare the rules with what was then observed."""
    rows = []
    for year in range(FIRST_TEST, TARGET):
        guess, _ = predict(history, year, minimum_weight)
        actual = history[history.season.eq(year)][['entity', 'observed', 'noise', 'weight']].rename(columns={'observed': 'actual', 'noise': 'actual_noise', 'weight': 'actual_weight'})
        rows.append(guess.merge(actual, on='entity').assign(target=year))
    rows = pd.concat(rows, ignore_index=True)
    weight = rows.actual_weight.to_numpy()
    errors = {rule: (rows[rule] - rows.actual) ** 2 for rule in RULES}
    rng = np.random.default_rng(SEED)
    picks = rng.integers(0, len(rows), size=(2000, len(rows)))
    gap = (errors['bayes'] - errors['carried']).to_numpy() * weight
    draws = gap[picks].sum(axis=1) / weight[picks].sum(axis=1)
    inside = (rows.bayes - rows.actual).abs().le(1.96 * np.sqrt(rows.bayes_variance + rows.noise))
    result = dict(label=label, predictions=len(rows), **{f'rmse_{rule}': float(np.sqrt(np.average(errors[rule], weights=weight))) for rule in RULES},
                  bayes_minus_carried_low=float(np.quantile(draws, .025)), bayes_minus_carried_high=float(np.quantile(draws, .975)),
                  inside_95=float(np.average(inside, weights=weight)))
    return result, rows


def team_history(table, name):
    return pd.DataFrame({'entity': table.team_id, 'label': table.team, 'season': table.season, 'observed': table[f'{name}_observed'],
                         'noise': table[f'{name}_noise'], 'weight': 1.0})


def teams():
    table = pd.read_csv(RESULTS / 'teams/team_seasons.csv')
    table['net_observed'] = table.offence_quality_observed + table.offence_making_observed - table.defence_quality_observed - table.defence_making_observed
    table['net_noise'] = table[[f'{name}_noise' for name in list(MEASURES)[:4]]].sum(axis=1)
    predictions, tests, settings, past = [], [], [], []
    for name, label in MEASURES.items():
        history = team_history(table, name)
        result, rows = backtest(history, label)
        guess, fitted = predict(history, TARGET)
        spread = np.sqrt(guess.bayes_variance + guess.noise)
        predictions.append(pd.DataFrame({'measure': name, 'team_id': guess.entity, 'team': guess.label, 'estimate_2026': guess.pooled, 'rule_prediction': guess.carried,
                                         'prediction': guess.bayes, 'low': guess.bayes - 1.96 * spread, 'high': guess.bayes + 1.96 * spread,
                                         'belief_variance': guess.bayes_variance, 'season_noise': guess.noise}))
        tests.append(dict(measure=name, **result))
        settings.append(dict(measure=name, label=label, **fitted))
        past.append(rows.assign(measure=name))
    return pd.concat(predictions, ignore_index=True), pd.DataFrame(tests), pd.DataFrame(settings), pd.concat(past, ignore_index=True)


def shooters():
    seasons = pd.read_csv(RESULTS / 'shooters/player_seasons.csv')
    history = pd.DataFrame({'entity': seasons.player_id, 'label': seasons.name, 'team_id': seasons.team_id, 'season': seasons.season, 'attempts': seasons.attempts,
                            'observed': seasons.raw_per_100, 'noise': 1e4 * seasons.chance_variance / seasons.attempts ** 2, 'weight': seasons.attempts.astype(float)})
    result, _ = backtest(history, 'Shooter makes above expected', SHOOTER_MINIMUM)
    guess, fitted = predict(history, TARGET, SHOOTER_MINIMUM)
    spread = np.sqrt(guess.bayes_variance + guess.noise)
    table = pd.DataFrame({'player_id': guess.entity, 'name': guess.label, 'team_id': guess.team_id, 'attempts_2026': guess.attempts, 'estimate_2026': guess.pooled,
                          'rule_prediction': guess.carried, 'prediction': guess.bayes, 'low': guess.bayes - 1.96 * spread, 'high': guess.bayes + 1.96 * spread,
                          'belief_variance': guess.bayes_variance, 'season_noise': guess.noise})
    return table.sort_values('prediction', ascending=False), dict(measure='shooter', **result), dict(measure='shooter', label='Shooter makes above expected', **fitted)


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
    team_table, team_tests, team_settings, team_rows = teams()
    shooter_table, shooter_test, shooter_setting = shooters()
    league_table = league()
    tests = pd.concat([team_tests, pd.DataFrame([shooter_test])], ignore_index=True)
    settings = pd.concat([team_settings, pd.DataFrame([shooter_setting])], ignore_index=True)
    team_table.to_csv(OUT / 'teams.csv', index=False)
    shooter_table.to_csv(OUT / 'shooters.csv', index=False)
    league_table.to_csv(OUT / 'league.csv', index=False)
    tests.to_csv(OUT / 'backtest.csv', index=False)
    settings.to_csv(OUT / 'season_model.csv', index=False)
    team_rows[['measure', 'target', 'label', *RULES, 'bayes_variance', 'noise', 'actual', 'actual_noise']].to_csv(OUT / 'team_backtest_rows.csv', index=False)

    net = team_table[team_table.measure.eq('net')].sort_values('prediction', ascending=False)
    wins = int((tests.rmse_bayes <= tests.rmse_carried).sum())
    lines = ['# Predictions for 2027', '', 'Written on 24 November 2026, before any 2027 game. They will be scored once against the 2027 season under the rules in the prospective test plan.', '',
             f'Teams and shooters are predicted with a Bayesian season model. On past seasons it had lower error than the simple carry over rule for {wins} of {len(tests)} measures.', '',
             '## League', '', '| Measure | 2026 | Predicted 2027 | 95% range | Rule |', '| --- | ---: | ---: | --- | --- |']
    lines += [f'| {r.measure} | {r.value_2026:.2f} | {r.prediction:.2f} | {r.low:.2f} to {r.high:.2f} | {r.rule} |' for r in league_table.itertuples()]
    lines += ['', '## Teams', '', 'Net is points per 100 shots against the league from field goals, adding shot quality and shot making on offence and subtracting what is allowed on defence.', '',
              '| Team | 2026 estimate | Predicted 2027 | 95% range |', '| --- | ---: | ---: | --- |']
    lines += [f'| {r.team} | {r.estimate_2026:+.1f} | {r.prediction:+.1f} | {r.low:+.1f} to {r.high:+.1f} |' for r in net.itertuples()]
    lines += ['', '## Shooters', '', f'Makes per 100 shots above the league expectation, for players with at least {SHOOTER_MINIMUM} eligible attempts in 2026. The range is for a season with the same number of attempts.', '',
              '| Player | 2026 estimate | Predicted 2027 | 95% range |', '| --- | ---: | ---: | --- |']
    lines += [f'| {r.name} | {r.estimate_2026:+.1f} | {r.prediction:+.1f} | {r.low:+.1f} to {r.high:+.1f} |' for r in shooter_table.head(10).itertuples()]
    lines += ['', '## How the rules did on past seasons', '',
              f'Each season from {FIRST_TEST} to 2026 was predicted using only earlier seasons. Error is the root mean squared error against what was then observed. The last column is coverage using prior-season noise. Shooter forecasts require 100 attempts in the preceding season and are weighted by target-season attempts.', '',
              '| Measure | Predictions | League average | Same as last season | Carry over rule | Bayesian season model | Inside 95% range |', '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    lines += [f'| {r.label} | {r.predictions:,} | {r.rmse_league:.2f} | {r.rmse_same:.2f} | {r.rmse_carried:.2f} | {r.rmse_bayes:.2f} | {100 * r.inside_95:.0f}% |' for r in tests.itertuples()]
    lines += ['', '## The Bayesian season model', '',
              'Each team or shooter has a true level in each season, measured against the league. Levels across the league are normal with a common spread. From one season to the next a level keeps a fraction of itself, the persistence, and the rest is replaced by new variation, so the spread stays the same. '
              'An observed season equals the true level plus noise of known size: game to game noise for teams and the chance in each shot for shooters.', '',
              'Starting from the league wide prior, the belief about a level is updated on each observed season in turn and then carried forward to 2027. This uses every past season, with older seasons counting less. '
              'The spread and the persistence are set by maximum likelihood on all past seasons. The 95% range is for the value that will be observed in 2027, so it adds the noise of a season of the same length.', '',
              '| Measure | Persistence from one season to the next | Spread of true levels |', '| --- | ---: | ---: |']
    lines += [f'| {r.label} | {r.persistence:.2f} | {r.spread:.2f} |' for r in settings.itertuples()]
    lines += ['', 'The carry over rule multiplies the pooled 2026 estimate by the slope of the next season on the pooled estimate across earlier pairs of seasons. League values use whichever of two simple rules had the lower past error.', '',
              'No rule here knows about trades, injuries, coaching changes, the draft or new teams. A team that changes its roster can move well outside its range. Players and teams with no 2026 record have no prediction.', '',
              '[Teams](teams.csv) · [Shooters](shooters.csv) · [League](league.csv) · [Past error](backtest.csv) · [Model settings](season_model.csv) · [Each past team prediction](team_backtest_rows.csv) · [Bayesian court surface](SURFACE.md)', '']
    (OUT / 'README.md').write_text('\n'.join(lines), encoding='utf-8', newline='\n')

    def team_record(team_id, part):
        row = dict(id=int(team_id), name=part.team.iloc[0])
        for r in part.itertuples():
            row[r.measure] = dict(last=round(float(r.estimate_2026), 2), prediction=round(float(r.prediction), 2), low=round(float(r.low), 2), high=round(float(r.high), 2))
        return row
    site = dict(manifestSha256=manifest_digest(), season=TARGET, written='24 November 2026', measures=MEASURES,
                league=json.loads(league_table.to_json(orient='records')), backtest=json.loads(tests.to_json(orient='records')),
                seasonModel=json.loads(settings.to_json(orient='records')),
                teams=sorted([team_record(team, part) for team, part in team_table.groupby('team_id')], key=lambda row: -row['net']['prediction']),
                shooters=[dict(id=int(r.player_id), name=r.name, team=int(r.team_id), attempts=int(r.attempts_2026), last=round(float(r.estimate_2026), 2),
                               estimate=round(float(r.prediction), 2), low=round(float(r.low), 2), high=round(float(r.high), 2)) for r in shooter_table.itertuples()])
    write_json(SITE / 'prediction-2027.json', site)
    print(tests[['label', 'predictions', 'rmse_league', 'rmse_same', 'rmse_carried', 'rmse_bayes', 'inside_95']].round(3).to_string(index=False), flush=True)
    print(settings.round(3).to_string(index=False), flush=True)
    print('PREDICTIONS_WRITTEN', len(net), 'teams', len(shooter_table), 'shooters', flush=True)


if __name__ == '__main__':
    main()
