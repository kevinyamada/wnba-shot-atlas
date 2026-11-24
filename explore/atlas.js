import { paintCourt, paintHistory, canvasSquare, metricValue as value, per100 } from './drawing.js?v=7';
import { renderStudy } from './study-findings.js?v=6';
import { shotMix } from './shot-mix.js?v=4';
import { headline, shooters, ladder, teamReport, teamControl, prediction, teamStory } from './overview.js?v=8';

const $ = id => document.getElementById(id);
const controls = ['season', 'team', 'player', 'phase', 'shot-type', 'compare'].map($);
const panels = ['court-primary', 'court-secondary'].map($);
const number = new Intl.NumberFormat('en-CA', {maximumFractionDigits: 0});
const percent = new Intl.NumberFormat('en-CA', {style: 'percent', maximumFractionDigits: 1});
const decimal = new Intl.NumberFormat('en-CA', {minimumFractionDigits: 2, maximumFractionDigits: 2});
const dataRelease = 'r10';
const extras = {teams: null, shooters: null, possessions: null};
const sampleFloor = 12;
const mappedAreas = 5;
const metricNames = {share: 'Shot share', per100: 'Attempts per 100 shots', attempts: 'Attempts',
    rate: 'Make rate', points: 'Points per shot'};
const yearName = year => year === 'all' ? 'All seasons' : year === 'prediction' ? '2027 prediction' : String(year);
const phaseNames = {'0': 'Regular season', '1': 'Playoffs', all: 'Regular season and playoffs'};
const model = {side: 'taken', metric: 'share', selection: {kind: 'cell', value: 50}, views: [], history: [], hover: []};
const cache = new Map();
let index;
let selectionVersion = 0;
let historyVersion = 0;

async function json(url) {
    const asset = new URL(url, import.meta.url);
    asset.searchParams.set('snapshot', `${index?.manifestSha256.slice(0, 12) ?? 'index'}-${dataRelease}`);
    const response = await fetch(asset);
    if (!response.ok) throw new Error(`Could not load ${url}`);
    return response.json();
}

function seasonData(year) {
    const allowed = model.side === 'allowed' && year !== 'prediction';
    const key = allowed ? `against-${year}` : String(year);
    if (!cache.has(key)) {
        const promise = json(`data/${key}.json`).catch(error => {
            cache.delete(key);
            throw error;
        });
        cache.set(key, promise);
    }
    return cache.get(key);
}

function options(select, first, items, selected) {
    select.replaceChildren(new Option(first, select === $('compare') ? 'off' : 'all'));
    for (const [key, name] of items) select.append(new Option(name, key));
    select.value = [...select.options].some(option => option.value === selected) ? selected : select.options[0].value;
}

const linkNames = [['season', 'season', 'all'], ['team', 'team', 'all'], ['player', 'player', 'all'], ['phase', 'games', 'all'], ['shot-type', 'type', 'all'], ['compare', 'compare', 'off']];

function shareLink() {
    const link = new URL(location.href);
    link.search = '';
    for (const [id, name, unset] of linkNames) {
        if ($(id).value !== unset) link.searchParams.set(name, $(id).value);
    }
    if (model.side !== 'taken') link.searchParams.set('side', model.side);
    if (model.metric !== 'share') link.searchParams.set('colour', model.metric);
    return link;
}

function setSide(side) {
    model.side = side;
    document.querySelectorAll('[data-side]').forEach(item => item.setAttribute('aria-pressed', String(item.dataset.side === side)));
    $('player').value = 'all';
    $('player').disabled = side === 'allowed';
}

function setMetric(metric) {
    model.metric = metric;
    document.querySelectorAll('[data-metric]').forEach(item => item.setAttribute('aria-pressed', String(item.dataset.metric === metric)));
}

