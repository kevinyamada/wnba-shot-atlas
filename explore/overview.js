import { posteriorView } from './posterior.js?v=5';
import { paintAreaMap } from './drawing.js?v=7';

const count = new Intl.NumberFormat('en-CA');
const whole = value => Math.round(100 * value) + '%';
const signed = value => (value < 0 ? '−' : '+') + Math.abs(value).toFixed(1);
const span = text => { const [a, b] = text.split(' to '); return a === b ? a : text; };
const moreWords = value => `${Math.abs(value).toFixed(1)} ${value < 0 ? 'fewer' : 'more'}`;
const betterWords = value => Math.abs(value) < .05 ? 'Level' : `${Math.abs(value).toFixed(1)} ${value > 0 ? 'better' : 'worse'}`;

function el(tag, text, className) {
    const node = document.createElement(tag);
    if (text != null) node.textContent = text;
    if (className) node.className = className;
    return node;
}

// Plain words for how alike a number is across two sets of games in the same season.
const steadiness = value => value >= .75 ? 'very consistent' : value >= .5 ? 'fairly consistent' : value >= .3 ? 'only somewhat consistent' : 'not consistent';

function takeaway(number, text) {
    const item = el('li');
    item.append(el('strong', number), el('span', text));
    return item;
}

function headlineParts(mix, timing) {
    const [change] = mix.comparisons;
    const areas = mix.comparisonAreas.filter(area => area.comparison === change.comparison).slice(0, 3);
    const names = ['Near the basket', 'Midrange', 'Threes'];
    const title = el('h2', 'Teams swapped midrange shots for threes');
    title.id = 'headline-title';
    const legend = el('p', null, 'diet-key');
    legend.append(...names.map((name, i) => el('span', name, 'area-' + i)));
    const chart = el('div', null, 'diet');
    chart.setAttribute('role', 'img');
    const described = [];
    for (const [period, shareKey, rateKey, total] of [[change.first, 'share_before', 'points_per_shot_before', change.before],
        [change.second, 'share_after', 'points_per_shot_after', change.after]]) {
        const row = el('div', null, 'diet-row');
        const bar = el('div', null, 'diet-bar');
        areas.forEach((area, i) => {
            const part = el('div', null, 'area-' + i);
            part.style.flexGrow = area[shareKey];
            part.dataset.area = names[i];
            const rate = el('small', area[rateKey].toFixed(2));
            rate.append(el('span', ' a shot', 'unit'));
            part.append(el('strong', whole(area[shareKey])), rate);
            bar.append(part);
        });
        row.append(el('span', span(period), 'diet-period'), bar, el('span', total.toFixed(2) + ' points per shot', 'diet-total'));
        chart.append(row);
        described.push(`${span(period)}: ` + areas.map((area, i) => `${names[i].toLowerCase()} ${whole(area[shareKey])}`).join(', '));
    }
    chart.setAttribute('aria-label', 'Share of shots by court area. ' + described.join('. ') + '.');
    const caption = el('p', 'Bar width is the share of shots from each area. The small number is points per shot there.', 'caption');
    const figure = el('div', null, 'diet-figure');
    figure.append(legend, chart, caption);
    const three = areas[2];
    const points = el('ul', null, 'takeaways');
    points.append(takeaway(whole(three.share_after), `of shots are threes now, up from ${whole(three.share_before)}.`),
        takeaway(change.after.toFixed(2), `points on the average shot, up from ${change.before.toFixed(2)}.`));
    if (timing) {
        const {Steal: steal, 'Opponent basket': basket} = timing.scopes.both.groups;
        const quick = group => 100 * group.shots[timing.mainSeconds] / group.starts;
        points.append(takeaway(Math.round(quick(steal)) + '%', `of possessions after a steal get a shot up within ${timing.mainSeconds} seconds. After a made basket it is ${Math.round(quick(basket))}%.`));
    }
    return {title, figure, points};
}

export function headline(target, mix, timing, teams) {
    const {title, figure, points} = headlineParts(mix, timing);
    if (teams) {
        const repeat = Object.fromEntries(teams.repeatability.map(row => [row.measure, row.split_half]));
        points.append(takeaway('Steady', `is the word for where a team shoots from: it looks ${steadiness(repeat.offence_quality)} from game to game. Whether opponents make their shots against a team is ${steadiness(repeat.defence_making)}.`));
    }
    const grid = el('div', null, 'headline-grid');
    grid.append(figure, points);
    target.replaceChildren(title, grid);
    target.hidden = false;
}

