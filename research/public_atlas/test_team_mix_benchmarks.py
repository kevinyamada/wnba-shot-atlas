"""Check fine-grid estimates in ordinary, missing, and resampled peer cells."""
import unittest

import numpy as np

from team_mix_benchmarks import score


class TeamBenchmarks(unittest.TestCase):
    def test_other_teams_set_both_cell_rate_and_fallback(self):
        games = np.array([
            [[[2, 4], [2, 0], [1, 2]], [[0, 0], [3, 3], [2, 0]]],
            [[[1, 0], [0, 0], [1, 2]], [[1, 2], [3, 0], [0, 0]]],
        ])
        draws = np.stack([games.sum(0), 2 * games[0]])
        result, baseline, fallback = score(draws, np.array([0, 0, 1]), True)
        for d, counts in enumerate(draws):
            for t in [0, 1]:
                own, other = counts[t], counts[1-t]
                expected = 0
                missing = 0
                for cell, (shots, _) in enumerate(own):
                    n, pts = other[cell]
                    if n == 0:
                        missing += shots
                        n, pts = other[:2].sum(0) if cell < 2 else other[2]
                    expected += shots * pts / n
                own_n, own_pts = own.sum(0)
                other_n, other_pts = other.sum(0)
                b = 100 * other_pts / other_n
                self.assertEqual(fallback[d, t], missing)
                self.assertAlmostEqual(baseline[d, t], b)
                np.testing.assert_allclose(result[d, t], [100 * expected / own_n - b,
                                                          100 * (own_pts - expected) / own_n])
        self.assertEqual(fallback[1, 0], 4)
        league, league_base, _ = score(draws, np.array([0, 0, 1]), False)
        self.assertNotEqual(league_base[1, 0], baseline[1, 0])
        self.assertNotEqual(league[1, 0, 0], result[1, 0, 0])


if __name__ == '__main__':
    unittest.main()
