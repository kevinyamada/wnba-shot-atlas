"""Score a season with the frozen shot models, following PROSPECTIVE_2027.md.

Run it on 2026 as a rehearsal: it must reproduce the saved 2026 predictions
exactly. Run it on 2027 once, after the 2027 files are pinned and built.
"""
import argparse
import json
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import log_loss

from benchmark import TEST, paired_games, sample_split
from build import DERIVED, RESULTS
from fetch import PIN, digest, file_digest, manifest_digest
from why_distance import STEPS, sample

OUT = RESULTS / 'prospective'
SPATIAL = ['x', 'y', 'distance', 'angle', 'line_offset_ft']
CONTEXT = ['period_number', 'seconds', 'home', 'prior_rate', 'log_prior_n']


def eligible_shots(last):
    """The benchmark sample rules, extended to seasons after the benchmark."""
    frames = []
    for year in range(2022, last + 1):
        path = DERIVED / f'shots_{year}.csv.gz'
        if not path.is_file():
            raise SystemExit(f'No built shot table for {year}. Pin and build that season first.')
        shots = pd.read_csv(path, low_memory=False)
        audit = pd.read_csv(DERIVED / f'player_game_audit_{year}.csv.gz')
        disputed = audit[audit.status.ne('matches') & (audit.attempts.gt(0) | audit.box_attempts.gt(0))]
        bad = set(disputed.game_id) | set(shots.loc[shots.player_id.eq(0), 'game_id'])
        shots['player_audit_pass'] = ~shots.game_id.isin(bad)
        frames.append(shots)
    s = pd.concat(frames, ignore_index=True)
    s['split'] = sample_split(s)
    later = s.season.gt(TEST) & s.scope.isin(['regular', 'playoffs'])
    s.loc[later, 'split'] = 'future ' + s.loc[later, 'scope']
    s = s[s.split.ne('outside the benchmark')].copy()
    boxes = pd.read_csv(RESULTS / 'team_game_audit.csv')
    matched = boxes[boxes.status.eq('matches')].groupby('game_id').size()
    s['team_audit_pass'] = s.game_id.isin(matched[matched.eq(2)].index)
    clock = s.clock_display_value.str.extract(r'^(\d+):(\d+(?:\.\d+)?)$').astype(float)
    s['seconds'] = 60 * clock[0] + clock[1]
    s['home'] = s.team_id.eq(s.home_id).astype(int)
    s['date'] = pd.to_datetime(s.game_date, utc=True).dt.normalize()
    audited = s[s.player_audit_pass & s.team_audit_pass].copy()
    history = audited.groupby(['player_id', 'date']).made.agg(n='size', k='sum').sort_index().reset_index()
    for key in ('n', 'k'):
        history['prior_' + key] = history.groupby('player_id')[key].cumsum() - history[key]
    audited = audited.merge(history[['player_id', 'date', 'prior_n', 'prior_k']], on=['player_id', 'date'], validate='many_to_one')
    audited['prior_rate'] = (audited.prior_k + 22) / (audited.prior_n + 50)
    audited['log_prior_n'] = np.log1p(audited.prior_n)
    keep = audited.cell.ge(0) & audited.seconds.between(0, np.where(audited.period_number.le(4), 600, 300))
    model = audited.loc[keep].rename(columns={'depth_ft': 'x', 'lateral_ft': 'y', 'distance_ft': 'distance'})
    model['angle'] = np.arctan2(model.y.abs(), model.x)
    assert np.isfinite(model[SPATIAL + CONTEXT].to_numpy()).all()
    return model


def frozen_prediction(entry, frame):
    for i, p in enumerate(entry['model'].staged_predict_proba(frame[entry['features']])):
        if i + 1 == entry['rounds']:
            return p[:, 1]


