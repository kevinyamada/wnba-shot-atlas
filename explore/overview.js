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

export function headline(target, mix, timing) {
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
