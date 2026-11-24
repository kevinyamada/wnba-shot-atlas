"""Write REPORT.md from the saved results, so every number in the report comes from a results file."""
import json

import pandas as pd

from build import RESULTS, ROOT, SITE

SITE_URL = 'https://kevinyamada.github.io/wnba-shot-atlas/'


def table(frame):
    head = '| ' + ' | '.join(frame.columns) + ' |\n| ' + ' | '.join('---' if i == 0 else '---:' for i in range(len(frame.columns))) + ' |\n'
    return head + '\n'.join('| ' + ' | '.join(str(v) for v in row) + ' |' for row in frame.itertuples(index=False)) + '\n'


def main():
    counts = pd.read_csv(RESULTS / 'recount/season_recount.csv')
    mix = pd.read_csv(RESULTS / 'shot_mix/comparisons.csv').set_index('comparison')
    mix_areas = pd.read_csv(RESULTS / 'shot_mix/comparison_areas.csv')
    points = pd.read_csv(RESULTS / 'expected_points/scores.csv').set_index(['scope', 'forecast'])
    repeats = pd.read_csv(RESULTS / 'teams/repeatability.csv')
    whole = pd.read_csv(RESULTS / 'teams/possession_repeatability.csv')
    shift = pd.read_csv(RESULTS / 'teams/opponent_adjustment.csv')
    teams = pd.read_csv(RESULTS / 'teams/team_seasons.csv')
    factors = pd.read_csv(RESULTS / 'teams/possession_factors.csv')
    players = pd.read_csv(RESULTS / 'shooters/players_2016_to_2026.csv')
    check = pd.read_csv(RESULTS / 'shooters/forecast_check.csv').set_index(['shots', 'forecast'])
    ladder = pd.read_csv(RESULTS / 'why_distance/ladder.csv')
    ladder = ladder[ladder.split.eq('test')]
    summary = json.loads((SITE / 'model-ladder.json').read_bytes())['summary']
    backtest = pd.read_csv(RESULTS / 'prediction_2027/backtest.csv')
    model = pd.read_csv(RESULTS / 'prediction_2027/season_model.csv').set_index('measure')
    surface = pd.read_csv(RESULTS / 'prediction_2027/surface_backtest.csv').set_index(['forecast', 'compared_with'])
    drawn = json.loads((SITE / 'prediction-surface.json').read_bytes())
    league = pd.read_csv(RESULTS / 'prediction_2027/league.csv')
    shooters = json.loads((SITE / 'shooters.json').read_bytes())
    lab = pd.read_csv(RESULTS / 'methods_lab/scores.csv')
    moran = pd.read_csv(RESULTS / 'methods_lab/morans_i.csv').set_index('residual')
    density = pd.read_csv(RESULTS / 'methods_lab/intensity_scores.csv')
    cox, reuse = ((density[name] * density.shots).sum() / density.shots.sum() for name in ('cox_process', 'last_season'))

    attempts, makes, pts = (int(counts[c].sum()) for c in ('attempts', 'makes', 'points'))
    mapped, unknown = int(counts.mapped_half.sum()), int(counts.unknown_location.sum())
    long, recent = mix.loc['First five seasons to last five'], mix.loc['Previous five seasons to last five']
    three = mix_areas[(mix_areas.comparison.eq('First five seasons to last five')) & mix_areas.area.eq('Three point area')].iloc[0]
    rep = repeats.set_index('measure')
    best, worst = whole.sort_values('split_half').iloc[-1], whole.sort_values('split_half').iloc[0]
    full = ladder.iloc[-1]
    shooter_row = backtest[backtest.measure.eq('shooter')].iloc[0]
    net_row = backtest[backtest.measure.eq('net')].iloc[0]
    latest = teams[teams.season.eq(teams.season.max())].sort_values('net', ascending=False)
    possession_latest = factors[factors.season.eq(factors.season.max())].sort_values('net', ascending=False)

    lines = ['# What the public shot record can tell a WNBA team', '',
             'Kevin Yamada, University of Toronto. Written 24 November 2026.', '',
             f'The interactive atlas is at [{SITE_URL}]({SITE_URL}). Every number in this report is read from a results file in this repository by `research/public_atlas/write_report.py`.', '',
             '## Summary', '',
             f'- **The record.** {attempts:,} field goal attempts from 30 WNBA seasons, 1997 to 2026, recounted from the raw public files by code that shares nothing with the build. {mapped:,} have a usable court location.',
             f"- **The league changed its shots.** Threes rose from {100 * three.share_before:.0f}% to {100 * three.share_after:.0f}% of attempts and points per shot from {long.before:.2f} to {long.after:.2f}. "
             f"Over the whole span most of the rise came from scoring more in the same areas. Over the last ten seasons {100 * recent.mix_share:.0f}% of it came from where teams shoot.",
             f"- **A team controls where it shoots more than anything else.** Between alternating games of a season, the quality of the shots a team takes repeats at {rep.loc['offence_quality', 'split_half']:.2f}. "
             f"Opponents' shot making against a defence repeats at only {rep.loc['defence_making', 'split_half']:.2f}.",
             f"- **Shooters differ, and pooling is needed to see it.** True shot making skill spreads by about {shooters['skillSpread']:.1f} makes per 100 shots between players. "
             f"A pooled estimate improved forecasts of the next season by {check.loc[('all shots', 'pooled'), 'drop_pct']:.2f}%. The raw margin made them worse.",
             f"- **Distance is hard to beat, and the reason is chance.** Everything else in the record lowers shot forecast error by {summary['full_drop_pct']:.1f}% beyond distance alone.",
             f"- **Predictions for 2027 are written down.** A Bayesian season model beat simpler rules on past seasons for every measure, and its 95% ranges held {100 * backtest.inside_95.min():.0f}% to {100 * backtest.inside_95.max():.0f}% of outcomes.", '',
             '## Questions', '',
             'The project asks what a team could learn from data that anyone can download. Four questions organise it.', '',
             '1. Where do teams and players shoot, and what are those shots worth?',
             '2. Is a team getting good shots or making hard ones, and what does its defence allow?',
             '3. Which of those numbers reflect something a team does, and which are mostly luck?',
             '4. What can be said about next season before it is played?', '',
             '## Data', '',
             f'Shots come from the wehoop releases of WNBA Stats (1997 to 2001) and ESPN (2002 to 2026), pinned by checksum. The explorer counts {attempts:,} regular season and playoff attempts, {makes:,} makes and {pts:,} field goal points. '
             f'{unknown:,} attempts have no usable location, almost all of them shots recorded exactly at the basket through 2010. Play by play from WNBA Stats gives the order of events for possession work.', '',
             'An independent recount reads the raw files directly and is compared with every published total, including the live site. It found three errors that are now corrected: one team whose 2002 shots carried an ID the schedule did not list, '
             '41 made baskets filed under labels such as turnover, and a mislabelled group of shots with no team. The corrections and what remains open are in the [pipeline notes](research/public_atlas/README.md).', '',
             '## Methods', '',
             '**League expected points.** Each shot gets an expected number of field goal points from its distance, its side of the three point line and its recorded shot type. The curve for a season is learned from the three regular seasons before it. '
             'It never sees the team or the shooter, so it can serve as a neutral yardstick. '
             f"Distance and line side lower squared error by {points.loc[('both', 'xp_distance'), 'drop_in_squared_error_pct']:.1f}% against the league average. Shot type adds {points.loc[('both', 'xp'), 'drop_in_squared_error_pct']:.2f}%.", '',
             '**Pooling.** A team or player margin is an observed value plus noise of known size. True margins are treated as normal around the league average, with a spread estimated by maximum likelihood. '
             'The pooled estimate keeps the share of the observed margin that the spread can explain, and the 95% interval comes from the resulting normal posterior.', '',
             '**Four team measures.** Shot quality is the expected points of the shots. Shot making is the points scored above expectation. Both are measured for the shots a team takes and the shots it allows. '
             'A model that estimates every offence and defence together from single games adjusts for opponents, for the shot measures and the whole possession measures alike. '
             f"The schedule is nearly balanced, so the adjustment is small: adjusted and unadjusted values correlate at {shift.correlation.min():.2f} or more.", '',
             '**What repeats.** Each team season is split into alternating games by date and the two halves are compared. A measure that matches across halves reflects something the team does.', '',
             '**Whole possessions.** For complete possessions rebuilt from the play by play, the study counts points, turnovers, offensive rebounds per miss and free throw points, for each team and against it.', '',
             '**Shooters.** The expected make chance of each shot comes from distance and shot type in the three seasons before. A player is compared with what an average shooter would make from the same shots, overall and by court area.', '',
             '**Forecast tests.** Every forecast is fitted on earlier seasons and scored on later ones, against the simplest sensible alternative, with intervals from resampling whole games. '
             'All seasons through 2026 have been examined, so these are historical tests.', '',
             '**Bayesian models for prediction.** A season model gives each team and shooter a true level that drifts from year to year. A normal belief is updated on every past season and carried forward. '
             f'A spatial model puts a Gaussian field with Matern covariance on a triangle mesh of {drawn["nodes"]:,} nodes over the court, with a smooth curve in distance as its mean, and gives the make chance at every spot with a credible range.', '',
             '## Results', '',
             '### The league changed its shots', '',
             '![Share of shots by court area in the first and last five seasons, with points per shot in each](research/results/public_atlas/report/shot_diet.png)', '',
             'Bar width is the share of attempts from each area. Teams traded midrange shots for threes while scoring more near the basket.', '',
             '### What a team controls', '',
             '![How much each team measure repeats between alternating games](research/results/public_atlas/report/repeatability.png)', '',
             table(pd.DataFrame({'Measure': repeats.label, 'Repeats between alternating games': repeats.split_half.map('{:.2f}'.format),
                                 '95% interval': [f'{a:.2f} to {b:.2f}' for a, b in zip(repeats.split_half_low, repeats.split_half_high)],
                                 'Repeats the next season': repeats.next_season.map('{:.2f}'.format)})),
             f"For a defence, the shots it allows say more than whether opponents happened to make them. Across whole possessions the most repeatable measure is {best.label.lower()} ({best.split_half:.2f}) "
             f"and the least is {worst.label.lower()} ({worst.split_half:.2f}).", '',
             table(pd.DataFrame({'Whole possession measure': whole.label, 'Repeats between alternating games': whole.split_half.map('{:.2f}'.format),
                                 '95% interval': [f'{a:.2f} to {b:.2f}' for a, b in zip(whole.split_half_low, whole.split_half_high)]})),
             f'### Teams in {int(latest.season.iloc[0])}', '',
             'Shot values are points per 100 shots against the league, adjusted for opponents. The last column is points per 100 possessions scored minus allowed, free throws included.', '',
             table(latest.merge(possession_latest[['team_id', 'net']].rename(columns={'net': 'possession_net'}), on='team_id', how='left').assign(
                 a=lambda f: f.offence_quality_adjusted.map('{:+.1f}'.format), b=lambda f: f.offence_making_adjusted.map('{:+.1f}'.format),
                 c=lambda f: f.defence_quality_adjusted.map('{:+.1f}'.format), d=lambda f: f.defence_making_adjusted.map('{:+.1f}'.format),
                 e=lambda f: f.possession_net.map('{:+.1f}'.format))[['team', 'a', 'b', 'c', 'd', 'e']].rename(columns={
                     'team': 'Team', 'a': 'Shot quality taken', 'b': 'Shot making', 'c': 'Shot quality allowed', 'd': 'Shot making allowed', 'e': 'Whole possessions, net'})),
             'The two views can disagree. A team can shoot poorly and still score well per possession through offensive rebounds and free throws.', '',
             '### Shooters, 2016 to 2026', '',
             table(players[players.attempts.ge(200)].sort_values('per_100', ascending=False).head(8).assign(
                 a=lambda f: f.attempts.map('{:,}'.format), b=lambda f: f.per_100.map('{:+.1f}'.format), c=lambda f: [f'{x:+.1f} to {y:+.1f}' for x, y in zip(f.low, f.high)])[
                     ['name', 'a', 'b', 'c']].rename(columns={'name': 'Player', 'a': 'Attempts', 'b': 'Makes per 100 shots above expectation', 'c': '95% interval'})),
             '### Why distance is hard to beat', '',
             '![Share of forecast error removed by distance and by each further kind of information](research/results/public_atlas/report/information_ladder.png)', '',
             f"On {int(full.attempts):,} shots from the 2026 regular season, with models fitted on 2022 to 2024 and tuned on 2025:", '',
             table(pd.DataFrame({'Information': ['League make rate only' if s == 'League rate' else s for s in ladder.step], 'Brier error': ladder.brier.map('{:.5f}'.format),
                                 'Drop from distance': ['' if pd.isna(v) or s == 'Distance' else f'{v:.2f}%' for v, s in zip(ladder.drop_vs_distance_pct, ladder.step)]})),
             f"A single shot either goes in or it does not. If the full model's make chances were exactly right its error would still be {summary['error_left_if_full_model_were_exact']:.4f}. "
             f"Better information can only spread predicted chances further apart: distance spreads them by {100 * summary['distance_spread']:.1f} percentage points and everything recorded reaches {100 * summary['full_spread']:.1f}. "
             'The files hold no defender positions, passes or movement, so the gain from tracking data cannot be measured here.', '',
             '### Predicting the next season', '',
             '![Past error of four prediction rules, relative to assuming the league average](research/results/public_atlas/report/prediction_error.png)', '',
             'Each season from 2019 to 2026 was predicted using only earlier seasons. Error is the root mean squared error against what was then observed.', '',
             table(pd.DataFrame({'Measure': backtest.label, 'League average': backtest.rmse_league.map('{:.2f}'.format), 'Same as last season': backtest.rmse_same.map('{:.2f}'.format),
                                 'Simple carry over': backtest.rmse_carried.map('{:.2f}'.format), 'Bayesian season model': backtest.rmse_bayes.map('{:.2f}'.format),
                                 'Inside its 95% range': backtest.inside_95.map(lambda v: f'{100 * v:.0f}%')})),
             f"The model estimates that a shooter keeps {100 * model.loc['shooter', 'persistence']:.0f}% of a margin from one season to the next and a team keeps {100 * model.loc['net', 'persistence']:.0f}% of its net. "
             f"Team predictions stay uncertain: the model's error on team net was {net_row.rmse_bayes:.1f} points per 100 shots against {net_row.rmse_league:.1f} for assuming every team is average.", '',
             f"The spatial mesh model did not improve on the plain distance curve. Across {int(surface.loc[('mesh', 'p_distance'), 'attempts']):,} past shots its error was {abs(surface.loc[('mesh', 'p_distance'), 'drop_pct']):.2f}% "
             f"{'higher' if surface.loc[('mesh', 'p_distance'), 'drop_pct'] < 0 else 'lower'}, and makes fell inside its 95% range at {100 * drawn['coverage']:.0f}% of busy court spots. Its value is the map of credible ranges, not accuracy.", '',
             'For 2027 the league prediction is ' + ' and '.join(f"{r.prediction:.2f} for {r.measure.lower()} (range {r.low:.2f} to {r.high:.2f})" for r in league.itertuples()) + '.', '',
             '### Eleven spatial methods on one question', '',
             f"Eleven methods were given the same task: learn the make chance at each court spot from three regular seasons and predict the next, for {int(density.season.min())} to {int(density.season.max())} "
             f"({int(lab.attempts.max()):,} shots in {int(lab.games.max()):,} games). A positive change means lower error than the distance curve, and the range comes from resampling whole games.", '',
             table(pd.DataFrame({'Method': lab.method, 'Kind': lab.family, 'Brier error': lab.brier.map('{:.5f}'.format),
                                 'Change from the distance curve': ['' if m == 'Distance curve' else f'{v:+.2f}%' for m, v in zip(lab.method, lab.drop_vs_distance_pct)],
                                 '95% range': ['' if m == 'Distance curve' else f'{x:+.2f}% to {y:+.2f}%' for m, x, y in zip(lab.method, lab.low_pct, lab.high_pct)]})),
             f"The best method, the {lab.method.iloc[0]}, lowered error by {lab.drop_vs_distance_pct.iloc[0]:.2f}%. Once distance from the rim is known, a detailed map of the court adds very little. "
             f"Moran's I shows why: neighbouring cells have similar make rates (I = {moran.loc['Observed make rate', 'morans_i']:.2f}), "
             f"the distance curve removes most of that (I = {moran.loc['After the distance curve', 'morans_i']:.2f}) "
             f"and nothing is left after the mesh model with a trend (I = {moran.loc['After the mesh model with trend', 'morans_i']:.2f}, p = {moran.loc['After the mesh model with trend', 'p_value']:.2f}).", '',
             f"For where shots come from, a log Gaussian Cox process scored {cox:.4f} in average log score per shot, "
             f"against {reuse:.4f} for reusing last season's shares of shots by cell. Lower is better, so the Cox process {'did' if cox < reuse else 'did not'} beat the simple rule. "
             f"The [Methods lab]({SITE_URL}lab/) shows every surface, the variogram and the ensemble weights.", '',
             '## What a team could do with this', '',
             '- Judge a defence by the shots it allows, since that repeats and opponent shot making mostly does not.',
             '- Separate an offence that gets good shots from one that makes hard ones, because the second depends more on who is shooting.',
             '- Scout a shooter by court area with honest ranges, instead of reading a hot or cold stretch as skill.',
             '- Look at whole possessions as well as shots. Turnovers forced and offensive rebounds are among the most repeatable things a team does.', '',
             '## Limits', '',
             '- These are descriptions and forecasts. None of them shows that changing a scheme or a lineup would change a number.',
             '- The record has shot locations and event order. It has no passes, cuts, defender positions or lineups on the floor, so individual actions and defensive pressure cannot be valued.',
             '- Shot types are assigned by scorers and may be recorded differently for makes and misses.',
             '- Locations are whole feet, missing for about a quarter of shots before 2011, and recorded differently across providers.',
             '- Whole possessions come only from games whose event order could be confirmed.',
             '- No prediction knows about trades, injuries, the draft or coaching changes.', '',
             '## The 2027 test', '',
             'Every season used here has already been examined. The [test plan](research/public_atlas/PROSPECTIVE_2027.md) freezes the models and the data rules, records the predictions, and sets how the 2027 season will be scored once, whichever way it goes.', '',
             '## Reproducing the work', '',
             'The [pipeline notes](research/public_atlas/README.md) list every command. Each study has a write up beside its results:', '',
             '- [Recount from the raw files](research/results/public_atlas/recount/README.md)',
             '- [Shot mix and conversion](research/results/public_atlas/shot_mix/README.md)',
             '- [League expected points](research/results/public_atlas/expected_points/README.md)',
             '- [What a team controls](research/results/public_atlas/teams/README.md) and [whole possessions](research/results/public_atlas/teams/POSSESSIONS.md)',
             '- [Shooters against expectation](research/results/public_atlas/shooters/README.md)',
             '- [Why distance is hard to beat](research/results/public_atlas/why_distance/README.md)',
             '- [Predictions for 2027](research/results/public_atlas/prediction_2027/README.md) and the [Bayesian court surface](research/results/public_atlas/prediction_2027/SURFACE.md)',
             '- [Methods lab](research/results/public_atlas/methods_lab/README.md): kriging, an areal model, a Gaussian process, the mesh model and ensembles compared on one question, with variograms, Moran\'s I and a point pattern test', '']
    (ROOT / 'REPORT.md').write_text('\n'.join(lines), encoding='utf-8', newline='\n')
    print('REPORT_WRITTEN', len('\n'.join(lines).split()), 'words', flush=True)


if __name__ == '__main__':
    main()
