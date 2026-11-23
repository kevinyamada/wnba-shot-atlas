"""Rebuild the denominators, distance estimates, paired intervals and visual from saved source rows."""
import json

import numpy as np
import pandas as pd

from build import DERIVED, RESULTS, SHOT_TYPES, SITE, crosswalk, write_json
from fetch import PIN, RAW, digest, file_matches, manifest_digest
from form_context import MODEL, OUTPUT, SAVED
from reference_audit import PIN as REFERENCE_PIN, REFERENCE, reference_sources
from shot_form import OUT, PREDICTIONS, SCORED, UNKNOWN, YEARS, recorded_form

KEYS = ['season','source_row']


def equal(actual, expected):
    np.testing.assert_allclose(actual,expected,rtol=1e-10,atol=1e-12)


def independent_curves(training, feet, form, bandwidth=1., prior=50):
    # Direct sums over occupied quarters of a foot give a separate calculation of the curves.
    grouped = training.groupby(['quarter','form']).made.agg(['sum','size']).reset_index()
    baseline, conditional = np.zeros(len(feet)), np.zeros(len(feet))
    overall = (training.made.sum()+1) / (len(training)+2)
    for quarter in np.unique(feet):
        ix = feet == quarter
        d = np.abs(grouped.quarter.to_numpy()-quarter) / (4*bandwidth)
        weights = np.where(d <= 4,np.exp(-.5*d**2),0)
        n = np.bincount(grouped.form,weights*grouped['size'],minlength=len(SHOT_TYPES))
        k = np.bincount(grouped.form,weights*grouped['sum'],minlength=len(SHOT_TYPES))
        base = (k.sum()+4*overall)/(n.sum()+4)
        p = (k+prior*base)/(n+prior)
        p[UNKNOWN] = base
        baseline[ix] = base
        conditional[ix] = p[form[ix]]
    return baseline, conditional


def verify_scores(frame, record, basic, extended):
    y = frame.made.to_numpy()
    p, q = frame[basic].to_numpy(), frame[extended].to_numpy()
    assert len(y) == record['attempts']
    u, v = (p-y)**2, (q-y)**2
    key = 'brier_context' if 'brier_context' in record else 'brier_distance'
    equal([u.mean(),v.mean()],[record[key],record['brier_form']])
    log = lambda j: -np.mean(y*np.log(j)+(1-y)*np.log1p(-j))
    equal([log(p),log(q)], [record['log_context' if key=='brier_context' else 'log_distance'],record['log_form']])
    equal(100*(u.sum()-v.sum())/u.sum(),record['gain_pct'])
    blocks = frame.assign(base_loss=u,delta=u-v).groupby(['season','scope','game_id'])[['base_loss','delta']].sum()
    assert len(blocks) == record['games']
    rng = np.random.default_rng(20261123)
    boot_base, boot_delta = np.zeros(2000), np.zeros(2000)
    for _, group in blocks.groupby(level=['season','scope']):
        n=len(group)
        weights = rng.multinomial(n,np.full(n,1/n),size=2000)
        boot_base += weights @ group.base_loss.to_numpy()
        boot_delta += weights @ group.delta.to_numpy()
    equal(np.percentile(100*boot_delta/boot_base,[2.5,97.5]),[record['low_pct'],record['high_pct']])


def load_raw(predictions):
    boxes = pd.read_csv(RESULTS/'team_game_audit.csv')
    coverage = pd.read_csv(OUT/'coverage.csv').set_index(['season','scope'])
    manifest = {r['filename']:r for r in json.loads(PIN.read_bytes())}
    frames = {}
    for year in YEARS:
        path = RAW/f'shots_{year}.csv'
        assert file_matches(path,manifest[path.name])
        raw = pd.read_csv(path,usecols=['game_id','score_value','type_text','coordinate_y_raw','coordinate_x_raw'])
        rows = pd.read_csv(DERIVED/f'shots_{year}.csv.gz',usecols=['game_id','source_row','scope','cell','distance_ft'])
        rows = rows[rows.scope.isin(['regular','playoffs'])].copy()
        teams = boxes[boxes.season.eq(year)].groupby('game_id').status.agg(list)
        games = set(teams[teams.map(lambda values: values == ['matches','matches'])].index)
        good=rows.game_id.isin(games)
        for phase,group in rows.groupby('scope'):
            ok = good.loc[group.index]
            kept=group.loc[ok & group.cell.ge(0)]
            c=coverage.loc[(year,phase)]
            assert [len(group),group.game_id.nunique(),int((~ok).sum()),int((ok & group.cell.lt(0)).sum()),
                    len(kept),kept.game_id.nunique()] == [c.source_shots,c.source_games,c.failing_boxes,
                    c.unmapped_after_boxes,c.eligible,c.eligible_games]
        rows = rows[good & rows.cell.ge(0)].copy()
        source = raw.iloc[rows.source_row.to_numpy()-2]
        equal(source.game_id,rows.game_id)
        rows['made'] = source.score_value.to_numpy() > 0
        rows['form'] = recorded_form(source.type_text)
        rows['x'],rows['y'] = 25-source.coordinate_x_raw.to_numpy(),source.coordinate_y_raw.to_numpy()
        rows['distance'] = np.hypot(rows.x,rows.y)
        equal(rows.distance,rows.distance_ft)
        rows['quarter'] = np.rint(4*rows.distance).astype(int)
        rows['season']=year
        for phase, group in rows.groupby('scope'):
            assert int(group.form.eq(UNKNOWN).sum()) == coverage.loc[(year,phase),'unknown_form']
        if year in SCORED:
            saved=predictions.loc[predictions.season.eq(year)].set_index('source_row').sort_index()
            ordered=rows.set_index('source_row').sort_index()
            assert saved.index.equals(ordered.index) and saved.scope.equals(ordered.scope)
            for field in ('game_id','distance_ft','made','form'):
                equal(saved[field].astype(float),ordered[field].astype(float))
        frames[year]=rows
    return frames


