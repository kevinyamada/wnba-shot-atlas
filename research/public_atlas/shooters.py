"""Compare shooters with the makes a league average shooter would expect from the same shots.

The expectation for a shot comes from distance and recorded shot type, learned
from the three regular seasons before it, so no shooter's own results in that
season enter it. Small samples are pulled toward the league expectation.
"""
import json

import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar

from benchmark import paired_games
from build import DERIVED, RESULTS, SITE, write_json
from fetch import manifest_digest

OUT = RESULTS / 'shooters'
EXPECTED = 'p_form'
SITE_MINIMUM = {'season': 50, 'career': 200}


def load():
    shots = pd.read_csv(DERIVED / 'shot_form_predictions.csv.gz')
    frames = []
    for year, season in shots.groupby('season'):
        names = pd.read_csv(DERIVED / f'shots_{year}.csv.gz', usecols=['source_row', 'player_id', 'athlete_name_1'])
        frames.append(season.merge(names, on='source_row', validate='one_to_one'))
    shots = pd.concat(frames, ignore_index=True)
    return shots[shots.player_id.ne(0)].copy()


def player_totals(shots, column=EXPECTED):
    """Makes, expected makes and chance variance for each player season, with the league level set without that player."""
    shots = shots.assign(p=shots[column])
    league = shots.groupby('season').agg(league_makes=('made', 'sum'), league_expected=('p', 'sum'))
    totals = shots.groupby(['season', 'player_id']).agg(attempts=('made', 'size'), makes=('made', 'sum'), raw_expected=('p', 'sum'),
                                                         name=('athlete_name_1', lambda s: s.mode().iat[0] if s.notna().any() else 'Unknown shooter')).reset_index()
    totals = totals.join(league, on='season')
    totals['season_level'] = (totals.league_makes - totals.makes) / (totals.league_expected - totals.raw_expected)
    level = shots.set_index(['season', 'player_id']).index.map(totals.set_index(['season', 'player_id']).season_level)
    adjusted = np.clip(shots.p.to_numpy() * level.to_numpy(), 0, 1)
    spread = pd.Series(adjusted * (1 - adjusted)).groupby([shots.season.to_numpy(), shots.player_id.to_numpy()]).sum()
    totals['expected'] = totals.raw_expected * totals.season_level
    totals['chance_variance'] = pd.MultiIndex.from_frame(totals[['season', 'player_id']]).map(spread).to_numpy()
    return totals.drop(columns=['league_makes', 'league_expected'])


def talent_variance(excess, noise):
    """Maximum likelihood variance of true shooter effects when each observed excess has its own noise."""
    def loss(tau2):
        total = tau2 + noise
        return float(np.sum(np.log(total) + excess ** 2 / total))
    return minimize_scalar(loss, bounds=(0, .01), method='bounded', options={'xatol': 1e-10}).x


def pool(totals, tau2):
    """Shrink each observed excess per shot toward zero in proportion to its noise."""
    excess = (totals.makes - totals.expected) / totals.attempts
    noise = totals.chance_variance / totals.attempts ** 2
    weight = tau2 / (tau2 + noise)
    sd = np.sqrt(weight * noise)
    return totals.assign(raw_per_100=100 * excess, weight=weight, per_100=100 * weight * excess,
                         low=100 * (weight * excess - 1.96 * sd), high=100 * (weight * excess + 1.96 * sd))


def careers(totals):
    summed = totals.groupby('player_id').agg(seasons=('season', 'nunique'), attempts=('attempts', 'sum'), makes=('makes', 'sum'),
                                              expected=('expected', 'sum'), chance_variance=('chance_variance', 'sum'),
                                              name=('name', 'last')).reset_index()
    excess = (summed.makes - summed.expected) / summed.attempts
    return pool(summed, talent_variance(excess.to_numpy(), (summed.chance_variance / summed.attempts ** 2).to_numpy()))


