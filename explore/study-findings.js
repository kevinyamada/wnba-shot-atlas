import { posteriorView } from './posterior.js?v=2';

const count = new Intl.NumberFormat('en-CA');
const format = (value, digits = 2) => Number(value).toFixed(digits);
const pct = value => `${format(100 * value, 1)}%`;
const cohorts = [
    ['test', '2026 regular season'],
    ['playoffs', '2026 playoffs'],
    ['validation', '2025 model selection']
];
const distance = 'Distance baseline';
const simpleNames = {
    'CatBoost context': 'CatBoost context',
    'XGBoost context': 'The context model',
    'Matérn GP': 'Smooth court model',
    'Five model average': 'Five model average',
    'Distance baseline': 'Distance only',
    'Distance outcomes': 'Distance only',
    'Stage average': 'Average for this situation',
    'Clock average': 'Average by time left',
    'Context boosting': 'Game context',
    'Markov': 'Play sequence model'
};

function el(tag, text, className) {
    const node = document.createElement(tag);
    if (text != null) node.textContent = text;
    if (className) node.className = className;
    return node;
}

function table(headers, entries) {
    const wrap = el('div', null, 'table-scroll');
    const node = el('table');
    const header = el('tr');
    for (const name of headers) {
        const th = el('th', name);
        th.scope = 'col';
        header.append(th);
    }
    const head = el('thead');
    head.append(header);
    const body = el('tbody');
    for (const entry of entries) {
        const tr = el('tr');
        entry.forEach((value, index) => {
            const cell = el(index === 0 ? 'th' : 'td', value);
            if (index === 0) cell.scope = 'row';
            tr.append(cell);
        });
        body.append(tr);
    }
    node.append(head, body);
    wrap.append(node);
    return wrap;
}

function details(label, ...contents) {
    const node = el('details');
    node.append(el('summary', label), ...contents);
    return node;
}

function picker(title, choices = cohorts) {
    const label = el('label', title, 'study-picker');
    const select = el('select');
    select.append(...choices.map(([value, name]) => new Option(name, value)));
    label.append(select);
    return {label, select};
}

function section(id, title) {
    const container = el('section', null, 'findings-section');
    const heading = el('h2', title);
    heading.id = id;
    container.setAttribute('aria-labelledby', id);
    container.append(heading);
    return container;
}

function arcSection(findings) {
    const a = findings.currentArc;
    const node = section('arc-title', 'Shots cluster just outside the arc');
    node.append(el('p', `In the 2026 regular season, players took ${count.format(a.outside)} shots in the first two feet outside the three point line and ${count.format(a.inside)} in the two feet inside. Per square foot, the outside strip got ${format(a.ratio, 1)} times as many shots.`));
    const strip = el('div', null, 'arc-strip');
    const maximum = Math.max(...findings.arcDensity.map(row => row.attempts_per_sqft));
    for (const row of findings.arcDensity) {
        const n = el('div', null, 'arc-bin');
        n.classList.toggle('outside', row.lower_ft >= 0);
        n.classList.toggle('near', row.lower_ft >= -2 && row.upper_ft <= 2);
        const bar = el('div', null, 'arc-bar');
        const fill = el('span');
        fill.style.height = `${100 * row.attempts_per_sqft / maximum}%`;
        fill.title = `${count.format(row.attempts)} attempts · ${format(row.attempts_per_sqft)} per square foot`;
        bar.append(fill);
        const label = `${String(row.lower_ft).replace('-', '−')} to ${String(row.upper_ft).replace('-', '−')}`;
        n.append(bar, el('span', label));
        strip.append(n);
    }
    strip.setAttribute('role', 'img');
    strip.setAttribute('aria-label', 'Shot attempts per square foot by distance from the three point line. Density jumps just outside the line.');
    const labels = el('div', null, 'arc-labels');
    labels.append(el('span', 'Feet inside the line'), el('span', 'Feet outside the line'));
    const [early, late] = findings.leagueThreeShare;
    node.append(strip, labels, details('See the counts and source checks',
        el('p', `Resampling games put the outside to inside ratio between ${format(a.lower)} and ${format(a.upper)}. Shifting each recorded location by up to half a foot per axis gave ratios between ${format(a.jitter_min)} and ${format(a.jitter_max)}.`),
        el('p', `Team box scores also show more threes. They accounted for ${pct(early.share)} of regular season attempts in the available ${early.season} boxes and ${pct(late.share)} in ${late.season}.`),
        table(['Offset from arc (ft)', 'Attempts', 'Attempts per sq ft'], findings.arcDensity.map(r => [
            `${String(r.lower_ft).replace('-', '−')} to ${String(r.upper_ft).replace('-', '−')}`,
            count.format(r.attempts), format(r.attempts_per_sqft)
        ]))
    ));
    return node;
}

function comparativeLine(record, baseline) {
    const delta = 100 * record.difference / baseline;
    if (Math.abs(delta) < .05) return 'about the same error as distance alone';
    return `${format(Math.abs(delta), 1)}% ${delta < 0 ? 'less' : 'more'} error than distance alone`;
}