function shooterRow(player, limit, chosen) {
    const row = el('div', null, 'relative-row');
    row.classList.toggle('chosen', chosen);
    const track = el('div', null, 'relative-track');
    const interval = el('span', null, 'relative-interval');
    const point = el('span', null, 'relative-point');
    const at = value => 50 + 50 * Math.max(-1, Math.min(1, value / limit));
    interval.style.left = at(player.low) + '%';
    interval.style.width = (at(player.high) - at(player.low)) + '%';
    point.style.left = at(player.estimate) + '%';
    track.append(interval, point);
    row.append(el('span', player.name), track, el('em', `${moreWords(player.estimate)} · ${count.format(player.attempts)} shots`));
    row.title = (player.makes == null ? 'Predicted. ' : `${player.makes} made, ${player.expected} expected. `) + `Range ${signed(player.low)} to ${signed(player.high)}.`;
    return row;
}

export function shooters(target, data, predicted, court) {
    const seasons = Object.keys(data.seasons).sort().reverse();
    const first = seasons.at(-1), last = seasons[0];
    const lead = el('p', 'For every 100 shots, how many more went in than an average shooter would make from the same distances with the same kinds of shot. The line shows how sure the number is: more shots give a shorter line. Players with few shots are pulled toward the middle, so one hot week does not top the list.');
    const season = el('select');
    season.id = 'shooter-season';
    season.append(new Option(`${first} to ${last}`, 'career'), ...(predicted ? [new Option(`${predicted.season} prediction`, 'prediction')] : []),
        ...seasons.map(year => new Option(year, year)));
    const who = el('select');
    who.id = 'shooter-player';
    const pickers = el('div', null, 'timing-controls');
    const seasonLabel = el('label', 'Seasons', 'study-picker');
    seasonLabel.append(season);
    const whoLabel = el('label', 'Find a player', 'study-picker');
    whoLabel.append(who);
    pickers.append(seasonLabel, whoLabel);
    const chart = el('div', null, 'relative-chart');
    chart.id = 'shooter-chart';
    chart.setAttribute('aria-live', 'polite');
    const note = el('p', null, 'caption');
    const forecast = data.forecast.find(row => row.shots === 'all shots' && row.forecast === 'pooled');
    const raw = data.forecast.find(row => row.shots === 'all shots' && row.forecast === 'raw');
    const method = el('p', `Does it hold up? Knowing a player’s number from last season made forecasts of next season’s shots ${forecast.drop_pct.toFixed(2)}% more accurate. `
        + `Without the pull toward the middle, they were ${Math.abs(raw.drop_pct).toFixed(2)}% ${raw.drop_pct < 0 ? 'less' : 'more'} accurate than forecasts that ignore who is shooting. `
        + `Players truly differ by about ${data.skillSpread.toFixed(1)} makes per 100 shots. The number reflects the shots a player took, so it cannot separate skill from shot choice or from how closely the player is guarded.`, 'caption');

    function players() {
        if (season.value === 'prediction') return predicted.shooters;
        return season.value === 'career' ? data.career : data.seasons[season.value];
    }

    function render() {
        const list = players();
        const limit = Math.ceil(Math.max(...list.map(p => Math.max(Math.abs(p.low), Math.abs(p.high)))) / 2) * 2;
        const key = el('div', null, 'relative-key');
        key.append(el('span', `${limit} fewer`), el('span', 'Average shooter'), el('span', `${limit} more`));
        const chosen = list.find(player => String(player.id) === who.value);
        const shown = list.slice(0, 10);
        if (chosen && !shown.includes(chosen)) shown.push(chosen);
        chart.replaceChildren(key, ...shown.map(player => shooterRow(player, limit, player === chosen)));
        const minimum = season.value === 'career' ? data.minimum.career : data.minimum.season;
        note.textContent = season.value === 'prediction'
            ? `Predicted for ${predicted.season} from ${predicted.season - 1}, written on ${predicted.written}. Top ten of ${list.length} players. Shot counts are from ${predicted.season - 1}.`
            : `Top ten of ${list.length} players with at least ${minimum} eligible attempts` + (chosen && shown.length > 10 ? `, plus ${chosen.name}.` : '.');
    }

    const scouting = el('div', null, 'area-scout');
    scouting.id = 'shooter-areas';
    scouting.hidden = true;
    let areaData = null;

    async function scout() {
        const chosen = players().find(player => String(player.id) === who.value);
        if (!court || !chosen || season.value === 'prediction') { scouting.hidden = true; return; }
        areaData ??= await court.load();
        const rows = (season.value === 'career' ? areaData.career : areaData.seasons[season.value])?.[chosen.id] ?? [];
        if (String(chosen.id) !== who.value || !rows.length) { scouting.hidden = true; return; }
        const limit = Math.max(4, ...rows.map(row => Math.abs(row[3])));
        const canvas = el('canvas');
        canvas.setAttribute('role', 'img');
        canvas.setAttribute('aria-label', `${chosen.name} by court area. ` + rows.map(row => `${areaData.areas[row[0]]} ${signed(row[3])}`).join(', ') + ' makes per 100 shots against expectation.');
        const list = el('div', null, 'area-list');
        for (const [zone, attempts, makes, estimate, low, high] of rows) {
            const line = el('div', null, 'area-line');
            line.dataset.zone = zone;
            line.dataset.value = estimate;
            const track = el('span', null, 'mini-track');
            const bar = el('i', null, estimate >= 0 ? 'good' : 'bad');
            bar.style.width = (50 * Math.min(1, Math.abs(estimate) / limit)) + '%';
            bar.style[estimate >= 0 ? 'left' : 'right'] = '50%';
            track.append(bar);
            const words = `${Math.abs(estimate).toFixed(1)} ${estimate >= 0 ? 'more' : 'fewer'} per 100`;
            line.title = `${makes} of ${attempts} made. Range ${signed(low)} to ${signed(high)}.`;
            line.append(el('span', areaData.areas[zone]), track, el('em', `${words} · ${count.format(attempts)} shots`, estimate >= 0 ? 'good' : 'bad'));
            list.append(line);
        }
        const title = el('h3', `${chosen.name} by court area`);
        const key = el('p', 'Blue areas are where the player makes more than an average shooter would from the same shots. Orange areas are where the player makes fewer. Small samples are pulled toward the middle.', 'caption');
        const body = el('div', null, 'area-scout-body');
        body.append(canvas, list);
        scouting.replaceChildren(title, body, key);
        scouting.hidden = false;
        const paint = () => paintAreaMap(canvas, court.rules, court.grid, court.rules.eras.at(-1), court.palette(), rows.map(row => [row[0], row[3]]), limit);
        requestAnimationFrame(paint);
        scouting.repaint = paint;
    }

    window.addEventListener('resize', () => { if (!scouting.hidden) scouting.repaint?.(); });
    new MutationObserver(() => { if (!scouting.hidden) scouting.repaint?.(); }).observe(document.documentElement, {attributes: true, attributeFilter: ['data-theme']});

    function fill() {
        const current = who.value;
        who.replaceChildren(new Option('Top ten only', ''), ...[...players()].sort((a, b) => a.name.localeCompare(b.name)).map(p => new Option(p.name, p.id)));
        who.value = [...who.options].some(option => option.value === current) ? current : '';
        render();
        scout();
    }

    season.addEventListener('change', fill);
    who.addEventListener('change', () => { render(); scout(); });
    target.replaceChildren(lead, pickers, chart, note, scouting, method);
    fill();
}

