"""Check recorded shot families for the same events in ESPN and WNBA Stats."""
import json

import numpy as np
import pandas as pd

from build import DERIVED, SHOT_TYPES, crosswalk
from reference_audit import REFERENCE, reference_sources
from shot_form import OUT, PREDICTIONS, SCOPES, SETTINGS, cohort, curves, game_totals, recorded_form, score

MATCH_KEYS = ['game_id','period_number','home','clock_cs','player_id']


def clock_cs(series, pattern):
    fields = series.astype('string').str.extract(pattern).astype(float)
    seconds = fields[0]*60 + fields[1]
    return (100*seconds).round().astype('Int64')


def prepare(year, identities):
    schedule = pd.read_csv(REFERENCE / f'wnba_schedule_crosswalk_{year}.csv')
    schedule = schedule[schedule.match_confidence.eq(1)].dropna(subset=['espn_game_id','wnba_game_id'])
    assert schedule.espn_game_id.is_unique and schedule.wnba_game_id.is_unique
    espn = pd.read_csv(DERIVED/f'shots_{year}.csv.gz',usecols=['game_id','scope','period_number',
        'source_row','team_id','home_id','away_id','clock_display_value','player_id','type_text','made'])
    espn = espn[espn.scope.isin(SCOPES)].copy()
    espn['home'] = espn.team_id.eq(espn.home_id).where(espn.team_id.eq(espn.home_id)|espn.team_id.eq(espn.away_id))
    espn['clock_cs'] = clock_cs(espn.clock_display_value,r'^(\d+):(\d+(?:\.\d+)?)$')
    espn['form'] = recorded_form(espn.type_text)
    espn['player_id'] = espn.player_id.mask(espn.player_id.eq(0)).astype('Int64')

    wnba = pd.read_csv(REFERENCE/f'shots_{year}.csv').rename(columns={'game_id':'wnba_game_id','period':'period_number'})
    wnba['reference_row'] = wnba.index + 2
    wnba = wnba[wnba.shot_value.isin([2,3]) & wnba.shot_result.isin(['Made','Missed'])].copy()
    wnba['scope'] = wnba.wnba_game_id.astype(str).str[2].map({'2':'regular','4':'playoffs'})
    wnba = wnba[wnba.scope.isin(SCOPES)].merge(schedule[['wnba_game_id','espn_game_id','wnba_home_team_id',
        'wnba_away_team_id']],on='wnba_game_id',how='left',validate='many_to_one').rename(columns={'espn_game_id':'game_id'})
    wnba['home'] = wnba.team_id.eq(wnba.wnba_home_team_id).where(
        wnba.team_id.eq(wnba.wnba_home_team_id) | wnba.team_id.eq(wnba.wnba_away_team_id))
    wnba['player_id'] = wnba.person_id.map(identities).astype('Int64')
    wnba['clock_cs'] = clock_cs(wnba.clock,r'^PT(\d+)M(\d+(?:\.\d+)?)S$')
    wnba['reference_form'] = recorded_form(wnba.sub_type)
    # A separate sensitivity checks three literal WNBA names seen in the label audit.
    # Unspecified bank shots retain the default family. This mapping never sees ESPN's label.
    aliases = {'turnaround fadeaway shot': 0, 'fadeaway bank shot': 0, 'tip layup shot': 4}
    wnba['alias_form'] = wnba.sub_type.str.lower().map(aliases).fillna(wnba.reference_form).astype('int8')
    wnba['reference_made'] = wnba.shot_result.eq('Made').astype('int8')
    exclusions = []
    for provider, data in [('ESPN',espn),('WNBA Stats',wnba)]:
        valid = data[MATCH_KEYS].notna().all(axis=1)
        unique = ~data.duplicated(MATCH_KEYS,keep=False)
        data['linkable'] = valid & unique
        for scope, group in data.groupby('scope'):
            good = valid.loc[group.index]
            once = unique.loc[group.index]
            exclusions.append(dict(season=year,provider=provider,scope=scope,attempts=len(group),
                incomplete_identity_or_clock=int((~good).sum()), ambiguous_rows=int((good & ~once).sum()),
                eligible_to_link=int((good & once).sum())))
    e, w = espn[espn.linkable], wnba[wnba.linkable]
    linked = e.merge(w[MATCH_KEYS+['scope','reference_form','alias_form','sub_type','reference_row','reference_made']],on=MATCH_KEYS,
                     suffixes=('','_wnba'),validate='one_to_one')
    assert linked.scope.eq(linked.scope_wnba).all() and linked.reference_row.is_unique and linked.source_row.is_unique
    linked = linked.assign(season=year, agree=linked.form.eq(linked.reference_form),
                           alias_agree=linked.form.eq(linked.alias_form), result_agree=linked.made.eq(linked.reference_made))
    for row in exclusions:
        row['linked'] = int(linked.scope.eq(row['scope']).sum())
        row['no_unique_counterpart'] = row['eligible_to_link'] - row['linked']
    return linked, exclusions


