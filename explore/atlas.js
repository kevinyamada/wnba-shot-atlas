import { paintCourt, paintHistory, canvasSquare } from './drawing.js?v=2';
import { renderStudy } from './study-findings.js?v=2';

const $ = id => document.getElementById(id);
const controls = ['season', 'team', 'player', 'phase', 'shot-type', 'compare'].map($);
const panels = ['court-primary', 'court-secondary'].map($);
const number = new Intl.NumberFormat('en-CA');
const percent = new Intl.NumberFormat('en-CA', {style: 'percent', maximumFractionDigits: 1});
const decimal = new Intl.NumberFormat('en-CA', {minimumFractionDigits: 2, maximumFractionDigits: 2});
const sampleFloor = 12;
const metricNames = {share: 'Shot share', rate: 'Make rate', points: 'Points per shot'};
const yearName = year => year === 'all' ? 'All seasons' : String(year);
const phaseNames = {'0': 'Regular season', '1': 'Playoffs', all: 'Regular season and playoffs'};
const model = {metric: 'share', selection: {kind: 'cell', value: 50}, views: [], history: [], hover: []};
const cache = new Map();
let index;
let selectionVersion = 0;
let historyVersion = 0;

async function json(url) {
    const asset = new URL(url, import.meta.url);
    asset.searchParams.set('snapshot', index?.manifestSha256.slice(0, 12) ?? 'public-2');
    const response = await fetch(asset);
    if (!response.ok) throw new Error(`Could not load ${url}`);
    return response.json();
}

function seasonData(year) {
    if (!cache.has(year)) {
        const promise = json(`data/${year}.json`).catch(error => {
            cache.delete(year);
            throw error;
        });
        cache.set(year, promise);
    }
    return cache.get(year);
}

function options(select, first, items, selected) {
    select.replaceChildren(new Option(first, select === $('compare') ? 'off' : 'all'));
    for (const [key, name] of items) select.append(new Option(name, key));
    select.value = [...select.options].some(option => option.value === selected) ? selected : select.options[0].value;
}

function searchFilters() {
    return {phase: $('phase').value, team: $('team').value, player: $('player').value, type: $('shot-type').value};
}

function matching(row, filters) {
    const [phase, team, player] = row;
    return (filters.phase === 'all' || phase === Number(filters.phase)) &&
        (filters.team === 'all' || team === Number(filters.team)) &&
        (filters.player === 'all' || player === Number(filters.player)) &&
        (filters.type === 'all' || row[8] === Number(filters.type));
}

function filtersFor(seasons, wanted) {
    const teamNames = new Map();
    for (const entry of seasons) {
        for (const row of entry.rows) {
            if (!matching(row, {...wanted, team: 'all', player: 'all', type: 'all'})) continue;
            const id = String(row[1]);
            if (!teamNames.has(id)) teamNames.set(id, entry.teams[id]);
        }
    }
    options($('team'), 'Whole league', [...teamNames].sort((a, b) => a[1].localeCompare(b[1])), wanted.team);
    const playerNames = new Map();
    for (const entry of seasons) {
        for (const row of entry.rows) {
            if (!row[2] || !matching(row, {...wanted, team: $('team').value, player: 'all', type: 'all'})) continue;
            const id = String(row[2]);
            if (!playerNames.has(id)) playerNames.set(id, entry.players[id]);
        }
    }
    options($('player'), 'All players', [...playerNames].sort((a, b) => a[1].localeCompare(b[1])), wanted.player);
}

function counts() {
    return {n: 0, makes: 0, points: 0};
}

function add(sum, row) {
    sum.n += row[5];
    sum.makes += row[6];
    sum.points += row[7];
}

function totals(rows, filters) {
    const total = counts(), area = counts();
    let unlocated = 0, otherHalf = 0;
    const cells = Array.from({length: index.grid.cols * index.grid.rows}, counts);
    const selected = model.selection;
    for (const row of rows) {
        if (!matching(row, filters)) continue;
        const cell = row[3];
        add(total, row);
        if (cell >= 0) add(cells[cell], row);
        if (cell === -1) unlocated += row[5];
        if (cell === -2) otherHalf += row[5];
        if ((selected.kind === 'cell' ? cell : row[4]) === selected.value) add(area, row);
    }
    return {total, area, cells, unlocated, otherHalf};
}

