const fonts = 'system-ui, sans-serif';
const count = new Intl.NumberFormat('en-CA');
const series = [['actual', 'Recorded', 'deep', []], ['fixed_mix', 'Same shot mix every season', 'accent', [7, 4]],
    ['fixed_conversion', 'Same scoring from each area every season', 'historic-line', [2, 4]]];

function el(tag, text, className) {
    const node = document.createElement(tag);
    if (text != null) node.textContent = text;
    if (className) node.className = className;
    return node;
}

const signed = value => (value < 0 ? '−' : '+') + Math.abs(value).toFixed(3);
const span = text => { const [a, b] = text.split(' to '); return a === b ? a : text; };
const share = value => (100 * value).toFixed(1) + '%';

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

function paint(canvas, seasons, colours) {
    const width = canvas.clientWidth, height = canvas.clientHeight;
    if (!width || !height) return;
    const ratio = Math.min(devicePixelRatio || 1, 2);
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    const ctx = canvas.getContext('2d');
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, height);
    const left = 44, right = width - 14, top = 14, bottom = height - 28;
    const all = seasons.flatMap(row => series.map(([key]) => row[key]));
    const low = Math.floor(Math.min(...all) * 20) / 20, high = Math.ceil(Math.max(...all) * 20) / 20;
    const first = seasons[0].season, last = seasons.at(-1).season;
    const x = year => left + (year - first) * (right - left) / (last - first);
    const y = value => bottom - (value - low) * (bottom - top) / (high - low);
    ctx.font = `12px ${fonts}`;
    ctx.textBaseline = 'middle';
    ctx.textAlign = 'right';
    ctx.lineWidth = 1;
    for (let tick = low; tick <= high + 1e-9; tick += .05) {
        ctx.strokeStyle = colours.line;
        ctx.beginPath();
        ctx.moveTo(left, y(tick));
        ctx.lineTo(right, y(tick));
        ctx.stroke();
        ctx.fillStyle = colours.muted;
        ctx.fillText(tick.toFixed(2), left - 6, y(tick));
    }
    ctx.textAlign = 'center';
    const step = width < 500 ? 5 : width < 740 ? 3 : 2;
    for (const {season} of seasons) {
        if ((season - first) % step === 0 && last - season >= 2 || season === last) ctx.fillText(season, x(season), bottom + 15);
    }
    for (const [key, , colour, dash] of series) {
        ctx.strokeStyle = colours[colour];
        ctx.lineWidth = key === 'actual' ? 2.6 : 2;
        ctx.setLineDash(dash);
        ctx.beginPath();
        seasons.forEach((row, i) => i ? ctx.lineTo(x(row.season), y(row[key])) : ctx.moveTo(x(row.season), y(row[key])));
        ctx.stroke();
    }
    ctx.setLineDash([]);
}