export function ladder(target, data) {
    const {summary, steps} = data;
    const removed = 1 - summary.distance_brier / summary.league_brier;
    const extra = (summary.distance_brier - summary.full_brier) / summary.league_brier;
    const parts = [['Distance', removed, 'area-0'], ['Everything else recorded', extra, 'area-2'], ['Still unexplained', 1 - removed - extra, 'area-1']];
    const lead = el('p', `Guess that every shot has the league’s average chance of going in and the guess will be off by some amount. Knowing only how far the shot is from the rim removes ${(100 * removed).toFixed(1)}% of that error. `
        + `Adding court position, shot type, the clock and score, the previous event and the shooter’s record removes just ${(100 * extra).toFixed(1)}% more.`);
    const bar = el('div', null, 'diet-bar ladder-bar');
    bar.setAttribute('role', 'img');
    bar.setAttribute('aria-label', parts.map(([name, value]) => `${name} ${(100 * value).toFixed(1)}%`).join(', '));
    for (const [name, value, tone] of parts) {
        const part = el('div', null, tone);
        part.style.flexGrow = Math.max(value, .08);
        part.append(el('strong', (100 * value).toFixed(1) + '%'));
        bar.append(part);
    }
    const legend = el('p', null, 'diet-key');
    legend.append(...parts.map(([name, , tone]) => el('span', name, tone)));
    const why = el('p', `One shot either goes in or it does not, so most of the error is chance that no forecast can remove. To do 10% better than distance, a forecast would have to tell easy shots from hard ones much more sharply: on a typical shot its make chance would sit about ${(100 * data.ceiling.find(row => row.target_drop_pct === 10).spread_needed).toFixed(0)} percentage points from the average. `
        + `Distance manages ${(100 * summary.distance_spread).toFixed(1)} and everything recorded today reaches ${(100 * summary.full_spread).toFixed(1)}. `
        + 'These files have no defender positions, passes or movement, so the gain from tracking data cannot be measured here.');
    const table = el('table');
    const head = table.createTHead().insertRow();
    for (const text of ['Information added', 'Error', 'Drop from distance']) head.append(Object.assign(el('th', text), {scope: 'col'}));
    const body = table.createTBody();
    for (const step of steps) {
        const row = body.insertRow();
        row.append(Object.assign(el('th', step.step === 'League rate' ? 'League make rate only' : step.step), {scope: 'row'}), el('td', step.brier.toFixed(5)),
            el('td', step.drop_vs_distance_pct == null || step.step === 'Distance' ? '' : step.drop_vs_distance_pct.toFixed(2) + '%'));
    }
    const wrap = el('div', null, 'table-scroll');
    wrap.append(table);
    const note = el('p', `${count.format(steps[0].attempts)} shots from the 2026 regular season. Models learned from 2022 to 2024 and were tuned on 2025. Error is the average squared gap between the forecast chance and what happened, known as the Brier score. Lower is better.`, 'caption');
    target.replaceChildren(lead, legend, bar, why, wrap, note);
}