function areaTotals(rows, filters, selection) {
    const total = counts(), area = counts();
    const key = selection.kind === 'cell' ? 3 : 4;
    for (const row of rows) {
        if (!matching(row, filters)) continue;
        add(total, row);
        if (row[key] === selection.value) add(area, row);
    }
    return {total, area};
}

function value(part, total, metric = model.metric) {
    if (metric === 'share') return total.n ? part.n / total.n : null;
    if (!part.n) return null;
    return (metric === 'rate' ? part.makes : part.points) / part.n;
}

function recordedGames(coverage, phase) {
    if (phase !== 'all') return coverage[phase === '1' ? 'playoffs' : 'regular'];
    const {regular, playoffs} = coverage;
    const sums = Object.fromEntries(['recorded_games','matched_team_games','checked_team_boxes','attempts','unknown']
        .map(key => [key, (regular[key] ?? 0) + (playoffs[key] ?? 0)]));
    sums.scheduled_games = regular.scheduled_games == null ? null : regular.scheduled_games + playoffs.scheduled_games;
    return sums;
}

function areaDescription() {
    const {kind, value} = model.selection;
    if (kind === 'zone') return {title: index.zones[value], description: 'Across this court area'};
    const {cols, size, baseline, midcourt} = index.grid;
    const side = value % cols * size - index.court.width / 2;
    const depth = Math.floor(value / cols) * size + baseline;
    const signed = x => x.toFixed(2).replace(/0+$/, '').replace(/\.$/, '').replace('-', '−');
    const radius = Math.hypot(side + size / 2, (depth + Math.min(depth + size, midcourt)) / 2);
    return {title: `About ${Math.round(radius)} ft from the rim`,
        description: `${signed(side)} to ${signed(side + size)} ft across · ${signed(depth)} to ${signed(Math.min(depth + size, midcourt))} ft forward`};
}

function format(value, metric) {
    if (value === null) return 'Unavailable';
    return metric === 'points' ? decimal.format(value) : percent.format(value);
}

function addStat(list, label, value) {
    const term = document.createElement('dt');
    const definition = document.createElement('dd');
    term.textContent = label;
    definition.textContent = value;
    list.append(term, definition);
}

function renderStats() {
    const {title, description} = areaDescription();
    $('area-title').textContent = title;
    $('area-position').textContent = description;
    $('selection-kind').textContent = model.selection.kind === 'cell' ? 'Selected square' : 'Selected area';
    const target = $('area-stats');
    target.replaceChildren();
    for (const {entry, data, league} of model.views) {
        const block = document.createElement('div');
        block.className = 'area-result';
        block.dataset.season = entry.season;
        const heading = document.createElement('h3');
        heading.textContent = yearName(entry.season);
        const list = document.createElement('dl');
        const part = data.area;
        addStat(list, 'Made / attempts', `${number.format(part.makes)} / ${number.format(part.n)}`);
        addStat(list, 'Field goal points', number.format(part.points));
        addStat(list, 'Share of shots', format(value(part, data.total, 'share'), 'share'));
        addStat(list, 'Make rate', format(value(part, data.total, 'rate'), 'rate'));
        addStat(list, 'Points per shot', format(value(part, data.total, 'points'), 'points'));
        const note = document.createElement('p');
        note.className = 'caption';
        const leagueRate = format(value(league.area, league.total, 'rate'), 'rate');
        note.textContent = league.area.n ? `${leagueRate} made across the league on ${number.format(league.area.n)} attempts.` : 'The league has no recorded shots here.';
        if (part.n > 0 && part.n < sampleFloor) note.textContent += ' Small sample.';
        block.append(heading, list, note);
        target.append(block);
    }
}

function palette() {
    const css = getComputedStyle(document.documentElement);
    return Object.fromEntries(['ink','muted','line','deep','accent','court','court-alt','court-line','historic-line','earliest-line','colour-min','colour-max','surface']
        .map(name => [name, css.getPropertyValue('--' + name).trim()]));
}

function activeScale() {
    if (model.metric === 'rate') return 1;
    if (model.metric === 'points') return 3;
    return Math.max(0.01, ...model.views.flatMap(({data}) => data.cells.map(cell => value(cell, data.total) ?? 0)));
}