function relativeChart(rows, baseline) {
    const chart = el('div', null, 'relative-chart');
    const scale = Math.max(baseline * .01, ...rows.flatMap(r => [Math.abs(r.lower), Math.abs(r.upper)])) * 1.1;
    const headers = el('div', null, 'relative-key');
    headers.append(el('span', 'Less error'), el('span', 'Same'), el('span', 'More error'));
    chart.append(headers);
    for (const row of rows) {
        const line = el('div', null, 'relative-row');
        line.append(el('span', simpleNames[row.model] || row.model));
        const area = el('div', null, 'relative-track');
        const interval = el('span', null, 'relative-interval');
        const point = el('span', null, 'relative-point');
        const position = value => 50 * (1 + value / scale);
        interval.style.left = `${position(row.lower)}%`;
        interval.style.width = `${position(row.upper) - position(row.lower)}%`;
        point.style.left = `${position(row.difference)}%`;
        area.append(interval, point);
        line.append(area, el('em', comparativeLine(row, baseline).replace(/ (than|as) distance alone$/, '')));
        chart.append(line);
    }
    return chart;
}

function shotSection(data, rules, surfaces, palette) {
    const node = section('prediction-title', 'How much does looking beyond distance help?');
    node.append(el('p', 'Distance gives two shots from 15 feet the same chance of going in. I compared that starting point with models that also use the spot on the court, the shooter, or the game situation.'));
    const {label, select} = picker('Games to compare');
    const target = el('div', null, 'finding-body');
    const surface = details('Explore the Bayesian court estimates',
        el('p', 'The Bayesian models let nearby spots share information, so a few shots in a quiet spot can borrow evidence from nearby. Select a square to see the estimate and its interval. The model fits 2022 to 2024 regular season shots.'),
        posteriorView(rules, surfaces, palette),
        el('p', 'The intervals describe uncertainty about the estimated make chance with the fitted smoothness fixed.')
    );
    node.append(label, target, surface);
    const spatial = [0, 2, 4].map(buffer => data.spatial.filter(r => r.buffer_ft === buffer).sort((a, b) => a.brier - b.brier));
    const shortest = el('div', null, 'spatial-findings');
    for (const run of spatial) {
        const winner = run[0];
        const base = run.find(r => r.model === distance);
        const box = el('div', null, 'spatial-result');
        box.append(el('span', `${winner.buffer_ft} ft gap`), el('strong', simpleNames[winner.model] || winner.model));
        if (winner.model !== distance) box.append(el('small', `${pct((base.brier - winner.brier) / base.brier)} less error than distance`));
        shortest.append(box);
    }
    node.append(details('Prediction in unfamiliar court areas',
        el('p', 'Each test hides one part of the court. The gap also removes training shots close to the hidden shots. This tests whether a model can predict from places it has never seen.'),
        shortest,
        table(['Gap (ft)', 'Model', 'Brier score'], spatial.flat().map(r => [r.buffer_ft, r.model, format(r.brier, 5)]))
    ));
    function render() {
        const split = select.value;
        const scores = data.shots.filter(r => r.split === split).sort((a, b) => a.brier - b.brier);
        const basic = scores.find(r => r.model === distance);
        const intervals = data.shotIntervals.filter(r => r.split === split && r.metric === 'Brier');
        const selection = intervals.find(r => r.model === data.shotSelected);
        const average = intervals.find(r => r.model === 'Five model average');
        const picked = el('p', `On ${count.format(basic.attempts)} shots, the five model average had ${comparativeLine(average, basic.brier)}. `
            + (average.lower <= 0 && average.upper >= 0
                ? 'Game to game variation leaves room for a tie.'
                : average.upper < 0 ? 'The improvement held up when games were resampled.' : 'The increase in error held up when games were resampled.'));
        const names = [...new Set(['Five model average', data.shotSelected, 'Matérn GP'])].filter(name => name !== distance);
        const selectedDescription = el('p', `${simpleNames[data.shotSelected] || data.shotSelected} had the lowest log loss in the 2025 model selection games. `
            + (selection.lower <= 0 && selection.upper >= 0 ? 'Its comparison with distance is compatible with a tie in the selected games.' : 'Its change in error held up when games were resampled.'));
        const results = details('See prediction scores and uncertainty',
            el('p', 'A dot shows the measured change in prediction error. An interval that reaches the centre leaves room for a tie.'),
            relativeChart(names.map(name => intervals.find(r => r.model === name)).filter(Boolean), basic.brier),
            selectedDescription,
            table(['Model', 'Brier score', 'Log loss'], scores.map(r => [r.model, format(r.brier, 5), format(r.log_loss, 5)])),
            el('p', 'The Brier score averages the squared difference between each predicted chance and the result. Lower scores are better. Models train on regular season games from 2022 to 2024. Settings come from 2025, and the 2026 scores use those fixed settings.')
        );
        const typeScores = data.shotTypeMetrics.filter(r => r.split === split
            && [distance, 'Five model average'].includes(r.model));
        const typeRows = typeScores.filter(r => r.model === distance).map(row => {
            const mean = typeScores.find(r => r.shot_type === row.shot_type && r.model === 'Five model average');
            return [row.shot_type, count.format(row.attempts), pct(row.makes / row.attempts),
                format(row.brier, 5), format(mean.brier, 5)];
        });
        results.append(details('See prediction scores by shot type',
            table(['Shot type', 'Attempts', 'Observed make rate', 'Distance Brier', 'Average Brier'], typeRows)));
        const points = data.pointModels.filter(r => r.split === split);
        const refits = data.refits.filter(r => r.split === split);
        results.append(details('Points per shot and refit checks',
            el('p', 'The points model predicts three outcomes from a shot, worth zero, two or three points. The table shows prediction errors in points.'),
            table(['Model', 'RMSE', 'Mean absolute error'], points.map(r => [r.model, format(r.rmse, 4), format(r.mae, 4)])),
            ...(refits.length ? [table(['Refit comparison', 'Original Brier', 'Refit Brier'],
                refits.map(r => [r.comparison, format(r.reference_brier, 5), format(r.expanded_brier, 5)]))] : [])
        ));
        target.replaceChildren(picked, results);
    }
    select.addEventListener('change', render);
    render();
    return node;
}

