'use strict';
const $=s=>document.querySelector(s), NS='http://www.w3.org/2000/svg';
const number=n=>Number(n).toLocaleString('en-CA');
const modelLabel=name=>name.replaceAll('Equal-weight','Equal weight').replaceAll('Validation-calibrated','Validation calibrated');
const pct=n=>(100*n).toFixed(1)+'%';
function svg(tag,attrs={},text){const el=document.createElementNS(NS,tag);for(const [k,v] of Object.entries(attrs))el.setAttribute(k,v);if(text!==undefined)el.textContent=text;return el;}
function label(parent,x,y,text,attrs={}){parent.append(svg('text',{x,y,class:'label-svg',...attrs},text));}
function colour(t){const stops=[[230,239,236],[141,186,177],[38,126,131],[0,61,77]];t=Math.max(0,Math.min(.999999,t))*3;const i=Math.floor(t),f=t-i;return 'rgb('+stops[i].map((v,j)=>Math.round(v*(1-f)+stops[i+1][j]*f)).join(',')+')';}
let D,cells=[],current=null,pinned=false;
function courtLines(parent){const g=svg('g',{class:'court-lines'});g.append(svg('rect',{x:0,y:0,width:500,height:470,stroke:'#8a9898'}));g.append(svg('path',{d:'M30 470 L30 392.13 A221.4583 221.4583 0 0 1 470 392.13 L470 470'}));g.append(svg('circle',{cx:250,cy:417.5,r:7.5}));g.append(svg('line',{x1:220,y1:430,x2:280,y2:430}));parent.append(g);}
function selectCell(cell,lock=false){if(!cell)return;if(pinned&&!lock)return;if(current?.el)current.el.classList.remove('selected');current=cell;cell.el.classList.add('selected');if(lock){pinned=true;$('#unpin').hidden=false;}const mode=$('#metric').value;$('#cell-title').textContent=cell.n?'This square, up close.':'An unvisited square.';$('#cell-location').textContent=`${cell.y0.toFixed(1)} to ${cell.y1.toFixed(1)} ft sideways; ${cell.x0.toFixed(1)} to ${cell.x1.toFixed(1)} ft toward half court.`;$('#cell-n').textContent=number(cell.n);$('#cell-k').textContent=number(cell.k);$('#cell-points').textContent=number(cell.points);$('#cell-rate').textContent=(mode==='gp'||mode==='uncertainty')?`Model at centre: ${pct(cell.gp[2])}. 95% credible interval: ${pct(cell.gp[3])} to ${pct(cell.gp[4])}.`:(cell.n?`Observed make rate: ${pct(cell.k/cell.n)} (${cell.k} of ${cell.n}).`:'No recorded attempts in this square.');const list=$('#leaders');list.replaceChildren();let leaders=[...cell.players].filter(([,p])=>p.points>0).sort((a,b)=>b[1].points-a[1].points||D.players[a[0]].localeCompare(D.players[b[0]]));if(leaders.length){const max=leaders[0][1].points;leaders=leaders.filter((v,i)=>i<3||v[1].points===max);leaders.forEach(([id,p],i)=>{const li=document.createElement('li');li.textContent=`${D.players[id]}: ${p.points} points · ${p.k} makes / ${p.n} attempts${p.points===max&&leaders.filter(v=>v[1].points===max).length>1?' (tied lead)':''}`;list.append(li);});}else{const li=document.createElement('li');li.textContent=cell.n?'No made baskets here.':'No player counts to rank.';list.append(li);}$('#cell-caution').textContent=(cell.n<20?'Few attempts: this local rate can be noisy. ':'')+'Leaders are ranked by recorded field goal points.';}
function renderCourt(){const size=Number($('#size').value),team=$('#team').value,mode=$('#metric').value;const cols=Math.ceil(51/size),rows=Math.ceil(48/size);const map=new Map();cells=[];for(let i=0;i<rows;i++)for(let j=0;j<cols;j++){const x0=Math.max(-5.25,-5.5+i*size),x1=Math.min(41.75,-5.5+(i+1)*size),y0=Math.max(-25,-25.5+j*size),y1=Math.min(25,-25.5+(j+1)*size);if(x1<=x0||y1<=y0)continue;const cx=Math.max(-5,Math.min(41,Math.round((x0+x1)/2))),cy=Math.max(-25,Math.min(25,Math.round((y0+y1)/2)));const cell={i,j,x0,x1,y0,y1,n:0,k:0,points:0,players:new Map(),gp:D.gp[(cx+5)*51+cy+25]};cells.push(cell);map.set(i+','+j,cell);}
for(const [x,y,t,p,n,k,points] of D.cells){if(team!=='all'&&String(t)!==team)continue;const cell=map.get(Math.floor((x+5.5)/size)+','+Math.floor((y+25.5)/size));if(!cell)throw Error('Shot outside cells');cell.n+=n;cell.k+=k;cell.points+=points;const v=cell.players.get(String(p))||{n:0,k:0,points:0};v.n+=n;v.k+=k;v.points+=points;cell.players.set(String(p),v);}
const court=$('#court');court.replaceChildren();const defs=svg('defs'),pattern=svg('pattern',{id:'sparse',patternUnits:'userSpaceOnUse',width:6,height:6});pattern.append(svg('rect',{width:6,height:6,fill:'#edece5'}),svg('path',{d:'M0 6 L6 0',stroke:'#d1d4ce','stroke-width':.5}));defs.append(pattern);court.append(defs);const max=Math.max(...cells.map(c=>c.n/((c.x1-c.x0)*(c.y1-c.y0))));for(const c of cells){let fill='#fffdf8';if(mode==='gp')fill=colour(c.gp[2]);else if(mode==='uncertainty')fill=colour((c.gp[4]-c.gp[3])/.6);else if(mode==='rate')fill=c.n<20?'url(#sparse)':colour(c.k/c.n);else if(c.n)fill=colour(Math.log1p(c.n/((c.x1-c.x0)*(c.y1-c.y0)))/Math.log1p(max));c.el=svg('rect',{x:(c.y0+25)*10,y:(41.75-c.x1)*10,width:(c.y1-c.y0)*10,height:(c.x1-c.x0)*10,fill,class:'cell','data-count':c.n,'data-points':c.points});c.el.addEventListener('pointerenter',()=>selectCell(c));c.el.addEventListener('click',()=>selectCell(c,true));court.append(c.el);}courtLines(court);pinned=false;$('#unpin').hidden=true;$('#legend-low').textContent=mode==='attempts'?'Fewer':mode==='uncertainty'?'0 percentage points':'0%';$('#legend-high').textContent=mode==='attempts'?'More':mode==='uncertainty'?'60+ percentage points':'100%';$('#map-note').textContent=mode==='attempts'?'Attempts per square foot, on a log colour scale. Blank means zero.':mode==='rate'?'Makes / attempts. Striped squares have fewer than 20 attempts.':(mode==='uncertainty'?'Width of the pointwise 95% credible interval. Darker means less certain. ':'')+'Bayesian make probability for a league reference player, fitted through Aug 9. Estimates use the nearest grid point to each square’s centre.';selectCell(cells.find(c=>c.x0<=2&&c.x1>2&&c.y0<=0&&c.y1>0));window.wnbaCheck={shownAttempts:cells.reduce((a,c)=>a+c.n,0),shownMakes:cells.reduce((a,c)=>a+c.k,0),shownPoints:cells.reduce((a,c)=>a+c.points,0),cellCount:cells.length};}
function drawBand() {
    const chart = $('#band');
    const narrow = window.matchMedia('(max-width: 680px)').matches;
    const width = narrow ? 360 : 480;
    chart.setAttribute('viewBox', `0 0 ${width} 320`);
    chart.replaceChildren();
    const left = narrow ? 50 : 60, right = width - 25;
    const x = distance => left + (distance + 4) / 7 * (right - left);
    const y = density => 260 - density / 55 * 220;
    for (const tick of [0, 10, 20, 30, 40, 50]) {
        chart.append(svg('line', {x1: left - 5, x2: right, y1: y(tick), y2: y(tick), class: 'chart-grid'}));
        label(chart, left - 15, y(tick) + 4, tick, {'text-anchor': 'end'});
    }
    for (const bin of D.arcBins) chart.append(svg('rect', {
        x: x(bin.offset_lower) + 4, y: y(bin.attempts_per_sqft),
        width: (right - left) / 7 - 8, height: 260 - y(bin.attempts_per_sqft),
        fill: bin.offset_lower < 0 ? '#85a8a6' : 'var(--orange)'
    }));
    chart.append(svg('line', {x1: x(0), x2: x(0), y1: 30, y2: 260, class: 'chart-zero'}));
    for (const tick of [-4, -3, -2, -1, 0, 1, 2, 3]) label(chart, x(tick), 280, tick, {'text-anchor': 'middle'});
    label(chart, left, 18, 'Attempts per square foot');
    label(chart, width / 2, 309, 'Feet outside the three point line', {'text-anchor': 'middle'});
}
function results(){const split=$('#evaluation').value,body=$('#results');body.replaceChildren();const rows=D.metrics.filter(r=>r.split===split).sort((a,b)=>a.log_loss-b.log_loss);for(const r of rows){const tr=document.createElement('tr');if(r.model===D.selection.selected_model)tr.className='selected';for(const value of [modelLabel(r.model),r.brier.toFixed(5),r.log_loss.toFixed(5)]){const td=document.createElement('td');td.textContent=value;tr.append(td);}body.append(tr);}const ci=D.bootstrap.find(r=>r.split===split&&r.model===D.selection.selected_model);$('#result-note').textContent=`${number(rows[0].shots)} identical eligible attempts per model. ${modelLabel(D.selection.selected_model)} was selected using August 10 to 26 log loss; the highlighted row stays fixed across periods. Training ends August 9. These are reused 2025 benchmarks.`+(ci?` Its Brier difference versus distance is ${ci.brier_difference.toFixed(5)} (95% game bootstrap interval ${ci.lower.toFixed(5)} to ${ci.upper.toFixed(5)}). Negative favours the selected model.`:' The validation calibrated ensemble is omitted here because its calibration is fitted on this interval.');pointsResults(split);modelComparison(split);}
const comparisonModels = [
    {name: 'Bayesian GP', label: 'Bayesian spatial model', detail: 'Gaussian process'},
    {name: 'CatBoost context', label: 'Player + game context', detail: 'CatBoost · selected on validation'},
    {name: 'Equal-weight ensemble', label: 'Five model average', detail: 'Equal weights, fixed components'}
];