const measureOrder = ['offence_quality', 'offence_making', 'defence_quality', 'defence_making'];
const place = n => n + (n % 100 > 10 && n % 100 < 14 ? 'th' : ['th', 'st', 'nd', 'rd'][n % 10] || 'th');

const plain = {offence_quality: 'Gets good shots', offence_making: 'Makes its shots', defence_quality: 'Limits good shots', defence_making: 'Opponents miss'};

// Points a game against an average team, signed so that a positive value always helps the team.
function perGame(row, name, field = 'estimate') {
    const own = name.startsWith('offence');
    return (own ? 1 : -1) * row[name][field] * (own ? row.shots : row.shotsAgainst) / row.games / 100;
}

const netPerGame = row => measureOrder.reduce((sum, name) => sum + perGame(row, name), 0);
const gameWords = value => Math.abs(value) < .05 ? 'level with an average team' : `${Math.abs(value).toFixed(1)} points a game ${value > 0 ? 'better' : 'worse'}`;

function phrase(name, value) {
    const lead = {offence_quality: 'Where it shoots from is worth', offence_making: 'Its shot making is worth', defence_quality: 'Where opponents shoot from is worth',
        defence_making: 'Opponents’ shot making is worth'}[name];
    return Math.abs(value) < .05 ? `${lead} about the same as for an average team.` : `${lead} ${Math.abs(value).toFixed(1)} points a game ${value > 0 ? 'for' : 'against'} it.`;
}

function startsTable(rows, heading) {
    const table = el('table');
    const head = table.createTHead().insertRow();
    for (const text of [heading, 'Share', 'Points per 100', 'Rest of league']) head.append(Object.assign(el('th', text), {scope: 'col'}));
    const body = table.createTBody();
    for (const row of rows) {
        const line = body.insertRow();
        line.append(Object.assign(el('th', row.start.replace('Opponent', 'After opponent').replace('Steal', 'After a steal').replace('Defensive rebound', 'After a defensive rebound')), {scope: 'row'}),
            el('td', whole(row.share)), el('td', `${row.per100.toFixed(0)} ± ${row.margin.toFixed(0)}`), el('td', row.league.toFixed(0)));
    }
    const wrap = el('div', null, 'table-scroll');
    wrap.append(table);
    return wrap;
}

const factorOrder = [['offence_turnovers', 'Keeps the ball', -1], ['offence_rebounds', 'Wins second chances', 1], ['offence_free_throws', 'Gets to the line', 1],
    ['defence_turnovers', 'Forces turnovers', 1], ['defence_rebounds', 'Ends it with the rebound', -1], ['defence_free_throws', 'Keeps them off the line', -1]];
let teamView = 'shots';

function miniBar(value, limit, title) {
    const cell = el('td', null, 'bar-cell');
    cell.dataset.value = value.toFixed(3);
    cell.title = title;
    cell.setAttribute('aria-label', title);
    const track = el('span', null, 'mini-track');
    const bar = el('i', null, value >= 0 ? 'good' : 'bad');
    bar.style.width = (50 * Math.min(1, Math.abs(value) / limit)) + '%';
    bar.style[value >= 0 ? 'left' : 'right'] = '50%';
    track.append(bar);
    cell.append(track);
    return cell;
}

function viewSwitch(redraw) {
    const group = el('div', null, 'metric-group');
    group.id = 'team-view';
    group.setAttribute('role', 'group');
    group.setAttribute('aria-label', 'Team table shows');
    for (const [value, text] of [['shots', 'Shots'], ['possessions', 'Whole possessions']]) {
        const button = el('button', text);
        button.type = 'button';
        button.dataset.view = value;
        button.setAttribute('aria-pressed', String(teamView === value));
        button.addEventListener('click', () => { teamView = value; redraw(); });
        group.append(button);
    }
    return group;
}