function draw() {
    if (!model.views.length) return;
    const limit = activeScale();
    const colours = palette();
    model.views.forEach(({entry, data, era}, i) => {
        const focus = model.selection.kind === 'cell' ? model.selection.value : null;
        const squares = data.cells.map(cell => ({n: cell.n, value: value(cell, data.total)}));
        paintCourt(panels[i].querySelector('canvas'), index.court, index.grid, era, colours,
            squares, focus, model.hover[i], model.metric, limit, sampleFloor);
    });
    $('legend-low').textContent = model.metric === 'points' ? '0' : '0%';
    $('legend-high').textContent = format(limit, model.metric);
    const metricNotes = {
        share: 'Darker squares contain a larger share of the selected shots. Shares use all attempts, including shots outside the map.',
        rate: 'Colour shows the share of shots made. Patterned squares have fewer than 12 attempts.',
        points: 'Colour shows points from the floor divided by attempts. Patterned squares have fewer than 12 attempts.'
    };
    $('metric-note').textContent = metricNotes[model.metric];
    paintHistory($('history-chart'), model.history, model.views.map(v => v.entry.season), colours, model.metric);
}

function renderTypes(entry, filters) {
    const byType = index.shotTypes.map(counts);
    const selection = {...filters, type: 'all'};
    for (const row of entry.rows) {
        if (matching(row, selection)) add(byType[row[8]], row);
    }
    $('type-rows').replaceChildren(...byType.map((part, i) => tableRow([
        index.shotTypes[i], number.format(part.n), number.format(part.makes),
        format(value(part, part, 'rate'), 'rate'), format(value(part, part, 'points'), 'points')
    ])));
    $('types-title').textContent = `Shot types in ${yearName(entry.season).toLowerCase()}`;
    const [jump, layup] = byType;
    $('types-summary').textContent = layup.n && jump.n
        ? `Layups went in ${percent.format(layup.makes / layup.n)} of the time, compared with ${percent.format(jump.makes / jump.n)} for jump shots.`
        : 'Compare scoring by the recorded shot type.';
}

function renderCourts() {
    const phase = $('phase').value;
    panels[1].hidden = model.views.length === 1;
    $('workbench').classList.toggle('comparing', model.views.length === 2);
    model.views.forEach(({entry, data, era}, i) => {
        const panel = panels[i];
        panel.querySelector('[data-year]').textContent = yearName(entry.season);
        panel.querySelector('[data-arc]').textContent = entry.season === 'all'
            ? `${index.seasons.at(0)} to ${index.seasons.at(-1)}` : `Arc ${era[0].arc_label}`;
        const key = panel.querySelector('[data-era-key]');
        key.replaceChildren(...era.map(rule => {
            const marker = document.createElement('span');
            marker.className = 'era-marker';
            marker.dataset.era = rule.id;
            marker.textContent = `${rule.first_season} to ${rule.last_season} · ${rule.arc_label}`;
            if (rule.arc_only) marker.title = 'The early arc is shown only in front of the rim';
            return marker;
        }));
        key.hidden = entry.season !== 'all';
        panel.querySelector('[data-total=n]').textContent = number.format(data.total.n);
        panel.querySelector('[data-total=rate]').textContent = format(value(data.total, data.total, 'rate'), 'rate');
        panel.querySelector('[data-total=points]').textContent = number.format(data.total.points);
        const coverage = recordedGames(entry.coverage, phase);
        panel.querySelector('[data-coverage]').textContent = entry.season === 'all'
            ? `${number.format(coverage.recorded_games)} games with recorded shots`
            : `${coverage.recorded_games}${coverage.scheduled_games === null ? '' : ` of ${coverage.scheduled_games}`} games with shots`
              + (coverage.checked_team_boxes ? `. ${coverage.matched_team_games} match both team boxes.` : '.');
        const offMap = data.unlocated + data.otherHalf;
        panel.querySelector('[data-location]').textContent = !data.total.n ? 'No shots for this selection.' :
            offMap ? `${number.format(data.total.n - offMap)} mapped · ${number.format(data.otherHalf)} from the other half · ${number.format(data.unlocated)} with unknown location` : '';
    });
    renderStats();
    draw();
}

function renderCoverage() {
    const phase = $('phase').value;
    $('coverage-summary').textContent = `${phaseNames[phase]} coverage across the pinned wehoop files. Open the audit to see what each year includes.`;
    $('coverage-rows').replaceChildren(...index.coverage.map(entry => {
        const row = recordedGames(entry, phase);
        return tableRow([entry.season, row.scheduled_games === null ? row.recorded_games : `${row.recorded_games} / ${row.scheduled_games}`,
            row.checked_team_boxes ? row.matched_team_games : 'Unavailable', number.format(row.attempts), number.format(row.unknown)]);
    }));

}

