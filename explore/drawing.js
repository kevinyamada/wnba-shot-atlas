const fonts = 'system-ui, sans-serif';
const clamp = (x, lo, hi) => Math.max(lo, Math.min(hi, x));

function surface(canvas) {
    const width = canvas.clientWidth, height = canvas.clientHeight;
    if (width === 0 || height === 0) return null;
    const ratio = Math.min(devicePixelRatio || 1, 2);
    const px = Math.round(width * ratio), py = Math.round(height * ratio);
    if (canvas.width !== px || canvas.height !== py) {
        canvas.width = px;
        canvas.height = py;
    }
    const ctx = canvas.getContext('2d');
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, height);
    return {ctx, width, height};
}

function blend(a, b, weight) {
    const rgb = [1, 3, 5].map(offset => {
        const low = parseInt(a.slice(offset, offset + 2), 16);
        const high = parseInt(b.slice(offset, offset + 2), 16);
        return Math.round(low + (high - low) * weight);
    });
    return `rgb(${rgb.join(',')})`;
}

function line(ctx, points) {
    ctx.beginPath();
    points.forEach(([x, y], i) => i ? ctx.lineTo(x, y) : ctx.moveTo(x, y));
    ctx.stroke();
}

function circle(ctx, x, y, radius, start = 0, end = 2 * Math.PI) {
    ctx.beginPath();
    ctx.arc(x, y, radius, start, end);
    ctx.stroke();
}

function bounds(cell, grid) {
    const left = cell % grid.cols * grid.size;
    const baseline = grid.baseline + Math.floor(cell / grid.cols) * grid.size;
    return [left, baseline, Math.min(grid.midcourt, baseline + grid.size)];
}

export function canvasSquare(event, canvas, grid) {
    const {width, height, left, top} = canvas.getBoundingClientRect();
    const col = Math.floor(((event.clientX - left) / width) * grid.cols);
    const depth = ((event.clientY - top) / height) * (grid.midcourt - grid.baseline);
    return clamp(Math.floor(depth / grid.size), 0, grid.rows - 1) * grid.cols + clamp(col, 0, grid.cols - 1);
}

function hatch(ctx, x, y, width, height, colour) {
    ctx.save();
    ctx.beginPath();
    ctx.rect(x, y, width, height);
    ctx.clip();
    ctx.strokeStyle = colour;
    ctx.globalAlpha = .28;
    ctx.lineWidth = .8;
    for (let offset = -height; offset < width; offset += 5) {
        line(ctx, [[x + offset, y + height], [x + offset + height, y]]);
    }
    ctx.restore();
}

export function per100(amount, attempts) {
    return attempts ? 100 * amount / attempts : null;
}

export function metricValue(area, total, metric) {
    if (metric === 'attempts') return area.n;
    if (metric === 'per100') return per100(area.n, total.n);
    if (metric === 'share') return total.n ? area.n / total.n : null;
    if (!area.n) return null;
    return (metric === 'rate' ? area.makes : area.points) / area.n;
}

