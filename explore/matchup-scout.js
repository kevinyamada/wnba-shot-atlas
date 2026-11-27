const number = new Intl.NumberFormat('en-CA');
const share = (n, total) => total ? 100 * n / total : 0;
const pct = n => n.toFixed(1) + '%';
const short = name => name.split(' ').at(-1);
const questions = [
    'What opens the path to the rim: a cut, a roll or an offensive rebound? Who is in position to help?',
    'Who creates the short shot, and does the ball handler finish or find a teammate?',
    'Which coverages lead to a midrange attempt, and who takes it?',
    'What draws the corner defender away before the catch?',
    'Do the above-the-break looks come off the dribble, a screen or a kick-out?'
];
function el(tag, text, cls) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (cls) node.className = cls;
    return node;
}
function fill(select, teams, wanted, fallback, exclude) {
    const sorted = Object.entries(teams).filter(([id]) => id !== exclude).sort((a,b) => a[1].localeCompare(b[1]));
    select.replaceChildren(...sorted.map(([id,name]) => new Option(name,id)));
    select.value = [wanted, fallback, sorted[0][0]].find(id => sorted.some(([key]) => key === id));
}
function saved() {
    const m = location.hash.match(/^#matchup-scout\/(2025|2026)\/(\d+)\/(\d+)\/(attack|defend)\/([0-4])(?:\/(\d+))?$/);
    return m && {year:m[1], us:m[2], them:m[3], side:m[4], zone:Number(m[5]), player:m[6]};
}
function shotLine(counts) {
    return counts[0] ? (counts[1] / counts[0]).toFixed(2) + ' field-goal points per shot' : 'no attempts';
}

export function matchupScout(section, load) {
    const find = selector => section.querySelector(selector);
    const season = find('#scout-year'), us = find('#scout-us'), them = find('#scout-them');
    const result = find('.scout-result'), status = find('.scout-status'), fallback = find('.scout-url');
    const board = find('.scout-board'), rows = find('.scout-rows');
    const cache = new Map();
    let pack, side = 'defend', selected = 0, playerId, version = 0;

    function linkHash() {
        const parts = ['matchup-scout',pack.season,us.value,them.value,side,selected];
        if (playerId) parts.push(playerId);
        return '#' + parts.join('/');
    }
    function render(requested, who) {
        const offense = side === 'defend' ? them.value : us.value;
        const defense = side === 'defend' ? us.value : them.value;
        const offName = short(pack.teams[offense]), defName = short(pack.teams[defense]);
        const card = pack.cards[offense + '-' + defense];
        const areas = card.areas.map((a, z) => {
            const off = share(a.off[0], card.shots[0]), allowed = share(a.allowed[0], card.shots[1]);
            const league = share(a.league, card.shots[2]);
            return {z, off, allowed, league, overlap: Math.min(off, allowed) - league};
        });
        const overlap = [...areas].sort((a,b) => b.overlap - a.overlap || a.z-b.z)[0];
        const shared = overlap.overlap > 0;
        const focus = shared ? overlap : [...areas].sort((a,b) => Math.abs(b.off-b.allowed) - Math.abs(a.off-a.allowed) || a.z-b.z)[0];
        selected = Number.isInteger(requested) && requested >= 0 && requested < 5 ? requested : focus.z;
        const current = card.areas[selected];
        const activePlayer = current.players.find(p => String(p.id) === String(who));
        playerId = activePlayer?.id;
        const ceiling = Math.max(10, 10 * Math.ceil(Math.max(...areas.flatMap(a => [a.off,a.allowed,a.league])) / 10));
        find('.scout-match').textContent = pack.teams[offense] + ' offense vs. ' + pack.teams[defense] + ' defense';
        find('.scout-period').textContent = pack.season + ' regular season';
        find('.scout-off-key').textContent = offName + ' took';
        find('.scout-def-key').textContent = defName + ' allowed';
        find('.scout-scale').textContent = '0–' + ceiling + '% of shots';
        find('.scout-lead').textContent = shared
            ? 'Start with ' + ['rim attempts', 'short twos', 'midrange shots', 'the corners', 'shots above the break'][focus.z] + '. ' + offName + ' took ' + pct(focus.off) + ' of shots there and ' + defName + ' allowed ' + pct(focus.allowed) + ', both above the ' + pct(focus.league) + ' league rate.'
            : 'No area is above league average for both teams. Their largest difference is ' + pack.zones[focus.z].toLowerCase() + ' (' + pct(focus.off) + ' taken and ' + pct(focus.allowed) + ' allowed).';
        for (const button of section.querySelectorAll('[data-scout-side]')) button.setAttribute('aria-pressed', String(button.dataset.scoutSide === side));
        for (const a of areas) {
            const row = rows.children[a.z];
            row.setAttribute('aria-pressed', String(a.z === selected));
            row.querySelector('.scout-zone').textContent = pack.zones[a.z];
            for (const [cls, value] of [['off',a.off],['def',a.allowed],['league',a.league]]) {
                row.querySelector('.spot-' + cls).style.left = (100 * value / ceiling) + '%';
                row.querySelector('.val-' + cls).textContent = pct(value);
            }
            const line = row.querySelector('.scout-connector');
            line.style.left = (100 * Math.min(a.off,a.allowed) / ceiling) + '%';
            line.style.width = (100 * Math.abs(a.off-a.allowed) / ceiling) + '%';
            row.setAttribute('aria-label', pack.zones[a.z] + ', ' + offName + ' took ' + pct(a.off) + ', ' + defName + ' allowed ' + pct(a.allowed) + ', league ' + pct(a.league));
        }
        find('.scout-area-title').textContent = pack.zones[selected];
        find('.scout-question').textContent = questions[selected];
        find('.scout-personnel-title').textContent = offName + ' shooters to review';
        const players = find('.scout-players');
        players.replaceChildren();
        for (const player of current.players) {
            const item = el('li'), button = el('button',player.name);
            button.type = 'button';
            button.setAttribute('aria-pressed', String(player.id === playerId));
            button.setAttribute('aria-label', 'Show ' + player.name + ' in film review');
            button.addEventListener('click',() => {
                render(selected, player.id === playerId ? null : player.id);
                players.querySelectorAll('button')[current.players.indexOf(player)].focus({preventScroll:true});
            });
            item.append(button, el('span',number.format(player.attempts) + ' shots · ' + pct(share(player.attempts, current.off[0]))));
            players.append(item);
        }
        if (!current.players.length) players.append(el('li','No attempts in this area.'));
        find('.scout-volume').textContent = offName + ' took ' + number.format(current.off[0]) + ' here (' + shotLine(current.off) + '). ' + defName + ' allowed ' + number.format(current.allowed[0]) + ' (' + shotLine(current.allowed) + ').';
        find('.scout-met').textContent = card.shots[3] ? 'In ' + card.games[3] + ' meetings, ' + offName + ' took ' + current.met[0] + ' of ' + card.shots[3] + ' shots here (' + pct(share(current.met[0],card.shots[3])) + ', ' + shotLine(current.met) + ').' : 'These teams did not meet this season.';
        find('.scout-film-title').textContent = activePlayer ? 'Pull plays for ' + activePlayer.name : 'Pull these plays';
        find('.scout-player-met').textContent = activePlayer ? activePlayer.name + ' took ' + activePlayer.met[0] + ' of those ' + current.met[0] + ' area shots and scored ' + activePlayer.met[1] + ' points.' : '';
        find('.scout-clear').hidden = !activePlayer;
        const plays = activePlayer ? activePlayer.plays : current.plays;
        const list = find('.scout-plays');
        list.replaceChildren();
        for (const [game, period, clock, player, play, points] of plays) {
            const item = el('li');
            const [date] = pack.games[game];
            const link = el('a',date + ' · ' + (period <= 4 ? 'Q' + period : 'OT' + (period-4)) + ' ' + clock);
            link.href = 'https://www.espn.com/wnba/playbyplay/_/gameId/' + game;
            item.append(link, el('span',player + ' · ' + play + ' · ' + (points ? points + ' points' : 'miss')));
            list.append(item);
        }
        if (!plays.length) list.append(el('li',activePlayer ? 'No head-to-head attempts here for this player.' : 'No head-to-head attempts in this area.'));
        find('.scout-sample').textContent = 'Shares use all field-goal attempts outside their meetings. ' + offName + ' offense, ' + number.format(card.shots[0]) + ' shots in ' + card.games[0] + ' games. ' + defName + ' defense, ' + number.format(card.shots[1]) + ' shots in ' + card.games[1] + ' games. League, ' + number.format(card.shots[2]) + ' shots.';
        find('.scout-data').href = new URL('data/matchup-scout-' + pack.season + '.json', import.meta.url);
        fallback.hidden = true;
        find('.scout-action-status').textContent = '';
        if (location.hash.startsWith('#matchup-scout/')) history.replaceState(history.state, '', linkHash());
    }
    function matchup(wanted) {
        fill(them,pack.teams,wanted,'19',us.value);
        render();
    }
    async function open(state, anchor = false) {
        const request = ++version;
        const year = state.year;
        season.value = year;
        status.textContent = 'Loading ' + year + ' matchups…';
        find('.scout-retry').hidden = true;
        result.hidden = true;
        board.hidden = true;
        try {
            if (!cache.has(year)) cache.set(year, load(year).catch(error => { cache.delete(year); throw error; }));
            const next = await cache.get(year);
            if (request !== version) return;
            pack = next;
            fill(us, pack.teams, state.us, year === '2026' ? '131935' : '8');
            fill(them, pack.teams, state.them, '19', us.value);
            side = state.side === 'attack' ? 'attack' : 'defend';
            render(state.zone, state.player);
            status.textContent = '';
            board.hidden = false;
            result.hidden = false;
            if (anchor && location.hash.startsWith('#matchup-scout')) section.scrollIntoView();
        } catch (error) {
            if (request !== version) return;
            status.textContent = 'The matchup data could not be loaded.';
            find('.scout-retry').hidden = false;
        }
    }
    for (let z=0; z<5; z++) {
        const row = el('button',undefined,'scout-row');
        row.type = 'button';
        const track = el('span',undefined,'scout-track');
        track.setAttribute('aria-hidden','true');
        for (const cls of ['scout-connector','spot-league','spot-off','spot-def']) track.append(el('i',undefined,cls));
        row.append(el('span',undefined,'scout-zone'), track, ...['off','def','league'].map(k => el('span',undefined,'val-' + k)));
        row.addEventListener('click',() => render(z));
        rows.append(row);
    }
    find('.scout-clear').addEventListener('click',() => { render(selected); find('.scout-players button')?.focus({preventScroll:true}); });
    us.addEventListener('change',() => matchup(them.value));
    them.addEventListener('change',() => render());
    for (const b of section.querySelectorAll('[data-scout-side]')) b.addEventListener('click',() => {side=b.dataset.scoutSide; render();});
    function switchYear() { open({year:season.value, us:us.value, them:them.value, side}); }
    season.addEventListener('change', switchYear);
    find('.scout-retry').addEventListener('click', switchYear);
    find('.scout-share').addEventListener('click', async () => {
        const url = new URL(location.href);
        url.search = '';
        url.hash = linkHash();
        try {
            await navigator.clipboard.writeText(url.href);
            find('.scout-action-status').textContent = 'Matchup link copied.';
        } catch {
            fallback.hidden = false;
            fallback.value = url.href;
            fallback.focus();
            fallback.select();
            find('.scout-action-status').textContent = 'Copy the selected matchup link.';
        }
    });
    find('.scout-print').addEventListener('click',() => {
        document.body.classList.add('printing-scout');
        try { window.print(); } finally { document.body.classList.remove('printing-scout'); }
    });
    const initial = () => open(saved() || {year:'2026'}, true);
    window.addEventListener('hashchange',() => { if (location.hash.startsWith('#matchup-scout/')) initial(); });
    initial();
}
