const count = new Intl.NumberFormat('en-CA');
const whole = value => Math.round(100 * value) + '%';
const signed = value => (value < 0 ? '−' : '+') + Math.abs(value).toFixed(1);
const span = text => { const [a, b] = text.split(' to '); return a === b ? a : text; };

function el(tag, text, className) {
    const node = document.createElement(tag);
    if (text != null) node.textContent = text;
    if (className) node.className = className;
    return node;
}

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
        points.append(takeaway(repeat.offence_quality.toFixed(2), `is how closely a team’s shot quality repeats between games, on a scale to 1. Opponents’ shot making against it repeats only ${repeat.defence_making.toFixed(2)}.`));
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
    row.append(el('span', player.name), track, el('em', `${signed(player.estimate)} · ${count.format(player.attempts)} shots`));
    row.title = `${player.makes} made, ${player.expected} expected. Range ${signed(player.low)} to ${signed(player.high)}.`;
    return row;
}

export function shooters(target, data) {
    const seasons = Object.keys(data.seasons).sort().reverse();
    const first = seasons.at(-1), last = seasons[0];
    const lead = el('p', 'Makes per 100 shots above what an average shooter would make from the same distances and shot types. The line shows the range the data support. Short records are pulled toward the middle.');
    const season = el('select');
    season.id = 'shooter-season';
    season.append(new Option(`${first} to ${last}`, 'career'), ...seasons.map(year => new Option(year, year)));
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
    const method = el('p', `Does it hold up? Using last season’s pooled estimate lowered the error of next season’s shot forecasts by ${forecast.drop_pct.toFixed(2)}%. `
        + `Using the raw margin without pooling made them ${Math.abs(raw.drop_pct).toFixed(2)}% ${raw.drop_pct < 0 ? 'worse' : 'better'}. `
        + `True skill differs between players by about ${data.skillSpread.toFixed(1)} makes per 100 shots. The estimate reflects the shots a player took and cannot separate skill from shot selection or defensive attention.`, 'caption');

    function players() {
        return season.value === 'career' ? data.career : data.seasons[season.value];
    }

    function render() {
        const list = players();
        const limit = Math.ceil(Math.max(...list.map(p => Math.max(Math.abs(p.low), Math.abs(p.high)))) / 2) * 2;
        const key = el('div', null, 'relative-key');
        key.append(el('span', `${limit} fewer`), el('span', 'League expectation'), el('span', `${limit} more`));
        const chosen = list.find(player => String(player.id) === who.value);
        const shown = list.slice(0, 10);
        if (chosen && !shown.includes(chosen)) shown.push(chosen);
        chart.replaceChildren(key, ...shown.map(player => shooterRow(player, limit, player === chosen)));
        const minimum = season.value === 'career' ? data.minimum.career : data.minimum.season;
        note.textContent = `Top ten of ${list.length} players with at least ${minimum} eligible attempts` + (chosen && shown.length > 10 ? `, plus ${chosen.name}.` : '.');
    }

    function fill() {
        const current = who.value;
        who.replaceChildren(new Option('Top ten only', ''), ...[...players()].sort((a, b) => a.name.localeCompare(b.name)).map(p => new Option(p.name, p.id)));
        who.value = [...who.options].some(option => option.value === current) ? current : '';
        render();
    }

    season.addEventListener('change', fill);
    who.addEventListener('change', render);
    target.replaceChildren(lead, pickers, chart, note, method);
    fill();
}

