import { shotTiming } from './shot-timing.js?v=1';

const num = new Intl.NumberFormat('en-CA');
const pc = a => (100*a).toFixed(1) + '%';
const names = {
    'Steal':'After a steal', 'Opponent turnover':'After another opponent turnover',
    'Defensive rebound':'After a defensive rebound','Offensive rebound':'After an offensive rebound',
    'Opponent basket':'After an opponent basket','Opponent free throw':'After an opponent free throw'
};

export function playSection(data, {el, table, details, section, picker}, timing) {
    const node = section('plays-title','What happens on the next play?');
    const steal=data.situations.find(r=>r.situation==='Steal');
    const basket=data.situations.find(r=>r.situation==='Opponent basket');
    node.append(el('p',`A shot was the next recorded event almost equally often after a steal (${pc(steal.next_shots/steal.states)}) and after an opponent basket (${pc(basket.next_shots/basket.states)}). Teams went on to score ${(steal.points/steal.states).toFixed(2)} points per turn after a steal, compared with ${(basket.points/basket.states).toFixed(2)} after a basket.`));
    const choices = Object.keys(names).filter(k=>data.situations.some(r=>r.situation===k));
    const {label,select} = picker('When the team gets the ball', choices.map(k=>[k,names[k]]));
    select.id = 'play-situation';
    const output = el('div',null,'play-output');
    output.setAttribute('aria-live','polite');
    function render() {
        const s = data.situations.find(r=>r.situation===select.value);
        const others = data.nextActions.filter(r=>r.situation===s.situation && r.next_action!=='Field goal attempt').sort((a,b)=>b.states-a.states);
        const item = (number,description) => {
            const group = el('div');
            group.append(el('strong',number),el('span',description));
            return group;
        };
        const tiles = el('div',null,'play-rates');
        tiles.append(item(pc(s.next_shots/s.states),'shot on the next recorded event'),
            item(pc(s.scoring_turns/s.states),'scored before the turn ended'),
            item((s.points/s.states).toFixed(2),'points by the end of the turn'));
        output.replaceChildren(tiles,el('p',`Across ${num.format(s.states)} situations, the next event was something other than a shot ${pc(1-s.next_shots/s.states)} of the time. The most common alternative was ${({Foul:'a foul',Turnover:'a turnover','Free throw':'a free throw','Period end':'the end of the period','Defensive rebound':'a defensive rebound','Offensive rebound':'an offensive rebound'})[others[0].next_action] || others[0].next_action.toLowerCase()}.`));
    }
    select.addEventListener('change',render);
    render();
    const ordered=[...data.situations].sort((a,b)=>b.points/b.states-a.points/a.states);
    const pathPanel = el('div');
    const shotCount=data.histories.reduce((n,row)=>n+row.attempts,0);
    const longCount=data.histories.find(r=>r.length===10)?.attempts || 0;
    const routePicker = picker('Recorded actions before the attempt', data.histories.map(b=>[b.length,b.length===10?'10 or more':String(b.length)]));
    routePicker.select.id='history-length';
    routePicker.select.value=data.histories.some(b=>b.length===3)?'3':String(data.histories[0].length);
    function route() {
        const group=data.histories.find(b=>b.length===Number(routePicker.select.value));
        const sequence=group.sequences[0];
        const trail=el('ol',null,'play-trail');
        for (const event of sequence.events) trail.append(el('li',event));
        trail.append(el('li','Shot attempted','shot-end'));
        pathPanel.replaceChildren(trail,el('p',`This was the most common recorded sequence of this length. It ended in ${num.format(sequence.attempts)} shots, with ${num.format(sequence.makes)} makes. There were ${num.format(group.attempts)} shots across all sequences in this group.`));
    }
    routePicker.select.addEventListener('change',route);
    route();
    const metrics=data.scores.filter(r=>r.season===2026);
    const forecastPick=picker('History to forecast',data.forecasts.map((r,i)=>[i,`${r.events.length} recorded ${r.events.length===1?'event':'events'}`]));
    forecastPick.select.id='play-forecast-history';
    const forecastText=el('p');
    const forecastExample=()=>{
        const r=data.forecasts[Number(forecastPick.select.value)];
        forecastText.textContent=`${r.events.join(' → ')}. The model gave a ${pc(r.predShot)} chance of a shot next, a ${pc(r.predScore)} chance of scoring before the turn ended, and ${r.predPoints.toFixed(2)} expected points. In ${num.format(r.states)} later cases the team scored ${pc(r.actualScore)} of the time and averaged ${r.actualPoints.toFixed(2)} points.`;
    };
    forecastPick.select.addEventListener('change',forecastExample);
    forecastExample();
    const results=details('What did the last ten actions add?',
        el('p','The sequence model estimates the chance of a shot next, the chance of scoring before the turn ends, and how many points are still to come. A rare sequence borrows information from shorter sequences ending the same way. Each forecast uses only events already recorded in that turn. Training ends in 2024.'),
        forecastPick.label,forecastText,table(['2026 games','History used','Shot error (Brier)','Scoring threat error (Brier)','Points error (RMSE)'],metrics.map(r=>[
            r.scope==='regular'?'Regular season':'Playoffs',r.model,r.brier.toFixed(5),r.score_brier.toFixed(5),r.rmse.toFixed(4)])),
        ...(metrics.filter(r=>r.model==='Up to ten actions').every(r=>r.brier_low<=0 && r.brier_high>=0 && r.mse_low<=0 && r.mse_high>=0)
            ? [el('p','In both the 2026 regular season and playoffs, the longer history and the most recent action gave almost identical predictions. The uncertainty ranges included a tie for both shot chance and points.')] : []),
        el('p','Lower scores mean closer predictions. These events capture shots, free throws, rebounds, fouls and turnovers. Passes, cuts and defender positions would require player and ball tracking.'));
    const clock = timing ? shotTiming(timing, {el, table, details, picker})
        : el('p', 'The shot timing comparison could not load. Reload the page to try again.', 'caption');
    node.append(clock, details('Compare all play situations', label, output,
        table(['Situation','Chances observed','Shot next','Scored in the turn','Points remaining'],ordered.map(s=>[
            names[s.situation],num.format(s.states),pc(s.next_shots/s.states),pc(s.scoring_turns/s.states),(s.points/s.states).toFixed(2)])),
        el('p','These are league averages in complete turns with verified scores and a clear change of control. The game clock, players and defense can differ across situations.')),
        details('Follow the actions before a shot',el('p',`Of ${num.format(shotCount)} attempts in complete turns, ${num.format(longCount)} had ten or more recorded actions available, including the event that began the turn. Choose a length to see what happened. Passes and cuts often leave no entry in the log.`),routePicker.label,pathPanel),results);
    return node;
}