def forecast_check(shots, totals):
    """Does last season's estimate improve the forecast of this season's shots? Only earlier seasons are used."""
    rows, scored = [], []
    seasons = sorted(totals.season.unique())
    for year in seasons[1:]:
        past = totals[totals.season.lt(year)]
        excess = ((past.makes - past.expected) / past.attempts).to_numpy()
        tau2 = talent_variance(excess, (past.chance_variance / past.attempts ** 2).to_numpy())
        last = pool(totals[totals.season.eq(year - 1)], tau2).set_index('player_id')
        now = shots[shots.season.eq(year)]
        pooled = now.player_id.map(last.per_100 / 100).fillna(0).to_numpy()
        raw = now.player_id.map(last.raw_per_100 / 100).fillna(0).to_numpy()
        base = now[EXPECTED].to_numpy()
        scored.append(pd.DataFrame({'season': year, 'game_id': now.game_id.to_numpy(), 'made': now.made.to_numpy(), 'league': base,
                                    'pooled': np.clip(base + pooled, .01, .99), 'raw': np.clip(base + raw, .01, .99),
                                    'returning': now.player_id.isin(last.index).to_numpy()}))
    scored = pd.concat(scored, ignore_index=True)
    for label, part in [('all shots', scored), ('returning shooters', scored[scored.returning])]:
        errors = {name: (part[name] - part.made) ** 2 for name in ('league', 'pooled', 'raw')}
        for name in ('pooled', 'raw'):
            gap = paired_games(part.game_id, errors[name] - errors['league'])
            base = errors['league'].mean()
            rows.append(dict(shots=label, forecast=name, attempts=len(part), games=part.game_id.nunique(), league_brier=float(base),
                             brier=float(errors[name].mean()), drop_pct=-100 * gap['difference'] / base,
                             low_pct=-100 * gap['upper'] / base, high_pct=-100 * gap['lower'] / base))
    return pd.DataFrame(rows)


