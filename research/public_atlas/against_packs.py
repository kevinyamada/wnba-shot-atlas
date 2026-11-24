"""Build the explorer files for shots allowed: the same shots, grouped by the team that was defending."""
import json

import pandas as pd

from build import DERIVED, GROUP_COLUMNS, PACK_COLUMNS, SITE, write_json
from fetch import YEARS, manifest_digest


def season_rows(year):
    shots = pd.read_csv(DERIVED / f'shots_{year}.csv.gz', usecols=['game_id', 'scope', 'team_id', 'cell', 'zone', 'made', 'points', 'shot_type'], low_memory=False)
    shots = shots[shots.scope.isin(['regular', 'playoffs'])].copy()
    sides = shots[shots.team_id.ne(0)].groupby('game_id').team_id.unique()
    sides = sides[sides.str.len().eq(2)]
    other = {(game, a): b for game, pair in sides.items() for a, b in (pair, pair[::-1])}
    shots['phase'] = shots.scope.eq('playoffs').astype(int)
    # The defending team is the other team with shots in the game. Zero means it could not be identified.
    shots['team_id'] = [other.get(key, 0) for key in zip(shots.game_id, shots.team_id)]
    shots['player_id'], shots['attempts'] = 0, 1
    return shots.groupby([*GROUP_COLUMNS, 'shot_type'], as_index=False)[['attempts', 'made', 'points']].sum()


def main():
    index = json.loads((SITE / 'index.json').read_bytes())
    batches, names = [], {}
    for year in YEARS:
        groups = season_rows(year)
        taken = json.loads((SITE / f'{year}.json').read_bytes())
        assert groups.attempts.sum() == sum(row[5] for row in taken['rows']) and groups.points.sum() == sum(row[7] for row in taken['rows'])
        teams = {str(team): 'Unknown team' if team == 0 else taken['teams'].get(str(team), str(team)) for team in sorted(groups.team_id.unique())}
        names.update(teams)
        write_json(SITE / f'against-{year}.json', dict(season=year, court=taken['court'], against=True, manifestSha256=index['manifestSha256'], teams=teams, players={},
                                                       rows=groups[PACK_COLUMNS].to_numpy(dtype=int).tolist()))
        batches.append(groups)
    pooled = pd.concat(batches).groupby([*GROUP_COLUMNS, 'shot_type'], as_index=False)[['attempts', 'made', 'points']].sum()
    labels = json.loads((SITE / 'all.json').read_bytes())['teams']
    write_json(SITE / 'against-all.json', dict(season='all', court='all', against=True, manifestSha256=manifest_digest(),
                                               teams={team: labels.get(team, name) for team, name in names.items()}, players={},
                                               rows=pooled[PACK_COLUMNS].to_numpy(dtype=int).tolist()))
    unknown = int(pooled[pooled.team_id.eq(0)].attempts.sum())
    print('SHOTS_ALLOWED_BUILT', len(YEARS), 'seasons', int(pooled.attempts.sum()), 'attempts', unknown, 'with no identified defending team', flush=True)


if __name__ == '__main__':
    main()
