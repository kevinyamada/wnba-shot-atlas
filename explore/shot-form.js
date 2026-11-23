const count = new Intl.NumberFormat('en-CA');
const rate = (makes, attempts) => (100 * makes / attempts).toFixed(1) + '%';
const shortChange = value => value >= 0 ? `${value.toFixed(2)}% less error` : `${Math.abs(value).toFixed(2)}% more error`;

function makeCard(row, label, shared, el) {
    const card = el('div', null, 'form-card');
    const heading = el('h3', label);
    const isLayup = row.name === 'Layup';
    const chance = shared ? (isLayup ? shared.layup_rate : shared.jump_rate) : row.makes / row.attempts;
    const n = Math.round(100 * chance);
    const sample = shared
        ? `${count.format(isLayup ? shared.layup_n : shared.jump_n)} attempts in shared groups`
        : `${count.format(row.makes)} makes in ${count.format(row.attempts)} attempts`;
    const dots = el('div', null, 'form-dots');
    dots.setAttribute('aria-hidden', 'true');
    for (let i = 0; i < 100; i++) dots.append(el('i', null, i < n ? 'made' : 'missed'));
    card.dataset.family = row.name;
    card.append(heading, el('strong', rate(chance, 1)), dots, el('small', sample));
    return card;
}

export function formComparison(data, {el, table, details}) {
    const node = el('div', null, 'form-comparison');
    const distance = el('label', 'Distance from the basket', 'form-distance');
    const select = el('select');
    select.id = 'form-distance';
    for (const band of data.diagram) select.append(new Option(`About ${band.feet} feet`, band.feet));
    select.value = '4';
    distance.append(select);
    const matched = el('input');
    matched.type = 'checkbox';
    matched.id = 'form-match';
    const matchLabel = el('label', null, 'form-match');
    matchLabel.append(matched, 'Match the court spots');
    const controls = el('div', null, 'form-controls');
    controls.append(distance, matchLabel);
    const cards = el('div', null, 'form-cards');
    const caption = el('p', null, 'caption');
    const note = el('p');
    note.id = 'form-observation';
    note.setAttribute('aria-live', 'polite');
    const counts = el('div');
    const adjusted = el('p');
    const allTypes = details('All shot types at this distance', counts, adjusted);
    const pooled = data.pooled.both;
    const wins = data.byYear.filter(r => r.scope === 'regular' && r.gain_pct > 0).length;
    const takeaway = el('p', `Across ${count.format(pooled.attempts)} shots, adding shot type to distance cut prediction error by ${pooled.gain_pct.toFixed(2)}%. It helped in ${wins} of ${data.seasons.length} regular seasons. Distance alone already captured most of what these two models could predict.`);
    takeaway.id = 'form-forecast';
    const scores = [...data.seasons].reverse().map(year => {
        const row = phase => data.byYear.find(r => r.season === year && r.scope === phase);
        return [year, shortChange(row('regular').gain_pct), shortChange(row('playoffs').gain_pct)];
    });
    const regular = data.context.find(r => r.scope === 'regular');
    const playoffs = data.context.find(r => r.scope === 'playoffs');
    const reference = data.reference;
    const methods = details('How the predictions held up',
        el('p', `For each season, both models learned from the previous three regular seasons. They predicted the same shots using distance, or distance and the recorded type. The pooled drop in Brier error was ${pooled.gain_pct.toFixed(2)}%, with a 95% interval from ${pooled.low_pct.toFixed(2)}% to ${pooled.high_pct.toFixed(2)}% after resampling whole games.`),
        table(['Test season', 'Regular season', 'Playoffs'], scores),
        el('p', `I also added shot type to the model that already knows the shooter, court position and game clock. Its error fell ${regular.gain_pct.toFixed(2)}% on ${count.format(regular.attempts)} shots in the 2026 regular season. `
            + (playoffs.low_pct <= 0 && playoffs.high_pct >= 0
                ? 'In the playoffs the difference was too small to distinguish from a tie.'
                : `The playoff comparison gave ${shortChange(playoffs.gain_pct)}.`)),
        el('p', `ESPN and WNBA Stats agreed on the shot family for ${count.format(reference.agree)} of ${count.format(reference.linked)} attempts that could be matched in 2025 and 2026. The type comes from how the attempt was recorded. A forecast made before the shooter chooses a shot would have less information.`));
    node.append(el('p', 'Compare shots players took across the league in the 2016 through 2026 regular seasons and playoffs.'),
        controls, cards, caption, note, allTypes, takeaway, methods);

    function render() {
        const band = data.diagram.find(b => b.feet === Number(select.value));
        const lay = band.rows.find(r => r.name === 'Layup');
        const jump = band.rows.find(r => r.name === 'Jump shot');
        matched.disabled = !band.sameSpots;
        if (matched.disabled) matched.checked = false;
        const shared = matched.checked ? band.sameSpots : null;
        cards.replaceChildren(makeCard(lay, 'Layups', shared, el), makeCard(jump, 'Jump shots', shared, el));
        caption.textContent = `Each filled dot is one make per 100 shots, rounded. The distance runs from ${band.feet - .5} feet to just under ${band.feet + .5} feet.`;
        const gap = 100 * (shared ? shared.layup_rate - shared.jump_rate : lay.makes / lay.attempts - jump.makes / jump.attempts);
        let description = Math.round(Math.abs(gap)) === 0 ? 'Both groups made about the same number per 100 attempts.'
            : `${gap > 0 ? 'Layups' : 'Jump shots'} went in about ${Math.round(Math.abs(gap))} more times per 100 attempts.`;
        if (shared) {
            description += ` Both rates now use the same mix of court spots, seasons and game types. ${count.format(shared.strata)} groups had at least five layups and five jump shots each.`;
            if (shared.strata < 10) description += ' Very few groups qualified at this distance.';
        } else if (Math.min(lay.attempts, jump.attempts) < 100) {
            description = `Only ${count.format(Math.min(lay.attempts, jump.attempts))} ${lay.attempts < jump.attempts ? 'layups' : 'jump shots'} were recorded here. That rate can swing with a handful of shots.`;
        }
        if (!band.sameSpots) description += ' No court spot had five of each shot type in the same season and game type.';
        note.textContent = description;
        counts.replaceChildren(table(['Shot type', 'Makes', 'Attempts', 'Make rate'],
            [...band.rows].sort((a,b) => b.attempts - a.attempts).map(r =>
                [r.name, count.format(r.makes), count.format(r.attempts), rate(r.makes, r.attempts)])));
        adjusted.textContent = 'These are observed counts across the league for the selected distance. Players can face different defenses and choose different shots even from the same spot.';
    }
    select.addEventListener('change', render);
    matched.addEventListener('change', render);
    render();
    return node;
}
