import { paintCourt, canvasSquare } from './drawing.js?v=7';

const $ = id => document.getElementById(id);
const count = new Intl.NumberFormat('en-CA');
const pct = value => (100 * value).toFixed(1) + '%';
const fonts = 'system-ui, sans-serif';

function el(tag, text, className) {
    const node = document.createElement(tag);
    if (text != null) node.textContent = text;
    if (className) node.className = className;
    return node;
}

function palette() {
    const css = getComputedStyle(document.documentElement);
    return Object.fromEntries(['ink', 'muted', 'line', 'deep', 'accent', 'court', 'court-alt', 'court-line', 'historic-line', 'earliest-line', 'colour-min', 'colour-mid', 'colour-max', 'surface']
        .map(name => [name, css.getPropertyValue('--' + name).trim()]));
}

function table(headings, rows) {
    const node = el('table');
    const head = node.createTHead().insertRow();
    for (const text of headings) head.append(Object.assign(el('th', text), {scope: 'col'}));
    const body = node.createTBody();
    for (const values of rows) {
        const row = body.insertRow();
        values.forEach((text, i) => row.append(i ? el('td', text) : Object.assign(el('th', text), {scope: 'row'})));
    }
    const wrap = el('div', null, 'table-scroll');
    wrap.append(node);
    return wrap;
}

// A small chart of points and lines. Each series is {points: [[x, y]], line: [[x, y]], colour}.
function chart(canvas, series, xLabel, yLabel) {
    const width = canvas.clientWidth, height = canvas.clientHeight;
    if (!width || !height) return;
    const ratio = Math.min(devicePixelRatio || 1, 2);
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    const ctx = canvas.getContext('2d');
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, height);
    const p = palette();
    const all = series.flatMap(s => [...(s.points ?? []), ...(s.line ?? [])]);
    const xMax = Math.max(...all.map(v => v[0])), yMax = Math.max(...all.map(v => v[1])) * 1.08;
    const left = 52, right = width - 12, top = 10, bottom = height - 38;
    const x = v => left + (right - left) * v / xMax, y = v => bottom - (bottom - top) * v / yMax;
    ctx.font = `12px ${fonts}`;
    ctx.fillStyle = p.muted;
    ctx.strokeStyle = p.line;
    ctx.textBaseline = 'middle';
    ctx.textAlign = 'right';
    for (let i = 0; i <= 4; i++) {
        const value = yMax * i / 4;
        ctx.beginPath();
        ctx.moveTo(left, y(value));
        ctx.lineTo(right, y(value));
        ctx.stroke();
        ctx.fillText(value >= 10 ? value.toFixed(0) : value.toFixed(2), left - 6, y(value));
    }
    ctx.textAlign = 'center';
    for (let i = 0; i <= 5; i++) ctx.fillText((xMax * i / 5).toFixed(0), x(xMax * i / 5), bottom + 12);
    ctx.fillText(xLabel, (left + right) / 2, height - 8);
    ctx.save();
    ctx.translate(12, (top + bottom) / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText(yLabel, 0, 0);
    ctx.restore();
    for (const s of series) {
        ctx.strokeStyle = ctx.fillStyle = p[s.colour];
        ctx.lineWidth = 2;
        ctx.setLineDash(s.dash ?? []);
        if (s.line) {
            ctx.beginPath();
            s.line.forEach(([a, b], i) => i ? ctx.lineTo(x(a), y(b)) : ctx.moveTo(x(a), y(b)));
            ctx.stroke();
        }
        ctx.setLineDash([]);
        for (const [a, b] of s.points ?? []) {
            ctx.beginPath();
            ctx.arc(x(a), y(b), 3.5, 0, 2 * Math.PI);
            ctx.fill();
        }
    }
}

const plainWords = {
    'League rate': 'Every shot gets the same chance: the league average.',
    'Distance curve': 'The chance depends only on how far the shot is from the rim.',
    'Inverse distance weighting': 'Each spot takes the average of the spots around it, and closer spots count for more.',
    'Ordinary kriging': 'A weighted average of nearby spots, where the weights come from how quickly make rates change across the court.',
    'Universal kriging': 'The distance curve first, then kriging on whatever distance leaves over.',
    'Areal CAR model': 'The court is cut into squares and each square borrows from the squares that touch it.',
    'Gaussian process': 'One smooth surface over the whole court, built on the idea that nearby spots are alike.',
    'SPDE mesh field': 'The same smooth surface, built on a net of triangles so that it is quick to fit.',
    'SPDE mesh with trend': 'The distance curve plus a net of triangles that picks up what distance misses.',
    'Simple average': 'The plain average of six of the methods.',
    'Stacked ensemble': 'A weighted average of the same six methods, which gives more say to the ones that did well the season before.',
};

