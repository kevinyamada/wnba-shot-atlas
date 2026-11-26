const descriptions = {
    'Near rim': 'Within 4 ft of the rim',
    'Short interior': '4–8 ft from the rim',
    'Middle interior': '8–16 ft from the rim',
    'Long interior': 'Long twos inside the arc',
    'Near the line': 'Within 1 ft of the three-point line',
    'Outside corner': 'Beyond the line in the corners',
    'Outside arc': 'Beyond the arc, away from the corners'
};

const count = new Intl.NumberFormat('en-CA');
const signed = number => (number < 0 ? '−' : '+') + Math.abs(number).toFixed(2);

export function shotChallenge(section, data) {
    const find = selector => section.querySelector(selector);
    const buttons = find('.challenge-regions');
    const slider = find('input[type=range]');
    const action = find('.challenge-action');
    const dots = find('.challenge-dots');
    const bars = find('.challenge-comparison');
    const live = find('.challenge-message');
    const records = new Map(data.regions.map(row => [row.region, row]));
    const names = Object.keys(descriptions);
    if (names.some(name => !records.has(name))) return;
    for (let i = 0; i < 100; i++) dots.append(document.createElement('i'));
    let current = names[0], revealed = false;

    function draw() {
        const row = records.get(current);
        const actual = 100 * row.makes / row.attempts;
        const model = 100 * row.expectedMakes / row.attempts;
        const guess = Number(slider.value);
        const shown = revealed ? actual : guess;
        find('.challenge-region-title').textContent = current;
        find('.challenge-location').textContent = descriptions[current];
        find('.challenge-value').textContent = revealed ? actual.toFixed(2) : String(guess);
        find('.challenge-value-label').textContent = revealed ? 'Actual makes per 100' : 'Your guess per 100';
        Array.from(dots.children).forEach((dot, i) => {
            const fill = Math.max(0, Math.min(1, shown - i));
            dot.style.setProperty('--fill', (100 * fill).toFixed(2) + '%');
            dot.classList.toggle('forecast-dot', revealed && i === Math.ceil(model) - 1);
        });
        find('.challenge-grid-key').textContent = revealed ? 'Ring = model forecast' : 'Tap a dot or move the slider';
        bars.hidden = !revealed;
        find('.challenge-guess').hidden = revealed;
        find('.challenge-sample').textContent = count.format(row.attempts) + ' recorded shots';
        action.textContent = revealed ? 'Next region' : 'Reveal result';
        section.dataset.revealed = String(revealed);
        for (const button of buttons.children) button.setAttribute('aria-pressed', String(button.dataset.region === current));
        if (revealed) {
            const guessError = Math.round(100 * Math.abs(guess - actual));
            const modelError = Math.round(100 * Math.abs(model - actual));
            find('.challenge-your-result').textContent = String(guess);
            find('.challenge-model-result').textContent = model.toFixed(2);
            live.textContent = guessError < modelError ? 'You were closer.' : guessError > modelError ? 'The model was closer.' : 'You and the model tied.';
            find('.challenge-range').textContent = 'Gap: ' + signed(row.gap) + ' per 100. 95% game-resampled range: ' + signed(row.low) + ' to ' + signed(row.high) + '.';
        } else {
            live.textContent = '';
        }
    }

    function select(name) {
        current = name;
        revealed = false;
        slider.value = '50';
        draw();
    }
    for (const name of names) {
        const button = document.createElement('button');
        button.type = 'button';
        button.dataset.region = name;
        button.textContent = name;
        button.addEventListener('click', () => select(name));
        buttons.append(button);
    }
    dots.addEventListener('click', event => {
        if (revealed || event.target.parentElement !== dots) return;
        slider.value = String(Array.prototype.indexOf.call(dots.children, event.target) + 1);
        draw();
    });
    slider.addEventListener('input', draw);
    action.addEventListener('click', () => {
        if (revealed) {
            select(names[(names.indexOf(current) + 1) % names.length]);
            slider.focus({preventScroll: true});
        } else {
            revealed = true;
            draw();
        }
    });
    section.hidden = false;
    draw();
    if (location.hash === '#' + section.id) section.scrollIntoView();
}