export function shotMix(target, data, palette) {
    const heading = el('h2', 'Better spots or better shooting?');
    heading.id = 'mix-title';
    const [whole, , , , , recent] = data.comparisons;
    const lead = el('p', `Field goal points per shot averaged ${whole.before.toFixed(2)} across ${span(whole.first)} and ${whole.after.toFixed(2)} across ${span(whole.second)}. `
        + `Where teams shot explains about ${Math.round(100 * whole.mix_share)}% of that rise. The rest came from scoring more on shots from the same areas. `
        + `Lately the balance has flipped. Between ${span(recent.first)} and ${span(recent.second)}, shot mix explains about ${Math.round(100 * recent.mix_share)}% of the rise.`);
    const legend = el('p', null, 'mix-legend');
    legend.append(...series.map(([key, name]) => el('span', name, key)));
    const canvas = el('canvas');
    canvas.id = 'mix-chart';
    canvas.setAttribute('role', 'img');
    canvas.setAttribute('aria-label', 'Field goal points per shot by season, as recorded, with the shot mix held fixed and with scoring from each area held fixed. Values are listed below.');
    const stage = el('div', null, 'history-stage');
    stage.append(canvas);
    const chartNote = el('p', 'The dashed line gives every season the 30 season average mix of areas, so it moves only when scoring within areas changes. The dotted line gives every season the 30 season average scoring from each area, so it moves only when the mix changes. The scale does not start at zero.', 'caption');
    const values = el('details');
    values.append(el('summary', 'View season values'), table(['Season', 'Attempts', 'Recorded', 'Same shot mix', 'Same scoring from each area'],
        data.seasons.map(row => [row.season, count.format(row.attempts), row.actual.toFixed(3), row.fixed_mix.toFixed(3), row.fixed_conversion.toFixed(3)])));

    const label = el('label', 'Compare two periods', 'study-picker');
    const select = el('select');
    select.id = 'mix-comparison';
    data.comparisons.forEach((row, i) => select.append(new Option(`${span(row.first)} and ${span(row.second)}`, i)));
    label.append(select);
    const parts = el('div', null, 'mix-parts');
    parts.setAttribute('aria-live', 'polite');
    const areas = el('div');
    const sample = el('p', null, 'caption');

    function part(name, value, low, high, note) {
        const card = el('div', null, 'mix-part');
        card.append(el('span', name), el('strong', signed(value)), el('small', `95% interval ${signed(low)} to ${signed(high)}`), el('small', note));
        return card;
    }

    function render() {
        const row = data.comparisons[Number(select.value)];
        parts.replaceChildren(
            part('Change in points per shot', row.change, row.change_low, row.change_high, `${row.before.toFixed(3)} to ${row.after.toFixed(3)}`),
            part('From shot mix', row.mix, row.mix_low, row.mix_high, 'where shots came from'),
            part('From conversion', row.conversion, row.conversion_low, row.conversion_high, 'points per shot within areas'));
        const rows = data.comparisonAreas.filter(area => area.comparison === row.comparison);
        const rate = value => value == null ? 'Unavailable' : value.toFixed(3);
        areas.replaceChildren(table(['Area', `Share in ${span(row.first)}`, `Share in ${span(row.second)}`, `Points per shot in ${span(row.first)}`, `Points per shot in ${span(row.second)}`],
            rows.map(area => [area.area, share(area.share_before), share(area.share_after), rate(area.points_per_shot_before), rate(area.points_per_shot_after)])));
        sample.textContent = `${count.format(row.attempts_first)} attempts in ${count.format(row.games_first)} games and ${count.format(row.attempts_second)} attempts in ${count.format(row.games_second)} games. Regular season and playoffs.`;
    }

    const located = data.coverage.map(row => `${share(row.mapped_share)} in ${row.seasons}`).join(', ');
    const [main, ...checks] = data.sensitivity;
    const shares = checks.filter(row => row.first === main.first && row.second === main.second).map(row => row.mix_share);
    const methods = el('details');
    methods.append(el('summary', 'How the split works and what it cannot say'),
        el('p', 'Shot mix is the share of attempts from each area. Conversion is field goal points per attempt within an area. The mix part multiplies each change in share by the average points per shot of the two periods. The conversion part multiplies each change in points per shot by the average share. The two parts add up to the change exactly.'),
        el('p', 'Near the basket covers mapped shots within 10 ft of the rim and shots recorded exactly at the basket through 2010, which are almost all layups. Midrange is inside the three point line and at least 10 ft out. The three point area is outside the line used in each season.'),
        el('p', `Shots with a mapped location: ${located}. Across other reasonable choices for the same first and last five seasons, such as dropping unmapped shots, using the regular season only or using the seven recorded areas, the shot mix part ranges from ${Math.round(100 * Math.min(...shares))}% to ${Math.round(100 * Math.max(...shares))}% of the change.`),
        el('p', 'A change in conversion cannot show why scoring rose. Shot selection within an area, defense, rules and how locations were recorded can all play a part. Intervals come from drawing whole games again within each season and do not cover recording changes.'),
        table(['Check', 'Periods', 'Change', 'From shot mix', 'From conversion'],
            data.sensitivity.map(row => [row.check, `${span(row.first)} and ${span(row.second)}`, signed(row.change), signed(row.mix), signed(row.conversion)])));
    target.replaceChildren(heading, lead, legend, stage, chartNote, values, label, parts, sample, areas, methods);
    target.hidden = false;
    select.addEventListener('change', render);
    render();
    let frame;
    const repaint = () => { cancelAnimationFrame(frame); frame = requestAnimationFrame(() => paint(canvas, data.seasons, palette())); };
    window.addEventListener('resize', repaint);
    new MutationObserver(repaint).observe(document.documentElement, {attributes: true, attributeFilter: ['data-theme']});
    repaint();
}
