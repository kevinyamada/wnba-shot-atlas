"""Summarize shot locations, official scoring and the density around the arc."""
import json
from functools import lru_cache

import numpy as np
import pandas as pd

from build import DERIVED, PHASE, RESULTS, SITE, write_json
from geometry import BASELINE, HALF_WIDTH, MIDCOURT, RULES, era_for, line_geometry

BIN_EDGES = np.arange(-4, 5)
PHASES = tuple(PHASE)


@lru_cache
def court_offsets(court):
    era = next(row for row in RULES['eras'] if row['id'] == court)
    x, y = np.meshgrid(np.arange(BASELINE + .025, MIDCOURT, .05),
                       np.arange(-HALF_WIDTH + .025, HALF_WIDTH, .05))
    offsets, join = line_geometry(x, y, era)
    return x, offsets, join


def in_band(offset):
    return (offset > 0) & (offset <= 2), (offset >= -2) & (offset < 0)


def arc_stats(shots, season, phase, output):
    era = era_for(season)
    x, offsets, join = court_offsets(era['id'])
    area_regions = [('Arc', x > join), ('Corners', x <= join), ('Whole half court', np.ones(x.shape, dtype=bool))]
    # The opening seasons have a documented radius. Use the middle of that arc
    # for inference so the exact undocumented corner shape does not enter.
    if era.get('arc_only'):
        area_regions = [('Front of arc', x >= 10)]
    measures = []
    for region, area_mask in area_regions:
        observed = {'Arc': shots.depth_ft > join, 'Corners': shots.depth_ft <= join,
                    'Whole half court': shots.cell.ge(0), 'Front of arc': shots.depth_ft.ge(10)}[region]
        selection = shots.loc[observed]
        offset = selection.line_offset_ft.to_numpy()
        court = offsets[area_mask]
        counts = np.histogram(offset, BIN_EDGES)[0]
        areas = np.histogram(court, BIN_EDGES)[0] * .0025
        output.extend(dict(season=season, phase=phase, region=region, lower_ft=int(lo), upper_ft=int(hi),
                           attempts=int(count), area_sqft=float(area), attempts_per_sqft=float(count / area))
                      for lo, hi, count, area in zip(BIN_EDGES[:-1], BIN_EDGES[1:], counts, areas) if area > 0)
        outside, inside = in_band(offset)
        area_outside, area_inside = [mask.sum() * .0025 for mask in in_band(court)]
        g = (selection.assign(inside=inside, outside=outside).groupby('game_id')[['inside', 'outside']].sum()
             .reindex(shots.game_id.unique(), fill_value=0))
        if not len(g) or not g.inside.sum() or not area_inside or not area_outside:
            continue
        rng = np.random.default_rng(20261122)
        w = rng.multinomial(len(g), np.full(len(g), 1 / len(g)), size=2000)
        den = w @ g.inside.to_numpy() / area_inside
        num = w @ g.outside.to_numpy() / area_outside
        draws = num[den > 0] / den[den > 0]
        ratio = (outside.sum() / area_outside) / (inside.sum() / area_inside)
        row = dict(season=season, phase=phase, region=region, attempts=len(selection),
                   games=int(shots.game_id.nunique()), inside=int(inside.sum()), outside=int(outside.sum()),
                   area_inside=area_inside, area_outside=area_outside, ratio=float(ratio),
                   lower=float(np.quantile(draws, .025)), upper=float(np.quantile(draws, .975)))
        if season in (2025, 2026) and phase == 'regular' and region == 'Whole half court':
            depth = selection.depth_ft.to_numpy()
            lateral = selection.lateral_ft.to_numpy()
            ratios = []
            for _ in range(100):
                jitter_depth = np.clip(depth + rng.uniform(-.5, .5, len(depth)), BASELINE, MIDCOURT)
                jitter_lateral = np.clip(lateral + rng.uniform(-.5, .5, len(lateral)), -HALF_WIDTH, HALF_WIDTH)
                perturbed, _ = line_geometry(jitter_depth, jitter_lateral, era)
                out, inn = in_band(perturbed)
                ratios.append((out.sum() / area_outside) / (inn.sum() / area_inside))
            row.update(jitter_min=min(ratios), jitter_max=max(ratios))
        measures.append(row)
    return measures


