"""Recount first shots directly from the pinned event clock, bypassing the saved shot table."""
import json

import numpy as np
import pandas as pd

from build import SITE, write_json
from fetch import YEARS, digest, manifest_digest
from league_turns import INPUT, OUT
from play_sources import DIRECTORY, MANIFEST, main as check_pins
from shot_timing import FOCUS, WINDOW, DEST, STARTS, FIT_END, PRIOR, game_intervals


def recount(year):
    keys = ['game_id', 'period', 'turn']
    turns = pd.read_csv(INPUT / f'turns_{year}.csv.gz', usecols=keys + ['end_order', 'team', 'scope'])
    assert not turns.duplicated(keys).any()
    starts = pd.read_csv(INPUT / f'states_{year}.csv.gz', usecols=keys + ['order', 'history_length', 'situation'])
    starts = starts[starts.history_length.eq(1)].merge(turns, on=keys, validate='one_to_one')
    assert len(starts) == len(turns)
    cols = ['game_id', 'period', 'order_index', 'seconds_remaining', 'team_id', 'action_type',
            'description', 'is_field_goal', 'shot_result', 'shot_value']
    raw = pd.read_csv(DIRECTORY / f'wnba_play_by_play_{year}.csv.gz', usecols=cols, low_memory=False)
    raw = raw[raw.game_id.isin(turns.game_id)]
    at = raw.rename(columns={'order_index': 'order'})
    src = starts.merge(at, on=['game_id', 'period', 'order'], validate='one_to_one')
    assert len(src) == len(turns)
    # Identify the source event independently, including separately credited steals.
    action = src.action_type.fillna('').str.lower()
    stole = src.description.fillna('').str.contains(r'\bsteal\b', case=False, regex=True)
    origin = np.select([stole & action.isin(['turnover', '']), action.eq('turnover'), action.eq('rebound'),
                        src.is_field_goal.eq(1) & src.shot_result.eq('Made'), action.eq('free throw')],
                       ['Steal', 'Opponent turnover', 'Defensive rebound', 'Opponent basket', 'Opponent free throw'],
                       default='unsupported')
    assert np.array_equal(origin, src.situation), (year, src.loc[origin != src.situation, ['situation', 'action_type', 'description']].head())
    # Look forward in the original play file for the first shot by this team.
    # A later shot in a different possession cannot fall inside the recorded end order.
    shots = raw.loc[raw.is_field_goal.eq(1) & raw.shot_result.isin(['Made', 'Missed'])].copy()
    shots['team'] = shots.team_id.astype('int64')
    shots['reward'] = shots.shot_value.where(shots.shot_result.eq('Made'), 0).astype(int)
    shots = shots.rename(columns={'order_index': 'shot_order', 'seconds_remaining': 'shot_clock'})
    who = ['game_id', 'period', 'team']
    joined = pd.merge_asof(src.sort_values('order'), shots[who + ['shot_order', 'shot_clock', 'reward']].sort_values('shot_order'),
                           left_on='order', right_on='shot_order', by=who, allow_exact_matches=False, direction='forward')
    eligible = joined.seconds_remaining.ge(WINDOW)
    cov = joined.assign(eligible=eligible).groupby(['scope', 'situation']).eligible.agg(complete='size', eligible='sum')
    valid = joined[eligible].copy()
    has = valid.shot_order.le(valid.end_order)
    delay = (valid.seconds_remaining - valid.shot_clock).where(has)
    assert delay[has].ge(0).all()
    # Count thresholds directly; the number missed before a shot is its integer bucket.
    buckets = np.zeros(len(valid), dtype=int)
    for t in range(WINDOW + 1):
        buckets += delay.gt(t).to_numpy(dtype=int)
    valid['bucket'] = np.where(has, buckets, -1)
    valid['first_points'] = valid.reward.where(has, 0).astype(int)
    valid['first_makes'] = valid.first_points.gt(0).astype(int)
    valid['first_shots'] = has.astype(int)
    counts = valid.groupby(['scope', 'situation', 'bucket']).agg(
        starts=('turn', 'size'), first_shots=('first_shots', 'sum'), first_makes=('first_makes', 'sum'),
        first_points=('first_points', 'sum'))
    early = has & delay.le(FOCUS)
    games = valid.assign(quick=early, points=valid.first_points.where(early, 0)).groupby(
        ['scope', 'game_id', 'situation']).agg(starts=('turn', 'size'), quick=('quick', 'sum'), points=('points', 'sum'))
    return [v.reset_index().assign(season=year) for v in (cov, counts, games)]


def verify_csv(name, expected, keys):
    actual = pd.read_csv(DEST/name).set_index(keys).sort_index()
    expected = expected.set_index(keys).sort_index()[actual.columns]
    pd.testing.assert_frame_equal(actual, expected, check_dtype=False)