function tableRow(values) {
    const row = document.createElement('tr');
    for (const [i, value] of values.entries()) {
        const cell = document.createElement(i === 0 ? 'th' : 'td');
        if (i === 0) cell.scope = 'row';
        cell.textContent = value;
        row.append(cell);
    }
    return row;
}

async function historySeries() {
    const version = ++historyVersion;
    const filters = searchFilters();
    const selection = {...model.selection};
    const league = filters.player === 'all' && filters.team === 'all' && filters.type === 'all';
    const title = areaDescription().title;
    const player = $('player').selectedOptions[0].textContent;
    const team = $('team').selectedOptions[0].textContent;
    $('history-context').textContent = `${title} · ${filters.player !== 'all' ? player : team} · ${phaseNames[filters.phase]}${filters.type === 'all' ? '' : ` · ${index.shotTypes[Number(filters.type)]}`}`;
    if (!league) $('history-status').textContent = 'Loading season history…';
    try {
        const series = [];
        for (let start = 0; start < index.seasons.length; start += 4) {
            const years = index.seasons.slice(start, start + 4);
            const chunk = await Promise.all(years.map(async season => {
                const rows = league ? index.leagueHistory[season] : (await seasonData(season)).rows;
                return {season, ...areaTotals(rows, filters, selection)};
            }));
            if (version !== historyVersion) return;
            series.push(...chunk);
        }
        model.history = series;
        $('history-status').textContent = '';
        $('history-rows').replaceChildren(...series.map(({season, area, total}) => tableRow([
            season, `${number.format(area.makes)} / ${number.format(area.n)}`,
            format(value(area, total, 'share'), 'share'), format(value(area, total, 'rate'), 'rate'),
            format(value(area, total, 'points'), 'points')
        ])));
        draw();
    } catch (error) {
        if (version === historyVersion) $('history-status').textContent = 'Season history could not load. Change a filter to try again.';
        console.warn(error);
    }
}

function refreshArea() {
    const filters = searchFilters();
    for (const view of model.views) {
        view.data = totals(view.entry.rows, filters);
        view.league = areaTotals(view.entry.rows, {...filters, team:'all', player:'all'}, model.selection);
    }
    model.history = [];
    $('history-rows').replaceChildren();
    renderCourts();
    historySeries();
}

async function refresh() {
    const version = ++selectionVersion;
    const primary = $('season').value === 'all' ? 'all' : Number($('season').value);
    const compare = $('compare').value;
    const years = compare === 'off' || Number(compare) === primary ? [primary] : [primary, Number(compare)];
    options($('compare'), 'No comparison', index.seasons.filter(y => y !== primary).map(y => [String(y), y]), compare);
    $('load-state').textContent = 'Loading selected games…';
    try {
        const seasons = await Promise.all(years.map(seasonData));
        if (version !== selectionVersion) return;
        filtersFor(seasons, searchFilters());
        model.views = seasons.map(entry => ({entry, era: entry.season === 'all' ? index.court.eras : index.court.eras.filter(era => era.id === entry.court)}));
        $('atlas-content').hidden = false;
        model.hover = [];
        panels.forEach(panel => { panel.querySelector('.court-hover').hidden = true; });
        refreshArea();
        renderCoverage();
        renderTypes(seasons[0], searchFilters());
        $('load-state').textContent = '';
        document.body.dataset.ready = 'true';
    } catch (error) {
        if (version === selectionVersion) {
            $('atlas-content').hidden = true;
            $('load-state').textContent = 'The selected data could not load. Select a season again or reload this page.';
        }
        console.error(error);
    }
}

function selectSquare(square) {
    model.selection = {kind: 'cell', value: square};
    model.lastSquare = square;
    $('zone').value = 'cell';
    refreshArea();
}

