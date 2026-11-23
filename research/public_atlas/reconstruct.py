"""Reapply the original audited possession reconstruction to public wehoop games."""
import json
import re
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

from benchmark import TEST, TRAIN, VALIDATION, sample_split
from build import DERIVED, RESULTS, games_for, source, write_json
from fetch import PIN, RAW, file_matches

sys.path.insert(0, str(RESULTS.parents[1]))
from possession_reconstruction import Reconstructor
from possession_recovery import POLICIES, qualify

OUT = RESULTS / 'possession'
EVENTS = ['game_id', 'season', 'period_number', 'game_play_number', 'type_id', 'type_text', 'text',
          'team_id', 'athlete_id_3', 'home_team_id', 'away_team_id', 'home_score', 'away_score',
          'score_value', 'clock_display_value', 'game_date', 'season_type', 'shooting_play']


def identify_jump_winners(events, players):
    by_id = players.groupby(['game_id', 'athlete_id']).team_id.agg(set).to_dict()
    by_name = players.groupby(['game_id', 'athlete_display_name']).team_id.agg(set).to_dict()
    valid = {}
    for row in events[events.type_id.eq(615)].itertuples():
        match = re.search(r'\((.*?) gains possession\)', str(row.text))
        evidence = by_id.get((row.game_id, row.athlete_id_3), set())
        if match:
            evidence = evidence | by_name.get((row.game_id, match.group(1)), set())
        valid[row.source_row] = evidence == {row.team_id}
    events['jump_winner_validated'] = events.source_row.map(valid).eq(True)
    return pd.DataFrame({'source_row': list(valid), 'validated': list(valid.values())})


def score_checks(states, events):
    proof = states.merge(events[['source_row', 'home_team_id', 'home_score', 'away_score']],
                         on='source_row', validate='many_to_one')
    side = np.where(proof.offense_team_id.astype(int).eq(proof.home_team_id), 1, -1)
    return proof.score_margin.eq(side * (proof.home_score - proof.away_score)).to_numpy()


