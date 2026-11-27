"""Publish the 2025 team comparison using pinned play-by-play and the original seven regions."""
from html import escape
import json
import sys

import numpy as np
import pandas as pd

from build import DERIVED, ROOT, SITE, manifest_digest, write_json
from team_mix_benchmarks import compare

sys.path.insert(0, str(ROOT / 'research'))
from court_geometry import zones

ARCHIVE = ROOT / 'research/results/data1/cpu/team_regions.csv'
PAGE = ROOT / 'study/shot-mix/index.html'
DRAWS, SEED = 2000, 20261126


def components(counts, exclude_team=False):
    """Final axes are team, region and [attempts, points]."""
    attempts, points = counts[..., 0], counts[..., 1]
    league_n, league_p = attempts.sum(axis=-2, keepdims=True), points.sum(axis=-2, keepdims=True)
    if exclude_team:
        league_n, league_p = league_n - attempts, league_p - points
    total = attempts.sum(axis=-1, keepdims=True)
    shares = attempts / total
    rates = league_p / league_n
    league_total = league_n.sum(axis=-1, keepdims=True)
    baseline = league_p.sum(axis=-1, keepdims=True) / league_total
    mix = 100 * (shares - league_n / league_total) * (rates - baseline)
    within = 100 * (points / total - shares * rates)
    observed = 100 * points.sum(axis=-1) / total[..., 0]
    np.testing.assert_allclose(observed, 100 * baseline[..., 0] + mix.sum(-1) + within.sum(-1))
    return observed, mix, within


def table(headers, rows):
    head = ''.join(f'<th scope="col">{item}</th>' for item in headers)
    lines = []
    for first, *values in rows:
        cells = ''.join(f'<td>{value}</td>' for value in values)
        lines.append(f'<tr><th scope="row">{first}</th>{cells}</tr>')
    return '<div class="table-scroll"><table><thead><tr>' + head + '</tr></thead><tbody>\n' + '\n'.join(lines) + '\n</tbody></table></div>'


def signed(x):
    return f'{x:+.2f}'.replace('-', '−')


def main():
    shots = pd.read_csv(DERIVED / 'shots_2025.csv.gz', usecols=['game_id','scope','team_id','depth_ft','lateral_ft','points','made'])
    shots = shots[shots.scope.eq('regular')].copy()
    shots['region'] = zones(shots.depth_ft, shots.lateral_ft)
    keys = ['team_id', 'region']
    original = pd.read_csv(ARCHIVE).set_index(keys).sort_index()
    grouped = shots.groupby(keys).agg(attempts=('points','size'), makes=('made','sum'), points=('points','sum'))
    pd.testing.assert_frame_equal(grouped, original[grouped.columns], check_dtype=False)
    kept = shots[shots.region.ne('Beyond half court')].copy()
    teams, regions, games = (sorted(kept[key].unique()) for key in ['team_id','region','game_id'])
    dims = ['game_id', *keys]
    index = pd.MultiIndex.from_product([games, teams, regions], names=dims)
    by_game = kept.groupby(dims).points.agg(['size','sum']).reindex(index, fill_value=0)
    cube = by_game.to_numpy().reshape(len(games), len(teams), len(regions), 2)
    totals = cube.sum(axis=0)
    observed, mix, within = components(totals)
    _, other_mix, other_within = components(totals, exclude_team=True)
    rng = np.random.default_rng(SEED)
    weights = rng.multinomial(len(games), np.full(len(games), 1 / len(games)), size=DRAWS)
    draws = (weights @ cube.reshape(len(games), -1)).reshape(DRAWS, *totals.shape)
    _, draw_mix, draw_within = components(draws)
    ranges = np.quantile(np.stack([draw_mix.sum(-1), draw_within.sum(-1)], axis=-1), [.025,.975], axis=0)
    baseline = 100 * kept.points.mean()
    grid = kept.assign(gx=np.floor((kept.depth_ft + 5.25) / 4), gy=np.floor((kept.lateral_ft + 25) / 4))
    cells = grid.groupby(['region','gx','gy']).points.agg(['mean','size'])
    grid = grid.join(cells['mean'].rename('expected'), on=['region','gx','gy'], validate='many_to_one')
    fine = 100 * grid.groupby('team_id').expected.mean()
    names = json.loads((SITE / '2025.json').read_bytes())['teams']
    comparisons = compare(kept, games, teams, names, cube, weights)
    for i, team in enumerate(comparisons):
        views = team['views']
        for metric, j, full, other in [('mix', 0, mix, other_mix), ('within', 1, within, other_within)]:
            np.testing.assert_allclose(views['regionsLeague'][metric], [full[i].sum(), *ranges[:, i, j]], atol=1e-10)
            np.testing.assert_allclose(views['regionsPeers'][metric][0], other[i].sum(), atol=1e-10)
        np.testing.assert_allclose(views['gridLeague']['mix'][0], fine[teams[i]] - baseline, atol=1e-10)
        ref = grid[grid.team_id.ne(teams[i])]
        peer_cells = ref.groupby(['region', 'gx', 'gy']).points.mean().rename('peer_cell')
        selected = grid[grid.team_id.eq(teams[i])].join(peer_cells, on=['region', 'gx', 'gy'])
        peer_rates = selected.peer_cell.fillna(selected.region.map(ref.groupby('region').points.mean()))
        assert peer_rates.notna().all() and selected.peer_cell.isna().sum() == views['gridPeers']['fallbackAttempts']
        np.testing.assert_allclose(views['gridPeers']['mix'][0], 100 * (peer_rates.mean() - ref.points.mean()), atol=1e-10)
    write_json(SITE / 'team-mix-2025.json', dict(manifestSha256=manifest_digest(), games=len(games), draws=DRAWS,
               attempts=len(kept), cells=len(cells), teams=comparisons))
    overview, fine_rows, peer_rows, sections = [], [], [], []
    for i in np.argsort(-observed):
        team = teams[i]
        name = escape(names[str(team)])
        m, w = signed(mix[i].sum()), signed(within[i].sum())
        overview.append([f'<a href="#team-{team}">{name}</a>', f'{observed[i]:.2f}', m, w])
        fine_rows.append([name, m, signed(fine[team]-baseline), w, signed(observed[i]-fine[team])])
        peer = comparisons[i]['views']['gridPeers']
        def with_range(metric):
            value, low, high = peer[metric]
            return f'{signed(value)} ({signed(low)} to {signed(high)})'
        peer_rows.append([name, f"{peer['baseline']:.2f}", with_range('mix'), with_range('within')])
        rows = [[escape(region), f'{totals[i,j,0]:,}', signed(mix[i,j]), signed(within[i,j])] for j, region in enumerate(regions)]
        intervals = [f'{signed(lo)} to {signed(hi)}' for lo, hi in ranges[:,i,:].T]
        sections.append(f'<section id="team-{team}"><h2>{name}</h2>' + table(['Region','Attempts','Shot mix','Within region'], rows)
                        + f'<p>The 95% game-resampled range was {intervals[0]} for mix and {intervals[1]} for within-region scoring. '
                        + f'Using the other 12 teams as the benchmark gives {signed(other_mix[i].sum())} and {signed(other_within[i].sum())}, respectively.</p>'
                        + f'<p><a href="../../?season=2025&amp;team={team}&amp;games=0#team-report">Compare with the opponent-adjusted team report</a></p></section>')
    content = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>2025 shot mix and conversion · WNBA Shot Atlas</title><meta name="description" content="Where each WNBA team gained and lost field-goal points in 2025.">