def verify_diagram(data, raw):
    raw = raw.assign(feet=np.floor(raw.distance+.5).astype(int))
    for band in data['diagram']:
        selected = raw[raw.feet.eq(band['feet'])]
        groups = selected.groupby('form').made.agg(['sum','size'])
        expect = {SHOT_TYPES[k]:(int(v['sum']),int(v['size'])) for k,v in groups.iterrows()}
        assert {r['name']:(r['makes'],r['attempts']) for r in band['rows']} == expect
        group = ['season','scope','x','y']
        lay = selected[selected.form.eq(1)].groupby(group).made.agg(['size','mean'])
        jump = selected[selected.form.eq(0)].groupby(group).made.agg(['size','mean'])
        both = lay.join(jump,lsuffix='_lay',rsuffix='_jump',how='inner').query('size_lay >= 5 and size_jump >= 5')
        shared = band['sameSpots']
        if both.empty:
            assert shared is None
            continue
        ln, jn = both.size_lay.sum(),both.size_jump.sum()
        assert (len(both),ln+jn,ln,jn) == (shared['strata'],shared['attempts'],shared['layup_n'],shared['jump_n'])
        wt = 1/(1/both.size_lay+1/both.size_jump)
        equal([(wt*both.mean_lay).sum()/wt.sum(),(wt*both.mean_jump).sum()/wt.sum()],
              [shared['layup_rate'],shared['jump_rate']])


def verify_sources(data, frames, predictions):
    reference_sources(False)
    linked=pd.read_csv(DERIVED/'shot_form_provider_links.csv.gz')
    assert not linked.duplicated(KEYS).any() and not linked.duplicated(['season','reference_row']).any()
    ids=crosswalk('player','wnba_player_id','espn_athlete_id','espn_full_name').espn_athlete_id
    summaries = pd.read_csv(OUT/'provider_agreement.csv')
    counts = pd.read_csv(OUT/'provider_coverage.csv')
    assert (counts.attempts == counts.incomplete_identity_or_clock+counts.ambiguous_rows+counts.no_unique_counterpart+counts.linked).all()
    assert (summaries.linked.sum(), summaries.same_form.sum(),summaries.same_family_with_aliases.sum()) == (
        len(linked),int(linked.form.eq(linked.reference_form).sum()),int(linked.form.eq(linked.alias_form).sum()))
    for year, g in linked.groupby('season'):
        e=pd.read_csv(RAW/f'shots_{year}.csv',usecols=['game_id','period_number','clock_display_value','athlete_id_1','type_text','score_value','team_id'])
        w=pd.read_csv(REFERENCE/f'shots_{year}.csv')
        es,ws=e.iloc[g.source_row.to_numpy()-2],w.iloc[g.reference_row.to_numpy()-2]
        sched=pd.read_csv(REFERENCE/f'wnba_schedule_crosswalk_{year}.csv').query('match_confidence == 1').set_index('wnba_game_id')
        games=sched.loc[ws.game_id]
        equal(games.espn_game_id,g.game_id)
        equal(es.game_id,g.game_id)
        equal(es.period_number,g.period_number)
        equal(ws.period,g.period_number)
        equal(es.athlete_id_1,ws.person_id.map(ids))
        equal(es.team_id.to_numpy()==games.home_espn_team_id.to_numpy(),g.home)
        equal(ws.team_id.to_numpy()==games.wnba_home_team_id.to_numpy(),g.home)
        eclock=es.clock_display_value.str.split(':',expand=True).astype(float)
        wclock=ws.clock.str.removeprefix('PT').str.removesuffix('S').str.split('M',expand=True).astype(float)
        for c in (eclock,wclock):
            equal(np.rint(100*(60*c[0]+c[1])),g.clock_cs)
        equal(recorded_form(es.type_text),g.form)
        equal(recorded_form(ws.sub_type),g.reference_form)
        expected=pd.Series(recorded_form(ws.sub_type),index=ws.index)
        expected.loc[ws.sub_type.str.lower().isin(['turnaround fadeaway shot','fadeaway bank shot'])]=0
        expected.loc[ws.sub_type.str.lower().eq('tip layup shot')]=4
        equal(expected,g.alias_form)
        equal(es.score_value.gt(0),g.made)
        equal(ws.shot_result.eq('Made'),g.reference_made)
        train=pd.concat([frames[k].query("scope=='regular'") for k in range(year-3,year)])
        matched=predictions.merge(g[KEYS+['reference_form','alias_form']],on=KEYS,validate='one_to_one')
        bins=np.rint(4*matched.distance_ft).astype(int).to_numpy()
        for provider, field in [('ESPN','form'),('WNBA Stats','reference_form'),('WNBA Stats with aliases','alias_form')]:
            _,matched['with_type']=independent_curves(train,bins,matched[field].to_numpy())
            for phase, by_phase in matched.groupby('scope'):
                row=next(r for r in data['sourceScores'] if (r['provider'],r['season'],r['scope'])==(provider,year,phase))
                verify_scores(by_phase,row,'p_distance','with_type')
    ref=data['reference']
    assert (ref['linked'],ref['agree'],ref['aliasAgree'],ref['resultAgree']) == (
        len(linked),int(linked.form.eq(linked.reference_form).sum()),int(linked.form.eq(linked.alias_form).sum()),
        int(linked.made.eq(linked.reference_made).sum()))
    for provider,field in [('ESPN','espnAttempts'),('WNBA Stats','wnbaAttempts')]:
        assert ref[field] == counts.loc[counts.provider.eq(provider),'attempts'].sum()