function modelComparison(split) {
    const chart = $('#model-chart');
    const narrow = window.matchMedia('(max-width: 680px)').matches;
    chart.setAttribute('viewBox', narrow ? '0 0 360 350' : '0 0 720 310');
    chart.replaceChildren();
    const baseline = D.metrics.find(row => row.split === split && row.model === 'Distance baseline');
    const rows = comparisonModels.map(model => {
        const score = D.metrics.find(row => row.split === split && row.model === model.name);
        const interval = D.bootstrap.find(row => row.split === split && row.model === model.name);
        return {...model, difference: score.brier - baseline.brier, interval};
    });
    // A shared scale across the game periods keeps the switch interpretable.
    const limits = D.bootstrap.filter(row => comparisonModels.some(model => model.name === row.model));
    const bound = Math.ceil(Math.max(...limits.flatMap(row => [Math.abs(row.lower), Math.abs(row.upper)]),
        ...rows.map(row => Math.abs(row.difference))) * 1000) / 1000;
    const centre = narrow ? 180 : 460;
    const span = narrow ? 150 : 190;
    const x = value => centre + value / bound * span;
    label(chart, narrow ? 20 : 270, 20, 'Better than distance alone', {'text-anchor': 'start'});
    label(chart, narrow ? 340 : 650, 20, 'Worse', {'text-anchor': 'end'});
    for (const tick of [-bound, -bound / 2, 0, bound / 2, bound]) {
        for (const [top, bottom] of narrow ? [[72, 102], [160, 190], [248, 278]] : [[34, 239]])
            chart.append(svg('line', {x1: x(tick), x2: x(tick), y1: top, y2: bottom,
                class: tick === 0 ? 'chart-zero' : 'chart-grid'}));
        label(chart, x(tick), narrow ? 310 : 263, tick === 0 ? '0' : tick.toFixed(4), {'text-anchor': 'middle'});
    }
    rows.forEach((row, i) => {
        const y = narrow ? 87 + i * 88 : 67 + i * 73;
        const group = svg('g', {'data-model': row.name, 'data-difference': row.difference,
            'data-lower': row.interval?.lower ?? '', 'data-upper': row.interval?.upper ?? ''});
        label(group, 12, y - (narrow ? 43 : 3), row.label, {class: 'chart-name'});
        label(group, 12, y + (narrow ? -25 : 17), row.detail, {class: 'chart-detail'});
        if (row.interval) {
            group.append(svg('line', {x1: x(row.interval.lower), x2: x(row.interval.upper), y1: y, y2: y,
                class: 'chart-interval'}));
            for (const end of [row.interval.lower, row.interval.upper])
                group.append(svg('line', {x1: x(end), x2: x(end), y1: y - 5, y2: y + 5, class: 'chart-interval'}));
        }
        const point = svg('circle', {cx: x(row.difference), cy: y, r: 5, class: 'chart-dot'});
        point.append(svg('title', {}, `${row.name}: ${row.difference.toFixed(6)} Brier difference` +
            (row.interval ? `; 95% interval ${row.interval.lower.toFixed(6)} to ${row.interval.upper.toFixed(6)}` : '; no interval for model selection data')));
        group.append(point);
        chart.append(group);
    });
    label(chart, centre, narrow ? 342 : 295, narrow ? 'Change in error (Brier score)' : 'Change in prediction error (Brier score)', {'text-anchor': 'middle'});
    const validation = split === 'validation';
    $('#model-chart-note').textContent = `${number(baseline.shots)} attempts, identical for every model. ` +
        (validation ? 'Dots only: this period chose the model settings; no uncertainty intervals are reported.' :
            'Dots show measured differences; lines show 95% game bootstrap intervals. A line crossing zero leaves the improvement uncertain.');
    $('#model-takeaway').textContent = validation
        ? 'These games chose the model settings. Switch to later games or the playoffs to check what happened next.'
        : split === 'test'
            ? 'Averaging five models gives a small improvement on these later games. The selected context model and the Bayesian model still have intervals crossing zero.'
            : 'In the playoffs, all three intervals cross zero. These games leave the advantage over distance alone uncertain.';
}

