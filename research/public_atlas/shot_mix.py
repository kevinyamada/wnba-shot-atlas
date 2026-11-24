"""Split changes in field goal points per shot into shot mix and conversion.

Shot mix is the share of attempts taken from each court area. Conversion is
field goal points per attempt within an area. The split is descriptive. It
cannot say why conversion changed.
"""
import json

import numpy as np
import pandas as pd

from build import DERIVED, RESULTS, SITE, write_json
from fetch import YEARS, manifest_digest

OUT = RESULTS / 'shot_mix'
AREAS = ['Near the basket', 'Midrange', 'Three point area', 'Other or unknown']
RECORDED = ['At the rim', 'Short two area', 'Midrange area', 'Corner three area', 'Above the break', 'Other half', 'Unknown location']
EARLY, RECENT = (1997, 2001), (2022, 2026)
COMPARISONS = [('First five seasons to last five', EARLY, RECENT),
               ('First line era to second', (1997, 2003), (2004, 2012)),
               ('Second line era to current', (2004, 2012), (2013, 2026)),
               ('Last season before the line moved to the first after', (2012, 2012), (2013, 2013)),
               ('First five seasons with full locations to last five', (2011, 2015), RECENT),
               ('Previous five seasons to last five', (2017, 2021), RECENT)]
DRAWS = 2000
SEED = 20261123


def load():
    """One row per game and comparable area, with counts kept for the sensitivity checks."""
    use = ['game_id', 'scope', 'zone', 'made', 'points', 'location_status', 'shot_type']
    espn = ['team_id', 'home_id', 'away_id', 'coordinate_x_raw', 'coordinate_y_raw']
    frames = []
    for year in YEARS:
        shots = pd.read_csv(DERIVED / f'shots_{year}.csv.gz', usecols=use if year < 2002 else use + espn, low_memory=False)
        shots = shots[shots.scope.isin(['regular', 'playoffs'])].assign(season=year)
        if year < 2002:
            shots['confirmed'] = True
        else:
            # ESPN gives two coordinate pairs. The pile needs both at the basket and a team that played in the game.
            in_game = shots.team_id.eq(shots.home_id) | shots.team_id.eq(shots.away_id)
            shots['confirmed'] = in_game & shots.coordinate_x_raw.eq(25) & shots.coordinate_y_raw.eq(0)
        frames.append(shots[use + ['season', 'confirmed']])
    shots = pd.concat(frames, ignore_index=True)
    at_basket = shots.location_status.eq('provider_origin_placeholder') & shots.confirmed
    shots['area'] = np.select([shots.zone.le(1) | at_basket, shots.zone.eq(2), shots.zone.isin([3, 4])], AREAS[:3], default=AREAS[3])
    shots['at_basket_pile'] = at_basket
    shots['recorded'] = shots.zone.map(dict(enumerate(RECORDED)))
    return shots


def tally(shots, column):
    grouped = shots.groupby(['season', 'game_id', column])
    return grouped.agg(attempts=('made', 'size'), makes=('made', 'sum'), points=('points', 'sum')).reset_index().rename(columns={column: 'area'})


def period(games, span):
    return games[games.season.between(*span)]


def profile(games, areas):
    totals = games.groupby('area')[['attempts', 'makes', 'points']].sum().reindex(areas, fill_value=0)
    share = totals.attempts / totals.attempts.sum()
    rate = (totals.points / totals.attempts).where(totals.attempts.gt(0))
    return totals, share, rate


def split(share0, rate0, share1, rate1):
    """Exact two part split using the average of both periods as weights."""
    rate0, rate1 = rate0.fillna(rate1), rate1.fillna(rate0)
    middle = ((share0 * rate0).sum() + (share1 * rate1).sum()) / 2
    mix = (share1 - share0) * ((rate0 + rate1) / 2 - middle)
    conversion = (share0 + share1) / 2 * (rate1 - rate0)
    return mix, conversion