function scoreboard(data) {
    const section = el('section', null, 'headline');
    const distance = data.methods.find(row => row.method === 'Distance curve');
    const best = data.methods[0];
    section.append(el('h2', 'Which method predicts best?'),
        el('p', `Each method learned from three regular seasons and was scored on the next, for ${data.tested[0]} to ${data.tested.at(-1)}: ${count.format(data.attempts)} shots. `
            + `${best.method} had the lowest error. Nothing moved far from the plain distance curve, at ${distance.brier.toFixed(5)}. In plain words: once you know how far a shot is from the rim, a more detailed map of the court adds very little.`));
    const limit = .3;
    const board = el('div', null, 'relative-chart');
    board.id = 'lab-scores';
    const key = el('div', null, 'relative-key');
    key.append(el('span', `${limit}% worse`), el('span', 'Distance curve'), el('span', `${limit}% better`));
    board.append(key);
    const at = value => 50 + 50 * Math.max(-1, Math.min(1, value / limit));
    for (const row of data.methods) {
        const line = el('div', null, 'relative-row');
        line.dataset.method = row.method;
        line.title = `${plainWords[row.method] ?? ''} ${row.description}`.trim();
        const name = el('span', row.method);
        name.append(el('small', row.family));
        const track = el('div', null, 'relative-track');
        const interval = el('span', null, 'relative-interval');
        const point = el('span', null, 'relative-point');
        interval.style.left = at(row.low_pct) + '%';
        interval.style.width = (at(row.high_pct) - at(row.low_pct)) + '%';
        point.style.left = at(row.drop_vs_distance_pct) + '%';
        track.append(interval, point);
        line.append(name, track, el('em', row.brier.toFixed(5)));
        board.append(line);
    }
    section.append(board, el('p', 'Each dot is the change in Brier error against the distance curve, with a 95% range from resampling whole games. Right is better. The number is the Brier error itself, where lower is better. The league rate sits far off the left edge.', 'caption'));
    return section;
}

function surfaces(data, rules) {
    const section = el('section', null, 'headline');
    section.append(el('h2', `What each method predicts for ${data.season}`));
    const view = el('div', null, 'posterior-view');
    view.id = 'lab-surface';
    const court = el('div', null, 'posterior-court');
    const canvas = el('canvas');
    canvas.tabIndex = 0;
    canvas.setAttribute('aria-label', 'Predicted make chance by court spot. Use the arrow keys to move.');
    court.append(canvas);
    const aside = el('div', null, 'posterior-aside');
    const label = el('label', 'Method');
    const select = el('select');
    select.id = 'lab-method';
    for (const row of data.methods) select.append(new Option(row.method, row.method));
    select.value = 'SPDE mesh with trend';
    label.append(select);
    const about = el('p', null, 'caption');
    const spot = el('p');
    spot.id = 'lab-spot';
    const all = el('div');
    all.id = 'lab-spot-all';
    aside.append(label, about, spot, all);
    view.append(court, aside);
    const grid = {baseline: -rules.rim_from_baseline, midcourt: rules.length / 2 - rules.rim_from_baseline, size: 1, cols: rules.width, rows: rules.length / 2};
    const cols = data.grid.cols;
    const cell = (name, square) => data.surfaces[name][Math.floor(square / grid.cols) * cols + square % grid.cols];
    let selected = 15 * grid.cols + 25;

    function draw() {
        if (!canvas.clientWidth) return;
        const name = select.value;
        const squares = Array.from({length: grid.rows * grid.cols}, (_, square) => ({n: 1, value: cell(name, square)}));
        paintCourt(canvas, rules, grid, [rules.eras.at(-1)], palette(), squares, selected, null, 'rate', 1, 1);
        const depth = Math.floor(selected / grid.cols) - 5, lateral = selected % grid.cols - 25;
        about.textContent = `${plainWords[name] ?? ''} In technical terms: ${data.methods.find(row => row.method === name).description}`.trim();
        spot.textContent = `${depth < 0 ? `${-depth} ft behind the rim` : `${depth} ft forward`}, ${lateral === 0 ? 'in the centre' : `${Math.abs(lateral)} ft ${lateral < 0 ? 'left' : 'right'}`}: ${pct(cell(name, selected))}`;
        all.replaceChildren(table(['At this spot', 'Make chance'], data.methods.map(row => [row.method, pct(cell(row.method, selected))])));
    }

    select.addEventListener('change', draw);
    canvas.addEventListener('click', event => { selected = canvasSquare(event, canvas, grid); draw(); });
    canvas.addEventListener('keydown', event => {
        const delta = {ArrowUp: -grid.cols, ArrowDown: grid.cols, ArrowLeft: -1, ArrowRight: 1}[event.key];
        if (delta === undefined) return;
        selected = Math.min(grid.rows * grid.cols - 1, Math.max(0, selected + delta));
        event.preventDefault();
        draw();
    });
    new ResizeObserver(draw).observe(canvas);
    new MutationObserver(draw).observe(document.documentElement, {attributes: true, attributeFilter: ['data-theme']});
    section.append(view, el('p', `Every method learned from the ${data.season - 3} to ${data.season - 1} regular seasons. Pick a spot to compare all of them there.`, 'caption'));
    return section;
}