def validate_forecasts(games, scores):
    train = games[games.season <= FIT_END].groupby('situation')[['quick', 'starts']].sum()
    prior_rate = train.quick.sum()/train.starts.sum()
    p = (train.quick + PRIOR*prior_rate) / (train.starts + PRIOR)
    assert set((s['season'], s['scope']) for s in scores) == {(y, ph) for y in (2025, 2026) for ph in ('regular', 'playoffs')}
    for score in scores:
        test = games[(games.season == score['season']) & (games.scope == score['scope'])].copy()
        assert set(test.game_id).isdisjoint(games.loc[games.season <= FIT_END, 'game_id'])
        assert test.starts.sum() == score['starts'] and test.game_id.nunique() == score['games']
        for key, prob in [('baseline', prior_rate), ('model', test.situation.map(p))]:
            # For a binary outcome, squared loss sums to n*p^2 + successes*(1-2p).
            test[key] = test.starts*prob**2 + test.quick*(1-2*prob)
            np.testing.assert_allclose(test[key].sum()/test.starts.sum(), score[key], atol=1e-12)
        tot = test.groupby('game_id')[['model', 'baseline', 'starts']].sum()
        n = len(tot)
        rng = np.random.default_rng(20261122)
        weights = rng.multinomial(n, np.full(n, 1/n), size=2000)
        diffs = tot.model - tot.baseline
        boot = (weights @ diffs) / (weights @ tot.starts)
        np.testing.assert_allclose([score['difference'], score['low'], score['high']],
                                   [diffs.sum()/tot.starts.sum(), *np.quantile(boot, [.025, .975])], atol=1e-12)
    exported = pd.read_csv(DEST/'forecast_scores.csv')
    pd.testing.assert_frame_equal(exported, pd.DataFrame(scores), check_exact=False, atol=1e-12)


def main():
    check_pins()
    data = json.loads((SITE/'shot-timing.json').read_bytes())
    assert data['manifestSha256'] == manifest_digest()
    assert data['playManifestSha256'] == digest(MANIFEST.read_text(encoding='utf-8').encode())
    assert (data['maxSeconds'], data['mainSeconds'], data['fitEnd'], data['prior']) == (12, 6, 2024, 40)
    frames = [recount(y) for y in YEARS]
    coverage, bins, games = [pd.concat(parts, ignore_index=True) for parts in zip(*frames)]
    verify_csv('coverage_by_season.csv', coverage, ['season', 'scope', 'situation'])
    verify_csv('first_shots_by_season.csv', bins, ['season', 'scope', 'situation', 'bucket'])
    gaps = game_intervals(games)
    for phase, block in data['scopes'].items():
        g = games if phase == 'both' else games[games.scope == phase]
        c = coverage if phase == 'both' else coverage[coverage.scope == phase]
        b = bins if phase == 'both' else bins[bins.scope == phase]
        assert (g.game_id.nunique(), c.complete.sum(), c.eligible.sum(), g.starts.sum()) == (
            block['games'], block['complete'], block['eligible'], block['eligible'])
        for name in STARTS:
            group = block['groups'][name]
            subset = b[b.situation == name]
            assert group['starts'] == subset.starts.sum()
            for t in range(WINDOW + 1):
                selected = subset[subset.bucket.between(0, t)]
                assert (group['shots'][t], group['makes'][t], group['points'][t]) == (
                    selected.first_shots.sum(), selected.first_makes.sum(), selected.first_points.sum())
        by_year = g.groupby(['season', 'situation'])[['starts', 'quick']].sum()
        rates = (by_year.quick/by_year.starts).unstack().dropna(subset=list(STARTS[:2]))
        assert (block['seasonsHigher'], block['seasonsCompared']) == (sum(rates['Steal'] > rates['Opponent basket']), len(rates))
        a, b = [block['groups'][s] for s in STARTS[:2]]
        for key in ('shots', 'points'):
            exact = 100*(a[key][FOCUS]/a['starts'] - b[key][FOCUS]/b['starts'])
            gap = block['sixSecondGap'][key]
            np.testing.assert_allclose(exact, gap['gap'], atol=1e-12)
            np.testing.assert_allclose([gap[k] for k in ('gap','low','high')],
                                       [gaps[phase][key][k] for k in ('gap','low','high')], atol=1e-12)
    validate_forecasts(games, data['forecasts'])
    verification = dict(seasons=len(YEARS), games=int(games.game_id.nunique()), completeStarts=int(coverage.complete.sum()),
                        eligibleStarts=int(coverage.eligible.sum()), secondsChecked=list(range(WINDOW + 1)),
                        situations=list(STARTS), gameScopes=list(data['scopes']), forecastTests=len(data['forecasts']),
                        playManifestSha256=data['playManifestSha256'])
    write_json(DEST/'verification.json', verification)
    print('SHOT_TIMING_VERIFIED', verification, flush=True)


if __name__ == '__main__':
    main()
