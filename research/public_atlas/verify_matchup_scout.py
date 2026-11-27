"""Replay published film cues and player counts from individual archived shots."""
from collections import Counter, defaultdict
import csv
import gzip
import json

from build import DERIVED, SITE


def verify(year):
    data = json.loads((SITE / f'matchup-scout-{year}.json').read_bytes())
    season_players, matchup_players, player_points = Counter(), Counter(), Counter()
    events = defaultdict(lambda: defaultdict(list))
    with gzip.open(DERIVED / f'shots_{year}.csv.gz', 'rt', encoding='utf-8', newline='') as f:
        for row in csv.DictReader(f):
            if row['scope'] != 'regular':
                continue
            a = int(row['team_id'])
            home, away = int(row['home_id']), int(row['away_id'])
            b = away if a == home else home
            z, pid = int(row['zone']), int(row['player_id'])
            points, game = int(row['points']), int(row['game_id'])
            season_players[a,z,pid] += 1
            matchup_players[a,b,z,pid] += 1
            player_points[a,b,z,pid] += points
            if z >= 5:
                continue
            period, clock = int(row['period_number']), row['clock_display_value']
            minute, second = clock.split(':')
            order = (period, -(60*int(minute) + float(second)), int(row['source_row']))
            cue = [game, period, clock, row['athlete_name_1'], row['type_text'], points]
            for who in [0, pid]:
                events[a,b,z,who][game].append((order, cue))
    assert sum(season_players.values()) == data['seasonShots']
    game_dates = {int(game): v[0] for game, v in data['games'].items()}
    checked = 0
    for key, card in data['cards'].items():
        a,b = map(int,key.split('-'))
        for z, area in enumerate(card['areas']):
            candidates = [(n-matchup_players[a,b,z,pid], pid)
                          for (team, zone, pid), n in season_players.items() if team == a and zone == z]
            top = sorted(((n,pid) for n,pid in candidates if n), key=lambda item:(-item[0],item[1]))[:3]
            assert top == [(p['attempts'],p['id']) for p in area['players']]
            for p in area['players']:
                assert p['met'] == [matchup_players[a,b,z,p['id']], player_points[a,b,z,p['id']]]
            for who, shown in [(0,area['plays']), *((p['id'],p['plays']) for p in area['players'])]:
                games = events[a,b,z,who]
                recent = sorted(games, key=lambda g:(game_dates[g], g), reverse=True)[:3]
                expected = [sorted(games[g])[(len(games[g])-1)//2][1] for g in recent]
                assert expected == shown, (year,key,z,who)
                checked += len(expected)
    print(f'SCOUT_CUES_VERIFIED {year}: {checked:,} published game-clock entries and every personnel list', flush=True)


if __name__ == '__main__':
    for season in (2025, 2026):
        verify(season)