function structure(data) {
    const section = el('section', null, 'headline');
    section.append(el('h2', 'Is there spatial structure to model?'));
    const [raw, after] = ['Make rate on the logit scale', 'After removing the distance trend'].map(kind => data.variogram.filter(row => row.kind === kind));
    const canvas = el('canvas');
    canvas.id = 'lab-variogram';
    canvas.setAttribute('role', 'img');
    canvas.setAttribute('aria-label', `Variogram of make rates. The fitted sill is ${raw[0].sill.toFixed(2)} before removing the distance trend and ${after[0].sill.toFixed(3)} after.`);
    const stage = el('div', null, 'history-stage');
    stage.append(canvas);
    const legend = el('p', null, 'mix-legend');
    legend.append(el('span', 'Make rate on the logit scale', 'actual'), el('span', 'After removing the distance trend', 'fixed_mix'));
    const draw = () => chart(canvas, [
        {points: raw.map(row => [row.distance_ft, row.semivariance]), line: raw.map(row => [row.distance_ft, row.fitted]), colour: 'deep'},
        {points: after.map(row => [row.distance_ft, Math.max(row.semivariance, 0)]), line: after.map(row => [row.distance_ft, row.fitted]), colour: 'accent', dash: [6, 4]}],
        'Distance between cells, in feet', 'Semivariance');
    new ResizeObserver(draw).observe(canvas);
    new MutationObserver(draw).observe(document.documentElement, {attributes: true, attributeFilter: ['data-theme']});
    section.append(el('p', `A variogram shows how different two cells are as they get further apart. Make rates differ more with distance, up to a range of about ${raw[0].range_ft.toFixed(0)} ft. Once a trend in distance from the rim is removed, almost nothing is left: the sill falls from ${raw[0].sill.toFixed(2)} to ${after[0].sill.toFixed(3)}.`),
        legend, stage);

    section.append(el('h3', 'Are neighbouring cells alike?'),
        el('p', 'Moran’s I measures whether neighbouring cells have similar values. It is near 1 when neighbours match and near 0 when they are unrelated.'));
    const moran = el('div', null, 'area-list');
    moran.id = 'lab-moran';
    for (const row of data.moran) {
        const line = el('div', null, 'area-line');
        line.dataset.value = row.morans_i.toFixed(3);
        const track = el('span', null, 'mini-track');
        const bar = el('i', null, row.morans_i >= 0 ? 'good' : 'bad');
        bar.style.width = (50 * Math.min(1, Math.abs(row.morans_i) / .6)) + '%';
        bar.style[row.morans_i >= 0 ? 'left' : 'right'] = '50%';
        track.append(bar);
        line.append(el('span', row.residual), track, el('em', `${row.morans_i.toFixed(2)} · p ${row.p_value < .002 ? 'below 0.002' : row.p_value.toFixed(2)}`));
        moran.append(line);
    }
    section.append(moran, el('p', `Raw make rates are strongly alike between neighbours. The distance curve removes most of that, and the mesh model with a trend removes the rest. ${data.moran[0].cells} cells of 2 ft with at least 20 shots, tested with 999 permutations.`, 'caption'));

    const pattern = data.pattern;
    section.append(el('h3', 'Are shot locations random?'),
        el('p', `No. If the ${count.format(pattern.shots)} shots of ${data.season - 1} were spread evenly, the counts in ${pattern.quadrats} equal blocks of the court would vary about as much as their average. They vary ${count.format(Math.round(pattern.variance_to_mean))} times more. `
            + 'Ripley’s K counts how many other shots fall within a given distance of a shot:'),
        table(['Within', 'Observed', 'If random', 'Times more'], data.kFunction.map(row => [`${row.radius_ft} ft`, row.observed.toFixed(0), row.random_expected.toFixed(0), (row.observed / row.random_expected).toFixed(1)])));
    return section;
}

