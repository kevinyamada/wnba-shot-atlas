"""Publish the shot form comparison, its denominator checks and the chart data."""
import json

import numpy as np
import pandas as pd

from build import DERIVED, SHOT_TYPES, SITE, write_json
from fetch import digest
from reference_audit import PIN as REFERENCE_PIN
from shot_form import DIAGRAM_FEET, OUT, PREDICTIONS, SCORED


def at_same_spots(predictions):
    # Compare both families with an identical mix of seasons, phases and recorded coordinates.
    located = []
    for year, group in predictions.groupby('season'):
        xy = pd.read_csv(DERIVED / f'shots_{year}.csv.gz', usecols=['source_row','lateral_ft','depth_ft'])
        rows = group.merge(xy,on='source_row',validate='one_to_one')
        assert len(rows) == len(group)
        located.append(rows)
    frame = pd.concat(located, ignore_index=True)
    frame['feet'] = np.floor(frame.distance_ft+.5).astype(int)
    types = frame.assign(shot_type=frame.form.map(dict(enumerate(SHOT_TYPES))))
    types.groupby(['season','scope','shot_type']).made.agg(attempts='size',makes='sum').to_csv(OUT/'families.csv')
    frame = frame[frame.form.isin([0,1]) & frame.feet.isin(DIAGRAM_FEET)]
    strata = ['feet','season','scope','lateral_ft','depth_ft','form']
    strata_counts = frame.groupby(strata).made.agg(['size','sum']).unstack('form')
    strata_counts = strata_counts.loc[:, [('size',0),('size',1),('sum',0),('sum',1)]]
    strata_counts.columns = ['jump_n','layup_n','jump_makes','layup_makes']
    shared = strata_counts.dropna().query('jump_n >= 5 and layup_n >= 5').copy()
    shared['weight'] = shared.jump_n * shared.layup_n / (shared.jump_n + shared.layup_n)
    result = {}
    for feet,spots in shared.groupby(level='feet'):
        result[int(feet)] = dict(strata=len(spots), attempts=int((spots.jump_n+spots.layup_n).sum()),
            layup_n=int(spots.layup_n.sum()), jump_n=int(spots.jump_n.sum()),
            layup_rate=float(np.average(spots.layup_makes/spots.layup_n,weights=spots.weight)),
            jump_rate=float(np.average(spots.jump_makes/spots.jump_n,weights=spots.weight)))
    pd.DataFrame([dict(feet=k,**v) for k,v in result.items()]).to_csv(OUT/'matched_spots.csv',index=False)
    return result


