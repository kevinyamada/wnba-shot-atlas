"""Compare a distance curve with the same curve conditioned on the recorded shot family."""
import json

import numpy as np
import pandas as pd

from build import DERIVED, RESULTS, SHOT_TYPES, shot_family, write_json
from fetch import manifest_digest
from geometry import HALF_WIDTH, MIDCOURT, era_for

OUT = RESULTS / 'shot_form'
YEARS = tuple(range(2013, 2027))
SCORED = YEARS[3:]
SCOPES = ('regular', 'playoffs')
UNKNOWN = SHOT_TYPES.index('Other field goal')
STEP = .25
GRID = np.arange(np.ceil(np.hypot(HALF_WIDTH, MIDCOURT) / STEP) + 1) * STEP
SETTINGS = ((1., 50), (.5, 50), (2., 50), (1., 20), (1., 100))
DIAGRAM_FEET = (2, 4, 6, 8, 10, 12, 15)
PREDICTIONS = DERIVED / 'shot_form_predictions.csv.gz'


def recorded_form(labels):
    # A bare three point designation gives the value attempted, but no shooting motion.
    explicit = labels.astype('string').str.contains(
        'dunk|layup|finger.?roll|hook|float|runner|running.?bank|tip.?shot|tip.?in|putback|jump',
        case=False, regex=True, na=False)
    return np.where(explicit, shot_family(labels), UNKNOWN).astype('int8')


def cohort():
    boxes = pd.read_csv(RESULTS / 'team_game_audit.csv')
    assert not boxes.duplicated(['season', 'game_id', 'team_id']).any()
    eligible = boxes.assign(ok=boxes.status.eq('matches')).groupby(['season', 'game_id']).ok.agg(['size', 'sum'])
    eligible = eligible[(eligible['size'] == 2) & (eligible['sum'] == 2)].reset_index()
    frames, coverage = {}, []
    cols = ['game_id', 'season', 'game_date', 'source_row', 'scope', 'cell', 'distance_ft', 'made', 'type_text']
    for year in YEARS:
        shots = pd.read_csv(DERIVED / f'shots_{year}.csv.gz', usecols=cols)
        assert shots.season.eq(year).all() and shots.source_row.is_unique
        assert era_for(year) == era_for(YEARS[0])
        shots = shots[shots.scope.isin(SCOPES)].copy()
        shots['form'] = recorded_form(shots.type_text)
        checks = shots.game_id.isin(eligible.loc[eligible.season.eq(year), 'game_id'])
        keep = checks & shots.cell.ge(0)
        for scope in SCOPES:
            phase = shots.scope.eq(scope)
            kept = shots[phase & keep]
            coverage.append(dict(season=year, scope=scope, source_shots=int(phase.sum()),
                source_games=shots.loc[phase, 'game_id'].nunique(), failing_boxes=int((phase & ~checks).sum()),
                unmapped_after_boxes=int((phase & checks & shots.cell.lt(0)).sum()), eligible=len(kept),
                eligible_games=kept.game_id.nunique(), unknown_form=int(kept.form.eq(UNKNOWN).sum())))
        frame = shots.loc[keep].drop(columns=['cell','type_text']).reset_index(drop=True)
        assert frame.made.isin([0, 1]).all() and frame.distance_ft.between(0, GRID[-1]).all()
        frame['bin'] = np.rint(frame.distance_ft / STEP).astype(int)
        frames[year] = frame
    pd.DataFrame(coverage).to_csv(OUT / 'coverage.csv', index=False)
    return frames


def curves(training, bandwidth, prior):
    size = (len(SHOT_TYPES), len(GRID))
    attempts, makes = np.zeros(size), np.zeros(size)
    key = training.form.to_numpy(), training['bin'].to_numpy()
    np.add.at(attempts, key, 1)
    np.add.at(makes, key, training.made.to_numpy())
    offsets = (GRID[:, None] - GRID) / bandwidth
    kernel = np.where(np.abs(offsets) <= 4, np.exp(-.5 * offsets ** 2), 0.)
    local_n, local_k = attempts @ kernel, makes @ kernel
    global_rate = (makes.sum() + 1) / (attempts.sum() + 2)
    base = (local_k.sum(axis=0) + 4 * global_rate) / (local_n.sum(axis=0) + 4)
    by_form = (local_k + prior * base) / (local_n + prior)
    by_form[UNKNOWN] = base
    return base, by_form


def game_totals(frame, basic='p_distance', typed='p_form'):
    y, b, t = (frame[col].to_numpy() for col in ['made', basic, typed])
    assert np.all((b > 0) & (b < 1) & (t > 0) & (t < 1))
    group = frame[['season', 'scope', 'game_id']].copy()
    group = group.assign(n=1, brier_distance=(b-y)**2, brier_form=(t-y)**2,
        log_distance=-np.where(y, np.log(b), np.log1p(-b)),
        log_form=-np.where(y, np.log(t), np.log1p(-t)))
    return group.groupby(['season', 'scope', 'game_id']).sum()