def main():
    data=json.loads((SITE/'shot-form.json').read_bytes())
    assert data['manifestSha256']==manifest_digest() and data['seasons']==list(SCORED)
    assert data['referenceManifestSha256']==digest(REFERENCE_PIN.read_text(encoding='utf-8').encode())
    pred=pd.read_csv(PREDICTIONS)
    assert not pred.duplicated(KEYS).any()
    frames=load_raw(pred)
    windows=pd.read_csv(OUT/'training_windows.csv').set_index('season')
    sensitivity=pd.read_csv(OUT/'sensitivity.csv')
    for year in SCORED:
        train=pd.concat([frames[k].query("scope=='regular'") for k in range(year-3,year)])
        sample=pred[pred.season.eq(year)].copy()
        assert windows.loc[year,'first_training_season']==year-3 and windows.loc[year,'last_training_season']==year-1
        assert len(train)==windows.loc[year,'training_attempts'] and train.game_id.nunique()==windows.loc[year,'training_games']
        assert windows.loc[year,'last_training_date']<windows.loc[year,'first_test_date']
        assert not set(train.game_id) & set(sample.game_id)
        for (band,prior), records in sensitivity[sensitivity.season.eq(year)].groupby(['bandwidth_ft','prior_attempts']):
            b,t=independent_curves(train,np.rint(4*sample.distance_ft).astype(int).to_numpy(),sample.form.to_numpy(),band,prior)
            if (band,prior)==(1,50):
                equal(b,sample.p_distance)
                equal(t,sample.p_form)
            for r in records.itertuples():
                mask=sample.scope.eq(r.scope)
                equal(np.mean((b[mask]-sample.made[mask])**2),r.brier_distance)
                equal(np.mean((t[mask]-sample.made[mask])**2),r.brier_form)
                assert mask.sum()==r.attempts
    for row in data['byYear']:
        verify_scores(pred[pred.season.eq(row['season']) & pred.scope.eq(row['scope'])],row,'p_distance','p_form')
    for scope,row in data['pooled'].items():
        verify_scores(pred if scope=='both' else pred[pred.scope.eq(scope)],row,'p_distance','p_form')
    verify_diagram(data,pd.concat([frames[k] for k in SCORED]))
    ctx=pd.read_csv(OUTPUT)
    old=pd.read_csv(SAVED,usecols=KEYS+['split','game_id','made',MODEL])
    old=old[old.split.isin(['test','playoffs'])]
    original=ctx.merge(old,on=KEYS+['split','game_id','made'],validate='one_to_one')
    assert len(original)==len(old)==len(ctx) and (original.baseline-original[MODEL+'_y']).abs().max()<1e-6
    for row in data['context']:
        verify_scores(ctx[ctx.scope.eq(row['scope'])],row,'baseline','with_form')
    verify_sources(data,frames,pred)
    certificate=dict(manifestSha256=data['manifestSha256'],referenceManifestSha256=data['referenceManifestSha256'],
        testSeasons=len(SCORED), rollingPredictions=len(pred), contextPredictions=len(ctx),
        auditedProviderLinks=data['reference']['linked'],distanceChoices=len(data['diagram']),
        independentlyCheckedSettings=int(sensitivity.groupby(['bandwidth_ft','prior_attempts']).ngroups))
    write_json(OUT/'verification.json',certificate)
    print('SHOT_FORM_VERIFIED',certificate,flush=True)


if __name__=='__main__':
    main()