function spatialComparison() {
    const chart = $('#spatial-chart');
    const narrow = window.matchMedia('(max-width: 680px)').matches;
    chart.setAttribute('viewBox', narrow ? '0 0 360 375' : '0 0 720 340');
    chart.replaceChildren();
    const series = [
        {name: 'Distance baseline', label: 'Distance alone', colour: 'var(--muted)', dash: '6 4'},
        {name: 'SPDE', label: 'Spatial field (SPDE)', colour: 'var(--teal)'},
        {name: 'Universal kriging', label: 'Distance + kriging', colour: 'var(--orange)'}
    ];
    const left = narrow ? 52 : 92, right = narrow ? 328 : 618;
    const bottom = narrow ? 224 : 244;
    const x = buffer => left + buffer / 4 * (right - left);
    const y = score => bottom - (score - .228) / .024 * (bottom - 60);
    for (const tick of [.23, .24, .25]) {
        chart.append(svg('line', {x1: left - 10, x2: right + 12, y1: y(tick), y2: y(tick), class: 'chart-grid'}));
        label(chart, left - 18, y(tick) + 4, tick.toFixed(2), {'text-anchor': 'end'});
    }
    label(chart, narrow ? 12 : 82, 23, 'Prediction error · lower is better');
    for (const buffer of [0, 2, 4]) label(chart, x(buffer), bottom + 25, buffer + ' ft', {'text-anchor': 'middle'});
    label(chart, narrow ? 180 : 360, bottom + 53, narrow ? 'Training buffer (feet)' : 'Buffer around held out shot locations', {'text-anchor': 'middle'});
    series.forEach((model, index) => {
        const rows = [0, 2, 4].map(buffer => D.spatialCV.find(row => row.buffer === buffer && row.model === model.name));
        chart.append(svg('path', {d: rows.map((row, i) => `${i ? 'L' : 'M'}${x(row.buffer)} ${y(row.brier)}`).join(' '),
            fill: 'none', stroke: model.colour, 'stroke-width': 2, ...(model.dash ? {'stroke-dasharray': model.dash} : {})}));
        for (const row of rows) {
            const point = svg('circle', {cx: x(row.buffer), cy: y(row.brier), r: 4.5, fill: model.colour,
                'data-model': model.name, 'data-buffer': row.buffer, 'data-brier': row.brier});
            point.append(svg('title', {}, `${model.label}, ${row.buffer} ft: ${row.brier.toFixed(5)} Brier score`));
            chart.append(point);
        }
        const keyX = narrow ? 48 : 76 + index * 216;
        const keyY = narrow ? 314 + index * 24 : 329;
        chart.append(svg('line', {x1: keyX, x2: keyX + 23, y1: keyY, y2: keyY, stroke: model.colour, 'stroke-width': 2,
            ...(model.dash ? {'stroke-dasharray': model.dash} : {})}));
        label(chart, keyX + 30, keyY + 4, model.label);
    });
}