function possessions(data) {
    const node = section('miss-title', 'A miss doesn’t always end the chance');
    node.append(el('p', 'Some misses lead to another scoring opportunity. The event records follow each team’s turn through rebounds and free throws.'));
    const {label, select} = picker('Games to show');
    const target = el('div', null, 'finding-body');
    node.append(label, target);

    function render() {
        const choice = select.value;
        const group = data.flow.filter(row => row.split === choice);
        const total = group.reduce((n, row) => n + row.misses, 0);
        const points = group.reduce((n, row) => n + row.later_points, 0);
        const outcomes = el('div', null, 'miss-outcomes');
        const track = el('div', null, 'miss-track');
        track.setAttribute('aria-hidden', 'true');
        const rebound = group.find(row => row.rebound);
        const after = data.stateCounts.find(row => row.split === choice && row.stage === 'after_offensive_rebound');
        const ordered = [rebound, group.find(row => !row.rebound)];
        for (const row of ordered) {
            const part = el('span');
            part.classList.toggle('rebound', row.rebound);
            part.style.flexGrow = row.misses;
            track.append(part);
            const box = el('div', null, row.rebound ? 'miss-outcome rebound' : 'miss-outcome');
            const name = row.rebound ? 'Offensive rebound next' : 'Other next plays';
            box.append(el('h3', name),
                el('strong', `${pct(row.misses / total)} of misses`),
                el('p', `${format(row.later_points / row.misses)} more points on average`),
                el('p', `${count.format(row.scored_after)} of ${count.format(row.misses)} led to points in the same turn`, 'caption'));
            outcomes.append(box);
        }
        const chart = el('div', null, 'miss-flow');
        chart.append(el('h3', `${count.format(total)} recorded misses`), track, outcomes);
        const entry = data.possession.filter(row => row.split === choice && row.stage === 'entry').sort((a, b) => a.rmse - b.rmse);
        const refit = data.recoveryMetrics.filter(r => r.split === choice && r.cohort === 'all' && r.model === data.possessionSelected);
        const match = data.seasonReconstruction.find(r => r.season === (choice === 'validation' ? 2025 : 2026));
        const explanation = el('p', `After a miss, the team still scored ${format(points / total)} more points on average. From the moment of an offensive rebound, the team scored ${format(after.mean)} more points on average.`);
        target.replaceChildren(chart, explanation, details('See the remaining points models and source checks',
            el('p', `These averages describe what happened next in recorded sequences. The play order and score checks retained ${count.format(match.clean_periods)} of ${count.format(match.periods)} periods in ${match.season}.`),
            table(['Forecast at start of turn', 'RMSE', 'Mean absolute error'],
                entry.map(r => [simpleNames[r.model] || r.model, format(r.rmse, 4), format(r.mae, 4)])),
            el('p', `Waiting for a confirmed defensive rebound after an unusual play recovered ${count.format(data.recovery[0].entry_states)} turns across the forecast samples. Waiting for a second confirmed restart recovered ${count.format(data.recovery[1].entry_states)}.`),
            ...(refit.length ? [table(['Restart rule', 'Original fit RMSE', 'Refit RMSE'], refit.map(r => [
                r.policy === 'first_rebound' ? 'First confirmed restart' : 'Second confirmed restart',
                format(r.original_rmse, 4), format(r.expanded_rmse, 4)
            ]))] : [])
        ));
    }
    select.addEventListener('change', render);
    render();
    return node;
}

export function renderStudy(findings, data, rules, surfaces, palette) {
    const target = document.getElementById('public-study');
    target.replaceChildren(arcSection(findings), shotSection(data, rules, surfaces, palette), possessions(data));
    target.hidden = false;
    document.getElementById('study-status').textContent = '';
}
