"""Time from a recorded change of possession to the first field goal attempt."""
import numpy as np
import pandas as pd

from benchmark import paired_games
from build import SITE, write_json
from fetch import YEARS, digest, manifest_digest
from league_turns import INPUT, OUT
from play_sources import DIRECTORY, MANIFEST, main as check_pins

WINDOW = 12
FOCUS = 6
FIT_END = 2024
PRIOR = 40
DRAWS = 2000
SEED = 20261123
STARTS = ('Steal', 'Opponent basket', 'Defensive rebound', 'Opponent turnover', 'Opponent free throw')
KEY = ['game_id', 'period', 'turn']
DEST = OUT / 'timing'


def season_counts(year):
    turns = pd.read_csv(INPUT / f'turns_{year}.csv.gz')
    states = pd.read_csv(INPUT / f'states_{year}.csv.gz', usecols=KEY + ['history_length', 'order', 'situation'])
    starts = states.loc[states.history_length.eq(1), KEY + ['order', 'situation']]
    data = turns.merge(starts, on=KEY, validate='one_to_one')
    assert len(data) == len(turns) == len(starts) and data.situation.isin(STARTS).all()
    shots = pd.read_csv(INPUT / f'shots_{year}.csv.gz', usecols=KEY + ['order', 'points'])
    first = shots.sort_values('order').drop_duplicates(KEY).rename(columns={'order': 'shot_order', 'points': 'first_points'})
    data = data.merge(first, how='left', on=KEY, validate='one_to_one')
    events = pd.read_csv(DIRECTORY / f'wnba_play_by_play_{year}.csv.gz',
                         usecols=['game_id', 'period', 'order_index', 'seconds_remaining'])
    clocks = events.loc[events.game_id.isin(turns.game_id)].set_index(['game_id', 'period', 'order_index']).seconds_remaining
    assert clocks.index.is_unique

    def clock(column):
        index = pd.MultiIndex.from_arrays([data.game_id, data.period, data[column]])
        return clocks.reindex(index).to_numpy()

    start_clock = clock('order')
    shot_clock = clock('shot_order')
    assert np.isfinite(start_clock).all() and np.array_equal(start_clock, clock('turn'))
    has_shot = data.shot_order.notna()
    assert np.array_equal(np.isfinite(shot_clock), has_shot)
    assert data.loc[has_shot, 'shot_order'].between(data.loc[has_shot, 'order'] + 1, data.loc[has_shot, 'end_order']).all()
    elapsed = start_clock - shot_clock
    assert (elapsed[has_shot] >= 0).all()
    data['eligible'] = start_clock >= WINDOW
    coverage = data.groupby(['season', 'scope', 'situation']).eligible.agg(complete='size', eligible='sum').reset_index()
    # A bucket of 6 means the first shot came after 5 and at or before 6 elapsed game seconds.
    data['bucket'] = np.where(has_shot, np.minimum(np.ceil(np.nan_to_num(elapsed)), WINDOW + 1), -1).astype(int)
    data['first_shots'] = has_shot.astype(int)
    data['first_points'] = data.first_points.fillna(0).astype(int)
    assert data.first_points.isin([0, 2, 3]).all()
    data['first_makes'] = data.first_points.gt(0).astype(int)
    data = data.loc[data.eligible].copy()
    data['early'] = data.bucket.between(0, FOCUS)
    data['early_points'] = data.first_points.where(data.early, 0)
    grouped = data.groupby(['season', 'scope', 'situation', 'bucket'])
    bins = grouped[['first_shots', 'first_makes', 'first_points']].sum().assign(starts=grouped.size()).reset_index()
    games = data.groupby(['season', 'scope', 'game_id', 'situation']).agg(
        starts=('turn', 'size'), quick=('early', 'sum'), points=('early_points', 'sum')).reset_index()
    return coverage, bins, games


def game_intervals(games):
    """Resample whole games within each season and phase, keeping both starts together."""
    rng = np.random.default_rng(SEED)
    pair = list(STARTS[:2])
    base = {phase: np.zeros((2, 3)) for phase in ('regular', 'playoffs')}
    draws = {phase: np.zeros((DRAWS, 2, 3)) for phase in base}
    for (_, phase), group in games.groupby(['season', 'scope'], sort=True):
        ids = sorted(group.game_id.unique())
        blocks = [group[group.situation.eq(name)].set_index('game_id')[['starts', 'quick', 'points']]
                  .reindex(ids, fill_value=0).to_numpy() for name in pair]
        values = np.stack(blocks, axis=1)
        base[phase] += values.sum(axis=0)
        n = len(ids)
        weights = rng.multinomial(n, np.full(n, 1/n), size=DRAWS)
        draws[phase] += (weights @ values.reshape(n, 6)).reshape(DRAWS, 2, 3)
    base['both'] = base['regular'] + base['playoffs']
    draws['both'] = draws['regular'] + draws['playoffs']
    results = {}
    for phase, sample in draws.items():
        stats = {}
        for j, metric in [(1, 'shots'), (2, 'points')]:
            delta = 100 * (sample[:, 0, j] / sample[:, 0, 0] - sample[:, 1, j] / sample[:, 1, 0])
            obs = base[phase]
            gap = 100 * (obs[0, j] / obs[0, 0] - obs[1, j] / obs[1, 0])
            lo, hi = np.quantile(delta, [.025, .975])
            stats[metric] = dict(gap=float(gap), low=float(lo), high=float(hi))
        results[phase] = stats
    return results