function continuationComparison(split) {
    const chart = $('#continuation-chart');
    const narrow = window.matchMedia('(max-width: 680px)').matches;
    chart.setAttribute('viewBox', narrow ? '0 0 360 350' : '0 0 720 290');
    chart.replaceChildren();
    const stages = [
        {name: 'entry', label: 'Start of a team’s turn'},
        {name: 'after_miss', label: 'After a miss'},
        {name: 'after_offensive_rebound', label: 'After an offensive rebound'}
    ];
    const rows = stages.map(stage => {
        const bins = D.possessionValue.summary.filter(row => row.split === split && row.stage === stage.name);
        const states = bins.reduce((total, row) => total + row.states, 0);
        const mean = bins.reduce((total, row) => total + row.states * row.mean_observed, 0) / states;
        return {...stage, states, mean};
    });
    const x = value => (narrow ? 24 : 268) + value / 1.5 * (narrow ? 282 : 365);
    for (const tick of [0, .5, 1, 1.5]) {
        for (const [top, bottom] of narrow ? [[66, 97], [156, 187], [246, 277]] : [[24, 228]])
            chart.append(svg('line', {x1: x(tick), x2: x(tick), y1: top, y2: bottom, class: 'chart-grid'}));
        label(chart, x(tick), narrow ? 309 : 250, tick.toFixed(1), {'text-anchor': 'middle'});
    }
    rows.forEach((row, i) => {
        const y = narrow ? 70 + i * 90 : 38 + i * 70;
        label(chart, 12, y + (narrow ? -32 : 13), row.label, {class: 'chart-name'});
        label(chart, 12, y + (narrow ? -13 : 34), number(row.states) + ' recorded states', {class: 'chart-detail'});
        const bar = svg('rect', {x: x(0), y, width: x(row.mean) - x(0), height: narrow ? 23 : 29,
            fill: i === 1 ? 'var(--orange)' : 'var(--teal)', 'data-stage': row.name,
            'data-states': row.states, 'data-mean': row.mean});
        bar.append(svg('title', {}, `${row.label}: ${row.mean.toFixed(6)} observed remaining points, ${number(row.states)} states`));
        chart.append(bar);
        label(chart, x(row.mean) + 9, y + (narrow ? 17 : 20), row.mean.toFixed(2), {class: 'chart-value'});
    });
    label(chart, narrow ? 180 : 450, narrow ? 340 : 281, 'Average points still to come', {'text-anchor': 'middle'});
    $('#continuation-takeaway').textContent = `After a miss, the team still scored an average of ${rows[1].mean.toFixed(2)} more points. ` +
        `In the situations with an offensive rebound, that average was ${rows[2].mean.toFixed(2)} points.`;
}

