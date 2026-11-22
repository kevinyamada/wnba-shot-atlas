"""Describe the public shot sample and check sensitivity to disputed games."""
import json
from pathlib import Path

import pandas as pd

from build import DERIVED, RESULTS, SITE
from geometry import RULES, ZONES


def analyses(years):
    audit = pd.read_csv(RESULTS / 'team_game_audit.csv')
    results = []
    for year in years:
        rows = pd.read_csv(DERIVED / f'shots_{year}.csv.gz', low_memory=False)
        team_boxes = audit[audit.season.eq(year) & audit.scope.eq('regular')]
        matched = team_boxes[team_boxes.status.eq('matches')].groupby('game_id').size()
        regular = rows[rows.scope.eq('regular')]
        for sample_name, sample in [('all recorded', regular), ('both team boxes match', regular[regular.game_id.isin(matched[matched.eq(2)].index)])]:
            nearby = sample.depth_ft.ge(10) & sample.distance_ft.ge(RULES['eras'][0]['arc_radius']) & sample.distance_ft.lt(RULES['eras'][1]['arc_radius'])
            results.append(dict(season=year, sample=sample_name, games=sample.game_id.nunique(), attempts=len(sample),
                                makes=int(sample.made.sum()), points=int(sample.points.sum()), mapped=int(sample.cell.ge(0).sum()),
                                rim=int(sample.zone.eq(0).sum()), midrange=int(sample.zone.eq(2).sum()),
                                three_area=int(sample.zone.isin([3,4]).sum()), former_arc_band=int(nearby.sum()),
                                exact_rim=int(sample.rim_coordinate.sum()),
                                ambiguous_attempt_value=int(sample.attempt_value.isna().sum()),
                                games_with_team_boxes=int(team_boxes[team_boxes.box_attempts.notna()].game_id.nunique()),
                                box_attempts=int(team_boxes.box_attempts.sum()), box_three_attempts=int(team_boxes.box_three_attempts.sum())))
    df = pd.DataFrame(results)
    df['make_rate'] = df.makes / df.attempts
    df['points_per_attempt'] = df.points / df.attempts
    df['three_area_share'] = df.three_area / df.attempts
    df['midrange_share'] = df.midrange / df.attempts
    df['box_three_share'] = df.box_three_attempts / df.box_attempts
    df.to_csv(RESULTS / 'eda_by_season.csv', index=False)
    return df


def report(index, df):
    first, last = index['seasons'][0], index['seasons'][-1]
    a = df[df['sample'].eq('all recorded')].set_index('season')
    b = df[df['sample'].eq('both team boxes match')].set_index('season')
    era_a, era_b = a.loc[2012], a.loc[2013]
    cross = index['archiveComparison']
    totals = {name:sum(row[phase][name] for row in index['coverage'] for phase in ['regular','playoffs']) for name in ['attempts','makes','points','mapped','other_half','unknown']}
    text = f'''# WNBA Shot Atlas data review

The pinned files support {totals['attempts']:,} recorded field goal attempts in regular season games and playoffs from {first} through {last}. There were {totals['makes']:,} makes and {totals['points']:,} points from those attempts. The court displays {totals['mapped']:,} attempts. Another {totals['other_half']:,} came from the other half of the court and {totals['unknown']:,} have an unusable location. The three counts sum to the attempt total.

## What changed

- The share of recorded shots from the geometric three point area rose from {a.loc[first,'three_area_share']:.1%} in {first} to {a.loc[last,'three_area_share']:.1%} in {last}. It was {b.loc[first,'three_area_share']:.1%} and {b.loc[last,'three_area_share']:.1%} when limited to games matching both team boxes.
- The team boxes also show more attempts credited as threes. The share was {a.loc[first,'box_three_share']:.1%} in {first} and {a.loc[last,'box_three_share']:.1%} in {last}, across the available regular season boxes. The box share uses recorded three point attempts. The map share uses court geometry and can differ.
- To compare the space affected by the 2013 rule change, use the same physical band in both years. Among locations at least 10 feet in front of the rim and between the old and new arc radii, there were {int(era_a.former_arc_band):,} shots in 2012 and {int(era_b.former_arc_band):,} in 2013. The source coverage and other changes across seasons matter for interpreting this difference.

## Season coverage

Games matching both boxes is a count of games whose attempts, makes, and points from the floor agree for both teams. A missing or different box is documented in team_game_audit.csv. The explorer shows the recorded attempts and gives those coverage counts for each season.

| Season | Recorded regular games | Both boxes match | Attempts | Made | Field goal points | Make rate | Points per attempt |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
'''
    for year in index['coverage']:
        r = year['regular']
        text += f"| {year['season']} | {r['recorded_games']}/{r['scheduled_games']} | {r['matched_team_games']} | {r['attempts']:,} | {r['makes']:,} | {r['points']:,} | {r['makes']/r['attempts']:.1%} | {r['points']/r['attempts']:.3f} |\n"
    text += f'''
## Agreement with Data (1)

All {cross['exact_shots']:,} of the {cross['archive_attempts']:,} field goal attempts match the public file for 2025 across {cross['shared_games']} games. This comparison includes the game, period, clock, team, shooter, play type, makes, points, and both coordinates. The two files have the same upstream source, so agreement checks that the data were joined and interpreted consistently. Box score differences in recording individual shooters remain visible in the player audit.

The source coordinates are recorded at coarse precision. The exact rim coordinate can hold many shots at the same point. Near the three point line the recorded shot value and the geometric zone are separate fields. A shot inside a court area can have an uncertain attempt value, especially on a miss. Aggregates by geometric area preserve those attempts, and their observed points only count actual makes.
'''
    (RESULTS / 'eda.md').write_text(text, encoding='utf-8', newline='')
    print(json.dumps({'totals':totals,'early_three_area_share':a.loc[first,'three_area_share'],
                      'late_three_area_share':a.loc[last,'three_area_share'],
                      'early_box_three_share':a.loc[first,'box_three_share'],
                      'late_box_three_share':a.loc[last,'box_three_share'],
                      '2012_2013_fixed_footprint':[int(era_a.former_arc_band),int(era_b.former_arc_band)]}),flush=True)


if __name__ == '__main__':
    index = json.loads((SITE / 'index.json').read_bytes())
    summary = analyses(index['seasons'])
    report(index, summary)
    observed = summary[summary['sample'].eq('all recorded')].set_index('season')
    matched = summary[summary['sample'].eq('both team boxes match')].set_index('season')
    first, last = index['seasons'][0], index['seasons'][-1]
    def band(year):
        return dict(season=year, attempts=int(observed.loc[year,'former_arc_band']),
                    total=int(observed.loc[year,'attempts']), matched_attempts=int(matched.loc[year,'former_arc_band']),
                    matched_total=int(matched.loc[year,'attempts']))
    result = {'band': [band(2012), band(2013)], 'leagueThreeShare': [
        {'season': year, 'share': float(observed.loc[year,'box_three_share'])} for year in (first, last)
    ]}
    (SITE / 'findings.json').write_text(json.dumps(result, separators=(',', ':')) + '\n', encoding='utf-8', newline='')
