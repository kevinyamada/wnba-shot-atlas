"""Build regular-season opponent scouting cards from recorded field goals."""
import json
from collections import Counter

import numpy as np
import pandas as pd

from build import DERIVED, SITE, write_json
from fetch import manifest_digest
from geometry import ZONES


def check_pack(year, counts, teams, allowed):
    filename = f'{"against-" if allowed else ""}{year}.json'
    pack = json.loads((SITE / filename).read_bytes())
    public = Counter()
    for phase, team, _, _, zone, attempts, _, points, _ in pack['rows']:
        if phase == 0:
            public[team, zone, 'n'] += attempts
            public[team, zone, 'p'] += points
    for team, row in zip(teams, counts):
        for zone in range(len(ZONES)):
            assert tuple(row[zone]) == (public[team, zone, 'n'], public[team, zone, 'p']), (year, team, zone, allowed)
    assert counts[..., 0].sum() == sum(v for k, v in public.items() if k[-1] == 'n')


def season(year):
    fields = ['game_id', 'game_date', 'team_id', 'home_id', 'away_id', 'scope', 'zone', 'points',
              'player_id', 'athlete_name_1', 'period_number', 'clock_display_value', 'source_row', 'type_text']
    raw = pd.read_csv(DERIVED / f'shots_{year}.csv.gz', usecols=fields, low_memory=False)
    shots = raw.loc[raw.scope.eq('regular')].copy()
    assert (shots.team_id.eq(shots.home_id) | shots.team_id.eq(shots.away_id)).all()
    assert shots.home_id.ne(shots.away_id).all() and shots.zone.between(0, len(ZONES)-1).all()
    shots['defense'] = np.where(shots.team_id.eq(shots.home_id), shots.away_id, shots.home_id)
    games = shots.drop_duplicates(['game_id','game_date','home_id','away_id']).set_index('game_id')
    assert games.index.is_unique
    schedule = pd.read_csv(DERIVED / f'games_{year}.csv').query("scope == 'regular'").set_index('game_id')
    pd.testing.assert_frame_equal(games[['game_date','home_id','away_id']].sort_index(),
                                  schedule[['game_date','home_id','away_id']].sort_index(), check_dtype=False)
    labels = json.loads((SITE / f'{year}.json').read_bytes())['teams']
    teams = sorted(shots.team_id.unique())
    shape = (len(teams), len(teams), len(ZONES), 2)
    counts = np.zeros(shape, dtype=int)
    lookup = pd.Index(teams)
    indices = (lookup.get_indexer(shots.team_id), lookup.get_indexer(shots.defense), shots.zone)
    np.add.at(counts[..., 0], indices, 1)
    np.add.at(counts[..., 1], indices, shots.points)
    attack, defense, league = counts.sum(1), counts.sum(0), counts.sum((0, 1))
    for cube, allowed in [(attack, False), (defense, True)]:
        check_pack(year, cube, teams, allowed)

    team_games = shots.groupby('team_id').game_id.nunique()
    assert shots[['clock_display_value','period_number','athlete_name_1','player_id','type_text']].notna().all().all()
    assert shots.player_id.ne(0).all()
    names = shots.groupby('player_id').athlete_name_1.last().to_dict()
    clocks = shots.clock_display_value.str.extract(r'^(\d+):(\d+(?:\.\d+)?)$').astype(float)
    assert clocks.notna().all().all()
    shots['seconds'] = 60 * clocks[0] + clocks[1]
    latest = shots.sort_values(['game_date','game_id','period_number','seconds','source_row'],
                               ascending=[False,False,False,True,False])
    def examples(by_player):
        keys = ['team_id','defense','zone'] + (['player_id'] if by_player else [])
        groups = latest.groupby([*keys, 'game_id'], sort=False)
        middle = latest[groups.cumcount().eq(groups.game_id.transform('size') // 2)]
        out = {}
        for key, g in middle.groupby(keys, sort=False):
            out[key] = [[int(r.game_id), int(r.period_number), r.clock_display_value, r.athlete_name_1,
                         r.type_text, int(r.points)] for r in g.head(3).itertuples()]
        return out

    game_examples, player_examples = examples(False), examples(True)
    met_players = shots.groupby(['team_id','defense','zone','player_id']).points.agg(['size','sum'])
    player_totals = {key:(int(n),int(p)) for key,(n,p) in zip(met_players.index, met_players.to_numpy())}
    pairs = dict(tuple(shots.groupby(['team_id','defense'])))
    cards = {}
    for i, a in enumerate(teams):
        own = shots[shots.team_id.eq(a)]
        for j, b in enumerate(teams):
            if i == j:
                continue
            h2h = pairs.get((a,b), shots.iloc[:0])
            meetings = h2h.game_id.nunique()
            nonmeeting = own[own.defense.ne(b)]
            outside = [attack[i] - counts[i,j], defense[j] - counts[i,j], league - counts[i,j] - counts[j,i]]
            assert all(x.min() >= 0 and x[:,0].sum() > 0 for x in outside)
            assert outside[0][:,0].sum() == len(nonmeeting)
            assert outside[1][:,0].sum() == len(shots[shots.defense.eq(b) & shots.team_id.ne(a)])
            assert outside[2][:,0].sum() == len(shots[~shots.game_id.isin(h2h.game_id)])
            personnel = nonmeeting.groupby(['zone','player_id']).size().rename('n').reset_index()
            personnel = personnel.sort_values(['n','player_id'], ascending=[False,True])
            areas = []
            for z in range(5):
                top = personnel[personnel.zone.eq(z)].head(3)
                areas.append(dict(off=outside[0][z].tolist(), allowed=outside[1][z].tolist(),
                                  league=int(outside[2][z,0]), met=counts[i,j,z].tolist(),
                                  players=[dict(id=int(r.player_id), name=names[r.player_id], attempts=int(r.n),
                                                met=player_totals.get((a,b,z,r.player_id), (0,0)),
                                                plays=player_examples.get((a,b,z,r.player_id), [])) for r in top.itertuples()],
                                  plays=game_examples.get((a,b,z), [])))
            cards[f'{a}-{b}'] = dict(shots=[int(x[:,0].sum()) for x in outside] + [len(h2h)],
                                      games=[int(team_games[a]-meetings),int(team_games[b]-meetings),
                                             len(games)-meetings,meetings], areas=areas)
    return dict(season=year, manifestSha256=manifest_digest(), teams={str(t):labels[str(t)] for t in teams},
                games={str(k):[r.game_date,int(r.away_id),int(r.home_id)] for k,r in games.sort_index().iterrows()},
                zones=list(ZONES[:5]), seasonShots=len(shots), cards=cards)


if __name__ == '__main__':
    for year in (2025, 2026):
        data = season(year)
        write_json(SITE / f'matchup-scout-{year}.json', data)
        print(f"SCOUT_VERIFIED {year}: {data['seasonShots']:,} attempts, {len(data['games'])} games, "
              f"{len(data['cards'])} directional matchups, offense and defense reconciled", flush=True)
