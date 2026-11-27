"""Compare region and four-foot scoring benchmarks on the same games and team shots."""
import numpy as np
import pandas as pd


def game_cells(shots, games, teams):
    frame = shots.assign(x_bin=np.floor((shots.depth_ft + 5.25) / 4),
                         y_bin=np.floor((shots.lateral_ft + 25) / 4))
    cell, labels = pd.factorize(pd.MultiIndex.from_frame(frame[['region', 'x_bin', 'y_bin']]), sort=True)
    region, _ = pd.factorize(labels.get_level_values(0), sort=True)
    game = pd.Index(games).get_indexer(frame.game_id)
    team = pd.Index(teams).get_indexer(frame.team_id)
    counts = np.zeros((len(games), len(teams), len(labels), 2))
    np.add.at(counts[..., 0], (game, team, cell), 1)
    np.add.at(counts[..., 1], (game, team, cell), frame.points)
    return counts, region


def score(counts, region, peers):
    attempts, points = counts[..., 0], counts[..., 1]
    totals = attempts.sum(-1)
    ref = counts.sum(axis=1, keepdims=True)
    if peers:
        ref = ref - counts
    ref_n, ref_p = ref[..., 0], ref[..., 1]
    starts = np.r_[0, np.flatnonzero(np.diff(region)) + 1]
    parent_n = np.add.reduceat(ref_n, starts, axis=-1)
    assert np.all(parent_n > 0) and np.all(totals > 0)
    parent_rate = np.add.reduceat(ref_p, starts, axis=-1) / parent_n
    rates = np.divide(ref_p, ref_n, out=parent_rate[..., region].copy(), where=ref_n > 0)
    expected = 100 * (attempts * rates).sum(-1) / totals
    baseline = 100 * ref_p.sum(-1) / ref_n.sum(-1)
    observed = 100 * points.sum(-1) / totals
    estimates = np.stack([expected - baseline, observed - expected], axis=-1)
    np.testing.assert_allclose(estimates.sum(-1), observed - baseline, atol=1e-10)
    return estimates, np.broadcast_to(baseline, totals.shape), (attempts * (ref_n == 0)).sum(-1)


def compare(shots, games, teams, names, coarse, weights):
    cells, region = game_cells(shots, games, teams)
    starts = np.r_[0, np.flatnonzero(np.diff(region)) + 1]
    np.testing.assert_array_equal(np.add.reduceat(cells, starts, axis=2), coarse)
    teams_out = [{'id': int(t), 'name': names[str(t)], 'attempts': int(n),
                  'observed': 100 * p / n, 'views': {}}
                 for t, (n, p) in zip(teams, coarse.sum(axis=(0, 2)))]
    for level, cube, parents in [('regions', coarse, np.arange(coarse.shape[2])), ('grid', cells, region)]:
        cube = cube.astype(float, copy=False)
        totals = cube.sum(axis=0, keepdims=True)
        samples = {False: [], True: []}
        for start in range(0, len(weights), 32):
            batch = weights[start:start + 32] @ cube.reshape(len(games), -1)
            batch = batch.reshape(-1, *cube.shape[1:])
            for peers in samples:
                samples[peers].append(score(batch, parents, peers)[0])
        for peers, batches in samples.items():
            value, baseline, fallback = score(totals, parents, peers)
            intervals = np.quantile(np.concatenate(batches), [.025, .975], axis=0)
            key = level + ('Peers' if peers else 'League')
            for i, team in enumerate(teams_out):
                team['views'][key] = dict(baseline=baseline[0, i], fallbackAttempts=int(fallback[0, i]))
                for j, metric in enumerate(['mix', 'within']):
                    team['views'][key][metric] = [value[0, i, j], *intervals[:, i, j]]
    return teams_out