export function ladder(target, data) {
    const {summary, steps} = data;
    const removed = 1 - summary.distance_brier / summary.league_brier;
    const extra = (summary.distance_brier - summary.full_brier) / summary.league_brier;
    const parts = [['Distance', removed, 'area-0'], ['Everything else recorded', extra, 'area-2'], ['Still unexplained', 1 - removed - extra, 'area-1']];
    const lead = el('p', `Start with a forecast that gives every shot the league make rate. Distance removes ${(100 * removed).toFixed(1)}% of its error. `
        + `Court position, shot type, the clock and score, the previous event and the shooter’s record remove ${(100 * extra).toFixed(1)}% more.`);
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
    const why = el('p', `One shot either goes in or it does not, so most of the error is chance that no forecast can remove. To beat distance by 10%, predicted make chances would need to spread about ${(100 * data.ceiling.find(row => row.target_drop_pct === 10).spread_needed).toFixed(0)} points around the average. `
        + `Distance spreads them ${(100 * summary.distance_spread).toFixed(1)} points and everything recorded today reaches ${(100 * summary.full_spread).toFixed(1)}. `
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
    const note = el('p', `${count.format(steps[0].attempts)} shots from the 2026 regular season. Models learned from 2022 to 2024 and were tuned on 2025. Error is the Brier score, where lower is better.`, 'caption');
    target.replaceChildren(lead, legend, bar, why, wrap, note);
}

const measureOrder = ['offence_quality', 'offence_making', 'defence_quality', 'defence_making'];
const helps = (name, value) => name.startsWith('offence') ? value >= 0 : value <= 0;
const place = n => n + (n % 100 > 10 && n % 100 < 14 ? 'th' : ['th', 'st', 'nd', 'rd'][n % 10] || 'th');

function phrase(name, value) {
    const size = Math.abs(value) < .5 ? 'about average' : `${Math.abs(value).toFixed(1)} points per 100 shots ${value > 0 ? 'above' : 'below'} the league`;
    return {offence_quality: `Its shots are worth ${size}`, offence_making: `It scores ${size} on those shots`,
        defence_quality: `Opponents get shots worth ${size}`, defence_making: `Opponents score ${size} on them`}[name].replace('worth about average', 'of about average value') + '.';
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

export function teamReport(target, data, shooterData, {season, team, pick}) {
    const years = Object.keys(data.seasons).sort();
    const year = years.includes(String(season)) ? String(season) : years.at(-1);
    const teams = data.seasons[year];
    const chosen = teams.find(row => String(row.id) === String(team));
    const repeat = Object.fromEntries(data.repeatability.map(row => [row.measure, row.split_half]));
    const trust = el('p', 'How often each number shows up again in other games of the same season: '
        + measureOrder.map(name => `${data.measures[name].toLowerCase()} ${repeat[name].toFixed(2)}`).join(', ')
        + '. Closer to 1 means the team controls it. Closer to 0 means mostly chance.', 'caption');
    const scope = el('p', (String(season) === year ? '' : `Showing ${year}. Team reports cover ${years[0]} to ${years.at(-1)}. `)
        + 'Regular season. Points per 100 shots against the rest of the league, with small samples pulled toward average.', 'caption');
    if (!chosen) {
        const title = el('h2', `What each team controlled in ${year}`);
        title.id = 'team-title';
        const table = el('table');
        table.id = 'team-table';
        const head = table.createTHead().insertRow();
        for (const text of ['Team', ...measureOrder.map(name => data.measures[name]), 'Net']) head.append(Object.assign(el('th', text), {scope: 'col'}));
        const body = table.createTBody();
        for (const row of teams) {
            const line = body.insertRow();
            const name = el('th');
            name.scope = 'row';
            const button = el('button', row.name);
            button.type = 'button';
            button.dataset.team = row.id;
            button.addEventListener('click', () => pick(row.id, year));
            name.append(button);
            line.append(name, ...measureOrder.map(key => el('td', signed(row[key].estimate), helps(key, row[key].estimate) ? 'good' : 'bad')),
                el('td', signed(row.net), row.net >= 0 ? 'good' : 'bad'));
        }
        const wrap = el('div', null, 'table-scroll');
        wrap.append(table);
        const key = el('p', 'Blue helps the team and orange hurts it. Net adds the four together. Pick a team for its full report.', 'caption');
        target.replaceChildren(title, wrap, key, trust, scope);
        target.hidden = false;
        return;
    }
    const title = el('h2', `${chosen.name} in ${year}`);
    title.id = 'team-title';
    const summary = el('p', measureOrder.map(name => phrase(name, chosen[name].estimate)).join(' '));
    summary.id = 'team-summary';
    const limit = Math.ceil(Math.max(...teams.flatMap(row => measureOrder.flatMap(name => [Math.abs(row[name].low), Math.abs(row[name].high)]))) / 2) * 2;
    const chart = el('div', null, 'relative-chart');
    chart.id = 'team-chart';
    const scale = el('div', null, 'relative-key');
    scale.append(el('span', `${limit} below`), el('span', 'League average'), el('span', `${limit} above`));
    chart.append(scale);
    for (const name of measureOrder) {
        const value = chosen[name];
        const better = (a, b) => name.startsWith('offence') ? b[name].estimate - a[name].estimate : a[name].estimate - b[name].estimate;
        const rank = [...teams].sort(better).indexOf(chosen) + 1;
        const row = el('div', null, 'relative-row');
        row.dataset.measure = name;
        const track = el('div', null, 'relative-track');
        const interval = el('span', null, 'relative-interval');
        const point = el('span', null, 'relative-point');
        const at = x => 50 + 50 * Math.max(-1, Math.min(1, x / limit));
        interval.style.left = at(value.low) + '%';
        interval.style.width = (at(value.high) - at(value.low)) + '%';
        point.style.left = at(value.estimate) + '%';
        track.append(interval, point);
        const note = el('em', `${signed(value.estimate)} · ${place(rank)} of ${teams.length}`);
        note.className = helps(name, value.estimate) ? 'good' : 'bad';
        row.append(el('span', data.measures[name]), track, note);
        chart.append(row);
    }
    const parts = [title, summary, chart, trust];
    if (chosen.starts.offence.length) {
        const starts = el('div', null, 'team-starts');
        starts.append(startsTable(chosen.starts.offence, 'When it has the ball'), startsTable(chosen.starts.defence, 'When opponents have the ball'));
        parts.push(starts);
    }
    const roster = shooterData?.seasons[year]?.filter(player => player.team === chosen.id).slice(0, 3) ?? [];
    if (roster.length) {
        parts.push(el('p', 'Best shooters against expectation: ' + roster.map(player => `${player.name} ${signed(player.estimate)} (${signed(player.low)} to ${signed(player.high)})`).join(', ')
            + ' makes per 100 shots.'));
    }
    const back = el('button', 'See all teams');
    back.type = 'button';
    back.id = 'team-back';
    back.addEventListener('click', () => pick('all', year));
    target.replaceChildren(...parts, back, scope);
    target.hidden = false;
}

export function teamControl(target, data) {
    const lead = el('p', 'Split each team season into alternating games and compare the two halves. A number that matches across the halves reflects something the team does. One that does not is mostly chance.');
    const table = el('table');
    const head = table.createTHead().insertRow();
    for (const text of ['Measure', 'Same season', 'Following season', 'Spread between teams']) head.append(Object.assign(el('th', text), {scope: 'col'}));
    const body = table.createTBody();
    for (const row of data.repeatability) {
        const line = body.insertRow();
        line.append(Object.assign(el('th', row.label), {scope: 'row'}), el('td', `${row.split_half.toFixed(2)} (${row.split_half_low.toFixed(2)} to ${row.split_half_high.toFixed(2)})`),
            el('td', `${row.next_season.toFixed(2)} (${row.next_season_low.toFixed(2)} to ${row.next_season_high.toFixed(2)})`), el('td', data.spread[row.measure].spread.toFixed(1)));
    }
    const wrap = el('div', null, 'table-scroll');
    wrap.append(table);
    const strongest = [...data.repeatability].sort((a, b) => b.split_half - a.split_half);
    const meaning = el('p', `${strongest[0].label} repeats most (${strongest[0].split_half.toFixed(2)}) and ${strongest.at(-1).label.toLowerCase()} repeats least (${strongest.at(-1).split_half.toFixed(2)}). `
        + 'For a defence, the shots it allows say more than whether opponents happened to make them. These are descriptions of past seasons and do not show that changing a scheme would move a number.');
    const note = el('p', `${data.repeatability[0].team_seasons} team seasons from 2016 to 2026. Values are correlations with 95% ranges. Spread is one standard deviation in points per 100 shots.`, 'caption');
    target.replaceChildren(lead, wrap, meaning, note);
}