def main():
    index = json.loads((SITE / 'index.json').read_bytes())
    boxes = pd.read_csv(RESULTS / 'team_game_audit.csv')
    report, density, arc, levels = [], [], [], []
    for season in index['seasons']:
        shots = pd.read_csv(DERIVED / f'shots_{season}.csv.gz', low_memory=False)
        for phase in PHASES:
            scope = shots[shots.scope.eq(phase)]
            box = boxes[boxes.season.eq(season) & boxes.scope.eq(phase)]
            matched = box[box.status.eq('matches')].groupby('game_id').size()
            close = scope[scope.game_id.isin(matched[matched.eq(2)].index)]
            for name, frame in [('all recorded', scope), ('both team boxes match', close)]:
                former = (frame.depth_ft.ge(10) & frame.distance_ft.ge(era_for(2012)['arc_radius'])
                          & frame.distance_ft.lt(era_for(2013)['arc_radius']))
                report.append(dict(season=season, phase=phase, sample=name, games=frame.game_id.nunique(),
                                   attempts=len(frame), makes=frame.made.sum(), points=frame.points.sum(),
                                   mapped=frame.cell.ge(0).sum(), other_half=frame.cell.eq(-2).sum(),
                                   unknown=frame.cell.eq(-1).sum(), former_arc_band=former.sum(),
                                   rim=frame.zone.eq(0).sum(), midrange=frame.zone.eq(2).sum(),
                                   geometric_threes=frame.zone.isin([3, 4]).sum(),
                                   known_attempt_value=frame.attempt_value.notna().sum(),
                                   recorded_three_attempts=frame.attempt_value.eq(3).sum(),
                                   box_attempts=box.box_attempts.sum(),
                                   box_three_attempts=box.box_three_attempts.sum()))
            mapped = scope[scope.cell.ge(0)]
            arc.extend(arc_stats(mapped, season, phase, density))
            for label, keys in [('league', ['zone']), ('team', ['team_id', 'zone']),
                                ('player', ['team_id', 'player_id', 'zone'])]:
                grouped = scope.groupby(keys).agg(attempts=('made', 'size'), makes=('made', 'sum'),
                                                 points=('points', 'sum'), games=('game_id', 'nunique')).reset_index()
                grouped['season'] = season
                grouped['phase'] = phase
                grouped['level'] = label
                levels.append(grouped)
    rows = pd.DataFrame(report)
    rows['make_rate'] = rows.makes / rows.attempts
    rows['points_per_shot'] = rows.points / rows.attempts
    rows['three_area_share_of_mapped'] = rows.geometric_threes / rows.mapped
    rows['box_three_share'] = rows.box_three_attempts / rows.box_attempts
    rows.to_csv(RESULTS / 'eda_by_season.csv', index=False)
    zones = pd.concat(levels, ignore_index=True)
    zones['make_rate'] = zones.makes / zones.attempts
    zones['points_per_shot'] = zones.points / zones.attempts
    zones.to_csv(DERIVED / 'descriptive_by_player_team_area.csv.gz', index=False)
    pd.DataFrame(density).to_csv(RESULTS / 'arc_density.csv', index=False)
    pd.DataFrame(arc).to_csv(RESULTS / 'arc_ratios.csv', index=False)

    regular = rows[rows.phase.eq('regular')]
    band = []
    for year in (2012, 2013):
        a, b = regular[regular.season.eq(year)].itertuples()
        band.append(dict(season=year, attempts=int(a.former_arc_band), total=int(a.attempts),
                         matched_attempts=int(b.former_arc_band), matched_total=int(b.attempts)))
    observed = rows[rows['sample'].eq('all recorded')]
    totals = {k: int(observed[k].sum()) for k in ('attempts', 'makes', 'points', 'mapped', 'other_half', 'unknown')}
    assert totals['attempts'] == totals['mapped'] + totals['other_half'] + totals['unknown']
    team_trend = observed[observed.phase.eq('regular') & observed.box_three_share.notna()]
    early, late = team_trend.iloc[0], team_trend.iloc[-1]
    current = next(row for row in arc if row['season'] == 2026 and row['phase'] == 'regular'
                   and row['region'] == 'Whole half court')
    write_json(SITE / 'findings.json', dict(band=band, totals=totals, currentArc=current,
               arcDensity=[r for r in density if r['season'] == 2026 and r['phase'] == 'regular'
                           and r['region'] == 'Whole half court'],
               leagueThreeShare=[dict(season=int(r.season), share=float(r.box_three_share)) for r in (early, late)]))

    first, last = index['seasons'][0], index['seasons'][-1]
    lines = [f'# WNBA Shot Atlas data review', '',
             f'The public releases contain {totals["attempts"]:,} field goal attempts from {first} to {last}, '
             f'with {totals["makes"]:,} makes and {totals["points"]:,} points. '
             f'The court maps {totals["mapped"]:,} attempts. The other half accounts for {totals["other_half"]:,} '
             f'and {totals["unknown"]:,} have unknown locations.', '',
             f'The regular season share of threes in the available team boxes was {early.box_three_share:.1%} '
             f'in {int(early.season)} and {late.box_three_share:.1%} in {int(late.season)}.', '',
             f'The same physical strip between the old and new arcs contained {band[0]["attempts"]:,} regular '
             f'season attempts in 2012 and {band[1]["attempts"]:,} in 2013. Restricting to games that match both '
             f'team boxes gives {band[0]["matched_attempts"]:,} and {band[1]["matched_attempts"]:,}.', '',
             f'In 2026 regular season games, shots per square foot were {current["ratio"]:.2f} times as common '
             f'in the two feet outside the line as in the two feet inside '
             f'(95% whole game resampling interval {current["lower"]:.2f} to {current["upper"]:.2f}). '
             f'Perturbing locations by up to half a foot per axis gave ratios from {current["jitter_min"]:.2f} '
             f'to {current["jitter_max"]:.2f}. These are descriptive contrasts.', '',
             'The 1997 to 2001 shot release identifies the game phase. ESPN schedules and box scores let us '
             'check coverage where available from 2002 onward. Shots at the exact basket from 1997 to 2010 '
             'stay in the totals with an unknown location given the large provider pileups at this coordinate.', '',
             '| Season | Games with records | Attempts | Makes | Field goal points | Mapped | Unknown |',
             '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for year, a in observed.groupby('season'):
        totals_year = a.sum(numeric_only=True)
        values = [f'{int(totals_year[k]):,}' for k in ('games', 'attempts', 'makes', 'points', 'mapped', 'unknown')]
        lines.append(f'| {year} | ' + ' | '.join(values) + ' |')
    (RESULTS / 'eda.md').write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='')
    print('PUBLIC_EDA_COMPLETE', totals, 'current arc ratio', current['ratio'], flush=True)


if __name__ == '__main__':
    main()
