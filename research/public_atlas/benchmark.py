"""Common season splits and paired comparisons for the public study."""
import numpy as np
import pandas as pd

TRAIN = (2022, 2023, 2024)
VALIDATION = 2025
TEST = 2026
COHORTS = ('validation', 'test', 'playoffs')


def sample_split(frame):
    regular = frame.scope.eq('regular')
    return np.select([regular & frame.season.isin(TRAIN), regular & frame.season.eq(VALIDATION),
                      regular & frame.season.eq(TEST), frame.scope.eq('playoffs') & frame.season.eq(TEST)],
                     ['train', 'validation', 'test', 'playoffs'], default='outside the benchmark')


def paired_games(game_ids, differences):
    """95% intervals from whole games, weighted by attempt or state count in each draw."""
    data = pd.DataFrame({'game_id': np.asarray(game_ids), 'difference': np.asarray(differences)})
    totals = data.groupby('game_id').difference.agg(['sum', 'size'])
    n = len(totals)
    rng = np.random.default_rng(20261122)
    weights = rng.multinomial(n, np.full(n, 1 / n), size=2000)
    draws = weights @ totals['sum'].to_numpy() / (weights @ totals['size'].to_numpy())
    lo, hi = np.quantile(draws, [.025, .975])
    return dict(difference=float(data.difference.mean()), lower=float(lo), upper=float(hi), games=n)
