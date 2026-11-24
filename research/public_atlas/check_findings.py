"""Spot check the main shooting and possession findings against raw rows.

Saved predictions are scored again with outcomes read from the raw shot files.
The first shot timing finding is recounted from the raw play by play with a
simpler rule than the possession reconstruction, so the two will be close
without being identical.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / 'research/data/public_wnba'
RAW = CACHE / 'raw'
DERIVED = CACHE / 'derived'
PLAYS = CACHE / 'league_plays'
RESULTS = ROOT / 'research/results/public_atlas'
OUT = RESULTS / 'recount'
SEED = 20261123
DRAWS = 2000
rows = []


def record(finding, published, recomputed, tolerance, note=''):
    ok = abs(recomputed - published) <= tolerance
    rows.append(dict(finding=finding, published=published, recomputed=round(float(recomputed), 6),
                     tolerance=tolerance, agrees=bool(ok), note=note))
    print(('OK   ' if ok else 'DIFF ') + f'{finding}: published {published}, recomputed {recomputed:.6g}', flush=True)


def raw_outcomes(years):
    frames = []
    for year in years:
        raw = pd.read_csv(RAW / f'shots_{year}.csv', usecols=['game_id', 'score_value'], low_memory=False)
        games = pd.read_csv(RAW / f'wnba_schedule_{year}.csv', usecols=['game_id', 'season_type'], low_memory=False)
        raw['source_row'] = raw.index + 2
        frames.append(raw.merge(games, on='game_id', how='left').assign(season=year))
    return pd.concat(frames)


def brier(p, y):
    return float(np.mean((p - y) ** 2))


def game_interval(games, difference, scale=None, strata=None):
    """95% interval from resampling whole games, optionally within strata."""
    data = pd.DataFrame({'game': np.asarray(games), 'd': np.asarray(difference),
                         's': 1.0 if scale is None else np.asarray(scale),
                         'stratum': 0 if strata is None else np.asarray(strata)})
    totals = data.groupby(['stratum', 'game'])[['d', 's']].sum()
    rng = np.random.default_rng(SEED)
    top, bottom = np.zeros(DRAWS), np.zeros(DRAWS)
    for _, part in totals.groupby(level=0):
        picks = rng.integers(0, len(part), size=(DRAWS, len(part)))
        top += part.d.to_numpy()[picks].sum(axis=1)
        bottom += part.s.to_numpy()[picks].sum(axis=1)
    return np.quantile(top / bottom, [.025, .975])


def shot_models():
    predictions = pd.read_csv(DERIVED / 'shot_predictions.csv.gz')
    raw = raw_outcomes((2025, 2026))
    joined = predictions.merge(raw, on=['season', 'source_row'], how='left', validate='one_to_one', suffixes=('', '_raw'))
    assert joined.game_id.eq(joined.game_id_raw).all()
    assert joined.made.eq(joined.score_value.gt(0)).all() and joined.points.eq(joined.score_value).all()
    expected = np.select([joined.season.eq(2025) & joined.season_type.eq(2), joined.season.eq(2026) & joined.season_type.eq(2),
                          joined.season.eq(2026) & joined.season_type.eq(3)], ['validation', 'test', 'playoffs'], default='none')
    assert (expected == joined.split).all(), 'a scored shot sits outside its season split'
    print('Scored shots match raw outcomes and season splits:', len(joined), flush=True)
    saved = pd.read_csv(RESULTS / 'shot_models/make_metrics.csv').set_index(['split', 'model'])
    intervals = pd.read_csv(RESULTS / 'shot_models/paired_game_intervals.csv').set_index(['split', 'model', 'metric'])
    for split in ('test', 'playoffs'):
        a = joined[joined.split.eq(split)]
        record(f'2026 {split} attempts scored', int(saved.loc[(split, 'Distance baseline'), 'attempts']), len(a), 0)
        for model in ('Constant baseline', 'Distance baseline', 'XGBoost context', 'Five model average'):
            record(f'2026 {split} Brier, {model}', round(saved.loc[(split, model), 'brier'], 5), brier(a[model], a.made), 1e-5)
        gain = (a['XGBoost context'] - a.made) ** 2 - (a['Distance baseline'] - a.made) ** 2
        low, high = game_interval(a.game_id, gain)
        stored = intervals.loc[(split, 'XGBoost context', 'Brier')]
        width = stored.upper - stored.lower
        record(f'2026 {split} Brier change from distance, XGBoost context', round(stored.difference, 6), gain.mean(), 1e-6)
        record(f'2026 {split} game interval lower bound', round(stored.lower, 6), low, .1 * width, 'new seed, so Monte Carlo error applies')
        record(f'2026 {split} game interval upper bound', round(stored.upper, 6), high, .1 * width, 'new seed, so Monte Carlo error applies')
    test = joined[joined.split.eq('test')]
    calibration = []
    for model in ('Distance baseline', 'XGBoost context'):
        stored = saved.loc[('test', model)]
        record(f'2026 test mean predicted minus observed make rate, {model}',
               round(stored.iloc[-2] - stored.iloc[-1], 5), test[model].mean() - test.made.mean(), 1e-5)
        bins = pd.qcut(test[model].rank(method='first'), 10, labels=False)
        table = test.groupby(bins).agg(attempts=('made', 'size'), predicted=(model, 'mean'), observed=('made', 'mean'))
        calibration.append(table.assign(model=model, gap=table.predicted - table.observed).reset_index(names='tenth'))
    calibration = pd.concat(calibration)
    calibration.to_csv(OUT / 'calibration_2026_test.csv', index=False)
    print(calibration.round(4).to_string(index=False), flush=True)


def shot_type():
    a = pd.read_csv(DERIVED / 'shot_form_predictions.csv.gz')
    raw = raw_outcomes(sorted(a.season.unique()))
    joined = a.merge(raw, on=['season', 'source_row'], how='left', validate='one_to_one', suffixes=('', '_raw'))
    assert joined.game_id.eq(joined.game_id_raw).all() and joined.made.eq(joined.score_value.gt(0)).all()
    assert joined.scope.eq(joined.season_type.map({2: 'regular', 3: 'playoffs'})).all()
    pooled = pd.read_csv(RESULTS / 'shot_form/pooled.csv').set_index('scope').loc['both']
    record('shot type test attempts, 2016 to 2026', int(pooled.attempts), len(a), 0)
    record('shot type test games', int(pooled.games), a.game_id.nunique(), 0)
    record('shot type first test season', 2016, a.season.min(), 0)
    distance, form = (a.p_distance - a.made) ** 2, (a.p_form - a.made) ** 2
    record('relative Brier reduction from shot type, percent', round(pooled.gain_pct, 4), 100 * (1 - form.sum() / distance.sum()), 1e-4)
    low, high = game_interval(a.game_id, form - distance, distance, a.season.astype(str) + a.scope)
    width = pooled.high_pct - pooled.low_pct
    record('shot type interval lower bound, percent', round(pooled.low_pct, 4), -100 * high, .1 * width, 'new seed')
    record('shot type interval upper bound, percent', round(pooled.high_pct, 4), -100 * low, .1 * width, 'new seed')


def first_shots(year):
    """Count early first shots after steals and opponent baskets with a simple forward scan."""
    use = ['game_id', 'period', 'order_index', 'team_id', 'seconds_remaining', 'event_type', 'description']
    plays = pd.read_csv(PLAYS / f'wnba_play_by_play_{year}.csv.gz', usecols=use, low_memory=False)
    plays = plays[plays.game_id.astype(str).str[2].isin(['2', '4'])].sort_values(['game_id', 'period', 'order_index'])
    steal = plays.description.fillna('').str.contains('STEAL').to_numpy()
    kind = plays.event_type.to_numpy()
    team = plays.team_id.to_numpy()
    clock = plays.seconds_remaining.to_numpy()
    block = (plays.game_id * 100 + plays.period).to_numpy()
    shot = np.isin(kind, ['made_shot', 'missed_shot'])
    live = shot | np.isin(kind, ['turnover', 'free_throw'])
    counts = {'steal': [0, 0], 'basket': [0, 0]}
    for i in np.flatnonzero(steal | (kind == 'made_shot')):
        if not clock[i] >= 12:
            continue
        start = 'steal' if steal[i] else 'basket'
        j = i + 1
        while j < len(kind) and block[j] == block[i] and not live[j]:
            j += 1
        if j == len(kind) or block[j] != block[i]:
            counts[start][0] += 1
            continue
        if start == 'basket' and kind[j] == 'free_throw' and team[j] == team[i]:
            continue
        counts[start][0] += 1
        gained = team[j] == team[i] if start == 'steal' else team[j] != team[i]
        if shot[j] and gained and clock[i] - clock[j] <= 6:
            counts[start][1] += 1
    return counts


def possessions():
    published = pd.read_csv(RESULTS / 'plays/timing/first_shots_by_season.csv')
    eligible = published.groupby('situation').starts.sum()
    early = published[published.bucket.between(0, 6)].groupby('situation').first_shots.sum()
    record('eligible possessions after a steal', 98400, eligible['Steal'], 0, 'saved season table')
    record('first shots within six seconds after a steal', 32209, early['Steal'], 0, 'saved season table')
    record('eligible possessions after an opponent basket', 334784, eligible['Opponent basket'], 0, 'saved season table')
    record('first shots within six seconds after an opponent basket', 2329, early['Opponent basket'], 0, 'saved season table')
    total = {'steal': [0, 0], 'basket': [0, 0]}
    higher = 0
    for year in range(1997, 2027):
        season = first_shots(year)
        for start in total:
            total[start][0] += season[start][0]
            total[start][1] += season[start][1]
        higher += season['steal'][1] / season['steal'][0] > season['basket'][1] / season['basket'][0]
        print(year, season, flush=True)
    note = 'simple scan of every raw game, without the verified possession filters'
    record('raw scan, percent with a shot within six seconds after a steal', 32.7, 100 * total['steal'][1] / total['steal'][0], 2, note)
    record('raw scan, percent with a shot within six seconds after an opponent basket', 0.7, 100 * total['basket'][1] / total['basket'][0], .5, note)
    record('raw scan, steals counted', 98400, total['steal'][0], 9000, note)
    record('raw scan, seasons where the steal rate was higher', 30, higher, 0, note)
    scores = pd.read_csv(DERIVED / 'league_sequence_predictions.csv.gz',
                         usecols=['season', 'scope', 'will_shoot', 'shot0', 'shot1', 'shot10', 'remaining', 'points0', 'points1', 'points10'])
    assert scores.season.isin([2025, 2026]).all(), 'scored decision points must come after the fitting seasons'
    test = scores[scores.season.eq(2026) & scores.scope.eq('regular')]
    record('2026 regular decision points', 56522, len(test), 0)
    for column, stated in [('shot0', 0.216555), ('shot1', 0.216352), ('shot10', 0.216361)]:
        record(f'2026 regular next shot Brier, {column}', stated, brier(test[column], test.will_shoot), 1e-6)
    for column, stated in [('points0', 1.1657), ('points1', 1.1649), ('points10', 1.1648)]:
        record(f'2026 regular points RMSE, {column}', stated, np.sqrt(brier(test[column], test.remaining)), 1e-4)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    shot_models()
    shot_type()
    possessions()
    table = pd.DataFrame(rows)
    table.to_csv(OUT / 'findings_check.csv', index=False)
    (OUT / 'findings_check.json').write_text(json.dumps(dict(checks=len(table), agree=int(table.agrees.sum()), seed=SEED), indent=2) + '\n')
    print(f'FINDINGS_CHECKED {int(table.agrees.sum())} of {len(table)} agree', flush=True)


if __name__ == '__main__':
    main()