function openLink() {
    const wanted = new URLSearchParams(location.search);
    if (['taken', 'allowed'].includes(wanted.get('side'))) setSide(wanted.get('side'));
    if (['share', 'rate', 'points'].includes(wanted.get('colour'))) setMetric(wanted.get('colour'));
    options($('compare'), 'No comparison', [...index.seasons.map(year => [String(year), year]), ['prediction', '2027 prediction']], wanted.get('compare'));
    for (const [id, name] of linkNames.filter(([id]) => ['season', 'phase', 'shot-type'].includes(id))) {
        if ([...$(id).options].some(option => option.value === wanted.get(name))) $(id).value = wanted.get(name);
    }
    return {team: wanted.get('team') ?? 'all', player: wanted.get('player') ?? 'all'};
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
    const zones = index.zones.map(counts);
    const selected = model.selection;
    for (const row of rows) {
        if (!matching(row, filters)) continue;
        const cell = row[3];
        add(total, row);
        add(zones[row[4]], row);
        if (cell >= 0) add(cells[cell], row);
        if (cell === -1) unlocated += row[5];
        if (cell === -2) otherHalf += row[5];
        if ((selected.kind === 'cell' ? cell : row[4]) === selected.value) add(area, row);
    }
    return {total, area, cells, zones, unlocated, otherHalf};
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

function leaders(entry, filters, selection) {
    const key = selection.kind === 'cell' ? 3 : 4;
    const anyPlayer = {...filters, player: 'all'};
    const byPlayer = new Map();
    for (const row of entry.rows) {
        if (!row[2] || row[key] !== selection.value || !matching(row, anyPlayer)) continue;
        if (!byPlayer.has(row[2])) byPlayer.set(row[2], counts());
        add(byPlayer.get(row[2]), row);
    }
    const ranked = [...byPlayer].map(([id, part]) => ({id, name: entry.players[id] ?? 'Unknown shooter', ...part}))
        .sort((a, b) => b.points - a.points || b.makes - a.makes || a.n - b.n || a.name.localeCompare(b.name));
    ranked.forEach((player, i) => { player.rank = i + 1; });
    const chosen = ranked.find(player => player.id === Number(filters.player)) ?? null;
    const shown = ranked.slice(0, 3).filter(player => player.points > 0);
    if (chosen && !shown.includes(chosen)) shown.push(chosen);
    return {shown, chosen};
}

function normalizedComparison() {
    return model.views.length === 2 && $('normalize-shots').checked;
}

function frequencyMetric() {
    if (model.views.length !== 2) return 'share';
    return normalizedComparison() ? 'per100' : 'attempts';
}

function displayedMetric() {
    return model.metric === 'share' ? frequencyMetric() : model.metric;
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
    if (kind === 'zone') {
        const notes = ['Within 4 ft of the rim', 'From 4 ft to 10 ft from the rim', 'Inside the line, 10 ft or more from the rim',
            'Outside the line beside the basket', 'Outside the line farther up the court',
            'Past the half court line. Not drawn on this court', 'No usable location in the source. Not drawn on this court'];
        const pooled = value >= 2 && value < mappedAreas && model.views[0]?.entry.season === 'all';
        return {title: index.zones[value], description: notes[value] + (pooled ? '. The outline uses the current line.' : '')};
    }
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
    if (metric === 'attempts') return number.format(value);
    if (metric === 'per100') return value > 0 && value < .01 ? '<0.01' : decimal.format(value);
    return metric === 'points' ? decimal.format(value) : percent.format(value);
}

function addStat(list, label, value) {
    const term = document.createElement('dt');
    const definition = document.createElement('dd');
    term.textContent = label;
    definition.textContent = value;
    list.append(term, definition);
}

function leaderList(found) {
    const wrap = document.createElement('div');
    wrap.className = 'leaders';
    const title = document.createElement('h4');
    title.textContent = 'Field goal points leaders';
    wrap.append(title);
    if (!found.shown.length) {
        const empty = document.createElement('p');
        empty.className = 'caption';
        empty.textContent = 'No made shots by a named shooter here.';
        wrap.append(empty);
        return wrap;
    }
    const list = document.createElement('ol');
    for (const player of found.shown) {
        const item = document.createElement('li');
        item.value = player.rank;
        item.classList.toggle('chosen', player === found.chosen);
        const line = document.createElement('div');
        const name = document.createElement('span');
        const points = document.createElement('strong');
        const detail = document.createElement('small');
        name.textContent = player.name;
        points.textContent = `${number.format(player.points)} points`;
        detail.textContent = `${number.format(player.makes)} of ${number.format(player.n)} made`;
        line.append(name, points);
        item.append(line, detail);
        list.append(item);
    }
    wrap.append(list);
    return wrap;
}

function renderStats() {
    const {title, description} = areaDescription();
    $('area-title').textContent = title;
    $('area-position').textContent = description;
    $('selection-kind').textContent = model.selection.kind === 'cell' ? 'Selected square' : 'Selected area';
    const target = $('area-stats');
    target.replaceChildren();
    for (const {entry, data, league, leaders: found} of model.views) {
        const block = document.createElement('div');
        block.className = 'area-result';
        block.dataset.season = entry.season;
        const heading = document.createElement('h3');
        heading.textContent = yearName(entry.season);
        const list = document.createElement('dl');
        const part = data.area;
        if (normalizedComparison()) {
            for (const [label, amount] of [['Attempts', part.n], ['Makes', part.makes], ['Points', part.points]]) {
                addStat(list, `${label} per 100 shots`, format(per100(amount, data.total.n), 'per100'));
            }
        } else {
            addStat(list, 'Made / attempts', `${number.format(part.makes)} / ${number.format(part.n)}`);
            addStat(list, 'Field goal points', number.format(part.points));
            addStat(list, 'Share of shots', format(value(part, data.total, 'share'), 'share'));
        }
        addStat(list, 'Make rate', format(value(part, data.total, 'rate'), 'rate'));
        addStat(list, 'Points per shot', format(value(part, data.total, 'points'), 'points'));
        const note = document.createElement('p');
        note.className = 'caption';
        const leagueRate = format(value(league.area, league.total, 'rate'), 'rate');
        const filtered = $('team').value !== 'all' || $('player').value !== 'all';
        note.textContent = !filtered ? '' : league.area.n ? `The league made ${leagueRate} here.` : 'The league has no recorded shots here.';
        if (part.n > 0 && part.n < sampleFloor) note.textContent += ' Small sample.';
        note.hidden = !note.textContent;
        block.append(heading, list, note);
        if (!entry.prediction && !entry.against) block.append(leaderList(found));
        target.append(block);
    }
}

function palette() {
    const css = getComputedStyle(document.documentElement);
    return Object.fromEntries(['ink','muted','line','deep','accent','court','court-alt','court-line','historic-line','earliest-line','colour-min','colour-mid','colour-max','surface']
        .map(name => [name, css.getPropertyValue('--' + name).trim()]));
}

function activeScale(metric) {
    if (metric === 'rate') return 1;
    if (metric === 'points') return 3;
    const minimum = metric === 'share' ? .01 : 1;
    return Math.max(minimum, ...model.views.flatMap(({data}) => data.cells.map(cell => value(cell, data.total, metric) ?? 0)));
}

function draw() {
    if (!model.views.length) return;
    const metric = displayedMetric();
    const limit = activeScale(metric);
    const colours = palette();
    model.views.forEach(({entry, data, era}, i) => {
        const {kind, value: chosen} = model.selection;
        const focus = kind === 'cell' ? chosen : null;
        const region = kind === 'zone' && chosen < mappedAreas ? {zone: chosen, rule: era.at(-1)} : null;
        const squares = data.cells.map(cell => ({n: cell.n, value: value(cell, data.total, metric)}));
        paintCourt(panels[i].querySelector('canvas'), index.court, index.grid, era, colours,
            squares, focus, model.hover[i], metric, limit, sampleFloor, region);
    });
    $('legend-low').textContent = metric === 'share' || metric === 'rate' ? '0%' : '0';
    $('legend-high').textContent = format(limit, metric) + (metric === 'per100' ? ' per 100' : '');
    $('history-unit').textContent = metricNames[metric];
    const metricNotes = {
        share: 'Shot share is the percentage of all selected attempts taken in a square. The total includes attempts outside the map.',
        per100: 'Each square shows how many of every 100 attempts came from that spot. The total for each selection includes shots outside the map. Both courts use the same colour scale.',
        attempts: 'Colour shows the number of selected attempts in each square. Both courts use the same scale.',
        rate: 'Colour shows the share of shots made. Patterned squares have fewer than 12 attempts.',
        points: 'Colour shows points from the floor divided by attempts. Patterned squares have fewer than 12 attempts.'
    };
    const summaryNote = normalizedComparison() && (metric === 'rate' || metric === 'points')
        ? ' The selected area also shows attempts, makes and points per 100 shots.' : '';
    $('metric-note').textContent = metricNotes[metric] + summaryNote;
    paintHistory($('history-chart'), model.history, model.views.map(v => v.entry.season), colours, metric);
}

function selectionLabel(filters) {
    const who = filters.player !== 'all' ? $('player').selectedOptions[0].textContent : $('team').selectedOptions[0].textContent;
    const type = filters.type === 'all' ? '' : ` · ${index.shotTypes[Number(filters.type)]}`;
    return `${who}${model.side === 'allowed' ? ', shots allowed' : ''} · ${phaseNames[filters.phase]}${type}`;
}

function areaLeaders(zones) {
    const mapped = zones.slice(0, mappedAreas).map((part, zone) => ({...part, zone})).filter(part => part.n);
    const busiest = mapped.reduce((best, part) => !best || part.n > best.n ? part : best, null);
    const scoring = mapped.filter(part => part.n >= sampleFloor)
        .reduce((best, part) => !best || part.points / part.n > best.points / best.n ? part : best, null);
    return {busiest, scoring};
}

function areaSentence({total, zones}) {
    const {busiest, scoring} = areaLeaders(zones);
    if (!busiest) return 'No located shots for this selection.';
    const most = `${index.zones[busiest.zone]} had the most shots (${format(value(busiest, total, 'share'), 'share')} of attempts).`;
    return scoring ? `${most} ${index.zones[scoring.zone]} produced the most points per shot (${format(value(scoring, total, 'points'), 'points')}).` : most;
}

function areaTableRows(zone) {
    const comparing = model.views.length === 2;
    const frequency = frequencyMetric();
    const picked = model.selection.kind === 'zone' && model.selection.value === zone;
    const widest = Math.max(1, ...model.views[0].data.zones.map(part => part.n));
    return model.views.map(({entry, data}, i) => {
        const part = zone === null ? data.total : data.zones[zone];
        const tops = areaLeaders(data.zones);
        const row = document.createElement('tr');
        const cell = (text, top = false) => {
            const item = document.createElement('td');
            item.textContent = text;
            item.classList.toggle('top', top);
            row.append(item);
        };
        if (zone !== null) {
            row.dataset.zone = zone;
            row.classList.toggle('selected', picked);
            row.classList.toggle('off-map', zone >= mappedAreas);
        }
        if (i === 0) {
            const head = document.createElement('th');
            head.scope = 'row';
            head.rowSpan = model.views.length;
            if (zone === null) head.textContent = 'All attempts';
            else {
                const button = document.createElement('button');
                button.type = 'button';
                button.dataset.zone = zone;
                button.textContent = index.zones[zone];
                button.setAttribute('aria-pressed', String(picked));
                head.append(button);
                if (!comparing) {
                    const bar = document.createElement('span');
                    bar.className = 'share-bar';
                    if (part.n) {
                        bar.append(document.createElement('i'));
                        bar.firstChild.style.width = `${100 * part.n / widest}%`;
                    }
                    head.append(bar);
                }
            }
            row.append(head);
        }
        const most = zone !== null && tops.busiest?.zone === zone;
        if (comparing) {
            cell(yearName(entry.season));
            cell(format(value(part, data.total, frequency), frequency), most);
        } else {
            cell(number.format(part.n));
            cell(format(value(part, data.total, 'share'), 'share'), most);
        }
        cell(format(value(part, data.total, 'rate'), 'rate'));
        cell(format(value(part, data.total, 'points'), 'points'), zone !== null && tops.scoring?.zone === zone);
        return row;
    });
}

function renderAreas() {
    const comparing = model.views.length === 2;
    const focused = $('area-rows').contains(document.activeElement) ? document.activeElement.dataset.zone : null;
    const seasons = model.views.map(({entry}) => yearName(entry.season));
    $('area-context').textContent = `${seasons.join(' and ')} · ${selectionLabel(searchFilters())}`;
    const headings = comparing ? ['Area', 'Season', metricNames[frequencyMetric()], 'Make rate', 'Points per shot']
        : ['Area', 'Attempts', 'Share', 'Make rate', 'Points per shot'];
    $('area-head').replaceChildren(...headings.map(text => {
        const head = document.createElement('th');
        head.scope = 'col';
        head.textContent = text;
        return head;
    }));
    $('area-rows').replaceChildren(...index.zones.flatMap((_, zone) => areaTableRows(zone)));
    $('area-total').replaceChildren(...areaTableRows(null));
    $('area-summary').textContent = model.views.map(({data}, i) => (comparing ? `${seasons[i]}: ` : '') + areaSentence(data)).join(' ');
    $('area-note').textContent = 'Tap an area to outline it on the court. Bold marks the most shots and the most points per shot.';
    if (focused !== null) $('area-rows').querySelector(`button[data-zone="${focused}"]`)?.focus();
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
    const [jump, layup] = byType;
    $('types-summary').textContent = layup.n && jump.n
        ? `Layups went in ${percent.format(layup.makes / layup.n)} of the time, compared with ${percent.format(jump.makes / jump.n)} for jump shots.`
        : 'Compare scoring by the recorded shot type.';
}

function renderCourts() {
    const phase = $('phase').value;
    const comparing = model.views.length === 2;
    const normalized = normalizedComparison();
    $('compare-units').hidden = !comparing;
    document.querySelector('[data-metric="share"]').textContent = comparing ? 'Shot frequency' : 'Shot share';
    panels[1].hidden = !comparing;
    $('workbench').classList.toggle('comparing', comparing);
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
        panel.querySelector('[data-points-label]').textContent = normalized ? 'Points per 100 shots' : 'Points';
        panel.querySelector('[data-total=points]').textContent = normalized
            ? format(per100(data.total.points, data.total.n), 'per100') : number.format(data.total.points);
        const offMap = data.unlocated + data.otherHalf;
        panel.querySelector('[data-location]').textContent = entry.prediction
            ? `Predicted for the whole league. Shots are placed where they were taken in the ${entry.basis} regular season, and the chance of each going in comes from the prediction model.`
            : !data.total.n ? 'No shots for this selection.' :
            offMap ? `${number.format(data.total.n - offMap)} mapped · ${number.format(data.otherHalf)} from the other half · ${number.format(data.unlocated)} with unknown location` : '';
    });
    renderStats();
    renderAreas();
    draw();
}