def score(games):
    totals = games.sum()
    result = dict(games=len(games), attempts=int(totals.n))
    for col in ('brier_distance','brier_form','log_distance','log_form'):
        result[col] = float(totals[col] / totals.n)
    result['gain_pct'] = float(100 * (1 - totals.brier_form / totals.brier_distance))
    # Draw whole games within each season and phase; use the paired ratio in every draw.
    rng = np.random.default_rng(20261123)
    sampled = np.zeros((2000, 2))
    for _, group in games.groupby(level=['season','scope'], sort=True):
        n = len(group)
        weights = rng.multinomial(n, np.full(n,1/n), size=len(sampled))
        sampled += weights @ group[['brier_distance','brier_form']].to_numpy()
    result['low_pct'], result['high_pct'] = np.quantile(100*(1-sampled[:,1]/sampled[:,0]), [.025,.975]).tolist()
    return result


def summaries(frame):
    g = game_totals(frame)
    years = [dict(season=int(year), scope=scope, **score(group))
             for (year,scope),group in g.groupby(level=['season','scope'])]
    pooled = {scope:score(g.xs(scope,level='scope',drop_level=False)) for scope in SCOPES}
    pooled['both'] = score(g)
    return years, pooled


def diagram(frame):
    whole_foot = np.floor(frame.distance_ft + .5).astype(int)
    counts = frame.assign(feet=whole_foot).groupby(['feet','form']).made.agg(['size','sum'])
    result = []
    for feet in DIAGRAM_FEET:
        rows = []
        for form, row in counts.loc[feet].iterrows():
            rows.append(dict(name=SHOT_TYPES[form], attempts=int(row['size']), makes=int(row['sum'])))
        result.append(dict(feet=feet, rows=rows))
    return result


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    seasons = cohort()
    predictions, sensitivity, windows = [], [], []
    for year in SCORED:
        training = pd.concat([seasons[k].query("scope == 'regular'") for k in range(year-3, year)])
        current = seasons[year].copy()
        assert set(training.season) == set(range(year-3,year)) and not set(training.game_id) & set(current.game_id)
        last = pd.to_datetime(training.game_date,utc=True).max()
        first = pd.to_datetime(current.game_date,utc=True).min()
        assert last < first
        windows.append(dict(season=year, first_training_season=year-3, last_training_season=year-1,
            training_attempts=len(training), training_games=training.game_id.nunique(),
            last_training_date=last.date().isoformat(), first_test_date=first.date().isoformat()))
        idx, form = current['bin'].to_numpy(), current.form.to_numpy()
        for bandwidth, prior in SETTINGS:
            base, typed = curves(training,bandwidth,prior)
            current['p_distance'], current['p_form'] = base[idx], typed[form,idx]
            g = game_totals(current)
            for scope, group in g.groupby(level='scope'):
                sums = group.sum()
                sensitivity.append(dict(season=year,scope=scope,bandwidth_ft=bandwidth,prior_attempts=prior,
                    attempts=int(sums.n),brier_distance=sums.brier_distance/sums.n,brier_form=sums.brier_form/sums.n))
            if (bandwidth, prior) == SETTINGS[0]:
                predictions.append(current.drop(columns=['game_date','bin']).copy())
        print('SCORED', year, 'training', len(training), 'evaluation',len(current), flush=True)
    frame = pd.concat(predictions, ignore_index=True)
    frame.to_csv(PREDICTIONS,index=False)
    by_year, pooled = summaries(frame)
    pd.DataFrame(by_year).to_csv(OUT/'by_season.csv', index=False)
    pd.DataFrame([dict(scope=scope,**s) for scope,s in pooled.items()]).to_csv(OUT/'pooled.csv',index=False)
    pd.DataFrame(windows).to_csv(OUT/'training_windows.csv', index=False)
    pd.DataFrame(sensitivity).to_csv(OUT/'sensitivity.csv',index=False)
    calibration = []
    for col in ('p_distance','p_form'):
        groups = frame.assign(probability=frame[col], band=np.floor(10*frame[col]).astype(int)).groupby(['scope','band'])
        calibration.append(groups.agg(attempts=('made','size'), observed=('made','mean'),
            predicted=('probability','mean')).reset_index().assign(model=col))
    pd.concat(calibration).to_csv(OUT/'calibration.csv',index=False)
    payload = dict(manifestSha256=manifest_digest(), seasons=list(SCORED), byYear=by_year, pooled=pooled,
                   diagram=diagram(frame))
    write_json(DERIVED/'shot_form_rolling.json',payload)
    print('POOLED',json.dumps(pooled),flush=True)


if __name__ == '__main__':
    run()
