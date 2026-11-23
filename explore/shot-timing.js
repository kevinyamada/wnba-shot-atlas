const count = new Intl.NumberFormat('en-CA');
const groupNames = {'Steal': 'After a steal', 'Opponent basket': 'After giving up a basket',
    'Defensive rebound': 'After a defensive rebound', 'Opponent turnover': 'After another turnover',
    'Opponent free throw': 'After an opponent made a free throw'};
const per100 = (value, total) => (100 * value / total).toFixed(1);

export function shotTiming(data, {el, table, details, picker}) {
    const panel = el('div', null, 'timing-panel');
    panel.id = 'shot-timing';
    const heading = el('h3', 'How soon does the first shot come?');
    const scope = picker('Games', [['both', 'Regular + playoffs'], ['regular', 'Regular season'], ['playoffs', 'Playoffs']]);
    scope.select.id = 'timing-games';
    const time = el('input');
    time.type = 'range';
    time.id = 'timing-seconds';
    time.min = '0';
    time.max = String(data.maxSeconds);
    time.step = '1';
    time.value = String(data.mainSeconds);
    const label = el('label', null, 'timing-clock');
    label.htmlFor = time.id;
    const current = el('span');
    label.append(current, time);
    const controls = el('div', null, 'timing-controls');
    controls.append(scope.label, label);
    const cards = el('div', null, 'timing-cards');
    cards.id = 'timing-cards';
    cards.setAttribute('aria-live', 'polite');
    time.setAttribute('aria-controls', cards.id);
    const caption = el('p', 'Each grid represents 100 possessions. Filled dots show how many had a shot by this time, rounded to the nearest dot. Possessions that ended without a shot count too.', 'caption');
    const context = el('p');
    const numbers = el('div');
    const evidence = el('p');
    const scores = [...data.forecasts].sort((a, b) => a.season - b.season || Number(a.scope !== 'regular') - Number(b.scope !== 'regular'));
    const improved = scores.filter(row => row.model < row.baseline).length;
    const forecast = table(['Test games', 'Possessions', 'One league rate', 'Rate by start', 'Change in error'],
        scores.map(row => [row.season + (row.scope === 'regular' ? ' regular season' : ' playoffs'),
            count.format(row.starts), row.baseline.toFixed(5), row.model.toFixed(5),
            (100 * Math.abs(row.difference) / row.baseline).toFixed(1) + (row.difference < 0 ? '% lower' : row.difference > 0 ? '% higher' : '%')]));
    const methods = details('Shot timing, scoring and forecast results', context, numbers, evidence,
        el('p', 'The clock starts at the recorded change of possession. Every start had at least 12 seconds left in the period. The points column counts only the first field goal attempt. A miss, or no attempt by the selected time, contributes zero.'),
        el('h3', 'Can the start predict a quick shot?'),
        el('p', 'Two forecasts give the chance of a shot within six seconds. One uses the league average. The other uses how the team got the ball. Both learned from games through 2024. The table shows Brier error on the same possessions in 2025 and 2026. Lower is better.'),
        forecast, el('p', 'Knowing how possession began gave closer predictions in ' + improved + ' of ' + scores.length + ' tests. These seasons were examined in earlier atlas studies.'));
    panel.append(heading, controls, cards, caption, methods);

    function render() {
        const block = data.scopes[scope.select.value];
        const seconds = Number(time.value);
        const unit = seconds === 1 ? 'second' : 'seconds';
        current.textContent = 'Game clock · ' + seconds + ' ' + unit + ' elapsed';
        time.setAttribute('aria-valuetext', seconds + ' ' + unit + ' since the possession began');
        cards.replaceChildren(...['Steal', 'Opponent basket'].map(name => {
            const group = block.groups[name];
            const card = el('div', null, 'timing-card');
            card.dataset.situation = name;
            const rate = per100(group.shots[seconds], group.starts);
            const dots = el('div', null, 'timing-dots');
            dots.setAttribute('aria-hidden', 'true');
            const filled = Math.round(100 * group.shots[seconds] / group.starts);
            for (let i = 0; i < 100; i++) dots.append(el('i', null, i < filled ? 'attempted' : ''));
            const points = per100(group.points[seconds], group.starts);
            card.append(el('h4', groupNames[name]), el('strong', rate + '%'),
                el('span', 'had taken a shot'), dots,
                el('small', count.format(group.shots[seconds]) + ' of ' + count.format(group.starts) + ' possessions'),
                el('small', points + ' points from first shots per 100 possessions'));
            return card;
        }));
        const gap = block.sixSecondGap.shots;
        context.textContent = count.format(block.eligible) + ' complete possessions had enough time on the clock across '
            + count.format(block.games) + ' games. The table shows the first ' + seconds + ' ' + unit + ' for all five ways a possession began.';
        numbers.replaceChildren(table(['Possession began', 'Possessions', 'First shots', 'Makes', 'First shot points per 100'],
            Object.entries(groupNames).map(([key, name]) => {
                const group = block.groups[key];
                return [name, count.format(group.starts), count.format(group.shots[seconds]), count.format(group.makes[seconds]),
                    per100(group.points[seconds], group.starts)];
            })));
        evidence.textContent = 'At six seconds the gap between steals and opponent baskets was ' + gap.gap.toFixed(1)
            + ' shots per 100 possessions. The 95% interval was ' + gap.low.toFixed(1) + ' to ' + gap.high.toFixed(1)
            + ' after resampling whole games within each season and game type. Steals had the higher rate in '
            + block.seasonsHigher + ' of ' + block.seasonsCompared + ' seasons.';
    }
    time.addEventListener('input', render);
    scope.select.addEventListener('change', render);
    render();
    if (location.hash === '#' + panel.id) requestAnimationFrame(() => panel.scrollIntoView());
    return panel;
}