def records(frame, minimum):
    keep = frame[frame.attempts.ge(minimum)].sort_values('per_100', ascending=False)
    return [dict(id=int(r.player_id), name=r.name, attempts=int(r.attempts), makes=int(r.makes), expected=round(float(r.expected), 1),
                 raw=round(float(r.raw_per_100), 2), estimate=round(float(r.per_100), 2), low=round(float(r.low), 2), high=round(float(r.high), 2))
            for r in keep.itertuples()]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    shots = load()
    totals = player_totals(shots)
    assert totals.attempts.sum() == len(shots) and np.isclose(totals.groupby('season').expected.sum(), totals.groupby('season').makes.sum(), rtol=2e-3).all()
    excess = ((totals.makes - totals.expected) / totals.attempts).to_numpy()
    tau2 = talent_variance(excess, (totals.chance_variance / totals.attempts ** 2).to_numpy())
    seasons = pool(totals, tau2)
    career = careers(totals)
    distance_only = pool(player_totals(shots, 'p_distance'), tau2)
    seasons['per_100_distance_only'] = distance_only.per_100.to_numpy()
    check = forecast_check(shots, totals)
    seasons.drop(columns=['season_level']).to_csv(OUT / 'player_seasons.csv', index=False)
    career.to_csv(OUT / 'players_2016_to_2026.csv', index=False)
    check.to_csv(OUT / 'forecast_check.csv', index=False)

    spread = 100 * np.sqrt(tau2)
    typical = seasons[seasons.attempts.ge(300)]
    top = career[career.attempts.ge(SITE_MINIMUM['career'])].sort_values('per_100', ascending=False).head(10)
    head = check[(check.shots.eq('all shots')) & check.forecast.eq('pooled')].iloc[0]
    naive = check[(check.shots.eq('all shots')) & check.forecast.eq('raw')].iloc[0]
    gain = 100 * np.average((seasons.per_100 / 100) ** 2, weights=seasons.attempts) / head.league_brier
    lines = ['# Shooters against expectation', '',
             f"Across {len(shots):,} shots from 2016 to 2026, the estimated spread of true shooting skill between players is {spread:.1f} makes per 100 shots (one standard deviation), "
             f"after accounting for distance and recorded shot type. A shooter with 300 attempts in a season keeps about {100 * typical.weight.median():.0f}% of her observed margin after pooling.", '',
             f"Using last season's pooled estimate lowered Brier error on the next season's shots by {head.drop_pct:.2f}% (95% game interval {head.low_pct:.2f}% to {head.high_pct:.2f}%). "
             f"Using last season's raw margin instead changed it by {naive.drop_pct:.2f}% ({naive.low_pct:.2f}% to {naive.high_pct:.2f}%). "
             f"Even perfect knowledge of each shooter's skill at this spread would lower shot error by only about {gain:.2f}%, which is one reason distance is hard to beat.", '',
             '## Leaders from 2016 to 2026', '', f"Players with at least {SITE_MINIMUM['career']} eligible attempts. Values are makes per 100 shots above the league expectation.", '',
             '| Player | Attempts | Makes | Expected makes | Observed margin | Pooled estimate | 95% interval |', '| --- | ---: | ---: | ---: | ---: | ---: | --- |']
    lines += [f'| {r.name} | {r.attempts:,} | {r.makes:,} | {r.expected:,.1f} | {r.raw_per_100:+.1f} | {r.per_100:+.1f} | {r.low:+.1f} to {r.high:+.1f} |' for r in top.itertuples()]
    lines += ['', '## Method', '',
              'The expected chance of each shot comes from the shot type study: a curve of make rate by distance for each recorded shot family, fitted on the three regular seasons before the shot. '
              'Each season, those chances are scaled so that the rest of the league, leaving the player out, makes exactly what is expected. Shooter identity never enters the expectation.', '',
              'A player season has an observed margin, makes minus expected makes per shot, and a noise variance from the chance in each shot. '
              'True margins are treated as draws from a normal distribution centred on zero. Its variance is estimated by maximum likelihood from all player seasons. '
              'The pooled estimate multiplies the observed margin by the share of its variance that is skill. The interval is the 95% range of the resulting normal posterior.', '',
              'The sample is the shot type study sample: mapped shots in games where both team boxes match the shot records. '
              'The estimate measures results on the shots a player took. It does not separate shooting skill from shot selection, defensive attention or teammates. '
              'Players who shoot rarely are pulled toward the league average, which may flatter weaker shooters with few attempts.', '',
              '## Forecast check', '',
              "Each season from 2017 on is forecast with estimates from the season before, and the spread of skill is estimated from earlier seasons only. Players without a previous season get the league expectation.", '',
              '| Shots | Forecast | Attempts | League Brier | Brier | Drop | 95% interval |', '| --- | --- | ---: | ---: | ---: | ---: | --- |']
    lines += [f"| {r.shots} | {'pooled estimate' if r.forecast == 'pooled' else 'raw margin'} | {r.attempts:,} | {r.league_brier:.5f} | {r.brier:.5f} | {r.drop_pct:.2f}% | {r.low_pct:.2f}% to {r.high_pct:.2f}% |"
              for r in check.itertuples()]
    lines += ['', '[Player seasons](player_seasons.csv) · [Players across 2016 to 2026](players_2016_to_2026.csv) · [Forecast check](forecast_check.csv)', '']
    (OUT / 'README.md').write_text('\n'.join(lines), encoding='utf-8', newline='\n')

    site = dict(manifestSha256=manifest_digest(), skillSpread=round(float(spread), 3), minimum=SITE_MINIMUM, attempts=len(shots),
                forecast=json.loads(check.to_json(orient='records')),
                seasons={str(year): records(frame, SITE_MINIMUM['season']) for year, frame in seasons.groupby('season')},
                career=records(career, SITE_MINIMUM['career']))
    write_json(SITE / 'shooters.json', site)
    print('SHOOTERS', dict(player_seasons=len(seasons), players=len(career), skill_spread_per_100=round(float(spread), 3),
                           forecast_drop_pct=round(float(head.drop_pct), 3)), flush=True)


if __name__ == '__main__':
    main()