def main():
    data = json.loads((DERIVED/'shot_form_rolling.json').read_bytes())
    predictions = pd.read_csv(PREDICTIONS)
    matched = at_same_spots(predictions)
    for band in data['diagram']:
        band['sameSpots'] = matched.get(band['feet'])
    agreements = pd.read_csv(OUT/'provider_agreement.csv')
    coverage = pd.read_csv(OUT/'provider_coverage.csv')
    context = pd.read_csv(OUT/'context.csv').to_dict('records')
    providers = pd.read_csv(OUT/'provider_scores.csv')
    link = dict(linked=int(agreements.linked.sum()), agree=int(agreements.same_form.sum()),
                aliasAgree=int(agreements.same_family_with_aliases.sum()), resultAgree=int(agreements.same_result.sum()),
                espnAttempts=int(coverage.loc[coverage.provider.eq('ESPN'),'attempts'].sum()),
                wnbaAttempts=int(coverage.loc[coverage.provider.eq('WNBA Stats'),'attempts'].sum()))
    data.update(context=context, reference=link, referenceManifestSha256=digest(
        REFERENCE_PIN.read_text(encoding='utf-8').encode()), sourceScores=providers.to_dict('records'))
    write_json(SITE/'shot-form.json',data)
    r = data['pooled']['both']
    example = next(b for b in data['diagram'] if b['feet']==4)
    lookup = {row['name']:row for row in example['rows']}
    lay, jump = lookup['Layup'], lookup['Jump shot']
    def fmt_row(r):
        return f"{r['makes']:,} of {r['attempts']:,} ({r['makes']/r['attempts']:.1%})"
    sensitivity = pd.read_csv(OUT/'sensitivity.csv')
    paired = sensitivity.groupby(['bandwidth_ft','prior_attempts'])
    def improvement(g):
        return 100 * (1 - (g.brier_form*g.attempts).sum() / (g.brier_distance*g.attempts).sum())
    robustness = [improvement(g) for _,g in paired]
    same = example['sameSpots']
    assert same is not None
    year_wins = sum(row['gain_pct']>0 for row in data['byYear'] if row['scope']=='regular')
    playoff_wins = sum(row['gain_pct']>0 for row in data['byYear'] if row['scope']=='playoffs')
    lines = [
        '# What shot type adds to distance', '',
        f"From 3.5 feet up to 4.5 feet, players made {fmt_row(lay)} layups and {fmt_row(jump)} jump shots. "
        f"Giving both groups the same mix of court spots, seasons and game types produced make rates of "
        f"{same['layup_rate']:.1%} and {same['jump_rate']:.1%} across {same['strata']:,} shared groups.",
        '',
        f"On {r['attempts']:,} shots in {r['games']:,} future games across {len(SCORED)} season tests, "
        f"adding the recorded shot type reduced Brier error by {r['gain_pct']:.2f}%. "
        f"The paired 95% interval was {r['low_pct']:.2f}% to {r['high_pct']:.2f}%. "
        f"Average error fell in {year_wins} of {len(SCORED)} regular seasons and {playoff_wins} of {len(SCORED)} playoffs.",
        '', '| Test | Attempts | Distance Brier | With shot type | Relative drop in error | 95% interval |',
        '| :--- | ---: | ---: | ---: | ---: | :--- |']
    for phase in ['regular','playoffs']:
        v = data['pooled'][phase]
        lines.append(f"| {phase.capitalize()} | {v['attempts']:,} | {v['brier_distance']:.6f} | {v['brier_form']:.6f} "
                     f"| {v['gain_pct']:.2f}% | {v['low_pct']:.2f}% to {v['high_pct']:.2f}% |")
    lines += ['', '## How the comparison works', '',
        'The first training season is 2013, when the current three point arc began. Each test from 2016 through 2026 uses the preceding three regular seasons for training. Both models see the same eligible shots in each test season. A shot needs verified coordinates on the attacking half and matching attempt, make and field goal point totals for both teams in its game. The coverage table accounts separately for each exclusion.',
        '',
        'The distance model estimates make rate on a quarter foot grid. A Gaussian kernel with a one foot bandwidth gives nearer training shots more weight. Each estimate also borrows four attempts at the overall training rate. The second model estimates the same curve separately for each recorded shot family and borrows 50 attempts at the distance rate. A type with little evidence stays close to the distance estimate. A missing or generic label gets the distance estimate directly. Only the recorded action name determines the family. Descriptions, scoring flags, awarded points and assists never enter the predictors.',
        '',
        'The primary score is the mean squared error of the predicted make chance (Brier score). Relative reduction is 100 times one minus the ratio of the two Brier scores. Intervals use 2,000 paired resamples of whole games within each season and phase, conditional on the fitted curves. The analysis uses previously examined public seasons. A future season would provide a prospective check.',
        '',
        f"Across bandwidths of 0.5, 1 and 2 feet and prior counts of 20, 50 and 100 varied one at a time, the pooled reduction ranged from {min(robustness):.2f}% to {max(robustness):.2f}%. Log loss and calibration bins are available with the scores.",
        '',
        'The figure rounds each recorded distance to the nearest whole foot, grouping the lower bound inclusively and the upper bound exclusively. The shared spot check keeps only season, phase and exact coordinate combinations with at least five layups and five jumpers. It weights each combination by the product of the two counts divided by their sum. These observations describe shots players took. Defense, shot selection and the way scorers assign shot types can affect the comparison.',
        '', '## A model that already knows the shooter', '',
        'The earlier context model uses court location, player, team, game clock and the shooter’s prior record. Both versions use the same 2022 to 2024 training attempts and the same tree depth chosen in 2025. The extension adds the shot family with all other settings held fixed. The baseline reproduces the original saved probabilities within one millionth. Here the denominator for the percentage change is the context model’s Brier score.',
        '', '| 2026 games | Shots | Context Brier | With type | Relative drop in error | 95% interval |',
        '| :--- | ---: | ---: | ---: | ---: | :--- |']
    for v in context:
        lines.append(f"| {v['scope'].capitalize()} | {v['attempts']:,} | {v['brier_context']:.6f} | {v['brier_form']:.6f} "
                     f"| {v['gain_pct']:.2f}% | {v['low_pct']:.2f}% to {v['high_pct']:.2f}% |")
    lines += ['', '## Agreement between the two feeds', '',
        f"Across 2025 and 2026, {link['linked']:,} attempts linked uniquely out of {link['espnAttempts']:,} ESPN attempts and "
        f"{link['wnbaAttempts']:,} WNBA Stats attempts. The shot family agreed for {link['agree']:,} ({link['agree']/link['linked']:.2%}) and the make or miss agreed for {link['resultAgree']:,}.",
        '',
        'An event must have the same game, period, team side, clock to the recorded hundredth and uniquely mapped shooter in both releases. Duplicate keys are excluded on both sides. Type, result and coordinates play no part in matching. A second check substitutes the WNBA Stats type on the same linked evaluation shots while holding the ESPN location, model and observed result fixed. The releases cover the same games and can share underlying scoring decisions. They do not supply tracking data or defense at release.',
        '',
        f"A sensitivity check harmonizes three literal WNBA names after reviewing the recorded terms. Tip Layup Shot is treated as a tip. Turnaround Fadeaway shot and Fadeaway Bank shot are treated as jump shots. This brings agreement to {link['aliasAgree']:,} of {link['linked']:,} ({link['aliasAgree']/link['linked']:.2%}). Other bank shots with unspecified form keep the original coding. This naming check changes only the second source comparison.",
        '', '| Matched test shots | Attempts | ESPN reduction | WNBA Stats reduction | WNBA with aliases |',
        '| :--- | ---: | ---: | ---: | ---: |']
    for (year,scope), group in providers.groupby(['season','scope']):
        provider_rows = group.set_index('provider')
        v = provider_rows.gain_pct
        lines.append(f"| {year} {scope} | {int(group.attempts.iloc[0]):,} | {v['ESPN']:.2f}% | {v['WNBA Stats']:.2f}% | {v['WNBA Stats with aliases']:.2f}% |")
    lines += ['', '## Supporting tables', '',
        '[Season scores](by_season.csv) · [Training windows](training_windows.csv) · [Coverage](coverage.csv) · [Shot families](families.csv) · [Shared spots](matched_spots.csv) · [Calibration](calibration.csv) · [Sensitivity](sensitivity.csv) · [Context comparison](context.csv) · [Event matching](provider_coverage.csv) · [Source agreement by result](provider_agreement.csv) · [Family disagreements](provider_confusion.csv) · [Recorded labels](label_differences.csv) · [Scores using both sources](provider_scores.csv)']
    (OUT/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf-8',newline='')
    print('FORM_PUBLICATION',r,link,same,flush=True)


if __name__ == '__main__':
    main()