function renderCoverage() {
    const phase = $('phase').value;
    $('coverage-summary').textContent = `${phaseNames[phase]} coverage across the pinned wehoop files.`;
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

function renderHistoryRows() {
    const frequency = frequencyMetric();
    $('history-frequency').textContent = metricNames[frequency];
    $('history-rows').replaceChildren(...model.history.map(({season, area, total}) => tableRow([
        season, `${number.format(area.makes)} / ${number.format(area.n)}`,
        format(value(area, total, frequency), frequency), format(value(area, total, 'rate'), 'rate'),
        format(value(area, total, 'points'), 'points')
    ])));
}

async function historySeries() {
    const version = ++historyVersion;
    const filters = searchFilters();
    const selection = {...model.selection};
    const league = filters.player === 'all' && filters.team === 'all' && filters.type === 'all' && model.side === 'taken';
    $('history-context').textContent = `${areaDescription().title} · ${selectionLabel(filters)}`;
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
        renderHistoryRows();
        draw();
    } catch (error) {
        if (version === historyVersion) $('history-status').textContent = 'Season history could not load. Change a filter to try again.';
        console.warn(error);
    }
}

function refreshArea() {
    const filters = searchFilters();
    const everything = {phase: 'all', team: 'all', player: 'all', type: 'all'};
    for (const view of model.views) {
        const own = view.entry.prediction ? everything : filters;
        view.data = totals(view.entry.rows, own);
        view.league = areaTotals(view.entry.rows, {...own, team:'all', player:'all'}, model.selection);
        view.leaders = leaders(view.entry, own, model.selection);
    }
    model.history = [];
    $('history-rows').replaceChildren();
    renderCourts();
    historySeries();
}