def compare(games, first, second, areas):
    _, share0, rate0 = profile(period(games, first), areas)
    _, share1, rate1 = profile(period(games, second), areas)
    mix, conversion = split(share0, rate0, share1, rate1)
    before, after = float((share0 * rate0.fillna(0)).sum()), float((share1 * rate1.fillna(0)).sum())
    base_mix = float(((share1 - share0) * rate0.fillna(rate1)).sum())
    end_mix = float(((share1 - share0) * rate1.fillna(rate0)).sum())
    return dict(before=before, after=after, change=after - before, mix=float(mix.sum()), conversion=float(conversion.sum()),
                mix_with_first_period_rates=base_mix, mix_with_second_period_rates=end_mix,
                by_area=pd.DataFrame({'share_before': share0, 'share_after': share1, 'points_per_shot_before': rate0,
                                      'points_per_shot_after': rate1, 'mix': mix, 'conversion': conversion}))


def resampled(games, span, areas, rng):
    """Area attempts and points for each draw of whole games within every season."""
    attempts, points = np.zeros((DRAWS, len(areas))), np.zeros((DRAWS, len(areas)))
    for _, season in period(games, span).groupby('season'):
        wide = season.pivot_table(index='game_id', columns='area', values=['attempts', 'points'], aggfunc='sum', fill_value=0)
        wide = wide.reindex(columns=pd.MultiIndex.from_product([['attempts', 'points'], areas]), fill_value=0)
        weights = rng.multinomial(len(wide), np.full(len(wide), 1 / len(wide)), size=DRAWS)
        attempts += weights @ wide['attempts'].to_numpy()
        points += weights @ wide['points'].to_numpy()
    return attempts, points


def intervals(games, first, second, areas):
    rng = np.random.default_rng(SEED)
    a0, p0 = resampled(games, first, areas, rng)
    a1, p1 = resampled(games, second, areas, rng)
    with np.errstate(invalid='ignore', divide='ignore'):
        share0, share1 = a0 / a0.sum(axis=1, keepdims=True), a1 / a1.sum(axis=1, keepdims=True)
        rate0, rate1 = p0 / a0, p1 / a1
    rate0, rate1 = np.where(np.isnan(rate0), rate1, rate0), np.where(np.isnan(rate1), rate0, rate1)
    rate0, rate1 = np.nan_to_num(rate0), np.nan_to_num(rate1)
    mix = ((share1 - share0) * (rate0 + rate1) / 2).sum(axis=1)
    conversion = ((share0 + share1) / 2 * (rate1 - rate0)).sum(axis=1)
    bounds = {}
    for name, draws in [('change', mix + conversion), ('mix', mix), ('conversion', conversion), ('mix_share', mix / (mix + conversion))]:
        bounds[f'{name}_low'], bounds[f'{name}_high'] = (float(v) for v in np.quantile(draws, [.025, .975]))
    return bounds


def season_series(games):
    """Actual points per shot, and the value with the shot mix or the conversion held at the 30 season average."""
    _, pooled_share, pooled_rate = profile(games, AREAS)
    rows = []
    for year, season in games.groupby('season'):
        totals, share, rate = profile(season, AREAS)
        rows.append(dict(season=year, attempts=int(totals.attempts.sum()), points=int(totals.points.sum()),
                         actual=float(totals.points.sum() / totals.attempts.sum()),
                         fixed_mix=float((pooled_share * rate.fillna(pooled_rate)).sum()),
                         fixed_conversion=float((share * pooled_rate).sum()),
                         **{f'share {area}': float(share[area]) for area in AREAS},
                         **{f'points per shot {area}': None if pd.isna(rate[area]) else float(rate[area]) for area in AREAS}))
    return pd.DataFrame(rows), pooled_share, pooled_rate