function possessionTable(teams, year, pick) {
    const ranked = [...teams].sort((a, b) => b.net - a.net);
    const limits = Object.fromEntries(factorOrder.map(([name]) => [name, Math.max(...teams.map(row => Math.abs(row[name].estimate)))]));
    const table = el('table');
    table.id = 'team-table';
    const head = table.createTHead().insertRow();
    for (const text of ['Team', ...factorOrder.map(([, label]) => label), 'Overall']) head.append(Object.assign(el('th', text), {scope: 'col'}));
    const body = table.createTBody();
    for (const row of ranked) {
        const line = body.insertRow();
        const name = el('th');
        name.scope = 'row';
        const button = el('button', row.name);
        button.type = 'button';
        button.dataset.team = row.id;
        button.addEventListener('click', () => pick(row.id, year));
        const words = Math.abs(row.net) < .05 ? 'Level' : `${Math.abs(row.net).toFixed(1)} ${row.net > 0 ? 'better' : 'worse'}`;
        name.append(button, el('small', words, 'team-overall ' + (row.net >= 0 ? 'good' : 'bad')));
        line.append(name);
        for (const [key, label, sign] of factorOrder) line.append(miniBar(sign * row[key].estimate, limits[key], `${label}: ${row[key].value} against ${row[key].league} for the rest of the league`));
        const overall = el('td', words, row.net >= 0 ? 'good' : 'bad');
        overall.dataset.value = row.net.toFixed(3);
        line.append(overall);
    }
    const wrap = el('div', null, 'table-scroll');
    wrap.append(table);
    return wrap;
}

function possessionDetail(row, labels, count) {
    const table = el('table');
    table.id = 'team-possessions';
    const head = table.createTHead().insertRow();
    for (const text of ['Whole possessions', 'This team', 'Rest of league', '']) head.append(Object.assign(el('th', text), {scope: 'col'}));
    const body = table.createTBody();
    const order = [['offence_points', 1], ['offence_turnovers', -1], ['offence_rebounds', 1], ['offence_free_throws', 1], ['defence_points', -1], ['defence_turnovers', 1], ['defence_rebounds', -1], ['defence_free_throws', -1]];
    for (const [name, sign] of order) {
        const line = body.insertRow();
        line.dataset.measure = name;
        const spread = Math.max(Math.abs(row[name].low), Math.abs(row[name].high), 1e-6);
        line.append(Object.assign(el('th', labels[name]), {scope: 'row'}), el('td', row[name].value.toFixed(1)), el('td', row[name].league.toFixed(1)),
            miniBar(sign * row[name].estimate, 1.5 * spread, sign * row[name].estimate >= 0 ? 'Helps the team' : 'Hurts the team'));
    }
    const wrap = el('div', null, 'table-scroll');
    wrap.append(table);
    return wrap;
}