async function refresh(opening = {}) {
    const version = ++selectionVersion;
    $('example-note').hidden = true;
    const primary = $('season').value === 'all' ? 'all' : Number($('season').value);
    const compare = $('compare').value;
    const other = compare === 'prediction' ? 'prediction' : Number(compare);
    const years = compare === 'off' || other === primary ? [primary] : [primary, other];
    options($('compare'), 'No comparison', [...index.seasons.filter(y => y !== primary).map(y => [String(y), y]), ['prediction', '2027 prediction']], compare);
    $('load-state').textContent = 'Loading selected games…';
    try {
        const seasons = await Promise.all(years.map(seasonData));
        if (version !== selectionVersion) return;
        filtersFor(seasons.filter(entry => !entry.prediction), {...searchFilters(), ...opening});
        model.views = seasons.map(entry => ({entry, era: entry.season === 'all' ? index.court.eras : index.court.eras.filter(era => era.id === entry.court)}));
        $('atlas-content').hidden = false;
        model.hover = [];
        panels.forEach(panel => { panel.querySelector('.court-hover').hidden = true; });
        refreshArea();
        renderCoverage();
        renderTypes(seasons[0], searchFilters());
        renderTeam();
        $('load-state').textContent = '';
        history.replaceState(null, '', shareLink());
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
    refreshArea();
}

function selectArea(zone) {
    const picked = model.selection.kind === 'zone' && model.selection.value === zone;
    model.selection = picked ? {kind: 'cell', value: model.lastSquare} : {kind: 'zone', value: zone};
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
        if (cell.n && displayedMetric() === 'per100') {
            const frequency = format(per100(cell.n, data.total.n), 'per100');
            tooltip.textContent = `${frequency} per 100 shots · ${tooltip.textContent}`;
        }
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

function renderTeam() {
    if (!extras.teams) return;
    teamReport($('team-report'), extras.teams, extras.shooters, {season: $('season').value, team: $('team').value, pick(team, year) {
        if (team !== 'all' && $('season').value === 'all') $('season').value = year;
        $('team').value = String(team);
        $('player').value = 'all';
        refresh();
    }}, extras.possessions);
}

function reveal() {
    const target = location.hash.length > 1 ? document.getElementById(location.hash.slice(1)) : null;
    if (!target) return;
    for (let node = target; node; node = node.parentElement) {
        if (node.tagName === 'DETAILS') node.open = true;
    }
    requestAnimationFrame(() => target.scrollIntoView());
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
    controls.forEach(control => {
        control.disabled = false;
        control.addEventListener('change', () => refresh());
    });
    document.querySelectorAll('[data-metric]').forEach(button => button.addEventListener('click', () => {
        setMetric(button.dataset.metric);
        draw();
        history.replaceState(null, '', shareLink());
    }));
    document.querySelectorAll('[data-side]').forEach(button => button.addEventListener('click', () => {
        setSide(button.dataset.side);
        refresh();
    }));
    $('copy-link').addEventListener('click', async () => {
        const copied = await navigator.clipboard?.writeText(shareLink().href).then(() => true, () => false);
        $('copy-link').textContent = copied ? 'Link copied' : 'Copy the address from the address bar';
        setTimeout(() => { $('copy-link').textContent = 'Copy link to this view'; }, 2500);
    });
    $('normalize-shots').addEventListener('change', () => {
        model.hover = [];
        panels.forEach(panel => { panel.querySelector('.court-hover').hidden = true; });
        renderCourts();
        renderHistoryRows();
    });
    $('area-rows').addEventListener('click', event => {
        const row = event.target.closest('tr[data-zone]');
        if (row) selectArea(Number(row.dataset.zone));
    });
    $('compare-rule').addEventListener('click', () => {
        $('season').value = '2012';
        options($('compare'), 'No comparison', index.seasons.filter(year => year !== 2012).map(year => [String(year), year]), '2013');
        $('phase').value = '0';
        $('team').value = 'all';
        $('player').value = 'all';
        $('shot-type').value = 'all';
        setMetric('share');
        const square = Math.floor((21 - grid.baseline) / grid.size) * grid.cols + Math.floor(grid.cols / 2);
        model.lastSquare = square;
        model.selection = {kind: 'cell', value: square};
        refresh();
    });
    panels.forEach(bindCourt);
    let paintFrame;
    const resize = () => { cancelAnimationFrame(paintFrame); paintFrame = requestAnimationFrame(draw); };
    window.addEventListener('resize', resize);
    new MutationObserver(resize).observe(document.documentElement, {attributes:true, attributeFilter:['data-theme']});
    await refresh(openLink());
    const matches = data => data.manifestSha256 === index.manifestSha256;
    const teamData = json('data/teams.json').catch(() => null);
    Promise.all([json('data/shot-mix.json'), json('data/shot-timing.json').catch(() => null), teamData]).then(([mix, timing, teams]) => {
        if (!matches(mix)) return;
        const usable = data => data && matches(data) ? data : null;
        headline($('headline'), mix, usable(timing), usable(teams));
        shotMix($('shot-mix'), mix, palette);
        if (!usable(teams)) return;
        extras.teams = teams;
        const example = teams.seasons['2026']?.find(row => row.name === 'Las Vegas Aces');
        if (example) {
            $('example-team').hidden = false;
            $('example-team').addEventListener('click', async () => {
                setSide('taken');
                $('season').value = '2026';
                $('compare').value = 'off';
                $('shot-type').value = 'all';
                await refresh({team: String(example.id), player: 'all'});
                $('example-text').textContent = teamStory(teams, '2026', example.id);
                $('example-note').hidden = false;
            });
            $('example-close').addEventListener('click', () => {
                $('season').value = 'all';
                refresh({team: 'all', player: 'all'});
            });
        }
        teamControl($('team-control'), teams);
        $('more-control').hidden = false;
        renderTeam();
    }).catch(error => console.warn(error));
    Promise.all([json('data/shooters.json'), json('data/prediction-2027.json').catch(() => null), json('data/prediction-surface.json').catch(() => null), teamData]).then(([data, forecast, surface, teams]) => {
        if (!matches(data)) return;
        forecast = forecast && matches(forecast) ? forecast : null;
        extras.shooters = data;
        shooters($('shooters'), data, forecast, {rules: index.court, grid: index.grid, palette, load: () => json('data/shooter-areas.json')});
        $('more-shooters').hidden = false;
        renderTeam();
        if (!forecast) return;
        prediction($('prediction'), forecast, surface && matches(surface) ? {surface, rules: index.court, palette} : null, teams && matches(teams) ? teams : null);
        $('more-prediction').hidden = false;
    }).catch(error => console.warn(error));
    json('data/team-possessions.json').then(data => {
        if (!matches(data)) return;
        extras.possessions = data;
        renderTeam();
    }).catch(error => console.warn(error));
    json('data/model-ladder.json').then(data => {
        if (!matches(data)) return;
        ladder($('model-ladder'), data);
        $('more-ladder').hidden = false;
    }).catch(error => console.warn(error));
    document.addEventListener('toggle', event => {
        if (event.target.open) window.dispatchEvent(new Event('resize'));
    }, true);
    window.addEventListener('hashchange', reveal);
    Promise.all([json('data/findings.json'), json('data/study.json'), json('data/bayesian.json'), json('data/shot-form.json'), json('data/plays.json'),
        json('data/shot-timing.json').catch(error => { console.warn(error); return null; })])
        .then(([findings, study, bayesian, forms, plays, timing]) => {
            if ([study, forms, plays].some(result => result.manifestSha256 !== index.manifestSha256)) throw new Error('Research data differ from the explorer snapshot');
            const matchedTiming = timing?.manifestSha256 === index.manifestSha256 && timing.playManifestSha256 === plays.playManifestSha256;
            renderStudy(findings, study, index.court, bayesian, palette, forms, plays, matchedTiming ? timing : null);
            reveal();
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
