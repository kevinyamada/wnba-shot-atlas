import { paintCourt, canvasSquare } from './drawing.js?v=4';

const pct = value => `${(100 * value).toFixed(1)}%`;

export function posteriorView(rules, surfaceData, palette) {
    const root = document.createElement('div');
    root.className = 'posterior-view';
    const chart = document.createElement('div');
    chart.className = 'posterior-court';
    const canvas = document.createElement('canvas');
    canvas.tabIndex = 0;
    canvas.setAttribute('aria-label', 'Estimated make chance by location. Use the arrow keys to move around the court.');
    chart.append(canvas);
    const aside = document.createElement('div');
    aside.className = 'posterior-aside';
    const options = document.createElement('div');
    options.className = 'posterior-controls';
    options.innerHTML = `<label>Model<select><option value="matern">Bayesian court model</option><option value="spde">Bayesian mesh model</option></select></label>
      <label>Colour by<select><option value="chance">Estimated make chance</option><option value="spread">Uncertainty</option></select></label>`;
    const [model, metric] = options.querySelectorAll('select');
    const result = document.createElement('p');
    result.className = 'posterior-numbers';
    result.setAttribute('aria-live', 'polite');
    const caption = document.createElement('p');
    caption.className = 'caption';
    const legend = document.createElement('div');
    legend.className = 'legend';
    legend.innerHTML = '<span>0%</span><span class="legend-strip" aria-hidden="true"></span><span></span>';
    aside.append(options, result, legend, caption);
    root.append(chart, aside);

    const grid = {baseline: -rules.rim_from_baseline, midcourt: rules.length / 2 - rules.rim_from_baseline,
                  size: 1, cols: rules.width, rows: rules.length / 2};
    const era = [rules.eras.at(-1)];
    const n = grid.rows * grid.cols;
    const lookup = Object.fromEntries(Object.entries(surfaceData).map(([key, rows]) => {
        const valid = rows.filter(([, lateral]) => lateral < grid.cols / 2);
        return [key, valid];
    }));
    let selected = 15 * grid.cols + 25;
    function draw() {
        if (!canvas.clientWidth) return;
        const values = lookup[model.value];
        const spread = metric.value === 'spread';
        const limit = spread ? Math.ceil(Math.max(...values.map(row => row[4] - row[3])) * 20) / 20 : 1;
        const squares = values.map(row => ({n: 1, value: spread ? row[4] - row[3] : row[2]}));
        paintCourt(canvas, rules, grid, era, palette(), squares, selected, null, 'rate', limit, 1);
        const [depth, lateral, p, lower, upper] = values[selected];
        const across = lateral === 0 ? 'in the centre' : `${Math.abs(lateral)} ft ${lateral < 0 ? 'left' : 'right'}`;
        const forward = depth < 0 ? `${Math.abs(depth)} ft behind the rim` : `${depth} ft forward`;
        result.replaceChildren();
        const location = document.createElement('span');
        location.textContent = `${forward}, ${across}`;
        const value = document.createElement('strong');
        value.textContent = `${pct(p)} estimated make chance`;
        const interval = document.createElement('span');
        interval.textContent = `95% interval from ${pct(lower)} to ${pct(upper)}`;
        result.append(location, value, interval);
        legend.lastElementChild.textContent = pct(limit);
        caption.textContent = spread ? 'Higher values on the scale mean wider intervals. The model is less sure about those spots.'
            : 'Each square shows the model’s estimate at one spot. The model uses the location of the shot.';
    }
    const resize = new ResizeObserver(draw);
    resize.observe(canvas);
    const theme = new MutationObserver(draw);
    theme.observe(document.documentElement, {attributes: true, attributeFilter: ['data-theme']});
    options.addEventListener('change', draw);
    canvas.addEventListener('click', event => {
        selected = canvasSquare(event, canvas, grid);
        draw();
    });
    canvas.addEventListener('keydown', event => {
        const delta = {ArrowUp: -grid.cols, ArrowDown: grid.cols, ArrowLeft: -1, ArrowRight: 1}[event.key];
        if (delta === undefined) return;
        selected = Math.min(n - 1, Math.max(0, selected + delta));
        event.preventDefault();
        draw();
    });
    return root;
}