def run():
    reference_sources(False)
    identities = crosswalk('player','wnba_player_id','espn_athlete_id','espn_full_name').espn_athlete_id
    identities = identities[~identities.duplicated(keep=False)]
    seasons = cohort()
    forecasts = pd.read_csv(PREDICTIONS)
    links, coverage, scores = [], [], []
    for year in (2025,2026):
        matched, counts = prepare(year,identities)
        coverage.extend(counts)
        links.append(matched)
        training = pd.concat([seasons[k].query("scope == 'regular'") for k in range(year-3,year)])
        basic, typed = curves(training,*SETTINGS[0])
        cols = ['season','source_row','game_id','scope','made','form']
        current = seasons[year].merge(matched[cols+['reference_form','alias_form']],on=cols,validate='one_to_one')
        current = current.merge(forecasts[cols+['p_distance','p_form']],on=cols,validate='one_to_one')
        b = current['bin'].to_numpy()
        assert np.allclose(current.p_distance,basic[b],rtol=0,atol=1e-12)
        assert np.allclose(current.p_form,typed[current.form,b],rtol=0,atol=1e-12)
        current['p_reference'] = typed[current.reference_form,b]
        current['p_alias'] = typed[current.alias_form,b]
        for provider, prob in [('ESPN','p_form'),('WNBA Stats','p_reference'),('WNBA Stats with aliases','p_alias')]:
            for scope,g in game_totals(current,'p_distance',prob).groupby(level='scope'):
                scores.append(dict(season=year,scope=scope,provider=provider,**score(g)))
    linked = pd.concat(links,ignore_index=True)
    linked.to_csv(DERIVED/'shot_form_provider_links.csv.gz',columns=['season','scope','source_row','reference_row',
        *MATCH_KEYS,'form','reference_form','alias_form','made','reference_made'],index=False)
    pd.DataFrame(coverage).to_csv(OUT/'provider_coverage.csv',index=False)
    pd.DataFrame(scores).to_csv(OUT/'provider_scores.csv',index=False)
    agreement = linked.groupby(['season','scope','made']).agg(linked=('source_row','size'),same_form=('agree','sum'),
        same_family_with_aliases=('alias_agree','sum'), same_result=('result_agree','sum')).reset_index()
    agreement.to_csv(OUT/'provider_agreement.csv',index=False)
    names = dict(enumerate(SHOT_TYPES))
    confusion = linked.assign(espn=linked.form.map(names), wnba=linked.reference_form.map(names))
    confusion.groupby(['season','scope','espn','wnba']).size().rename('attempts').to_csv(OUT/'provider_confusion.csv')
    linked[~linked.agree].groupby(['type_text','sub_type','alias_agree']).size().sort_values(
        ascending=False).rename('attempts').to_csv(OUT/'label_differences.csv')
    print('LINKAGE',json.dumps(coverage), 'AGREEMENT',int(linked.agree.sum()),len(linked),flush=True)


if __name__ == '__main__':
    run()