<link rel="stylesheet" href="../../style.css"><script src="../../theme.js"></script></head><body>
<a class="skip" href="#results">Skip to team results</a><header><a href="../../">WNBA Shot Atlas</a>
<button type="button" id="theme-toggle" class="theme-toggle" aria-label="Switch to dark mode">☾</button></header>
<main><h1>Where did teams gain their points in 2025?</h1>
<p class="lede">Los Angeles gained from where it shot. Minnesota scored above the league rate in all seven regions. Las Vegas overcame an unfavorable mix, while Chicago scored below expectation despite a favorable mix.</p>
<section id="results"><h2>Field-goal points per 100 shots</h2><p>The league averaged {baseline:.2f}. Shot mix measures how much each team’s shot locations raised or lowered its expected scoring. Within-region scoring measures how far a team finished above or below that expectation. Select a team for its regional breakdown.</p>
{table(['Team','Observed','Shot mix','Within region'], overview)}</section>
<section><h2>How to read the comparison</h2>
<p>The original study counted {len(shots):,} attempts and {int(shots.points.sum()):,} field-goal points in {len(games)} regular-season games. Excluding {len(shots)-len(kept)} beyond-half-court attempts worth zero points leaves {len(kept):,} shots. Free throws are excluded.</p>
<p>For each region, the mix contribution is the team’s difference from league shot share multiplied by the difference between the regional and overall league scoring rates. The within-region contribution is the team’s share times its scoring-rate difference from the league. Add both columns to the league baseline to recover observed scoring. Rounding can change a total by 0.01.</p>
<p>The ranges resample {len(games)} entire games {DRAWS:,} times, keeping opponents together and recalculating league rates. Within-region scoring combines shooting ability, difficulty, defender pressure and exact location. This comparison describes the season and cannot establish the payoff from changing shot selection.</p></section>
<section><h2>Does a finer court grid change the result?</h2>
<p>Dividing each region into four-foot squares preserves the four headline comparisons. The {len(cells)} occupied cells include {int(cells.loc[cells['size'].lt(10),'size'].sum())} shots in cells with fewer than ten attempts leaguewide.</p>
{table(['Team','Mix, 7 regions','Mix, 4 ft','Within, 7 regions','Within, 4 ft'], fine_rows)}</section>
<section id="other-teams"><h2>What if only the other 12 teams set the rates?</h2>
<p>Each shot gets the average field-goal points scored by the other teams in the same four-foot square and region. When those teams took no shots there, we use their rate in the surrounding region. Across the 13 teams, {sum(t['views']['gridPeers']['fallbackAttempts'] for t in comparisons)} of {len(kept):,} attempts needed that fallback. The baseline also excludes the selected team.</p>
<p>The chart shows the middle 95% of {DRAWS:,} whole-game resamples for each component. Each draw refits the benchmark and applies the same fallback rule. Each interval describes one team and one component. They are not simultaneous intervals across teams. The axes describe field-goal points per 100 attempts.</p>
{table(['Team', 'Other teams’ baseline', 'Shot mix (95% range)', 'Within locations (95% range)'], peer_rows)}
<p><a href="../../#team-mix-map">Explore the 13 teams</a> · <a href="../../explore/data/team-mix-2025.json">Download chart data and intervals</a></p></section>
{''.join(sections)}<footer><a href="../">Original 2025 study</a> · <a href="../../?season=2025&amp;games=0#team-report">Team explorer</a> · <a href="https://github.com/kevinyamada/wnba-shot-atlas/blob/main/research/results/data1/cpu/team_regions.csv">Source counts</a> · <a href="https://github.com/kevinyamada/wnba-shot-atlas/blob/main/research/summary.md">Methods and source limits</a></footer></main></body></html>
'''
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(content, encoding='utf-8', newline='\n')
    print(f'TEAM_REGIONS_VERIFIED {len(original)} source rows, {len(teams)} teams, {len(kept):,} attempts, baseline {baseline:.2f}')


if __name__ == '__main__':
    main()
