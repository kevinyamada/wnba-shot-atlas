"""Synthetic exclusion/resynchronization logic, not extra basketball data."""
import unittest
import pandas as pd
from possession_reconstruction import Reconstructor,FEATURES
from possession_recovery import HAZARDS,qualify,restarts
from test_possession_reconstruction import frame


def analyze(events,policy='first_rebound',modify=None):
    f=frame(events)
    if modify is not None:modify(f)
    b=Reconstructor();b.game(f)
    s,m=qualify(f,pd.DataFrame(b.periods),pd.DataFrame(b.episodes),pd.DataFrame(b.states),policy)
    return f,b,s,m


def sequence(hazard=35):
    return [(615,1,0,'10:00'),(hazard,1,0,'9:40'),(92,1,0,'9:20'),(155,2,0,'9:18'),
            (92,2,2,'9:10'),(92,1,0,'8:50'),(155,2,0,'8:48'),(92,2,3,'8:40'),(402,1,0,'0:00')]


class RecoveryTests(unittest.TestCase):
    def test_every_hazard_type_is_quarantined_before_restart(self):
        for tid in sorted(HAZARDS):
            with self.subTest(tid=tid):
                f,b,s,m=analyze(sequence(tid))
                self.assertTrue(len(s)>0);self.assertTrue(s.source_row.ge(5).all())
                self.assertTrue(s.cohort.eq('recovered').all());self.assertEqual(m.iloc[0].status,'tail_available')

    def test_actual_ordinary_points_after_technical(self):
        events=sequence();events.insert(2,(103,2,1,'9:40'))
        f,b,s,m=analyze(events);entry=s[s.stage.eq('entry')].iloc[0]
        self.assertEqual(entry.remaining_points,2);self.assertEqual(entry.score_margin,1)
        self.assertEqual(entry.points_so_far,0);self.assertEqual(entry.fga_so_far,0)

    def test_transition_take_retention_uncertainty_ends_at_live_rebound(self):
        events=[(615,1,0,'10:00'),(257,2,0,'9:40'),(97,1,1,'9:40'),(92,1,0,'9:20'),
                (155,2,0,'9:18'),(92,2,2,'9:10'),(402,1,0,'0:00')]
        f,b,s,m=analyze(events);self.assertTrue(len(s)>0);self.assertTrue(s.source_row.ge(6).all())
        self.assertEqual(s[s.stage.eq('entry')].iloc[0].remaining_points,2)

    def test_clear_path_and_flagrant_series_do_not_resume_at_deadball_rebound(self):
        for types in [(107,108),(104,105),(157,165,166)]:
            events=[(615,1,0,'10:00'),(37,2,0,'9:40')]+[(tid,1,0,'9:40') for tid in types]
            events +=[(156,1,0,'9:40'),(92,1,0,'9:20'),(155,2,0,'9:18'),(92,2,2,'9:10'),(402,1,0,'0:00')]
            f,b,s,m=analyze(events);anchor=f[f.type_id.eq(155)].source_row.iloc[0]
            self.assertTrue(s.source_row.ge(anchor).all())

    def test_last_review_restarts_the_quarantine(self):
        events=sequence();events[5:5]=[(215,2,0,'9:05')]
        f,b,s,m=analyze(events);last=f[f.type_id.eq(215)].source_row.iloc[0]
        self.assertTrue(s.source_row.gt(last).all());self.assertEqual(m.iloc[0].restart_seconds,528)

    def test_same_clock_rebound_is_not_a_live_resumption(self):
        events=sequence();events[2]=(92,1,0,'9:40');events[3]=(155,2,0,'9:40')
        f,b,s,m=analyze(events);self.assertEqual(m.iloc[0].restart_seconds,528)

    def test_corroboration_of_rebound_owner_is_required(self):
        events=sequence();events[4]=(92,1,0,'9:10')
        f,b,s,m=analyze(events);self.assertEqual(m.iloc[0].restart_seconds,528)

    def test_no_later_miss_rebound_means_no_recovery(self):
        f,b,s,m=analyze([(615,1,0,'10:00'),(35,1,0,'0:20'),(103,2,1,'0:20'),(402,1,0,'0:00')])
        self.assertTrue(s.empty);self.assertEqual(m.iloc[0].status,'no_supported_restart')

    def test_hard_score_and_unknown_jump_exclusions_stay(self):
        for change in [lambda f:f.__setitem__('home_score',f.home_score+1),lambda f:f.__setitem__('jump_winner_validated',False)]:
            f,b,s,m=analyze(sequence(),modify=change);self.assertTrue(s.empty);self.assertEqual(m.iloc[0].status,'hard_period_exclusion')

    def test_second_restart_is_stricter(self):
        _,_,first,_=analyze(sequence());_,_,second,_=analyze(sequence(),policy='second_rebound')
        self.assertTrue(set(second.state_id)<set(first.state_id));self.assertTrue(second.source_row.ge(8).all())

    def test_normal_period_is_preserved(self):
        events=[(615,1,0,'10:00'),(92,1,0,'9:20'),(155,2,0,'9:18'),(92,2,2,'9:10'),(402,1,0,'0:00')]
        f,b,s,m=analyze(events);original={r['state_id'] for r in b.states if r['eligible']}
        self.assertEqual(set(s.state_id),original);self.assertTrue(s.cohort.eq('original').all())

    def test_features_and_targets_are_copied_without_relabeling(self):
        f,b,s,m=analyze(sequence());original=pd.DataFrame(b.states).set_index('state_id')
        for r in s.to_dict('records'):
            self.assertEqual([r[c] for c in FEATURES+['remaining_points']],[original.loc[r['state_id'],c] for c in FEATURES+['remaining_points']])


if __name__=='__main__':unittest.main(verbosity=2)