def sensitivity(shots, main):
    """Repeat the headline comparison under other reasonable choices."""
    rows = []

    def add(name, games, areas, first=EARLY, second=RECENT):
        result = compare(games, first, second, areas)
        rows.append(dict(check=name, first=f'{first[0]} to {first[1]}', second=f'{second[0]} to {second[1]}',
                         attempts=int(period(games, first).attempts.sum() + period(games, second).attempts.sum()),
                         **{key: result[key] for key in ('before', 'after', 'change', 'mix', 'conversion')},
                         mix_share=result['mix'] / result['change']))

    add('Main: four comparable areas', main, AREAS)
    add('Mix weighted by first period points per shot only', main, AREAS)
    rows[-1].update(mix=compare(main, EARLY, RECENT, AREAS)['mix_with_first_period_rates'])
    add('Mix weighted by second period points per shot only', main, AREAS)
    rows[-1].update(mix=compare(main, EARLY, RECENT, AREAS)['mix_with_second_period_rates'])
    for row in rows[1:]:
        row.update(conversion=row['change'] - row['mix'], mix_share=row['mix'] / row['change'])
    add('Seven recorded areas, shots at the basket through 2010 left as unknown', tally(shots, 'recorded'), RECORDED)
    mapped = shots[shots.zone.le(4)]
    add('Only shots with a mapped location', tally(mapped, 'area'), AREAS[:3])
    moved = shots.assign(area=shots.area.where(~(shots.at_basket_pile & shots.shot_type.eq(0)), AREAS[3]))
    add('Jump shots recorded at the basket moved to unknown', tally(moved, 'area'), AREAS)
    add('Regular season only', tally(shots[shots.scope.eq('regular')], 'area'), AREAS)
    add('Playoffs only', tally(shots[shots.scope.eq('playoffs')], 'area'), AREAS)
    add('Full location seasons, four areas', main, AREAS, (2011, 2015), RECENT)
    add('Full location seasons, seven recorded areas', tally(shots, 'recorded'), RECORDED, (2011, 2015), RECENT)
    add('Current line only, four areas', main, AREAS, (2013, 2017), RECENT)
    return pd.DataFrame(rows)


def coverage(shots):
    spans = pd.cut(shots.season, [1996, 2001, 2010, 2026], labels=['1997 to 2001', '2002 to 2010', '2011 to 2026'])
    table = shots.groupby(spans, observed=True).agg(
        attempts=('made', 'size'), mapped=('zone', lambda z: int(z.le(4).sum())),
        recorded_at_basket=('at_basket_pile', 'sum'), other_half=('zone', lambda z: int(z.eq(5).sum())))
    table['other_unknown'] = table.attempts - table.mapped - table.recorded_at_basket - table.other_half
    table['mapped_share'] = table.mapped / table.attempts
    return table.reset_index(names='seasons')


