"""Draw the figures for REPORT.md from the saved results."""
import json

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd

from build import RESULTS, SITE

OUT = RESULTS / 'report'
INK, NAVY, RUST, GREY, LINE = '#17243a', '#163e73', '#ad461f', '#4f5d72', '#d9dfe6'
plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 11, 'axes.edgecolor': LINE, 'axes.labelcolor': INK, 'text.color': INK,
                     'xtick.color': GREY, 'ytick.color': INK, 'axes.spines.top': False, 'axes.spines.right': False, 'figure.dpi': 150})


def save(figure, name):
    figure.tight_layout()
    figure.savefig(OUT / name, dpi=150, facecolor='white')
    plt.close(figure)


def shot_diet():
    areas = pd.read_csv(RESULTS / 'shot_mix/comparison_areas.csv')
    change = pd.read_csv(RESULTS / 'shot_mix/comparisons.csv').iloc[0]
    areas = areas[areas.comparison.eq(change.comparison)].iloc[:3]
    names, colours = ['Near the basket', 'Midrange', 'Threes'], [NAVY, GREY, RUST]
    figure, axis = plt.subplots(figsize=(8, 2.9))
    for row, (label, share, rate, total) in enumerate([(change['first'], 'share_before', 'points_per_shot_before', change.before),
                                                       (change.second, 'share_after', 'points_per_shot_after', change.after)]):
        left = 0
        for i, area in enumerate(areas.itertuples()):
            width = 100 * getattr(area, share)
            axis.barh(row, width, left=left, color=colours[i], edgecolor='white', linewidth=2, label=names[i] if row == 0 else None)
            axis.text(left + width / 2, row, f'{width:.0f}%\n{getattr(area, rate):.2f} a shot', ha='center', va='center', color='white', fontsize=10)
            left += width
        axis.text(101, row, f'{total:.2f} points\nper shot', va='center', fontsize=10)
    axis.set_yticks([0, 1], [change['first'], change.second])
    axis.invert_yaxis()
    axis.set_xlim(0, 118)
    axis.set_xticks([])
    axis.spines['bottom'].set_visible(False)
    axis.spines['left'].set_visible(False)
    axis.legend(ncols=3, frameon=False, loc='lower left', bbox_to_anchor=(0, 1))
    save(figure, 'shot_diet.png')


def repeatability():
    shots = pd.read_csv(RESULTS / 'teams/repeatability.csv').assign(kind='Shots')
    whole = pd.read_csv(RESULTS / 'teams/possession_repeatability.csv').assign(kind='Whole possessions')
    rows = pd.concat([shots, whole]).sort_values('split_half')
    figure, axis = plt.subplots(figsize=(8, 4.6))
    for i, row in enumerate(rows.itertuples()):
        colour = NAVY if row.kind == 'Shots' else RUST
        axis.plot([row.split_half_low, row.split_half_high], [i, i], color=colour, linewidth=2)
        axis.plot(row.split_half, i, 'o', color=colour, markersize=7)
    axis.set_yticks(range(len(rows)), rows.label)
    axis.set_xlim(0, 1)
    axis.set_xlabel('Correlation between alternating games of a team season')
    axis.grid(axis='x', color=LINE, linewidth=.8)
    axis.plot([], [], 'o-', color=NAVY, label='Shot measures')
    axis.plot([], [], 'o-', color=RUST, label='Whole possession measures')
    axis.legend(frameon=False, ncols=2, loc='lower left', bbox_to_anchor=(0, 1))
    save(figure, 'repeatability.png')


def ladder():
    data = json.loads((SITE / 'model-ladder.json').read_bytes())
    steps = [step for step in data['steps'] if step['step'] != 'League rate']
    base = data['summary']['league_brier']
    figure, axis = plt.subplots(figsize=(8, 3.4))
    removed = [100 * (1 - step['brier'] / base) for step in steps]
    axis.barh(range(len(steps)), removed, color=[NAVY] + [RUST] * (len(steps) - 1))
    for i, value in enumerate(removed):
        axis.text(value + .08, i, f'{value:.2f}%', va='center', fontsize=10)
    axis.set_yticks(range(len(steps)), ['Distance'] + ['+ ' + step['step'].lower() for step in steps[1:]])
    axis.invert_yaxis()
    axis.set_xlim(0, 10)
    axis.set_xlabel('Share of the error of a league rate forecast that is removed')
    axis.grid(axis='x', color=LINE, linewidth=.8)
    save(figure, 'information_ladder.png')


def prediction_error():
    table = pd.read_csv(RESULTS / 'prediction_2027/backtest.csv')
    figure, axis = plt.subplots(figsize=(8, 3.6))
    rules = [('rmse_league', 'League average', LINE), ('rmse_same', 'Same as last season', GREY), ('rmse_carried', 'Simple carry over', RUST), ('rmse_bayes', 'Bayesian season model', NAVY)]
    for k, (column, label, colour) in enumerate(rules):
        axis.bar([i + .2 * (k - 1.5) for i in range(len(table))], table[column] / table.rmse_league, width=.2, color=colour, label=label)
    axis.set_xticks(range(len(table)), [label.replace(' ', '\n', 1) if len(label) > 12 else label for label in table.label], fontsize=9)
    axis.set_ylim(.75, 1.02)
    axis.set_ylabel('Error against the league average rule')
    axis.legend(frameon=False, ncols=2, fontsize=9, loc='lower left')
    save(figure, 'prediction_error.png')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    shot_diet()
    repeatability()
    ladder()
    prediction_error()
    print('FIGURES_WRITTEN', sorted(path.name for path in OUT.glob('*.png')), flush=True)


if __name__ == '__main__':
    main()
