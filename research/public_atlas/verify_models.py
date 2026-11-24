"""Check the information ladder and the shooter comparison against raw shot rows."""
import json

import numpy as np
import pandas as pd

import recount
from fetch import manifest_digest

DERIVED = recount.ROOT / 'research/data/public_wnba/derived'
RESULTS = recount.RESULTS


def raw_rows(years):
    frames = []
    for year in years:
        raw = pd.read_csv(recount.RAW / f'shots_{year}.csv', usecols=['game_id', 'score_value', 'athlete_id_1'], low_memory=False)
        games = pd.read_csv(recount.RAW / f'wnba_schedule_{year}.csv', usecols=['game_id', 'season_type'], low_memory=False)
        raw['source_row'] = raw.index + 2
        frames.append(raw.merge(games, on='game_id', how='left').assign(season=year))
    return pd.concat(frames)


def ladder():
    scored = pd.read_csv(DERIVED / 'why_distance_predictions.csv.gz')
    joined = scored.merge(raw_rows((2025, 2026)), on=['season', 'source_row'], how='left', validate='one_to_one', suffixes=('', '_raw'))
    assert joined.game_id.eq(joined.game_id_raw).all() and joined.made.eq(joined.score_value.gt(0)).all()
    split = np.select([joined.season.eq(2025) & joined.season_type.eq(2), joined.season.eq(2026) & joined.season_type.eq(2),
                       joined.season.eq(2026) & joined.season_type.eq(3)], ['validation', 'test', 'playoffs'], default='none')
    assert (split == joined.split).all(), 'a scored shot sits outside its season split'
    saved = pd.read_csv(RESULTS / 'why_distance/ladder.csv')
    for row in saved.itertuples():
        part = joined[joined.split.eq(row.split)]
        assert len(part) == row.attempts and np.isclose(row.brier, np.mean((part[row.step] - part.made) ** 2), atol=1e-12), (row.split, row.step)
        assert part[row.step].between(0, 1).all()
    test = saved[saved.split.eq('test')].set_index('step')
    site = json.loads((recount.SITE / 'model-ladder.json').read_bytes())
    assert site['manifestSha256'] == manifest_digest() and [step['step'] for step in site['steps']] == list(test.index)
    assert np.isclose(site['summary']['full_drop_pct'], 100 * (1 - test.brier.iloc[-1] / test.brier['Distance']))
    for row in site['ceiling']:
        assert np.isclose(row['spread_needed'] ** 2, test.brier['League rate'] - row['brier_needed'])
    return dict(scored_shots=len(joined), test_attempts=int(test.attempts.iloc[0]), distance_brier=round(float(test.brier['Distance']), 5),
                full_brier=round(float(test.brier.iloc[-1]), 5))


def spread_of_skill(excess, noise):
    """A plain grid search, written separately from the study's optimiser."""
    grid = np.linspace(0, .01, 20001)
    loss = [np.sum(np.log(t + noise) + excess ** 2 / (t + noise)) for t in grid[1:]]
    return grid[1 + int(np.argmin(loss))]