function density(data, rules) {
    const section = el('section', null, 'headline');
    const scores = data.intensity.scores;
    section.append(el('h2', `Where will shots come from in ${data.season}?`),
        el('p', 'A log Gaussian Cox process treats shot locations as a point pattern with a smoothly varying intensity. '
            + `Predicting where the next season’s shots fall, its average log score per shot was ${scores.cox_process.toFixed(4)}, against ${scores.three_seasons.toFixed(4)} for reusing the cell shares of the three seasons before and ${scores.last_season.toFixed(4)} for reusing the last season alone. Lower is better, and the gaps are tiny: ${scores.last_season <= scores.cox_process ? 'reusing last season was best, so smoothing adds little once a full season of shots is in hand' : 'the Cox process was best'}.`));
    const court = el('div', null, 'posterior-court');
    court.id = 'lab-density';
    const canvas = el('canvas');
    canvas.setAttribute('role', 'img');
    canvas.setAttribute('aria-label', 'Predicted share of shots from each court spot. Shots concentrate at the rim and just outside the three point line.');
    court.append(canvas);
    const grid = {baseline: -rules.rim_from_baseline, midcourt: rules.length / 2 - rules.rim_from_baseline, size: 1, cols: rules.width, rows: rules.length / 2};
    const cols = data.grid.cols;
    const squares = Array.from({length: grid.rows * grid.cols}, (_, square) => ({n: 1, value: data.intensity.surface[Math.floor(square / grid.cols) * cols + square % grid.cols]}));
    const limit = Math.max(...squares.map(square => square.value));
    const draw = () => paintCourt(canvas, rules, grid, [rules.eras.at(-1)], palette(), squares, null, null, 'share', limit, 1);
    new ResizeObserver(draw).observe(canvas);
    new MutationObserver(draw).observe(document.documentElement, {attributes: true, attributeFilter: ['data-theme']});
    section.append(court, el('p', 'Darker spots are expected to take a larger share of shots. The model is fitted to counts in 2 ft cells from the three seasons before, with a Poisson likelihood and a neighbour prior on the log intensity.', 'caption'));
    return section;
}

function ensemble(data) {
    const section = el('section', null, 'headline');
    section.append(el('h2', 'Combining the methods'),
        el('p', 'The stacked ensemble is a weighted average. Its weights cannot be negative, add up to one, and are fitted on the season before the one being predicted.'));
    const list = el('div', null, 'area-list');
    list.id = 'lab-weights';
    for (const row of data.weights) {
        const line = el('div', null, 'area-line');
        line.dataset.value = row.weight;
        const track = el('span', null, 'mini-track');
        const bar = el('i', null, 'good');
        bar.style.width = (50 * row.weight) + '%';
        bar.style.left = '50%';
        track.append(bar);
        line.append(el('span', row.method), track, el('em', pct(row.weight)));
        list.append(line);
    }
    section.append(list, el('p', `Weights for the ${data.season} surface. They change from season to season, which is a sign that the methods are close to interchangeable.`, 'caption'));
    return section;
}

async function start() {
    const read = name => fetch(new URL(`data/${name}.json?lab=1`, import.meta.url)).then(response => {
        if (!response.ok) throw new Error(`Could not load ${name}`);
        return response.json();
    });
    const [index, data] = await Promise.all([read('index'), read('methods-lab')]);
    if (data.manifestSha256 !== index.manifestSha256) throw new Error('The lab results differ from the atlas snapshot');
    $('lab-content').replaceChildren(scoreboard(data), surfaces(data, index.court), ensemble(data), structure(data), density(data, index.court));
    $('lab-content').hidden = false;
    $('lab-status').textContent = '';
    document.body.dataset.ready = 'true';
}

start().catch(error => {
    $('lab-status').textContent = 'The methods lab could not load. Reload this page to try again.';
    console.error(error);
});
