"""Check the shot mix study from the raw shot files, without the derived tables it was built from."""
import json

import numpy as np
import pandas as pd

import recount
from fetch import manifest_digest

OUT = recount.RESULTS / 'shot_mix'
AREAS = ['Near the basket', 'Midrange', 'Three point area', 'Other or unknown']
SEED = 7
DRAWS = 1000


def raw_games():
    """Attempts and points for each game and comparable area, straight from the raw files."""
    frames = []
    for year in recount.YEARS:
        shots, _, _ = recount.early_season(year) if year < 2002 else recount.espn_season(year)
        shots = shots[shots.phase.isin(recount.PHASES)]
        # The published build files a shot under disagreeing pairs before it looks for the basket pile.
        pile = shots.unknown_reason.eq('exactly at the basket through 2010') & shots.pairs_agree
        area = np.select([shots.zone.le(1) | pile, shots.zone.eq(2), shots.zone.isin([3, 4])], AREAS[:3], default=AREAS[3])
        table = shots.assign(area=area).groupby(['game_id', 'area']).agg(attempts=('makes', 'size'), points=('points', 'sum'))
        frames.append(table.reset_index().assign(season=year))
    return pd.concat(frames, ignore_index=True)


def shares_and_rates(games):
    totals = games.groupby('area')[['attempts', 'points']].sum().reindex(AREAS, fill_value=0)
    return totals.attempts / totals.attempts.sum(), totals.points / totals.attempts


def two_parts(games, first, second):
    """Average of the two one sided splits, written separately from the study code."""
    w0, p0 = shares_and_rates(games[games.season.between(*first)])
    w1, p1 = shares_and_rates(games[games.season.between(*second)])
    before, after = (w0 * p0).sum(), (w1 * p1).sum()
    mix = (((w1 - w0) * p0).sum() + ((w1 - w0) * p1).sum()) / 2
    return before, after, mix, after - before - mix


def mix_interval(games, first, second):
    rng = np.random.default_rng(SEED)
    draws = []
    by_season = {year: season for year, season in games.groupby('season')}
    ids = {year: season.game_id.unique() for year, season in by_season.items()}
    wide = {year: season.pivot_table(index='game_id', columns='area', values=['attempts', 'points'], aggfunc='sum', fill_value=0)
            .reindex(columns=pd.MultiIndex.from_product([['attempts', 'points'], AREAS]), fill_value=0) for year, season in by_season.items()}
    for _ in range(DRAWS):
        parts = []
        for span in (first, second):
            total = sum(wide[year].loc[rng.choice(ids[year], len(ids[year]))].sum() for year in range(span[0], span[1] + 1))
            parts.append((total['attempts'] / total['attempts'].sum(), total['points'] / total['attempts']))
        (w0, p0), (w1, p1) = parts
        draws.append(((w1 - w0) * (p0 + p1) / 2).sum())
    return np.quantile(draws, [.025, .975])


def main():
    games = raw_games()
    assert games.attempts.sum() == 902729 and games.points.sum() == 858999
    saved = pd.read_csv(OUT / 'by_season.csv').set_index('season')
    pooled_share, pooled_rate = shares_and_rates(games)
    for year, season in games.groupby('season'):
        share, rate = shares_and_rates(season)
        row = saved.loc[year]
        assert row.attempts == season.attempts.sum() and row.points == season.points.sum(), year
        assert np.isclose(row.actual, season.points.sum() / season.attempts.sum())
        assert np.isclose(row.fixed_mix, (pooled_share * rate.fillna(pooled_rate)).sum()), year
        assert np.isclose(row.fixed_conversion, (share * pooled_rate).sum()), year
        for area in AREAS:
            assert np.isclose(row[f'share {area}'], share[area])
            assert np.isclose(row[f'points per shot {area}'], rate[area], equal_nan=True)
    comparisons = pd.read_csv(OUT / 'comparisons.csv')
    for row in comparisons.itertuples():
        first, second = ([int(year) for year in text.split(' to ')] for text in (row.first, row.second))
        before, after, mix, conversion = two_parts(games, first, second)
        assert np.allclose([row.before, row.after, row.change, row.mix, row.conversion], [before, after, after - before, mix, conversion]), row.comparison
        assert np.isclose(row.mix + row.conversion, row.change) and np.isclose(row.mix_share, row.mix / row.change)
        assert row.attempts_first == games[games.season.between(*first)].attempts.sum()
        assert row.change_low <= row.change <= row.change_high and row.mix_low <= row.mix <= row.mix_high
    head = comparisons.iloc[0]
    low, high = mix_interval(games, (1997, 2001), (2022, 2026))
    width = head.mix_high - head.mix_low
    assert abs(low - head.mix_low) <= .2 * width and abs(high - head.mix_high) <= .2 * width, (low, high)
    areas = pd.read_csv(OUT / 'comparison_areas.csv')
    for name, table in areas.groupby('comparison'):
        row = comparisons[comparisons.comparison.eq(name)].iloc[0]
        assert np.isclose(table.mix.sum(), row.mix) and np.isclose(table.conversion.sum(), row.conversion)
        assert np.isclose(table.share_before.sum(), 1) and np.isclose(table.share_after.sum(), 1)
    coverage = pd.read_csv(OUT / 'location_coverage.csv')
    assert coverage.attempts.sum() == 902729
    assert (coverage.mapped + coverage.recorded_at_basket + coverage.other_half + coverage.other_unknown).eq(coverage.attempts).all()
    counted = pd.read_csv(OUT.parent / 'recount/season_recount.csv')
    assert coverage.mapped.sum() == counted.mapped_half.sum() and coverage.other_half.sum() == counted.other_half.sum()
    site = json.loads((recount.SITE / 'shot-mix.json').read_bytes())
    assert site['manifestSha256'] == manifest_digest() and site['areas'] == AREAS
    assert len(site['seasons']) == 30 and len(site['comparisons']) == len(comparisons)

    for shown, row in zip(site['seasons'], saved.reset_index().itertuples()):
        assert shown['season'] == row.season and np.isclose(shown['actual'], row.actual) and np.isclose(shown['fixed_mix'], row.fixed_mix)
    for shown, row in zip(site['comparisons'], comparisons.itertuples()):
        assert shown['comparison'] == row.comparison and np.isclose(shown['mix'], row.mix) and np.isclose(shown['conversion'], row.conversion)
    report = (OUT / 'README.md').read_text(encoding='utf-8')
    assert f'{head.before:.3f}' in report and f'{head.after:.3f}' in report and f'{head.mix:+.3f}' in report
    certificate = dict(attempts=int(games.attempts.sum()), points=int(games.points.sum()), seasons=30, comparisons=len(comparisons),
                       headline=dict(before=round(head.before, 4), after=round(head.after, 4), mix=round(head.mix, 4), conversion=round(head.conversion, 4)),
                       independent_mix_interval=[round(float(low), 4), round(float(high), 4)], manifestSha256=manifest_digest())
    (OUT / 'verification.json').write_text(json.dumps(certificate, indent=2) + '\n', encoding='utf-8', newline='\n')
    print('SHOT_MIX_VERIFIED', certificate, flush=True)


if __name__ == '__main__':
    main()
