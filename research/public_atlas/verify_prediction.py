"""Check the 2027 predictions with separately written arithmetic."""
import json

import numpy as np
import pandas as pd

from fetch import manifest_digest
from recount import RESULTS, ROOT, SITE

OUT = RESULTS / 'prediction_2027'
DERIVED = ROOT / 'research/data/public_wnba/derived'
PARTS = ['offence_quality', 'offence_making', 'defence_quality', 'defence_making']


def belief(seasons, values, noise, rho, tau2, until):
    """Normal updating written as precision weighted averages, apart from the study code. Returns the forecast and the log likelihood."""
    mean, precision, loglik = 0.0, 1 / tau2, 0.0
    previous = None
    for season, value, v in zip(seasons, values, noise):
        if previous is not None:
            shrink = rho ** (season - previous)
            mean, precision = shrink * mean, 1 / (shrink ** 2 / precision + (1 - shrink ** 2) * tau2)
        total = 1 / precision + v
        loglik += -.5 * np.log(2 * np.pi * total) - .5 * (value - mean) ** 2 / total
        mean = (precision * mean + value / v) / (precision + 1 / v)
        precision, previous = precision + 1 / v, season
    shrink = rho ** (until - previous)
    return shrink * mean, shrink ** 2 / precision + (1 - shrink ** 2) * tau2, loglik


def check_series(history, settings, saved, key):
    rho, tau2 = settings.persistence, settings.spread ** 2
    assert 0 < rho < 1 and tau2 > 0

    def likelihood(r, t):
        return sum(belief(part.season.to_numpy(), part.observed.to_numpy(), part.noise.to_numpy(), r, t, 2027)[2] for _, part in history.groupby('entity'))
    here = likelihood(rho, tau2)
    for r, t in [(rho * .9, tau2), (min(rho * 1.05, .999), tau2), (rho, tau2 * .8), (rho, tau2 * 1.25)]:
        assert likelihood(r, t) <= here + 1e-3, 'the saved settings are not at the top of the likelihood'
    checked = 0
    for entity, part in history.groupby('entity'):
        if entity not in saved.index:
            continue
        mean, var, _ = belief(part.season.to_numpy(), part.observed.to_numpy(), part.noise.to_numpy(), rho, tau2, 2027)
        row = saved.loc[entity]
        noise = part.noise.iloc[-1]
        assert abs(row.prediction - mean) < .02 and abs(row.belief_variance - var) < .02 * max(var, 1), (key, entity)
        assert np.isclose(row.high - row.low, 2 * 1.96 * np.sqrt(row.belief_variance + noise), rtol=1e-6)
        checked += 1
    return checked