def markdown(frame, digits=3):
    def text(value):
        if isinstance(value, (int, np.integer)):
            return f'{value:,}'
        if isinstance(value, (float, np.floating)):
            return '' if np.isnan(value) else f'{value:.{digits}f}'
        return str(value)
    head = '| ' + ' | '.join(frame.columns) + ' |\n| ' + ' | '.join('---' for _ in frame.columns) + ' |\n'
    return head + '\n'.join('| ' + ' | '.join(text(v) for v in row) + ' |' for row in frame.itertuples(index=False)) + '\n'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    shots = load()
    games = tally(shots, 'area')
    assert games.attempts.sum() == len(shots)
    series, pooled_share, pooled_rate = season_series(games)
    assert np.isclose((series.actual * series.attempts).sum(), shots.points.sum())
    results, area_tables = [], []
    for name, first, second in COMPARISONS:
        result = compare(games, first, second, AREAS)
        assert np.isclose(result['mix'] + result['conversion'], result['change'])
        table = result.pop('by_area').reset_index(names='area')
        area_tables.append(table.assign(comparison=name))
        results.append(dict(comparison=name, first=f'{first[0]} to {first[1]}', second=f'{second[0]} to {second[1]}',
                            games_first=int(period(games, first).game_id.nunique()), games_second=int(period(games, second).game_id.nunique()),
                            attempts_first=int(period(games, first).attempts.sum()), attempts_second=int(period(games, second).attempts.sum()),
                            **result, mix_share=result['mix'] / result['change'], **intervals(games, first, second, AREAS)))
        print(f"{name}: {result['before']:.3f} to {result['after']:.3f}, mix {result['mix']:+.3f}, conversion {result['conversion']:+.3f}", flush=True)
    results, areas = pd.DataFrame(results), pd.concat(area_tables)
    checks, located = sensitivity(shots, games), coverage(shots)
    series.to_csv(OUT / 'by_season.csv', index=False)
    results.to_csv(OUT / 'comparisons.csv', index=False)
    areas.to_csv(OUT / 'comparison_areas.csv', index=False)
    checks.to_csv(OUT / 'sensitivity.csv', index=False)
    located.to_csv(OUT / 'location_coverage.csv', index=False)

    head = results.iloc[0]
    main_areas = areas[areas.comparison.eq(head.comparison)].drop(columns='comparison')
    lines = ['# Shot mix and conversion', '',
             f"Field goal points per shot rose from {head.before:.3f} in {head['first']} to {head.after:.3f} in {head.second}, a change of {head.change:+.3f}. "
             f"Holding conversion at the average of the two periods, the change in where shots came from accounts for {head.mix:+.3f} "
             f"(95% game resampling interval {head.mix_low:+.3f} to {head.mix_high:+.3f}). "
             f"Holding the shot mix at the average of the two periods, the change in points per shot within areas accounts for {head.conversion:+.3f} "
             f"({head.conversion_low:+.3f} to {head.conversion_high:+.3f}). Shot mix is {100 * head.mix_share:.0f}% of the change "
             f"({100 * head.mix_share_low:.0f}% to {100 * head.mix_share_high:.0f}%).", '',
             'A change in conversion alone cannot establish why players scored more from an area. Defense, rules, shot selection within an area and how scorers record locations can all contribute.', '',
             '## Areas', '',
             'Near the basket covers mapped shots within 10 ft of the rim and shots recorded exactly at the basket through 2010. Midrange is inside the three point line and 10 ft or more from the rim. '
             'The three point area is outside the line used in that season. Other or unknown covers the other half and the remaining shots without a usable location.', '',
             markdown(main_areas), '## Comparisons', '',
             markdown(results[['comparison', 'first', 'second', 'attempts_first', 'attempts_second', 'before', 'after', 'change', 'mix', 'conversion', 'mix_share']]),
             '## Location coverage', '', markdown(located), '## Sensitivity of the headline comparison', '', markdown(checks),
             '## Method', '',
             'For each area, shot share is its attempts divided by all attempts in the period, and points per shot is its field goal points divided by its attempts. Counts are pooled before any rate is computed. '
             'The mix part is the sum over areas of the change in share times the average points per shot of the two periods. Area rows show that product relative to the overall average, so an area adds to the mix part when it gains share and scores above average or loses share and scores below it. The conversion part is the sum of the average share times the change in points per shot. The two parts add up to the change exactly. '
             f'Intervals resample whole games within each season {DRAWS:,} times with seed {SEED}. They describe game to game variation and leave out uncertainty from how locations were recorded. '
             'The season file also gives points per shot with the mix held at the 30 season average and with conversion held at the 30 season average. '
             'A version based on the recorded attempt value instead of location is not possible, because ESPN misses in recent seasons do not say whether the attempt was a two or a three.', '',
             '[Season values](by_season.csv) · [Comparisons and intervals](comparisons.csv) · [Areas in each comparison](comparison_areas.csv) · [Sensitivity](sensitivity.csv) · [Location coverage](location_coverage.csv)', '']
    (OUT / 'README.md').write_text('\n'.join(lines), encoding='utf-8', newline='\n')

    site = dict(manifestSha256=manifest_digest(), areas=AREAS, seed=SEED, draws=DRAWS,
                pooled=[dict(area=area, share=float(pooled_share[area]), pointsPerShot=float(pooled_rate[area])) for area in AREAS],
                seasons=json.loads(series.to_json(orient='records')),
                comparisons=json.loads(results.to_json(orient='records')),
                comparisonAreas=json.loads(areas.to_json(orient='records')),
                sensitivity=json.loads(checks.to_json(orient='records')),
                coverage=json.loads(located.to_json(orient='records')))
    write_json(SITE / 'shot-mix.json', site)
    print('SHOT_MIX_WRITTEN', len(series), 'seasons', int(series.attempts.sum()), 'attempts', flush=True)


if __name__ == '__main__':
    main()