export function teamReport(target, data, shooterData, {season, team, pick}, possessionData) {
    const redraw = () => teamReport(target, data, shooterData, {season, team, pick}, possessionData);
    const years = Object.keys(data.seasons).sort();
    const year = years.includes(String(season)) ? String(season) : years.at(-1);
    const teams = data.seasons[year];
    const chosen = teams.find(row => String(row.id) === String(team));
    const repeat = Object.fromEntries(data.repeatability.map(row => [row.measure, row.split_half]));
    const trust = el('p', 'How consistent was this across games? '
        + measureOrder.map(name => `${plain[name]}: ${steadiness(repeat[name])}.`).join(' ')
        + ' A number that is not consistent can swing a lot from one stretch of games to the next, so read that bar with care.', 'caption');
    trust.id = 'team-consistency';
    const scope = el('p', (String(season) === year ? '' : `Showing ${year}. Team reports cover ${years[0]} to ${years.at(-1)}. `)
        + 'Regular season, field goals only. Each value compares the team with the rest of the league, with small samples pulled toward average.', 'caption');
    if (!chosen) {
        const factors = possessionData?.seasons[year];
        if (factors && teamView === 'possessions') {
            const title = el('h2', `What each team did with its possessions in ${year}`);
            title.id = 'team-title';
            const key = el('p', 'Each bar compares the team with the rest of the league. Blue to the right helps the team and orange to the left hurts it. The columns use different units, so compare bars within a column. Overall is points per 100 possessions scored minus allowed, free throws included.', 'caption');
            target.replaceChildren(title, viewSwitch(redraw), possessionTable(factors, year, pick), key, scope);
            target.hidden = false;
            return;
        }
        const title = el('h2', `Where each team gained and lost points in ${year}`);
        title.id = 'team-title';
        const ranked = [...teams].sort((x, y) => netPerGame(y) - netPerGame(x));
        const limit = Math.max(...teams.flatMap(row => measureOrder.map(name => Math.abs(perGame(row, name)))));
        const table = el('table');
        table.id = 'team-table';
        const head = table.createTHead().insertRow();
        for (const text of ['Team', ...measureOrder.map(name => plain[name]), 'Overall']) head.append(Object.assign(el('th', text), {scope: 'col'}));
        const body = table.createTBody();
        for (const row of ranked) {
            const line = body.insertRow();
            const name = el('th');
            name.scope = 'row';
            const button = el('button', row.name);
            button.type = 'button';
            button.dataset.team = row.id;
            button.addEventListener('click', () => pick(row.id, year));
            const net = netPerGame(row);
            const words = Math.abs(net) < .05 ? 'Level' : `${Math.abs(net).toFixed(1)} ${net > 0 ? 'better' : 'worse'}`;
            name.append(button, el('small', words, 'team-overall ' + (net >= 0 ? 'good' : 'bad')));
            line.append(name);
            for (const key of measureOrder) {
                const value = perGame(row, key);
                line.append(miniBar(value, limit, `${plain[key]}: ${gameWords(value)}`));
            }
            const overall = el('td', words, net >= 0 ? 'good' : 'bad');
            overall.dataset.value = net.toFixed(3);
            line.append(overall);
        }
        const wrap = el('div', null, 'table-scroll');
        wrap.append(table);
        const key = el('p', 'Each bar is field goal points a game against an average team. A blue bar to the right helps the team. An orange bar to the left hurts it. Overall adds the four. Pick a team for its full report.', 'caption');
        target.replaceChildren(title, ...(factors ? [viewSwitch(redraw)] : []), wrap, key, trust, scope);
        target.hidden = false;
        return;
    }
    const title = el('h2', `${chosen.name} in ${year}`);
    title.id = 'team-title';
    const summary = el('p', measureOrder.map(name => phrase(name, perGame(chosen, name))).join(' ') + ` Overall it is ${gameWords(netPerGame(chosen))}.`);
    summary.id = 'team-summary';
    const ends = (row, name) => [perGame(row, name, 'low'), perGame(row, name, 'high')].sort((x, y) => x - y);
    const limit = Math.ceil(Math.max(...teams.flatMap(row => measureOrder.flatMap(name => ends(row, name).map(Math.abs)))));
    const chart = el('div', null, 'relative-chart');
    chart.id = 'team-chart';
    const scale = el('div', null, 'relative-key');
    scale.append(el('span', `${limit} points a game worse`), el('span', 'Average team'), el('span', `${limit} better`));
    chart.append(scale);
    for (const name of measureOrder) {
        const value = perGame(chosen, name);
        const [low, high] = ends(chosen, name);
        const rank = [...teams].sort((x, y) => perGame(y, name) - perGame(x, name)).indexOf(chosen) + 1;
        const row = el('div', null, 'relative-row');
        row.dataset.measure = name;
        row.dataset.value = value.toFixed(3);
        const track = el('div', null, 'relative-track');
        const interval = el('span', null, 'relative-interval');
        const point = el('span', null, 'relative-point');
        const at = x => 50 + 50 * Math.max(-1, Math.min(1, x / limit));
        interval.style.left = at(low) + '%';
        interval.style.width = (at(high) - at(low)) + '%';
        point.style.left = at(value) + '%';
        track.append(interval, point);
        const note = el('em', `${place(rank)} of ${teams.length}`);
        note.className = value >= 0 ? 'good' : 'bad';
        row.append(el('span', plain[name]), track, note);
        chart.append(row);
    }
    const parts = [title, summary, chart, trust];
    const whole = possessionData?.seasons[year]?.find(row => row.id === chosen.id);
    if (whole) parts.push(possessionDetail(whole, possessionData.labels, count));
    if (chosen.starts.offence.length) {
        const starts = el('div', null, 'team-starts');
        starts.append(startsTable(chosen.starts.offence, 'When it has the ball'), startsTable(chosen.starts.defence, 'When opponents have the ball'));
        parts.push(starts);
    }
    const roster = shooterData?.seasons[year]?.filter(player => player.team === chosen.id).slice(0, 3) ?? [];
    if (roster.length) {
        parts.push(el('p', 'Best shooters, in makes per 100 shots against an average shooter: ' + roster.map(player => `${player.name} ${moreWords(player.estimate)}`).join(', ') + '.'));
    }
    const back = el('button', 'See all teams');
    back.type = 'button';
    back.id = 'team-back';
    back.addEventListener('click', () => pick('all', year));
    target.replaceChildren(...parts, back, scope);
    target.hidden = false;
}