function spatialResults(){const body=$('#spatial-results');for(const name of [...new Set(D.spatialCV.map(r=>r.model))]){const tr=document.createElement('tr');[modelLabel(name),...[0,2,4].map(b=>D.spatialCV.find(r=>r.model===name&&r.buffer===b)?.brier.toFixed(5)??'Not available')].forEach(value=>{const td=document.createElement('td');td.textContent=value;tr.append(td);});body.append(tr);}}
function pointsResults(split){const body=$('#points-results');body.replaceChildren();for(const r of D.pointsMetrics.filter(r=>r.split===split).sort((a,b)=>a.rmse-b.rmse)){const tr=document.createElement('tr');for(const value of [modelLabel(r.model),r.rmse.toFixed(4),r.mae.toFixed(4)]){const td=document.createElement('td');td.textContent=value;tr.append(td);}body.append(tr);}}
function followupResults(){
const panel=$('#followup-panel');if(!D.localFollowup){panel.hidden=true;return;}panel.hidden=false;
const split=$('#followup-period').value,body=$('#followup-results');body.replaceChildren();
for(const r of D.localFollowup.metrics.filter(r=>r.split===split)){
const tr=document.createElement('tr');for(const v of [modelLabel(r.model),r.brier.toFixed(5),r.log_loss.toFixed(5)]){const td=document.createElement('td');td.textContent=v;tr.append(td);}body.append(tr);}
const pair=D.localFollowup.paired.find(r=>r.split===split&&r.model==='CPU CatBoost refit');
$('#followup-note').textContent=`${number(pair.shots)} identical eligible attempts. Refit minus matched CPU reference Brier: ${pair.brier_difference.toFixed(6)} (95% game bootstrap interval ${pair.lower.toFixed(6)} to ${pair.upper.toFixed(6)}). Negative favours refitting. Refit means training through August 26; reference means through August 9. All use the supplied archive; these remain reused 2025 benchmarks.`;
}
function possessionResults(){
const p=D.possessionValue;if(!p){$('#possession-value').hidden=true;return;}
const split=$('#possession-period').value,stage=$('#possession-stage').value,selected=p.selection.selected_model;
continuationComparison(split);
const rows=p.metrics.filter(r=>r.split===split&&r.stage===stage).sort((a,b)=>a.rmse-b.rmse),body=$('#possession-results');body.replaceChildren();
for(const r of rows){const tr=document.createElement('tr');if(r.model===selected)tr.className='selected';for(const value of [modelLabel(r.model),r.rmse.toFixed(5),r.mae.toFixed(5)]){const td=document.createElement('td');td.textContent=value;tr.append(td);}body.append(tr);}
const pair=p.bootstrap.find(r=>r.split===split&&r.stage===stage&&r.model===selected);
$('#possession-note').textContent=`${number(rows[0].states)} recorded states in ${rows[0].games} games. ${modelLabel(selected)} was selected on validation entry state MSE; training ends August 9. `+(pair?`Selected model minus training stage mean MSE: ${pair.mse_difference.toFixed(5)} (95% game bootstrap interval ${pair.lower.toFixed(5)} to ${pair.upper.toFixed(5)}). Negative favours the selected model. `:'This interval selected the model and is not independent confirmation. ')+'This is a screened subset of reused 2025 data.';
const chart=$('#possession-chart');chart.replaceChildren();chart.append(svg('title',{id:'possession-chart-title'},'Mean predicted and observed remaining points by period clock'));
const groups=p.summary.filter(r=>r.split===split&&r.stage===stage).sort((a,b)=>a.clock_bin-b.clock_bin),clock=['2 to 5','5 to 24','24 to 60','60 to 120','120 to 300','300 to 600'];
const top=Math.max(1.5,Math.ceil(Math.max(...groups.flatMap(r=>[r.mean_predicted,r.mean_observed]))*2)/2),x=i=>65+i*110,y=v=>205-v/top*165;
for(let i=0;i<=3;i++){const v=top*i/3;chart.append(svg('line',{x1:55,x2:630,y1:y(v),y2:y(v),stroke:'var(--line)'}));label(chart,46,y(v)+4,v.toFixed(1),{'text-anchor':'end'});}
label(chart,55,20,'Remaining points');label(chart,340,271,'Period clock remaining (seconds)',{'text-anchor':'middle'});
for(let i=0;i<6;i++)label(chart,x(i),228,clock[i],{'text-anchor':'middle'});
for(const [key,fill] of [['mean_predicted','var(--teal)'],['mean_observed','var(--orange)']]){
chart.append(svg('path',{d:groups.map((r,i)=>(i?'L':'M')+x(r.clock_bin)+' '+y(r[key])).join(' '),stroke:fill,'stroke-width':2,fill:'none'}));
for(const r of groups){const point=svg('circle',{cx:x(r.clock_bin),cy:y(r[key]),r:4,fill});point.append(svg('title',{},`${clock[r.clock_bin]} seconds: ${r[key].toFixed(3)} points; ${number(r.states)} states`));chart.append(point);}}
for(const r of groups)label(chart,x(r.clock_bin),245,`n=${number(r.states)}`,{'text-anchor':'middle','font-size':10});
const calibration=$('#possession-calibration');calibration.replaceChildren();for(const r of p.calibration.filter(r=>r.split===split&&r.stage===stage&&r.model===selected)){const tr=document.createElement('tr');for(const value of [r.prediction_bin,number(r.states),r.mean_prediction.toFixed(3),r.observed_remaining_points.toFixed(3)]){const td=document.createElement('td');td.textContent=value;tr.append(td);}calibration.append(tr);}
}
async function start(){const r=await fetch('assets/data.json');if(!r.ok)throw Error('Data request failed');D=await r.json();for(const [id,name] of Object.entries(D.teams).sort((a,b)=>a[1].localeCompare(b[1]))){const o=document.createElement('option');o.value=id;o.textContent=name;$('#team').append(o);}$('#metric').addEventListener('change',()=>{const gp=['gp','uncertainty'].includes($('#metric').value);if(gp)$('#team').value='all';$('#team').disabled=gp;renderCourt();});$('#team').addEventListener('change',renderCourt);$('#size').addEventListener('change',renderCourt);$('#unpin').addEventListener('click',()=>{pinned=false;$('#unpin').hidden=true;});$('#court').addEventListener('keydown',e=>{const moves={ArrowLeft:[0,-1],ArrowRight:[0,1],ArrowUp:[1,0],ArrowDown:[-1,0]};if(!moves[e.key]||!current)return;e.preventDefault();const [di,dj]=moves[e.key];selectCell(cells.find(c=>c.i===current.i+di&&c.j===current.j+dj),true);});$('#evaluation').addEventListener('change',results);$('#followup-period').addEventListener('change',followupResults);$('#possession-period').addEventListener('change',possessionResults);$('#possession-stage').addEventListener('change',possessionResults);renderCourt();drawBand();results();spatialComparison();spatialResults();followupResults();possessionResults();document.body.dataset.ready='true';}
start().catch(e=>{$('#load-error').hidden=false;console.error(e);});

let chartResize;
window.addEventListener('resize', () => {
    cancelAnimationFrame(chartResize);
    chartResize = requestAnimationFrame(() => {
        if (!D || document.body.dataset.ready !== 'true') return;
        drawBand();
        modelComparison($('#evaluation').value);
        spatialComparison();
        continuationComparison($('#possession-period').value);
    });
});
