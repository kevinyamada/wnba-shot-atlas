"""Synthetic logic checks, not additional basketball observations."""
import unittest
import pandas as pd
from possession_reconstruction import Reconstructor,FEATURES


def frame(events):
    rows=[];score={1:0,2:0}
    for n,(tid,team,points,clock) in enumerate(events,2):
        score[team]+=points
        rows.append(dict(source_row=n,game_play_number=n,game_id=999,home_team_id=1,away_team_id=2,
            team_id=team,type_id=tid,score_value=points,clock_display_value=clock,
            home_score=score[1],away_score=score[2],period_number=1,
            shooting_play=tid==92,type_text='Jump Shot' if tid==92 else 'Free Throw' if tid in range(97,109) else 'Other',
            text='synthetic logic check',game_date='2025-07-01',season_type=2,jump_winner_validated=True))
    return pd.DataFrame(rows)


def build(events):
    b=Reconstructor();b.game(frame(events));return b


class ReconstructionTests(unittest.TestCase):
    def test_offensive_rebound_and_five_point_episode(self):
        b=build([(615,1,0,'10:00'),(92,1,2,'9:50'),(97,1,0,'9:50'),
                 (156,1,0,'9:48'),(92,1,3,'9:40'),(402,2,0,'0:00')])
        e=b.episodes[0]
        self.assertEqual((e['points'],e['fga'],e['fta'],e['offensive_rebounds']),(5,2,1,1))
        self.assertTrue(e['eligible']);self.assertEqual(e['end_reason'],'made_field_goal')
        orb=next(s for s in b.states if s['stage']=='after_offensive_rebound')
        self.assertEqual((orb['points_so_far'],orb['remaining_points']),(2,3))

    def test_miss_rebound_turnover(self):
        b=build([(615,1,0,'10:00'),(92,1,0,'9:50'),(156,1,0,'9:48'),
                 (92,1,0,'9:40'),(155,2,0,'9:38'),(84,2,0,'9:30'),(402,1,0,'0:00')])
        self.assertEqual(b.episodes[0]['offensive_rebounds'],1)
        self.assertEqual(b.episodes[0]['end_reason'],'defensive_rebound')
        self.assertEqual(b.episodes[1]['offense_team_id'],2)
        self.assertEqual(b.episodes[1]['end_reason'],'turnover')
        self.assertEqual(sum(e['turnovers'] for e in b.episodes),1)

    def test_nonfinal_ft_deadball_rebound(self):
        b=build([(615,1,0,'10:00'),(98,1,0,'9:50'),(156,1,0,'9:50'),
                 (99,1,1,'9:50'),(402,2,0,'0:00')])
        self.assertEqual(b.episodes[0]['points'],1)
        self.assertEqual(b.episodes[0]['offensive_rebounds'],0)
        self.assertEqual(b.episodes[0]['end_reason'],'made_free_throw')
        self.assertTrue(b.episodes[0]['eligible'])
        self.assertEqual(sum(s['stage']=='after_offensive_rebound' for s in b.states),0)

    def test_missed_final_ft_continues_until_rebound(self):
        b=build([(615,1,0,'10:00'),(98,1,1,'9:50'),(99,1,0,'9:50'),
                 (156,1,0,'9:48'),(92,1,2,'9:40'),(402,2,0,'0:00')])
        self.assertEqual(b.episodes[0]['points'],3)
        self.assertEqual(b.episodes[0]['offensive_rebounds'],1)

    def test_offensive_foul_does_not_duplicate_turnover(self):
        b=build([(615,1,0,'10:00'),(42,1,0,'9:50'),(84,1,0,'9:50'),(402,2,0,'0:00')])
        self.assertEqual(sum(e['turnovers'] for e in b.episodes),1)
        self.assertEqual(len([e for e in b.episodes if e['end_reason']=='turnover']),1)

    def test_special_ft_separate_without_control_flip(self):
        b=build([(615,1,0,'10:00'),(92,1,0,'9:50'),(103,2,1,'9:50'),
                 (156,1,0,'9:48'),(92,1,2,'9:40'),(402,2,0,'0:00')])
        self.assertEqual(b.episodes[0]['points'],2)
        self.assertEqual(sum(e['points'] for e in b.episodes),2)
        self.assertEqual(sum(r['points'] for r in b.ledger if r['reward_lane']=='special_free_throw'),1)
        self.assertFalse(any(e['eligible'] for e in b.episodes))

    def test_incomplete_series_and_unknown_jump_quarantined(self):
        b=build([(615,1,0,'10:00'),(99,1,1,'9:50'),(402,2,0,'0:00')])
        self.assertIn('incomplete_free_throw_series',b.episodes[0]['flags'])
        a=frame([(615,1,0,'10:00'),(92,1,2,'9:50'),(402,2,0,'0:00')])
        a['jump_winner_validated']=False;b=Reconstructor();b.game(a)
        self.assertFalse(any(e['eligible'] for e in b.episodes))

    def test_prefix_features_do_not_use_future_outcomes(self):
        events=[(615,1,0,'10:00'),(92,1,0,'9:50'),(156,1,0,'9:48'),(92,1,2,'9:40'),(402,2,0,'0:00')]
        a=build(events);b=build(events[:3]);key=lambda s:(s['source_row'],s['stage'],s['offense_team_id'])
        full={key(s):s for s in a.states}
        for s in b.states:
            if key(s) in full:self.assertEqual([s[c] for c in FEATURES],[full[key(s)][c] for c in FEATURES])


if __name__=='__main__':unittest.main(verbosity=2)