export function teamControl(target, data) {
    const lead = el('p', 'Take one team’s season and deal its games into two piles, like dealing cards. If a number comes out about the same in both piles, it is consistent: it reflects how the team plays. If the two piles disagree, the number swings from game to game and one stretch of games says little.');
    const table = el('table');
    const head = table.createTHead().insertRow();
    for (const text of ['Measure', 'Match between the two piles', 'Match with the next season', 'In words']) head.append(Object.assign(el('th', text), {scope: 'col'}));
    const body = table.createTBody();
    for (const row of data.repeatability) {
        const line = body.insertRow();
        line.append(Object.assign(el('th', row.label), {scope: 'row'}), el('td', `${row.split_half.toFixed(2)} (${row.split_half_low.toFixed(2)} to ${row.split_half_high.toFixed(2)})`),
            el('td', `${row.next_season.toFixed(2)} (${row.next_season_low.toFixed(2)} to ${row.next_season_high.toFixed(2)})`), el('td', steadiness(row.split_half)));
    }
    const wrap = el('div', null, 'table-scroll');
    wrap.append(table);
    const strongest = [...data.repeatability].sort((a, b) => b.split_half - a.split_half);
    const meaning = el('p', `${strongest[0].label} is the most consistent and ${strongest.at(-1).label.toLowerCase()} the least. `
        + 'For a defence, the shots it allows say more than whether opponents happened to make them. These are descriptions of past seasons and do not show that changing a scheme would move a number.');
    const note = el('p', `${data.repeatability[0].team_seasons} team seasons from 2016 to 2026. The match is scored from 0 to 1, where 1 means the two piles agree exactly. The range in brackets is where the true value plausibly lies.`, 'caption');
    target.replaceChildren(lead, wrap, meaning, note);
}

function dotKey(last, season) {
    const key = el('p', null, 'dot-key');
    for (const [kind, text] of [['hollow', String(last)], ['', `${season} prediction`], ['range', 'Likely range']]) {
        const item = el('span', text);
        item.prepend(el('i', null, kind));
        key.append(item);
    }
    return key;
}