def reconstruct(year):
    games = games_for(year).query("scope in ['regular', 'playoffs']")
    events = pd.read_csv(RAW / f'play_by_play_{year}.csv', usecols=EVENTS, low_memory=False)
    assert events.season.eq(year).all()
    events['source_row'] = events.index + 2
    events = events[events.game_id.isin(games.game_id)].copy()
    assert events.shooting_play.isin([True, False]).all()
    jumps = identify_jump_winners(events, source('player_box', year))
    boxes = source('team_box', year)[['game_id', 'team_id', 'team_score']]
    official = games.set_index('game_id')
    periods, episodes, states, receipts = [], [], [], []
    failed = []
    for game_id, rows in events.groupby('game_id'):
        game = official.loc[game_id]
        builder = Reconstructor()
        problem = ''
        scores = {}
        if rows.game_play_number.isna().any() or rows.game_play_number.duplicated().any():
            problem = 'Missing or duplicate play order'
        elif not (rows.home_team_id.eq(game.home_id) & rows.away_team_id.eq(game.away_id)).all():
            problem = 'Team IDs differ from schedule'
        else:
            try:
                scores = builder.game(rows)
            except (AssertionError, ValueError, TypeError, KeyError) as exc:
                problem = f'Reconstruction rejected the sequence ({type(exc).__name__} {exc})'
        if problem:
            failed.append({'game_id': game_id, 'events': len(rows), 'reason': problem})
            continue
        assert len(builder.ledger) == len(rows)
        ledger = pd.DataFrame(builder.ledger)
        ep = pd.DataFrame(builder.episodes)
        st = pd.DataFrame(builder.states)
        ordinary = ledger[ledger.reward_lane.eq('ordinary')].groupby('episode_id').points.sum()
        assert ep.points.eq(ordinary.reindex(ep.episode_id).fillna(0).to_numpy()).all()
        assert rows.score_value.sum() == ledger.points.sum()
        special = ledger.loc[ledger.reward_lane.eq('special_free_throw'), 'points'].sum()
        assert ledger.points.sum() == ep.points.sum() + special
        assert st.remaining_points.eq(st.episode_points - st.points_so_far).all()
        assert st.remaining_points.ge(0).all()
        for team_id, points in scores.items():
            receipts.append({'game_id': game_id, 'team_id': team_id, 'reconstructed_points': points})
        periods.extend(builder.periods)
        episodes.extend(builder.episodes)
        states.extend(builder.states)

    checks = boxes[boxes.game_id.isin(games.game_id)].merge(pd.DataFrame(receipts),
                     on=['game_id', 'team_id'], how='outer', validate='one_to_one')
    checks['difference'] = checks.reconstructed_points - checks.team_score
    matched = checks[checks.difference.eq(0)].groupby('game_id').size()
    matched = set(matched[matched.eq(2)].index)
    st, ep, pe = pd.DataFrame(states), pd.DataFrame(episodes), pd.DataFrame(periods)
    for frame in [st, ep, pe]:
        frame['season'] = year
        frame['scope'] = frame.game_id.map(official.scope)
        frame['split'] = sample_split(frame)
        frame['both_scores_match'] = frame.game_id.isin(matched)
    st['eligible'] = st.eligible & st.both_scores_match
    pe.to_csv(OUT / f'period_quality_{year}.csv', index=False)
    checks.to_csv(OUT / f'score_audit_{year}.csv', index=False)
    pd.DataFrame(failed, columns=['game_id', 'events', 'reason']).to_csv(OUT / f'rejected_games_{year}.csv', index=False)
    retained = st[st.eligible].copy()
    assert score_checks(retained, events).all()
    retained.to_csv(DERIVED / f'states_{year}.csv.gz', index=False)
    original_ids = set(retained.state_id)
    recovered = {}
    for policy in POLICIES:
        selected, manifest = qualify(events, pe, ep, st, policy)
        added = selected[selected.cohort.eq('recovered') & selected.both_scores_match].copy()
        assert not (set(added.state_id) & original_ids)
        assert score_checks(added, events).all()
        assert added.state_id.is_unique
        recovered[policy] = set(added.state_id)
        added.to_csv(DERIVED / f'{policy}_{year}.csv.gz', index=False)
        manifest.to_csv(OUT / f'{policy}_restarts_{year}.csv', index=False)
    assert recovered['second_rebound'] <= recovered['first_rebound']

    # The first offensive rebound before another recorded miss identifies the
    # observed continuation of this miss. It can be measured without predicting it.
    moment = retained[retained.stage.isin(['after_miss', 'after_offensive_rebound'])].copy()
    for column in ('stage', 'source_row'):
        moment['next_' + column] = moment.groupby('episode_id')[column].shift(-1)
    miss = moment[moment.stage.eq('after_miss')].copy()
    # An intervening made shot or free throw can precede a later rebound. Use
    # the next live shot/free throw/turnover/control event to break that link.
    ordered = events.sort_values(['game_id', 'game_play_number'])
    from possession_reconstruction import FT, SPECIAL_FT, TURNOVERS
    relevant = ordered[ordered.shooting_play | ordered.type_id.isin(set(FT) | SPECIAL_FT | TURNOVERS | {11, 155, 156, 402, 412, 615})]
    next_event = relevant.assign(next_row=relevant.groupby('game_id').source_row.shift(-1)).set_index('source_row').next_row
    miss['retained_by_rebound'] = (miss.next_stage.eq('after_offensive_rebound')
                                   & miss.source_row.map(next_event).eq(miss.next_source_row))
    miss[['season', 'split', 'game_id', 'episode_id', 'source_row', 'remaining_points',
          'retained_by_rebound']].to_csv(DERIVED / f'miss_flow_{year}.csv.gz', index=False)
    receipt = dict(season=year, events=len(events), games_with_events=int(events.game_id.nunique()),
                   games_matching_scores=len(matched), rejected_games=len(failed), periods=len(pe),
                   clean_periods=int((pe['flags'].eq('') & pe.both_scores_match).sum()), states=len(retained),
                   jumps=len(jumps), validated_jumps=int(jumps.validated.sum()),
                   first_restart=len(recovered['first_rebound']), second_restart=len(recovered['second_rebound']))
    print(receipt, flush=True)
    return receipt


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    DERIVED.mkdir(parents=True, exist_ok=True)
    pins = {row['filename']: row for row in json.loads(PIN.read_bytes())}
    years = (*TRAIN, VALIDATION, TEST)
    for year in years:
        for name in [f'{kind}_{year}.csv' for kind in ('play_by_play', 'player_box', 'team_box', 'wnba_schedule')]:
            if not file_matches(RAW / name, pins[name]):
                raise ValueError(f'Pinned input missing or changed: {name}')
    write_json(OUT / 'reconstruction.json', [reconstruct(year) for year in years])


if __name__ == '__main__':
    main()