function bindCourt(panel, i) {
    const canvas = panel.querySelector('canvas');
    const tooltip = panel.querySelector('.court-hover');
    canvas.addEventListener('click', event => selectSquare(canvasSquare(event, canvas, index.grid)));
    canvas.addEventListener('pointermove', event => {
        if (event.pointerType === 'touch' || !model.views[i]) return;
        const square = canvasSquare(event, canvas, index.grid);
        const {data} = model.views[i];
        const cell = data.cells[square];
        const moved = model.hover[i] !== square;
        model.hover[i] = square;
        const x = event.offsetX, y = event.offsetY;
        tooltip.textContent = cell.n ? `${number.format(cell.makes)} made / ${number.format(cell.n)} attempts · ${percent.format(cell.makes / cell.n)}` : 'No recorded shots here';
        tooltip.hidden = false;
        const bound = tooltip.offsetWidth / 2 + 4;
        tooltip.style.left = `${Math.min(canvas.clientWidth - bound, Math.max(bound, x))}px`;
        tooltip.style.top = `${Math.max(tooltip.offsetHeight + 14, y)}px`;
        if (moved) draw();
    });
    canvas.addEventListener('pointerleave', () => {
        model.hover[i] = null;
        tooltip.hidden = true;
        draw();
    });
    canvas.addEventListener('keydown', event => {
        const move = {ArrowLeft: [-1,0], ArrowRight: [1,0], ArrowUp: [0,-1], ArrowDown: [0,1]}[event.key];
        if (!move) return;
        event.preventDefault();
        const {cols, rows} = index.grid;
        const col = Math.min(cols - 1, Math.max(0, model.lastSquare % cols + move[0]));
        const row = Math.min(rows - 1, Math.max(0, Math.floor(model.lastSquare / cols) + move[1]));
        selectSquare(row * cols + col);
    });
}

async function start() {
    index = await json('data/index.json');
    json('data/findings.json').then(({band}) => {
        const [old, current] = band;
        $('arc-finding').textContent = `In the strip between the old and new arcs in front of the rim, players took ${number.format(old.attempts)} shots in the 2012 regular season and ${number.format(current.attempts)} in 2013.`;
        $('comparison-callout').hidden = false;
    }).catch(error => console.warn(error));
    const total = index.coverage.reduce((sum, row) => sum + row.regular.attempts + row.playoffs.attempts, 0);
    $('total-shots').textContent = `${number.format(total)} recorded attempts`;
    $('season').append(new Option('All seasons', 'all', true, true), ...index.seasons.slice().reverse().map(year => new Option(year, year)));
    $('phase').value = 'all';
    const grid = index.grid;
    model.lastSquare = Math.floor((1 - grid.baseline) / grid.size) * grid.cols + Math.floor(index.court.width / grid.size / 2);
    model.selection.value = model.lastSquare;
    $('shot-type').append(...index.shotTypes.map((name, i) => new Option(name, i)));
    $('zone').append(...index.zones.map((name, i) => new Option(name, i)));
    controls.forEach(control => {
        control.disabled = false;
        control.addEventListener('change', refresh);
    });
    document.querySelectorAll('[data-metric]').forEach(button => button.addEventListener('click', () => {
        model.metric = button.dataset.metric;
        document.querySelectorAll('[data-metric]').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
        draw();
    }));
    $('zone').addEventListener('change', event => {
        model.selection = event.target.value === 'cell' ? {kind:'cell', value:model.lastSquare} : {kind:'zone', value:Number(event.target.value)};
        refreshArea();
    });
    $('compare-rule').addEventListener('click', () => {
        $('season').value = '2012';
        options($('compare'), 'No comparison', index.seasons.filter(year => year !== 2012).map(year => [String(year), year]), '2013');
        $('phase').value = '0';
        $('team').value = 'all';
        $('player').value = 'all';
        $('shot-type').value = 'all';
        model.metric = 'share';
        const square = Math.floor((21 - grid.baseline) / grid.size) * grid.cols + Math.floor(grid.cols / 2);
        model.lastSquare = square;
        model.selection = {kind: 'cell', value: square};
        $('zone').value = 'cell';
        document.querySelectorAll('[data-metric]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.metric === 'share')));
        refresh();
    });
    panels.forEach(bindCourt);
    let paintFrame;
    const resize = () => { cancelAnimationFrame(paintFrame); paintFrame = requestAnimationFrame(draw); };
    window.addEventListener('resize', resize);
    new MutationObserver(resize).observe(document.documentElement, {attributes:true, attributeFilter:['data-theme']});
    await refresh();
    Promise.all([json('data/findings.json'), json('data/study.json'), json('data/bayesian.json')])
        .then(([findings, study, bayesian]) => {
            if (study.manifestSha256 !== index.manifestSha256) throw new Error('Research data differ from the explorer snapshot');
            renderStudy(findings, study, index.court, bayesian, palette);
        })
        .catch(error => {
            $('study-status').textContent = 'The research findings could not load. Reload to try again.';
            console.error(error);
        });
}

start().catch(error => {
    $('load-state').textContent = 'The season index could not load. Reload this page to try again.';
    console.error(error);
});