def main():
    table = pd.read_csv(RESULTS / 'teams/team_seasons.csv')
    assert table.season.max() == 2026, 'no 2027 results may enter the predictions'
    table['net_observed'] = table.offence_quality_observed + table.offence_making_observed - table.defence_quality_observed - table.defence_making_observed
    table['net_noise'] = table[[f'{name}_noise' for name in PARTS]].sum(axis=1)
    saved = pd.read_csv(OUT / 'teams.csv')
    settings = pd.read_csv(OUT / 'season_model.csv').set_index('measure')
    backtest = pd.read_csv(OUT / 'backtest.csv').set_index('measure')
    for name in [*PARTS, 'net']:
        history = pd.DataFrame({'entity': table.team_id, 'season': table.season, 'observed': table[f'{name}_observed'], 'noise': table[f'{name}_noise']}).sort_values('season')
        rows = saved[saved.measure.eq(name)].set_index('team_id')
        assert check_series(history, settings.loc[name], rows, name) == len(rows) == 15
        following = table.set_index(['season', 'team_id'])[f'{name}_observed']
        tested = table[table.season.between(2019, 2026)]
        tested = tested[[(season - 1, team) in following.index for season, team in zip(tested.season, tested.team_id)]]
        assert len(tested) == backtest.loc[name, 'predictions']
        assert np.isclose(np.sqrt(np.mean(tested[f'{name}_observed'] ** 2)), backtest.loc[name, 'rmse_league'])
        assert backtest.loc[name, 'rmse_bayes'] < backtest.loc[name, 'rmse_league'] and .85 <= backtest.loc[name, 'inside_95'] <= 1

    seasons = pd.read_csv(RESULTS / 'shooters/player_seasons.csv')
    assert seasons.season.max() == 2026
    shooters = pd.read_csv(OUT / 'shooters.csv').set_index('player_id')
    history = pd.DataFrame({'entity': seasons.player_id, 'season': seasons.season, 'observed': seasons.raw_per_100,
                            'noise': 1e4 * seasons.chance_variance / seasons.attempts ** 2}).sort_values('season')
    eligible = seasons.loc[seasons.attempts.ge(100), ['player_id', 'season']].copy()
    eligible['season'] += 1
    rows = seasons.merge(eligible, on=['player_id', 'season'], validate='one_to_one')
    rows = rows[rows.season.between(2019, 2026)]
    assert len(rows) == backtest.loc['shooter', 'predictions']
    assert np.isclose(np.sqrt(np.average(rows.raw_per_100 ** 2, weights=rows.attempts)), backtest.loc['shooter', 'rmse_league'])
    historical = pd.read_csv(OUT / 'team_backtest_rows.csv')
    for measure, sample in historical.groupby('measure'):
        inside = (sample.bayes - sample.actual).abs() <= 1.96 * np.sqrt(sample.bayes_variance + sample.noise)
        assert np.isclose(inside.mean(), backtest.loc[measure, 'inside_95'])
    last = seasons[seasons.season.eq(2026) & seasons.attempts.ge(100)]
    assert check_series(history, settings.loc['shooter'], shooters, 'shooter') == len(shooters) == len(last)
    assert shooters.prediction.is_monotonic_decreasing and (shooters.low < shooters.prediction).all() and (shooters.prediction < shooters.high).all()
    assert backtest.loc['shooter', 'rmse_bayes'] < backtest.loc['shooter', 'rmse_league']

    mix = pd.read_csv(RESULTS / 'shot_mix/by_season.csv').set_index('season')
    league = pd.read_csv(OUT / 'league.csv').set_index('measure')
    for label, column, scale in [('Share of shots from the three point area', 'share Three point area', 100), ('Field goal points per shot', 'actual', 1)]:
        row = league.loc[label]
        recent = scale * mix[column].loc[2022:2026]
        design = np.column_stack([np.ones(5), recent.index])
        trend = np.array([1, 2027]) @ np.linalg.lstsq(design, recent.to_numpy(), rcond=None)[0]
        expected = recent.loc[2026] if row.rule == 'Same as last season' else trend
        assert np.isclose(row.value_2026, recent.loc[2026]) and np.isclose(row.prediction, expected) and row.low < row.prediction < row.high

    surface = pd.read_csv(OUT / 'surface_2027.csv')
    assert len(surface) == 47 * 51 and ((0 < surface.lower) & (surface.lower < surface.probability) & (surface.probability < surface.upper) & (surface.upper < 1)).all()
    shots = pd.read_csv(DERIVED / 'shot_form_predictions.csv.gz', usecols=['season', 'source_row', 'scope', 'made', 'p_distance'])
    shots = shots[shots.scope.eq('regular') & shots.season.between(2024, 2026)]
    place = pd.concat([pd.read_csv(DERIVED / f'shots_{year}.csv.gz', usecols=['source_row', 'depth_ft', 'lateral_ft']).assign(season=year) for year in (2024, 2025, 2026)])
    shots = shots.merge(place, on=['season', 'source_row'], validate='one_to_one')
    shots['x'], shots['y'] = shots.depth_ft.round().astype(int), shots.lateral_ft.round().astype(int)
    joined = shots.merge(surface, on=['x', 'y'], how='inner')
    assert len(joined) > .98 * len(shots)
    assert abs(joined.probability.mean() - joined.made.mean()) < .005, 'the surface should match the overall make rate of the seasons it learned from'
    bands = joined.groupby(pd.cut(np.hypot(joined.x, joined.y), [0, 3, 8, 16, 22, 30], include_lowest=True), observed=True).agg(shots=('made', 'size'), made=('made', 'mean'), surface=('probability', 'mean'))
    assert (bands.made - bands.surface).abs().max() < .02, bands
    pooled = pd.read_csv(OUT / 'surface_backtest.csv').set_index(['forecast', 'compared_with'])
    past = pd.read_csv(DERIVED / 'shot_form_predictions.csv.gz', usecols=['season', 'scope', 'made', 'p_distance'])
    past = past[past.scope.eq('regular') & past.season.between(2019, 2026)]
    assert len(past) == pooled.loc[('p_distance', 'league'), 'attempts'] and np.isclose(np.mean((past.p_distance - past.made) ** 2), pooled.loc[('p_distance', 'league'), 'brier'])

    court = json.loads((SITE / 'prediction.json').read_bytes())
    last = pd.read_csv(DERIVED / 'shots_2026.csv.gz', usecols=['scope', 'cell', 'depth_ft', 'lateral_ft', 'made'], low_memory=False)
    last = last[last.scope.eq('regular')]
    rows = pd.DataFrame(court['rows'], columns=['phase', 'team', 'player', 'cell', 'zone', 'attempts', 'made', 'points', 'shot_type'])
    assert court['manifestSha256'] == manifest_digest() and rows.attempts.sum() == len(last) == court['summary']['attempts']
    by_cell = last.groupby('cell').size()
    assert (rows.groupby('cell').attempts.sum().reindex(by_cell.index) == by_cell).all() and rows.cell.nunique() == len(by_cell)
    on_court = last[last.cell.ge(0)]
    chance = surface.set_index(['x', 'y']).probability.reindex(pd.MultiIndex.from_arrays([on_court.depth_ft.round().astype(int), on_court.lateral_ft.round().astype(int)]))
    assert abs(chance.sum() - rows[rows.cell.ge(0)].made.sum()) < 1 and (rows.points >= 2 * rows.made - .002).all() and (rows.points <= 3 * rows.made + .002).all()

    site = json.loads((SITE / 'prediction-2027.json').read_bytes())
    assert site['manifestSha256'] == manifest_digest() and site['season'] == 2027 and len(site['teams']) == 15
    for team in site['teams']:
        rows = saved[saved.team_id.eq(team['id'])].set_index('measure')
        assert all(np.isclose(team[name]['prediction'], rows.loc[name, 'prediction'], atol=.006) for name in [*PARTS, 'net'])
    assert [p['id'] for p in site['shooters']] == list(shooters.index)
    drawn = json.loads((SITE / 'prediction-surface.json').read_bytes())
    assert drawn['manifestSha256'] == manifest_digest() and np.allclose(np.array(drawn['surface']), surface.to_numpy(), atol=1e-6)
    certificate = dict(teams=15, shooters=len(shooters), persistence=settings.persistence.round(3).to_dict(), surface_cells=len(surface),
                       surface_minus_observed_make_rate=round(float(joined.probability.mean() - joined.made.mean()), 4), manifestSha256=manifest_digest())
    (OUT / 'verification.json').write_text(json.dumps(certificate, indent=2) + '\n', encoding='utf-8', newline='\n')
    print('PREDICTIONS_VERIFIED', certificate, flush=True)


if __name__ == '__main__':
    main()