export function prediction(target, data, court, teams) {
    const last = data.season - 1;
    const lead = el('p', `Written on ${data.written}, before any ${data.season} game. Each prediction starts from what a team or shooter did in past seasons and pulls it part of the way back toward average, because a very good or very bad year rarely repeats in full.`);
    const league = el('ul', null, 'takeaways');
    for (const row of data.league) {
        const share = row.measure.startsWith('Share');
        const show = value => share ? value.toFixed(1) + '%' : value.toFixed(2);
        league.append(takeaway(show(row.prediction), `${share ? 'of shots from the three point area' : 'field goal points per shot'}. Likely range ${show(row.low)} to ${show(row.high)}. In ${last} it was ${show(row.value_2026)}.`));
    }

    function dotRow(name, value, limit, words) {
        const line = el('div', null, 'relative-row');
        line.dataset.value = value.prediction.toFixed(3);
        line.dataset.last = value.last.toFixed(3);
        line.title = `In ${last}: ${words(value.last)}. Likely range ${words(value.low)} to ${words(value.high)}.`;
        const track = el('div', null, 'relative-track');
        const interval = el('span', null, 'relative-interval');
        const before = el('span', null, 'relative-last');
        const point = el('span', null, 'relative-point');
        const at = x => 50 + 50 * Math.max(-1, Math.min(1, x / limit));
        interval.style.left = at(value.low) + '%';
        interval.style.width = (at(value.high) - at(value.low)) + '%';
        before.style.left = at(value.last) + '%';
        point.style.left = at(value.prediction) + '%';
        track.append(interval, before, point);
        line.append(el('span', name), track, el('em', words(value.prediction)));
        return line;
    }

    const teamParts = [];
    const past = teams?.seasons[last] ?? [];
    if (past.length) {
        const pace = row => ({own: row.shots / row.games / 100, other: row.shotsAgainst / row.games / 100});
        const usual = {own: past.reduce((sum, row) => sum + pace(row).own, 0) / past.length, other: past.reduce((sum, row) => sum + pace(row).other, 0) / past.length};
        const aGame = (team, name, field) => {
            const {own, other} = pace(past.find(row => row.id === team.id) ?? {shots: 100 * usual.own, shotsAgainst: 100 * usual.other, games: 1});
            return team[name][field] * (name === 'net' ? (own + other) / 2 : name.startsWith('offence') ? own : -other);
        };
        const label = el('label', 'Show', 'study-picker');
        const select = el('select');
        select.id = 'prediction-measure';
        for (const [name, text] of [['net', 'Overall'], ...measureOrder.map(name => [name, plain[name]])]) select.append(new Option(text, name));
        label.append(select);
        const chart = el('div', null, 'relative-chart');
        chart.id = 'prediction-teams';
        chart.setAttribute('aria-live', 'polite');
        const render = () => {
            const name = select.value;
            const rows = data.teams.map(team => {
                const [low, high] = [aGame(team, name, 'low'), aGame(team, name, 'high')].sort((a, b) => a - b);
                return {name: team.name, prediction: aGame(team, name, 'prediction'), last: aGame(team, name, 'last'), low, high};
            }).sort((a, b) => b.prediction - a.prediction);
            const limit = Math.ceil(Math.max(...rows.flatMap(row => [Math.abs(row.low), Math.abs(row.high)])));
            const key = el('div', null, 'relative-key');
            key.append(el('span', `${limit} points a game worse`), el('span', 'Average team'), el('span', `${limit} better`));
            chart.replaceChildren(key, ...rows.map(row => dotRow(row.name, row, limit, betterWords)));
        };
        select.addEventListener('change', render);
        render();
        const teamNote = el('p', `Field goal points a game against an average team, for a season with as many shots a game as in ${last}. The lines are wide because one season says only so much about the next, and the prediction knows nothing about trades, injuries, the draft or coaching changes.`, 'caption');
        teamParts.push(el('h3', 'Teams'), label, dotKey(last, data.season), chart, teamNote);
    }

    const shooterTitle = el('h3', 'Shooters most likely to beat an average shooter');
    const top = data.shooters.slice(0, 10);
    const limit = Math.ceil(Math.max(...top.flatMap(p => [Math.abs(p.low), Math.abs(p.high)])) / 2) * 2;
    const shooterChart = el('div', null, 'relative-chart');
    shooterChart.id = 'prediction-shooters';
    const key = el('div', null, 'relative-key');
    key.append(el('span', `${limit} fewer`), el('span', 'Average shooter'), el('span', `${limit} more`));
    shooterChart.append(key, ...top.map(p => dotRow(p.name, {prediction: p.estimate, last: p.last, low: p.low, high: p.high}, limit, moreWords)));
    const shooterNote = el('p', `Makes per 100 shots against an average shooter, for a season with as many attempts as in ${last}. All ${data.shooters.length} predicted players are under “Who makes more shots than expected?”.`, 'caption');
    const table = el('table');
    const head = table.createTHead().insertRow();
    for (const text of ['Typical miss', 'Guess the league average', 'Guess the same as last season', 'Simple carry over', 'Bayesian model', 'Real result inside the range']) head.append(Object.assign(el('th', text), {scope: 'col'}));
    const body = table.createTBody();
    for (const item of data.backtest) {
        const line = body.insertRow();
        line.append(Object.assign(el('th', item.label), {scope: 'row'}), el('td', item.rmse_league.toFixed(2)), el('td', item.rmse_same.toFixed(2)),
            el('td', item.rmse_carried.toFixed(2)), el('td', item.rmse_bayes.toFixed(2)), el('td', whole(item.inside_95)));
    }
    const wrap = el('div', null, 'table-scroll');
    wrap.id = 'prediction-backtest';
    wrap.append(table);
    const keeps = Object.fromEntries(data.seasonModel.map(row => [row.measure, row.persistence]));
    const record = el('p', `Each season from 2019 to 2026 was predicted using only earlier seasons and then compared with what happened. Each number is the typical size of the miss, so lower is better. The Bayesian model is the one used above. It finds that a shooter keeps ${whole(keeps.shooter)} of a margin from one season to the next and a team keeps ${whole(keeps.net)} of its overall number. These predictions will be scored once against the ${data.season} season.`, 'caption');
    const check = el('details');
    check.id = 'prediction-check';
    check.append(el('summary', 'How did this method do on past seasons?'), wrap, record);
    const parts = [lead, league];
    if (court) {
        const title = el('h3', 'Predicted make chance by spot');
        const view = posteriorView(court.rules, {spde: court.surface.surface}, court.palette, [['spde', 'Bayesian mesh model']]);
        view.id = 'prediction-surface';
        const fit = court.surface.backtest.find(row => row.forecast === 'mesh' && row.compared_with === 'p_distance');
        const note = el('p', `The colour is the chance that a shot from each spot goes in, learned from ${count.format(court.surface.training_shots)} shots in the three seasons before ${data.season}. Pick a spot for its chance and the range it could reasonably fall in. `
            + `On past seasons the real make rate fell inside that range at ${whole(court.surface.coverage)} of busy spots, and the forecasts were within ${Math.abs(fit.drop_pct).toFixed(2)}% of the accuracy of using distance alone. The Methods lab tab compares this model with ten others.`, 'caption');
        parts.push(title, view, note);
    }
    target.replaceChildren(...parts, ...teamParts, shooterTitle, dotKey(last, data.season), shooterChart, shooterNote, check);
}

export function teamStory(data, year, id) {
    const teams = data.seasons[year] ?? [];
    const team = teams.find(row => row.id === id);
    if (!team) return '';
    const rank = name => [...teams].sort((a, b) => perGame(b, name) - perGame(a, name)).indexOf(team) + 1;
    const quality = perGame(team, 'offence_quality'), making = perGame(team, 'offence_making');
    const effect = (value, thing) => `${thing} ${value >= 0 ? 'earned' : 'cost'} them ${Math.abs(value).toFixed(1)} points a game`;
    return `${team.name}, ${year}: ${place(rank('offence_quality'))} of ${teams.length} for getting good shots and ${place(rank('offence_making'))} for making them. `
        + `${effect(quality, 'Where they shot from')}, and ${effect(making, 'their shot making')}, compared with an average team. The full report is under the court.`;
}