def forecast(games):
    """Use frozen historical rates to predict a first shot within six game seconds."""
    fit = games[games.season.le(FIT_END)].groupby('situation')[['starts', 'quick']].sum()
    baseline = fit.quick.sum() / fit.starts.sum()
    rates = (fit.quick + PRIOR * baseline) / (fit.starts + PRIOR)
    scores = []
    for (year, phase), group in games[games.season.gt(FIT_END)].groupby(['season', 'scope']):
        p = group.situation.map(rates)
        assert p.notna().all() and p.between(0, 1).all()
        def losses(prob):
            return group.quick * (1-prob)**2 + (group.starts-group.quick) * prob**2
        base_loss, model_loss = losses(baseline), losses(p)
        # paired_games weights by individual decisions. Use the two possible losses per start.
        ds = (1-p)**2 - (1-baseline)**2
        dn = p**2 - baseline**2
        ids = np.concatenate([np.repeat(group.game_id, group.quick), np.repeat(group.game_id, group.starts-group.quick)])
        difference = np.concatenate([np.repeat(ds, group.quick), np.repeat(dn, group.starts-group.quick)])
        comparison = paired_games(ids, difference)
        scores.append(dict(season=int(year), scope=phase, starts=int(group.starts.sum()), games=int(group.game_id.nunique()),
                           baseline=float(base_loss.sum()/group.starts.sum()), model=float(model_loss.sum()/group.starts.sum()),
                           difference=comparison['difference'], low=comparison['lower'], high=comparison['upper']))
    return scores


def summarize(coverage, bins, games, gaps):
    scopes = {}
    for phase in ('both', 'regular', 'playoffs'):
        selected = bins if phase == 'both' else bins[bins.scope.eq(phase)]
        sample = games if phase == 'both' else games[games.scope.eq(phase)]
        by_year = sample.groupby(['season', 'situation'])[['starts', 'quick']].sum()
        rates = by_year.quick.div(by_year.starts).unstack()
        pair = rates.loc[:, list(STARTS[:2])].dropna()
        groups = {}
        for name in STARTS:
            subset = selected[selected.situation.eq(name)]
            totals = subset.groupby('bucket')[['first_shots', 'first_makes', 'first_points']].sum()
            curve = totals.reindex(range(WINDOW + 1), fill_value=0).cumsum()
            groups[name] = dict(starts=int(subset.starts.sum()), shots=curve.first_shots.tolist(),
                                makes=curve.first_makes.tolist(), points=curve.first_points.tolist())
        cov = coverage if phase == 'both' else coverage[coverage.scope.eq(phase)]
        scopes[phase] = dict(games=int(sample.game_id.nunique()), complete=int(cov.complete.sum()),
                             eligible=int(cov.eligible.sum()), groups=groups, sixSecondGap=gaps[phase],
                             seasonsHigher=int(pair.iloc[:, 0].gt(pair.iloc[:, 1]).sum()), seasonsCompared=len(pair))
    return scopes


def main():
    check_pins()
    tally = [season_counts(y) for y in YEARS]
    coverage, bins, games = [pd.concat(parts, ignore_index=True) for parts in zip(*tally)]
    assert coverage.complete.ge(coverage.eligible).all() and coverage.eligible.sum() == games.starts.sum() == bins.starts.sum()
    assert not games.groupby('game_id').season.nunique().gt(1).any()
    scores = forecast(games)
    scopes = summarize(coverage, bins, games, game_intervals(games))
    DEST.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(DEST/'coverage_by_season.csv', index=False)
    bins.to_csv(DEST/'first_shots_by_season.csv', index=False)
    pd.DataFrame(scores).to_csv(DEST/'forecast_scores.csv', index=False)
    data = dict(manifestSha256=manifest_digest(), playManifestSha256=digest(MANIFEST.read_text(encoding='utf-8').encode()),
                maxSeconds=WINDOW, mainSeconds=FOCUS, fitEnd=FIT_END, prior=PRIOR, scopes=scopes, forecasts=scores)
    write_json(SITE/'shot-timing.json', data)
    for phase, row in scopes.items():
        print('TIMING', phase, row['eligible'], 'eligible starts', row['games'], 'games', flush=True)
        for name in STARTS[:2]:
            grp = row['groups'][name]
            print(name, grp['shots'][FOCUS], 'quick shots', grp['points'][FOCUS], 'points in', grp['starts'], 'starts', flush=True)
        print('six second gaps', row['sixSecondGap'], 'seasons', row['seasonsHigher'], '/', row['seasonsCompared'], flush=True)
    print('FORECASTS', scores, flush=True)


if __name__ == '__main__':
    main()