export function locationPanel(data,{el,table,details,picker}) {
    const {label,select}=picker('2026 games',[['both','Regular season and playoffs'],['regular','Regular season'],['playoffs','Playoffs']]);
    select.id='location-model-phase';
    const host=el('div');
    const render=()=>{
        const subset=data.shotValue.filter(r=>r.scope===select.value).sort((a,b)=>b.expected-a.expected);
        host.replaceChildren(table(['Location','Attempts','Shot share','Make rate','Expected points per shot','Actual points per shot'],
            subset.map(r=>[r.area,num.format(r.attempts),pc(r.share),pc(r.makes/r.attempts),r.expected.toFixed(2),r.observed.toFixed(2)])));
    };
    select.addEventListener('change',render);
    render();
    return details('Expected points by shot location',el('p','How many points would a shot here usually produce? For each attempt, the model gives a chance of scoring zero, two or three points. The table compares the average forecast with the points actually scored, including misses.'),
        label,host,el('p','This league comparison uses the same eligible 2026 shots for every area summary. The model learned from 2022 to 2024, with settings chosen in 2025. It also uses information about the shooter and game situation.'));
}

export function sourceBreakdown(data,{el,table}) {
    const source=data.sources;
    const target=document.getElementById('source-explanation');
    target.replaceChildren(el('p',`wehoop distributes both feeds. Each season contributes shots from one provider. Together they contain ${num.format(source.regularPlayoffs)} regular season and playoff attempts.`),
        table(['Years','Shot provider','Attempts'],source.bands.map(r=>[`${r.start} to ${r.end}`,r.source,num.format(r.attempts)])),
        el('p',`The 2011 through 2026 ESPN files contain ${num.format(source.recentAllRecorded)} field goal attempts across all recorded games. Setting aside ${num.format(source.recentSpecial)} attempts in special games leaves ${num.format(source.recentRegularPlayoffs)} in the regular season and playoffs. The separate play by play study traces these games without adding shots to the explorer.`));
}
