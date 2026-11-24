"""Check the 2027 predictions with separately written arithmetic."""
import json

import numpy as np
import pandas as pd

from fetch import manifest_digest
from recount import RESULTS, SITE

OUT = RESULTS / 'prediction_2027'
PARTS = ['offence_quality', 'offence_making', 'defence_quality', 'defence_making']


def spread(values, noise):
    grid = np.linspace(0, 100, 100001)[1:]
    loss = [np.sum(np.log(t + noise) + values ** 2 / (t + noise)) for t in grid]
    return grid[int(np.argmin(loss))]


def main():
    table = pd.read_csv(RESULTS / 'teams/team_seasons.csv')
    assert table.season.max() == 2026, 'no 2027 results may enter the predictions'
    table['net_observed'] = table.offence_quality_observed + table.offence_making_observed - table.defence_quality_observed - table.defence_making_observed
    table['net_noise'] = table[[f'{name}_noise' for name in PARTS]].sum(axis=1)
    saved = pd.read_csv(OUT / 'teams.csv')
    backtest = pd.read_csv(OUT / 'backtest.csv').set_index('measure')
    for name in [*PARTS, 'net']:
        tau2 = spread(table[f'{name}_observed'].to_numpy(), table[f'{name}_noise'].to_numpy())
        table['pooled'] = tau2 / (tau2 + table[f'{name}_noise']) * table[f'{name}_observed']
        following = table.set_index(['season', 'team_id'])[f'{name}_observed']
        pairs = table[[(season + 1, team) in following.index for season, team in zip(table.season, table.team_id)]]
        nxt = np.array([following[(season + 1, team)] for season, team in zip(pairs.season, pairs.team_id)])
        slope = np.sum(pairs.pooled * nxt) / np.sum(pairs.pooled ** 2)
        mine = table[table.season.eq(2026)].set_index('team_id').pooled
        rows = saved[saved.measure.eq(name)].set_index('team_id')
        assert len(rows) == len(mine) == 15
        assert np.allclose(rows.estimate_2026, mine.loc[rows.index], atol=.02) and abs(rows.carry_over.iloc[0] - slope) < .01, name
        assert np.allclose(rows.prediction, rows.carry_over * rows.estimate_2026)
        assert np.allclose(rows.high - rows.low, 2 * 1.96 * backtest.loc[name, 'rmse_carried'])
        assert 0 < rows.carry_over.iloc[0] < 1, 'a carry over factor should shrink toward the league'
        tested = table[table.season.between(2019, 2026)]
        tested = tested[[(season - 1, team) in following.index for season, team in zip(tested.season, tested.team_id)]]
        assert len(tested) == backtest.loc[name, 'predictions']
        assert np.isclose(np.sqrt(np.mean(tested[f'{name}_observed'] ** 2)), backtest.loc[name, 'rmse_league'])
        assert backtest.loc[name, 'rmse_carried'] < backtest.loc[name, 'rmse_league']

    seasons = pd.read_csv(RESULTS / 'shooters/player_seasons.csv')
    assert seasons.season.max() == 2026
    shooters = pd.read_csv(OUT / 'shooters.csv').set_index('player_id')
    last = seasons[seasons.season.eq(2026) & seasons.attempts.ge(100)].set_index('player_id')
    assert len(shooters) == len(last) and np.allclose(shooters.estimate_2026, last.per_100.loc[shooters.index], atol=.05)
    assert np.allclose(shooters.prediction, shooters.carry_over * shooters.estimate_2026) and shooters.prediction.is_monotonic_decreasing
    assert (shooters.low < shooters.prediction).all() and (shooters.prediction < shooters.high).all() and 0 < shooters.carry_over.iloc[0] < 1
    assert backtest.loc['shooter', 'rmse_carried'] < backtest.loc['shooter', 'rmse_league']

    mix = pd.read_csv(RESULTS / 'shot_mix/by_season.csv').set_index('season')
    league = pd.read_csv(OUT / 'league.csv').set_index('measure')
    for label, column, scale in [('Share of shots from the three point area', 'share Three point area', 100), ('Field goal points per shot', 'actual', 1)]:
        row = league.loc[label]
        recent = scale * mix[column].loc[2022:2026]
        assert np.isclose(row.value_2026, recent.loc[2026])
        design = np.column_stack([np.ones(5), recent.index])
        trend = np.array([1, 2027]) @ np.linalg.lstsq(design, recent.to_numpy(), rcond=None)[0]
        expected = recent.loc[2026] if row.rule == 'Same as last season' else trend
        assert np.isclose(row.prediction, expected) and row.low < row.prediction < row.high
        assert (row.rmse_trend < row.rmse_same_as_last) == (row.rule == 'Five season trend')

    site = json.loads((SITE / 'prediction-2027.json').read_bytes())
    assert site['manifestSha256'] == manifest_digest() and site['season'] == 2027 and len(site['teams']) == 15
    for team in site['teams']:
        rows = saved[saved.team_id.eq(team['id'])].set_index('measure')
        assert all(np.isclose(team[name]['prediction'], rows.loc[name, 'prediction'], atol=.006) for name in [*PARTS, 'net'])
    assert [p['id'] for p in site['shooters']] == list(shooters.index)
    certificate = dict(teams=15, shooters=len(shooters), carry_over=saved.groupby('measure').carry_over.first().round(3).to_dict(),
                       shooter_carry_over=round(float(shooters.carry_over.iloc[0]), 3), manifestSha256=manifest_digest())
    (OUT / 'verification.json').write_text(json.dumps(certificate, indent=2) + '\n', encoding='utf-8', newline='\n')
    print('PREDICTIONS_VERIFIED', certificate, flush=True)


if __name__ == '__main__':
    main()
