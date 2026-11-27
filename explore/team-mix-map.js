const signed = value => (value < 0 ? '−' : '+') + Math.abs(value).toFixed(2);
const svgNS = 'http://www.w3.org/2000/svg';
function mark(parent, tag, attrs, text) {
    const el = document.createElementNS(svgNS, tag);
    for (const [name, value] of Object.entries(attrs)) el.setAttribute(name, value);
    if (text !== undefined) el.textContent = text;
    parent.append(el);
    return el;
}

export function teamMixMap(section, data) {
    const teamPicker = section.querySelector('select');
    const grid = section.querySelector('#mix-grid');
    const peers = section.querySelector('#mix-peers');
    const svg = section.querySelector('svg');
    const teams = data.teams;
    for (const team of [...teams].sort((a, b) => a.name.localeCompare(b.name))) {
        teamPicker.add(new Option(team.name, String(team.id)));
    }
    teamPicker.value = '6';
    const all = teams.flatMap(t => Object.values(t.views));
    const limit = metric => Math.max(4, 4 * Math.ceil(Math.max(...all.flatMap(v => v[metric].map(Math.abs))) / 4));
    const xmax = limit('mix'), ymax = limit('within');
    const x = n => 218 + n * 174 / xmax;
    const y = n => 137 - n * 104 / ymax;
    function draw() {
        const key = (grid.checked ? 'grid' : 'regions') + (peers.checked ? 'Peers' : 'League');
        const team = teams.find(t => String(t.id) === teamPicker.value);
        const view = team.views[key];
        svg.replaceChildren();
        for (const k of [-1, -.5, 0, .5, 1]) {
            const col = x(k * xmax), row = y(k * ymax);
            const cls = k === 0 ? 'mix-axis' : 'mix-guide';
            mark(svg, 'line', {x1: col, x2: col, y1: y(ymax), y2: y(-ymax), class: cls});
            mark(svg, 'line', {x1: x(-xmax), x2: x(xmax), y1: row, y2: row, class: cls});
            mark(svg, 'text', {x: col, y: 259, 'text-anchor': 'middle'}, String(k * xmax).replace('-', '−'));
            mark(svg, 'text', {x: 36, y: row + 4, 'text-anchor': 'end'}, String(k * ymax).replace('-', '−'));
        }
        mark(svg, 'text', {x: 44, y: 17, class: 'mix-axis-title'}, 'Scoring within locations');
        mark(svg, 'text', {x: 218, y: 281, 'text-anchor': 'middle', class: 'mix-axis-title'}, 'Shot mix');
        const [m, mlo, mhi] = view.mix, [w, wlo, whi] = view.within;
        mark(svg, 'line', {x1: x(mlo), x2: x(mhi), y1: y(w), y2: y(w), class: 'mix-whisker'});
        mark(svg, 'line', {x1: x(m), x2: x(m), y1: y(wlo), y2: y(whi), class: 'mix-whisker'});
        for (const t of [...teams.filter(t => t !== team), team]) {
            const cx = x(t.views[key].mix[0]), cy = y(t.views[key].within[0]);
            const dot = mark(svg, 'g', {'data-team': t.id, class: t === team ? 'mix-dot selected' : 'mix-dot'});
            mark(dot, 'title', {}, t.name);
            mark(dot, 'circle', {cx, cy, r: 10, fill: 'transparent'});
            mark(dot, 'circle', {cx, cy, r: t === team ? 6 : 4.4, class: 'mix-mark'});
        }
        const end = m > 0;
        mark(svg, 'text', {x: x(m) + (end ? -9 : 9), y: y(w) - 9, 'text-anchor': end ? 'end' : 'start', class: 'mix-name'}, team.name.split(' ').at(-1));
        section.querySelector('.mix-result h3').textContent = team.name;
        for (const metric of ['mix', 'within']) {
            const [v, lo, hi] = view[metric], cell = section.querySelector('.mix-' + metric);
            cell.querySelector('strong').textContent = signed(v);
            cell.querySelector('small').textContent = signed(lo) + ' to ' + signed(hi);
        }
        section.querySelector('.mix-observed').textContent = team.observed.toFixed(2) + ' points per 100 shots, against a ' + view.baseline.toFixed(2) + ' benchmark.';
    }
    for (const control of [teamPicker, grid, peers]) control.addEventListener('change', draw);
    svg.addEventListener('click', event => {
        const dot = event.target.closest('[data-team]');
        if (dot) { teamPicker.value = dot.dataset.team; draw(); }
    });
    draw();
    section.hidden = false;
    if (location.hash === '#' + section.id) section.scrollIntoView();
}