def publish_once(destination, table, record):
    with TemporaryDirectory(dir=destination.parent) as temporary:
        pending = Path(temporary) / 'pending'
        pending.mkdir()
        table.to_csv(pending / 'scores.csv', index=False)
        (pending / 'scores.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8', newline='\n')
        try:
            pending.rename(destination)
        except OSError:
            if destination.exists():
                raise SystemExit(f'A score already exists at {destination}') from None
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--season', type=int, required=True)
    args = parser.parse_args()
    if args.season not in (TEST, TEST + 1):
        parser.error('Choose the 2026 rehearsal or the prospective 2027 season.')
    rehearsal = args.season == TEST
    destination = OUT / f'season_{args.season}'
    if not rehearsal and any(p.exists() for p in (destination, destination.with_suffix('.csv'), destination.with_suffix('.json'))):
        raise SystemExit(f'A score for {args.season} is already archived.')
    registered = json.loads((OUT / 'model_registration.json').read_bytes())
    sources = json.loads(PIN.read_bytes())
    history = sorted((r for r in sources if r['season'] <= TEST), key=lambda r: r['filename'])
    if digest(json.dumps(history, sort_keys=True).encode()) != registered['historicalPinsSha256']:
        raise SystemExit('Historical source pins differ from the original rehearsal.')
    if not rehearsal and not any(r['season'] == args.season for r in sources):
        raise SystemExit('Pin and build the complete 2027 season before scoring.')
    model_path = DERIVED / 'why_distance_models.joblib'
    if not model_path.is_file() or file_digest(model_path) != registered['originalModelSha256']:
        raise SystemExit('The local fitted model differs from the registered original.')
    if version('scikit-learn') != registered['rehearsalEnvironment']['scikit-learn']:
        raise SystemExit('Use the scikit-learn version recorded in the original rehearsal.')
    models = joblib.load(model_path)
    data = sample(eligible_shots(args.season))
    splits = ['test', 'playoffs'] if rehearsal else ['future regular', 'future playoffs']
    scored = data[data.season.eq(args.season) & data.split.isin(splits)].copy()
    if set(scored.split.unique()) != set(splits):
        raise SystemExit('Both regular-season and playoff shots are required.')
    names = [STEPS[0][0], STEPS[-1][0]]
    for name in names:
        scored[name] = frozen_prediction(models[name], scored)
    if rehearsal:
        saved_path = DERIVED / 'why_distance_predictions.csv.gz'
        if not saved_path.is_file() or file_digest(saved_path) != registered['savedPredictionsSha256']:
            raise SystemExit('The saved rehearsal predictions differ from the registered original.')
        saved = pd.read_csv(saved_path)
        both = scored.merge(saved, on=['season', 'source_row'], validate='one_to_one', suffixes=('', '_saved'))
        if not len(both) == len(scored) == int(saved.split.isin(splits).sum()) == registered['rehearsal']['shots']:
            raise SystemExit('The rehearsal and the original predictions have different shot coverage.')
        gap = max(float((both[name] - both[f'{name}_saved']).abs().max()) for name in names)
        if not gap < 1e-12 or both[[*names, *(f'{name}_saved' for name in names)]].isna().any().any():
            raise SystemExit(f'The rehearsal differs from the original predictions: {gap}')
        print(f'Rehearsal on {args.season}: {len(scored):,} saved predictions reproduced exactly.', flush=True)
    rows = []
    for split, part in scored.groupby('split'):
        y = part.made.to_numpy()
        base, full = (part[name].to_numpy() for name in names)
        gap = paired_games(part.game_id, (full - y) ** 2 - (base - y) ** 2)
        error = float(np.mean((base - y) ** 2))
        rows.append(dict(season=args.season, split=split, attempts=len(part), games=part.game_id.nunique(), distance_brier=error,
                         full_brier=float(np.mean((full - y) ** 2)), distance_log_loss=float(log_loss(y, base)), full_log_loss=float(log_loss(y, full)),
                         drop_pct=-100 * gap['difference'] / error, low_pct=-100 * gap['upper'] / error, high_pct=-100 * gap['lower'] / error,
                         predicted_minus_observed=float(full.mean() - y.mean()), holds_up=bool(-gap['upper'] > 0)))
    table = pd.DataFrame(rows)
    if rehearsal:
        reference = pd.read_csv(OUT / 'season_2026.csv').set_index('split').sort_index()
        pd.testing.assert_frame_equal(table.set_index('split').sort_index(), reference, rtol=0, atol=1e-12)
    else:
        record = dict(season=args.season, modelSha256=registered['originalModelSha256'], manifestSha256=manifest_digest(),
                      referenceRevision=registered['referenceRevision'], results=json.loads(table.to_json(orient='records', double_precision=15)))
        publish_once(destination, table, record)
    print(table.round(5).to_string(index=False), flush=True)
    print('FUTURE_SEASON_SCORED', args.season, 'rehearsal' if rehearsal else 'prospective', flush=True)


if __name__ == '__main__':
    main()