def shooters():
    shots = pd.read_csv(DERIVED / 'shot_form_predictions.csv.gz')
    raw = raw_rows(sorted(shots.season.unique()))
    shots = shots.merge(raw, on=['season', 'source_row'], how='left', validate='one_to_one', suffixes=('', '_raw'))
    assert shots.made.eq(shots.score_value.gt(0)).all()
    shots = shots[shots.athlete_id_1.notna() & shots.athlete_id_1.ne(0)]
    saved = pd.read_csv(RESULTS / 'shooters/player_seasons.csv')
    assert len(shots) == saved.attempts.sum()
    rows = []
    for (season, player), mine in shots.groupby(['season', 'athlete_id_1']):
        rest = shots[shots.season.eq(season) & shots.athlete_id_1.ne(player)]
        level = rest.made.sum() / rest.p_form.sum()
        p = np.clip(mine.p_form * level, 0, 1)
        rows.append(dict(season=season, player_id=int(player), attempts=len(mine), makes=int(mine.made.sum()), expected=p.sum(), noise=(p * (1 - p)).sum()))
    mine = pd.DataFrame(rows).merge(saved, on=['season', 'player_id'], validate='one_to_one', suffixes=('', '_saved'))
    assert len(mine) == len(saved) and mine.attempts.eq(mine.attempts_saved).all() and mine.makes.eq(mine.makes_saved).all()
    assert np.allclose(mine.expected, mine.expected_saved) and np.allclose(mine.noise, mine.chance_variance)
    excess = ((mine.makes - mine.expected) / mine.attempts).to_numpy()
    noise = (mine.noise / mine.attempts ** 2).to_numpy()
    tau2 = spread_of_skill(excess, noise)
    weight = tau2 / (tau2 + noise)
    assert np.allclose(100 * weight * excess, mine.per_100, atol=.02), 'pooled estimates differ'
    assert np.allclose(100 * (weight * excess + 1.96 * np.sqrt(weight * noise)), mine.high, atol=.03)
    assert (mine.low <= mine.per_100).all() and (mine.per_100 <= mine.high).all() and (mine.per_100.abs() <= mine.raw_per_100.abs() + 1e-9).all()
    site = json.loads((recount.SITE / 'shooters.json').read_bytes())
    assert site['manifestSha256'] == manifest_digest() and np.isclose(site['skillSpread'], 100 * np.sqrt(tau2), atol=.01)
    for season, players in site['seasons'].items():
        expected = saved[saved.season.eq(int(season)) & saved.attempts.ge(site['minimum']['season'])].set_index('player_id')
        assert len(players) == len(expected)
        for player in players:
            row = expected.loc[player['id']]
            assert player['attempts'] == row.attempts and player['makes'] == row.makes and np.isclose(player['estimate'], row.per_100, atol=.006)
    areas = pd.read_csv(RESULTS / 'shooters/player_areas.csv')
    zones = pd.concat([pd.read_csv(DERIVED / f'shots_{year}.csv.gz', usecols=['source_row', 'zone']).assign(season=year) for year in sorted(shots.season.unique())])
    placed = shots.merge(zones, on=['season', 'source_row'], validate='one_to_one')
    placed = placed[placed.zone.le(4)]
    counted = placed.groupby(['season', 'athlete_id_1', 'zone']).made.agg(attempts='size', makes='sum').reset_index().rename(columns={'athlete_id_1': 'player_id'})
    both = areas.merge(counted, on=['season', 'player_id', 'zone'], validate='one_to_one', suffixes=('', '_raw'))
    assert len(both) == len(areas) == len(counted) and both.attempts.eq(both.attempts_raw).all() and both.makes.eq(both.makes_raw).all()
    assert (areas.low <= areas.per_100).all() and (areas.per_100 <= areas.high).all() and (areas.per_100.abs() <= areas.raw_per_100.abs() + 1e-9).all()
    drawn = json.loads((recount.SITE / 'shooter-areas.json').read_bytes())
    assert drawn['manifestSha256'] == manifest_digest()
    for season, players in drawn['seasons'].items():
        table = areas[areas.season.eq(int(season))].set_index(['player_id', 'zone'])
        for player, rows in players.items():
            assert all(table.loc[(int(player), zone), 'attempts'] == n and abs(table.loc[(int(player), zone), 'per_100'] - value) < .006 for zone, n, _, value, _, _ in rows)
    check = pd.read_csv(RESULTS / 'shooters/forecast_check.csv').set_index(['shots', 'forecast'])
    assert check.loc[('all shots', 'pooled'), 'brier'] < check.loc[('all shots', 'pooled'), 'league_brier']
    return dict(player_seasons=len(mine), shots=len(shots), skill_spread_per_100=round(float(100 * np.sqrt(tau2)), 3))


def main():
    certificate = dict(ladder=ladder(), shooters=shooters(), manifestSha256=manifest_digest())
    (RESULTS / 'why_distance/verification.json').write_text(json.dumps(certificate, indent=2) + '\n', encoding='utf-8', newline='\n')
    print('MODELS_VERIFIED', certificate, flush=True)


if __name__ == '__main__':
    main()