export function paintCourt(canvas, court, grid, era, p, squares, focus, hover, metric, limit, floor) {
    const frame = surface(canvas);
    if (!frame) return;
    const {ctx, width, height} = frame;
    const scale = width / court.width;
    const y = depth => height * (depth - grid.baseline) / (grid.midcourt - grid.baseline);
    const x = lateral => width / 2 + lateral * scale;
    ctx.fillStyle = p.court;
    ctx.fillRect(0, 0, width, height);
    ctx.fillStyle = p['court-alt'];
    for (let strip = 0; strip < 10; strip += 2) ctx.fillRect(strip * width / 10, 0, width / 10, height);
    const efficiency = metric === 'rate' || metric === 'points';
    for (let i = 0; i < squares.length; i++) {
        const cell = squares[i];
        if (!cell.n) continue;
        const [left, below, above] = bounds(i, grid);
        const xpos = left * scale + .45, ypos = y(below) + .45;
        const w = grid.size * scale - .9, h = y(above) - ypos - .45;
        if (efficiency && cell.n < floor) {
            hatch(ctx, xpos, ypos, w, h, p['court-line']);
            continue;
        }
        const weight = clamp(cell.value / limit, 0, 1);
        const colourFraction = efficiency ? weight : Math.log1p(60 * weight) / Math.log(61);
        ctx.fillStyle = colourFraction <= .5
            ? blend(p['colour-min'], p['colour-mid'], colourFraction * 2)
            : blend(p['colour-mid'], p['colour-max'], (colourFraction - .5) * 2);
        ctx.fillRect(xpos, ypos, w, h);
    }
    ctx.strokeStyle = p['court-line'];
    ctx.lineWidth = Math.max(1, scale * .12);
    ctx.strokeRect(.8, .8, width - 1.6, height - 1.6);
    circle(ctx, x(0), y(grid.midcourt), 6 * scale, Math.PI, 2 * Math.PI);
    const lane = era.length === 1 ? (era[0].lane_width ?? court.lane_width) : court.lane_width;
    const halfLane = lane / 2;
    const freeThrow = grid.baseline + court.free_throw_from_baseline;
    ctx.strokeRect(x(-halfLane), y(grid.baseline), lane * scale, y(freeThrow) - y(grid.baseline));
    circle(ctx, x(0), y(freeThrow), 6 * scale, 0, Math.PI);
    ctx.setLineDash([4, 4]);
    circle(ctx, x(0), y(freeThrow), 6 * scale, Math.PI, 2 * Math.PI);
    ctx.setLineDash([]);
    if (!era.every(rule => rule.arc_only)) circle(ctx, x(0), y(0), 4 * scale, 0, Math.PI);
    line(ctx, [[x(-3), y(-1.25)], [x(3), y(-1.25)]]);
    circle(ctx, x(0), y(0), .75 * scale);
    for (const rule of era) {
        const radius = rule.arc_radius, corner = rule.corner_distance;
        const join = Math.sqrt(radius * radius - corner * corner);
        const curvedWidth = rule.arc_only ? Math.sqrt(radius * radius - 100) : corner;
        const points = rule.arc_only ? [] : [[x(-corner), y(grid.baseline)]];
        for (let i = 0; i <= 100; i++) {
            const lateral = -curvedWidth + 2 * curvedWidth * i / 100;
            points.push([x(lateral), y(Math.sqrt(radius * radius - lateral * lateral))]);
        }
        if (!rule.arc_only) points.push([x(corner), y(join)], [x(corner), y(grid.baseline)]);
        const older = rule.first_season < 2013;
        ctx.setLineDash(era.length > 1 && older ? (rule.arc_only ? [2, 5] : [5, 4]) : []);
        ctx.lineWidth = Math.max(3, scale * .31);
        ctx.strokeStyle = p.surface;
        line(ctx, points);
        ctx.lineWidth = Math.max(1.4, scale * .16);
        ctx.strokeStyle = era.length === 1 || !older ? p.deep : rule.arc_only ? p['earliest-line'] : p['historic-line'];
        line(ctx, points);
        ctx.setLineDash([]);
    }
    function outline(cell, colour, lineWidth) {
        if (cell === undefined || cell === null) return;
        const [left, below, above] = bounds(cell, grid);
        ctx.strokeStyle = colour;
        ctx.lineWidth = lineWidth;
        ctx.strokeRect(left * scale + 1, y(below) + 1, grid.size * scale - 2, y(above) - y(below) - 2);
    }
    if (hover !== focus) outline(hover, p.ink, 1.2);
    outline(focus, p.ink, 2.8);
    outline(focus, p.surface, 1.2);
    canvas.dataset.arc = era.map(rule => rule.arc_radius).join(',');
    canvas.dataset.selected = focus === null ? '' : String(focus);
}

export function paintHistory(canvas, values, years, p, metric) {
    const frame = surface(canvas);
    if (!frame || !values.length) return;
    const {ctx, width, height} = frame;
    const left = metric === 'attempts' ? 51 : 43, right = width - 19, top = 21, bottom = height - 27;
    const start = values[0].season, end = values.at(-1).season;
    const x = year => left + (year - start) * (right - left) / Math.max(end - start, 1);
    const series = values.map(({season, area, total}) => [season, metricValue(area, total, metric)]);
    const max = Math.max(.02, ...series.map(([, m]) => m ?? 0));
    const limits = {rate: 1, points: 3, share: Math.min(1, Math.ceil(max * 25) / 25),
        per100: Math.min(100, Math.ceil(max / 4) * 4), attempts: Math.ceil(max / 2) * 2};
    const limit = limits[metric];
    const y = v => bottom - (bottom - top) * v / limit;
    const fmt = v => metric === 'rate' || metric === 'share'
        ? `${+(100 * v).toFixed(1)}%` : v.toLocaleString('en-CA');
    ctx.font = `12px ${fonts}`;
    ctx.fillStyle = p.muted;
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    ctx.strokeStyle = p.line;
    ctx.lineWidth = 1;
    for (const tick of [0, limit / 2, limit]) {
        line(ctx, [[left, y(tick)], [right, y(tick)]]);
        ctx.fillText(fmt(tick), left - 6, y(tick));
    }
    for (const rule of [2004, 2013].filter(year => start <= year && year <= end)) {
        ctx.setLineDash([4, 4]);
        ctx.strokeStyle = p.accent;
        line(ctx, [[x(rule), top], [x(rule), bottom]]);
        ctx.setLineDash([]);
    }
    ctx.textAlign = 'center';
    const step = width < 500 ? 5 : width < 740 ? 3 : 2;
    const ticks = Array.from(new Set([start, ...values.map(a => a.season).filter(year => (year - start) % step === 0 && end - year >= 2), end]));
    for (const year of ticks) ctx.fillText(year, x(year), bottom + 15);
    ctx.strokeStyle = p.deep;
    ctx.lineWidth = 2;
    let previous = null;
    for (const point of series) {
        const [year, value] = point;
        if (value !== null && previous !== null) line(ctx, [[x(previous[0]), y(previous[1])], [x(year), y(value)]]);
        previous = value === null ? null : point;
    }
    for (const [year, value] of series) {
        if (value === null) continue;
        ctx.fillStyle = years.includes(year) ? p.accent : p.deep;
        ctx.beginPath();
        ctx.arc(x(year), y(value), years.includes(year) ? 4.5 : 2.6, 0, 2 * Math.PI);
        ctx.fill();
    }
    if (series.every(([, value]) => value === null)) {
        ctx.fillStyle = p.muted;
        ctx.fillText('No attempts in this area', width / 2, height / 2);
    }
}
