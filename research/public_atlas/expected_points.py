"""League expected field goal points for every shot, from where and how it was taken.

For each season from 2016, the expectation is learned from the three regular
seasons before it. It uses distance, the side of the three point line and the
recorded shot type. No team or player enters it, so it can serve as a neutral
yardstick for both.
"""
import numpy as np
import pandas as pd

from benchmark import paired_games
from build import DERIVED, RESULTS, SHOT_TYPES
from shot_form import GRID, SCORED, UNKNOWN, cohort

OUT = RESULTS / 'expected_points'
BANDWIDTH = 1.0
PRIOR = 50
EXTRA = ['source_row', 'points', 'line_offset_ft', 'team_id', 'home_id', 'away_id', 'player_id', 'zone']


def curves(training, target):
    """Kernel average of a per shot value by distance, for each shot type on each side of the line."""
    size = (2, len(SHOT_TYPES), len(GRID))
    attempts, total = np.zeros(size), np.zeros(size)
    key = training.outside.to_numpy(), training.form.to_numpy(), training['bin'].to_numpy()
    np.add.at(attempts, key, 1)
    np.add.at(total, key, training[target].to_numpy())
    offsets = (GRID[:, None] - GRID) / BANDWIDTH
    kernel = np.where(np.abs(offsets) <= 4, np.exp(-.5 * offsets ** 2), 0.)
    local_n, local_sum = attempts @ kernel, total @ kernel
    side_n, side_sum = attempts.sum(axis=(1, 2)), total.sum(axis=(1, 2))
    side = (side_sum + 1) / (side_n + 1)
    base = (local_sum.sum(axis=1) + 4 * side[:, None]) / (local_n.sum(axis=1) + 4)
    typed = (local_sum + PRIOR * base[:, None, :]) / (local_n + PRIOR)
    typed[:, UNKNOWN] = base
    return base, typed


def load():
    frames = cohort()
    for year, frame in frames.items():
        more = pd.read_csv(DERIVED / f'shots_{year}.csv.gz', usecols=EXTRA, low_memory=False)
        frame = frame.merge(more, on='source_row', validate='one_to_one')
        frame['outside'] = frame.line_offset_ft.gt(0).astype(int)
        frame['square'] = frame.points ** 2
        frame['defence_id'] = np.where(frame.team_id.eq(frame.home_id), frame.away_id, frame.home_id)
        frames[year] = frame
    return frames


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    seasons = load()
    scored = []
    for year in SCORED:
        training = pd.concat([seasons[k][seasons[k].scope.eq('regular')] for k in range(year - 3, year)])
        test = seasons[year].copy()
        key = test.outside.to_numpy(), test.form.to_numpy(), test['bin'].to_numpy()
        base, typed = curves(training, 'points')
        _, second = curves(training, 'square')
        test['xp_league'] = training.points.mean()
        test['xp_distance'] = base[key[0], key[2]]
        test['xp'] = typed[key]
        test['xp_variance'] = np.maximum(second[key] - typed[key] ** 2, 0)
        scored.append(test)
        print(year, 'training', len(training), 'scored', len(test), flush=True)
    shots = pd.concat(scored, ignore_index=True)
    keep = ['season', 'scope', 'game_id', 'game_date', 'source_row', 'team_id', 'defence_id', 'player_id', 'zone', 'distance_ft', 'form',
            'made', 'points', 'xp_league', 'xp_distance', 'xp', 'xp_variance']
    shots[keep].to_csv(DERIVED / 'expected_points.csv.gz', index=False)

    rows = []
    for scope, part in [('regular', shots[shots.scope.eq('regular')]), ('playoffs', shots[shots.scope.eq('playoffs')]), ('both', shots)]:
        errors = {name: (part[name] - part.points) ** 2 for name in ('xp_league', 'xp_distance', 'xp')}
        for name, other in [('xp_distance', 'xp_league'), ('xp', 'xp_distance')]:
            gap = paired_games(part.game_id, errors[name] - errors[other])
            rows.append(dict(scope=scope, forecast=name, compared_with=other, attempts=len(part), games=part.game_id.nunique(),
                             rmse=float(np.sqrt(errors[name].mean())), rmse_compared=float(np.sqrt(errors[other].mean())),
                             drop_in_squared_error_pct=-100 * gap['difference'] / errors[other].mean(),
                             low_pct=-100 * gap['upper'] / errors[other].mean(), high_pct=-100 * gap['lower'] / errors[other].mean(),
                             mean_expected=float(part[name].mean()), mean_points=float(part.points.mean())))
    scores = pd.DataFrame(rows)
    by_zone = shots.groupby('zone').agg(attempts=('points', 'size'), points_per_shot=('points', 'mean'), expected=('xp', 'mean')).reset_index()
    by_season = shots.groupby('season').agg(attempts=('points', 'size'), points_per_shot=('points', 'mean'), expected=('xp', 'mean')).reset_index()
    scores.to_csv(OUT / 'scores.csv', index=False)
    by_zone.to_csv(OUT / 'calibration_by_area.csv', index=False)
    by_season.to_csv(OUT / 'calibration_by_season.csv', index=False)

    both = scores[scores.scope.eq('both')].set_index('forecast')
    lines = ['# League expected points per shot', '',
             f"Across {len(shots):,} shots from 2016 to 2026, a forecast from distance and the side of the three point line lowers the squared error of field goal points by "
             f"{both.loc['xp_distance', 'drop_in_squared_error_pct']:.2f}% against the league average. Adding the recorded shot type lowers it by a further "
             f"{both.loc['xp', 'drop_in_squared_error_pct']:.2f}% (95% game interval {both.loc['xp', 'low_pct']:.2f}% to {both.loc['xp', 'high_pct']:.2f}%).", '',
             'Each season is forecast from the three regular seasons before it. The expectation uses distance, the side of the line and the recorded shot type. '
             'It never uses the team, the shooter or anything from the season being scored, so it can be used to compare teams and players.', '',
             'A miss is worth zero and a make is worth its recorded two or three points. The side of the line comes from the recorded location, so a shot near the line can be expected to score between two and three points when made.', '',
             '| Games | Forecast | Compared with | Attempts | RMSE | Drop in squared error | 95% interval |', '| --- | --- | --- | ---: | ---: | ---: | --- |']
    names = {'xp_league': 'league average', 'xp_distance': 'distance and line side', 'xp': 'distance, line side and shot type'}
    lines += [f'| {r.scope} | {names[r.forecast]} | {names[r.compared_with]} | {r.attempts:,} | {r.rmse:.4f} | {r.drop_in_squared_error_pct:.2f}% | {r.low_pct:.2f}% to {r.high_pct:.2f}% |'
              for r in scores.itertuples()]
    lines += ['', 'Expected and actual points differ a little from season to season, because each forecast learned from earlier seasons. '
              'Team and player comparisons remove that season level before they are made.', '',
              '[Scores](scores.csv) · [Expected and actual by area](calibration_by_area.csv) · [Expected and actual by season](calibration_by_season.csv)', '']
    (OUT / 'README.md').write_text('\n'.join(lines), encoding='utf-8', newline='\n')
    print('EXPECTED_POINTS', len(shots), 'shots', {k: round(float(v), 3) for k, v in both.drop_in_squared_error_pct.items()}, flush=True)


if __name__ == '__main__':
    main()
