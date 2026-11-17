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
function selectCell(cell,lock=false){if(!cell)return;if(pinned&&!lock)return;if(current?.el)current.el.classList.remove('selected');current=cell;cell.el.classList.add('selected');if(lock){pinned=true;$('#unpin').hidden=false;}const mode=$('#metric').value;$('#cell-title').textContent=cell.n?'This square, up close.':'An unvisited square.';$('#cell-location').textContent=`${cell.y0.toFixed(1)} to ${cell.y1.toFixed(1)} ft sideways; ${cell.x0.toFixed(1)} to ${cell.x1.toFixed(1)} ft toward half court.`;$('#cell-n').textContent=number(cell.n);$('#cell-k').textContent=number(cell.k);$('#cell-points').textContent=number(cell.points);$('#cell-rate').textContent=(mode==='gp'||mode==='uncertainty')?`Model at centre: ${pct(cell.gp[2])}. 95% credible interval: ${pct(cell.gp[3])} to ${pct(cell.gp[4])}.`:(cell.n?`Observed make rate: ${pct(cell.k/cell.n)} (${cell.k} of ${cell.n}).`:'No recorded attempts in this square.');const list=$('#leaders');list.replaceChildren();let leaders=[...cell.players].filter(([,p])=>p.points>0).sort((a,b)=>b[1].points-a[1].points||D.players[a[0]].localeCompare(D.players[b[0]]));if(leaders.length){const max=leaders[0][1].points;leaders=leaders.filter((v,i)=>i<3||v[1].points===max);leaders.forEach(([id,p],i)=>{const li=document.createElement('li');li.textContent=`${D.players[id]}: ${p.points} points · ${p.k} makes / ${p.n} attempts${p.points===max&&leaders.filter(v=>v[1].points===max).length>1?' (tied lead)':''}`;list.append(li);});}else{const li=document.createElement('li');li.textContent=cell.n?'No made baskets here.':'No player counts to rank.';list.append(li);}$('#cell-caution').textContent=(cell.n<20?'Few attempts: avoid reading much into this local rate. ':'')+'Leaders use observed season field goal points, not model estimates or shooting skill.';}
function renderCourt(){const size=Number($('#size').value),team=$('#team').value,mode=$('#metric').value;const cols=Math.ceil(51/size),rows=Math.ceil(48/size);const map=new Map();cells=[];for(let i=0;i<rows;i++)for(let j=0;j<cols;j++){const x0=Math.max(-5.25,-5.5+i*size),x1=Math.min(41.75,-5.5+(i+1)*size),y0=Math.max(-25,-25.5+j*size),y1=Math.min(25,-25.5+(j+1)*size);if(x1<=x0||y1<=y0)continue;const cx=Math.max(-5,Math.min(41,Math.round((x0+x1)/2))),cy=Math.max(-25,Math.min(25,Math.round((y0+y1)/2)));const cell={i,j,x0,x1,y0,y1,n:0,k:0,points:0,players:new Map(),gp:D.gp[(cx+5)*51+cy+25]};cells.push(cell);map.set(i+','+j,cell);}
for(const [x,y,t,p,n,k,points] of D.cells){if(team!=='all'&&String(t)!==team)continue;const cell=map.get(Math.floor((x+5.5)/size)+','+Math.floor((y+25.5)/size));if(!cell)throw Error('Shot outside cells');cell.n+=n;cell.k+=k;cell.points+=points;const v=cell.players.get(String(p))||{n:0,k:0,points:0};v.n+=n;v.k+=k;v.points+=points;cell.players.set(String(p),v);}
const court=$('#court');court.replaceChildren();const defs=svg('defs'),pattern=svg('pattern',{id:'sparse',patternUnits:'userSpaceOnUse',width:6,height:6});pattern.append(svg('rect',{width:6,height:6,fill:'#edece5'}),svg('path',{d:'M0 6 L6 0',stroke:'#d1d4ce','stroke-width':.5}));defs.append(pattern);court.append(defs);const max=Math.max(...cells.map(c=>c.n/((c.x1-c.x0)*(c.y1-c.y0))));for(const c of cells){let fill='#fffdf8';if(mode==='gp')fill=colour(c.gp[2]);else if(mode==='uncertainty')fill=colour((c.gp[4]-c.gp[3])/.6);else if(mode==='rate')fill=c.n<20?'url(#sparse)':colour(c.k/c.n);else if(c.n)fill=colour(Math.log1p(c.n/((c.x1-c.x0)*(c.y1-c.y0)))/Math.log1p(max));c.el=svg('rect',{x:(c.y0+25)*10,y:(41.75-c.x1)*10,width:(c.y1-c.y0)*10,height:(c.x1-c.x0)*10,fill,class:'cell','data-count':c.n,'data-points':c.points});c.el.addEventListener('pointerenter',()=>selectCell(c));c.el.addEventListener('click',()=>selectCell(c,true));court.append(c.el);}courtLines(court);pinned=false;$('#unpin').hidden=true;$('#legend-low').textContent=mode==='attempts'?'Fewer':mode==='uncertainty'?'0 percentage points':'0%';$('#legend-high').textContent=mode==='attempts'?'More':mode==='uncertainty'?'60+ percentage points':'100%';$('#map-note').textContent=mode==='attempts'?'Attempts per square foot, on a log colour scale. Blank means zero.':mode==='rate'?'Makes / attempts. Striped squares have fewer than 20 attempts.':(mode==='uncertainty'?'Width of the pointwise 95% credible interval. Darker means less certain. ':'')+'Data (1) Bayesian GP, trained through Aug 9. Player effect zero; context at training means. Nearest grid prediction at each square centre. This is a model estimate, not player skill.';selectCell(cells.find(c=>c.x0<=2&&c.x1>2&&c.y0<=0&&c.y1>0));window.wnbaCheck={shownAttempts:cells.reduce((a,c)=>a+c.n,0),shownMakes:cells.reduce((a,c)=>a+c.k,0),shownPoints:cells.reduce((a,c)=>a+c.points,0),cellCount:cells.length};}
function drawBand(){const chart=$('#band');chart.replaceChildren();const x=v=>60+(v+4)/7*395,y=v=>260-v/55*220;for(const t of [0,10,20,30,40,50]){chart.append(svg('line',{x1:55,x2:455,y1:y(t),y2:y(t),stroke:'#d8ddd6'}));label(chart,45,y(t)+4,t,{'text-anchor':'end'});}for(const b of D.arcBins){chart.append(svg('rect',{x:x(b.offset_lower)+4,y:y(b.attempts_per_sqft),width:48,height:260-y(b.attempts_per_sqft),fill:b.offset_lower<0?'#85a8a6':'#c45f36'}));}chart.append(svg('line',{x1:x(0),x2:x(0),y1:30,y2:260,stroke:'#263b43'}));for(const t of [-4,-3,-2,-1,0,1,2,3])label(chart,x(t),280,t,{'text-anchor':'middle'});label(chart,60,18,'Attempts per square foot');label(chart,260,309,'Feet outside the three point line',{'text-anchor':'middle'});}
function results(){const split=$('#evaluation').value,body=$('#results');body.replaceChildren();const rows=D.metrics.filter(r=>r.split===split).sort((a,b)=>a.log_loss-b.log_loss);for(const r of rows){const tr=document.createElement('tr');if(r.model===D.selection.selected_model)tr.className='selected';for(const value of [modelLabel(r.model),r.brier.toFixed(5),r.log_loss.toFixed(5)]){const td=document.createElement('td');td.textContent=value;tr.append(td);}body.append(tr);}const ci=D.bootstrap.find(r=>r.split===split&&r.model===D.selection.selected_model);$('#result-note').textContent=`${number(rows[0].shots)} identical eligible attempts per model. ${modelLabel(D.selection.selected_model)} was selected using August 10 to 26 log loss; the highlighted row stays fixed across periods. Training ends August 9. These are reused 2025 benchmarks.`+(ci?` Its Brier difference versus distance is ${ci.brier_difference.toFixed(5)} (95% game bootstrap interval ${ci.lower.toFixed(5)} to ${ci.upper.toFixed(5)}). Negative favours the selected model.`:' The validation calibrated ensemble is omitted here because its calibration is fitted on this interval.');pointsResults(split);}
function renderSpdeMesh(chart) {
    const mesh = D.mesh;
    const vertexCoordinates = [[1, -1], [1, 2], [4, -1]];
    const [shotX, shotY] = $('#mesh-location').value.split(',').map(Number);
    const vertexIds = vertexCoordinates.map(([x, y]) =>
        mesh.nodes.findIndex(([nodeX, nodeY]) => nodeX === x && nodeY === y)
    );
    const triangleExists = mesh.triangles.some(triangle => vertexIds.every(id => triangle.includes(id)));
    const locationExists = D.trainingLocations.some(([x, y]) => x === shotX && y === shotY);
    if (!triangleExists || !locationExists) throw Error('SPDE example is missing from the training geometry');

    const [[ax, ay], [bx, by], [cx, cy]] = vertexCoordinates;
    const area = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy);
    const weightA = ((by - cy) * (shotX - cx) + (cx - bx) * (shotY - cy)) / area;
    const weightB = ((cy - ay) * (shotX - cx) + (ax - cx) * (shotY - cy)) / area;
    const weights = [weightA, weightB, 1 - weightA - weightB].map(weight =>
        Math.abs(weight) < 1e-10 ? 0 : weight
    );
    const fractions = new Map([[0, '0'], [1, '⅓'], [2, '⅔'], [3, '1']]);
    weights.forEach((weight, index) => {
        const cell = $('#mesh-weight-' + 'abc'[index]);
        const thirds = Math.round(weight * 3);
        cell.textContent = Math.abs(weight * 3 - thirds) < 1e-10
            ? fractions.get(thirds)
            : weight.toFixed(3);
        cell.dataset.weight = String(weight);
    });

    const xs = mesh.nodes.map(([x]) => x);
    const ys = mesh.nodes.map(([, y]) => y);
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);
    const scale = 236 / Math.max(maxX - minX, maxY - minY);
    const meshPoint = ([x, y]) => [18 + (y - minY) * scale, 52 + (maxX - x) * scale];
    const detailPoint = ([x, y]) => [311 + (y + 1) * 49, 244 - (x - 1) * 49];
    const polygonPoints = (points, project) => points.map(point => project(point).join(',')).join(' ');

    label(chart, 18, 33, 'Full fitted mesh', {class: 'mesh-heading'});
    label(chart, 280, 33, 'One triangle, enlarged', {class: 'mesh-heading'});
    chart.append(svg('rect', {
        x: 18, y: 52, width: (maxY - minY) * scale, height: (maxX - minX) * scale, class: 'mesh-domain'
    }));
    const [courtLeft, courtTop] = meshPoint([41.75, -25]);
    chart.append(svg('rect', {
        x: courtLeft, y: courtTop, width: 50 * scale, height: 47 * scale, class: 'mesh-court'
    }));
    const projectedNodes = mesh.nodes.map(meshPoint);
    const edges = new Set();
    for (const [a, b, c] of mesh.triangles) {
        for (const [i, j] of [[a, b], [b, c], [c, a]]) {
            edges.add(i < j ? `${i},${j}` : `${j},${i}`);
        }
    }
    const edgePath = Array.from(edges, edge => {
        const [i, j] = edge.split(',').map(Number);
        return `M${projectedNodes[i].join(' ')} L${projectedNodes[j].join(' ')}`;
    }).join(' ');
    chart.append(svg('path', {d: edgePath, class: 'mesh-grid'}));
    const markings = svg('g', {transform: `translate(${courtLeft} ${courtTop}) scale(${scale / 10})`});
    courtLines(markings);
    chart.append(markings);
    chart.append(svg('polygon', {
        points: polygonPoints(vertexCoordinates, meshPoint), class: 'mesh-triangle', 'data-mesh': 'selected'
    }));
    const [overviewX, overviewY] = meshPoint([shotX, shotY]);
    chart.append(svg('circle', {cx: overviewX, cy: overviewY, r: 3.5, class: 'mesh-shot'}));

    chart.append(svg('rect', {x: 278, y: 52, width: 204, height: 236, rx: 3, class: 'mesh-inset'}));
    chart.append(svg('polygon', {points: polygonPoints(vertexCoordinates, detailPoint), class: 'mesh-triangle'}));
    vertexCoordinates.forEach((vertex, index) => {
        const [x, y] = detailPoint(vertex);
        chart.append(svg('circle', {cx: x, cy: y, r: 5, class: 'mesh-vertex'}));
        label(chart, x, y + (index === 2 ? -13 : 22), 'ABC'[index], {
            class: 'mesh-vertex-label', 'text-anchor': 'middle'
        });
    });
    const [detailX, detailY] = detailPoint([shotX, shotY]);
    chart.append(svg('circle', {cx: detailX, cy: detailY, r: 9, class: 'mesh-shot', 'data-mesh': 'shot'}));

    chart.append(svg('line', {x1: 18, x2: 33, y1: 314, y2: 314, class: 'mesh-boundary-key'}));
    label(chart, 41, 319, 'Court outline', {class: 'mesh-key'});
    chart.append(svg('line', {x1: 169, x2: 184, y1: 314, y2: 314, class: 'mesh-triangle'}));
    label(chart, 192, 319, 'Selected triangle', {class: 'mesh-key'});
    chart.append(svg('circle', {cx: 350, cy: 314, r: 5, class: 'mesh-shot'}));
    label(chart, 362, 319, 'Shot location', {class: 'mesh-key'});

    const activeVertices = weights.filter(weight => weight > 0).length;
    const contribution = {
        1: 'Only the vertex at this location contributes.',
        2: 'The two endpoints of the edge contribute.',
        3: 'All three vertices contribute.'
    }[activeVertices];
    $('#geometry-note').textContent =
        `Recorded training location (${shotX}, ${shotY}) ft in court coordinates, with the basket at (0, 0). ` +
        `${contribution} The fitted mesh has ${number(mesh.nodes.length)} vertices at ${mesh.spacing} ft grid spacing.`;
}

function geometry() {
    const view = $('#geometry').value;
    const chart = $('#geometry-chart');
    chart.replaceChildren();
    chart.dataset.view = view;
    chart.setAttribute('viewBox', view === 'mesh' ? '0 0 500 340' : '0 0 500 380');
    $('#buffer-label').hidden = view !== 'buffer';
    $('#mesh-location-label').hidden = view !== 'mesh';
    $('#mesh-weights').hidden = view !== 'mesh';
    if (view === 'mesh') {
        chart.setAttribute('aria-label', 'Fitted SPDE mesh with court outline and an enlarged triangle around a training shot location');
        renderSpdeMesh(chart);
        return;
    }
    if (view === 'variogram') {
        chart.setAttribute('aria-label', 'Empirical residual variogram and fitted exponential variogram');
        const empirical = D.variogram;
        const low = Math.min(0, ...empirical.map(row => row.semivariance));
        const high = Math.max(.1, ...empirical.map(row => row.semivariance));
        const x = value => 55 + value / 32 * 400;
        const y = value => 320 - (value - low) / (high - low) * 260;
        for (let i = 0; i < 5; i++) {
            const tick = low + (high - low) * i / 4;
            chart.append(svg('line', {x1: 55, x2: 455, y1: y(tick), y2: y(tick), stroke: '#d1d8d1'}));
            label(chart, 48, y(tick) + 4, tick.toFixed(2), {'text-anchor': 'end'});
        }
        for (const row of empirical) {
            chart.append(svg('circle', {cx: x(row.distance), cy: y(row.semivariance), r: 4, fill: '#006775'}));
        }
        const {sill, scale} = D.kriging;
        const path = Array.from({length: 65}, (_, i) => {
            const lag = i / 2;
            return `${i ? 'L' : 'M'}${x(lag)} ${y(sill * (1 - Math.exp(-lag / scale)))}`;
        }).join(' ');
        chart.append(svg('path', {d: path, fill: 'none', stroke: '#c45f36', 'stroke-width': 2}));
        for (const tick of [0, 8, 16, 24, 32]) label(chart, x(tick), 342, tick, {'text-anchor': 'middle'});
        label(chart, 250, 370, 'Distance between cell centres (feet)', {'text-anchor': 'middle'});
        label(chart, 55, 25, 'Residual semivariance (log odds²)');
        $('#geometry-note').textContent = 'Dots show empirical residual semivariance after removing the distance trend and approximate sampling noise. The orange line is the fitted exponential variogram, used to model spatial dependence for kriging. The fit uses training cells with at least 20 attempts. Sampling variation can make a corrected bin negative.';
        return;
    }

    chart.setAttribute('aria-label', 'Held out court region and buffered training shot locations');
    const buffer = Number($('#buffer').value);
    const plot = svg('g', {transform: 'translate(60 12) scale(.72)'});
    chart.append(plot);
    plot.append(svg('rect', {x: 0, y: 0, width: 500, height: 470, fill: '#fffdf8'}));
    for (const [x, y, fold, distance] of D.trainingLocations) {
        const fill = fold === 0 ? '#bd5a36' : distance <= buffer ? '#d9c6a7' : '#5d9a96';
        plot.append(svg('circle', {cx: (y + 25) * 10, cy: (41.75 - x) * 10, r: 2.8, fill}));
    }
    courtLines(plot);
    const fold = D.folds.find(row => row.buffer_ft === buffer && row.fold === 0);
    $('#geometry-note').textContent =
        `One of four folds. Orange shows the held out region, teal shows retained training locations, and sand shows locations removed by the buffer. ` +
        `${number(fold.train_shots)} training shots and ${number(fold.test_shots)} held out. ` +
        `The nearest retained training shot is ${fold.minimum_separation_ft.toFixed(1)} ft from a held out shot. ` +
        'The region boundaries are x = 16 ft and y = 0.';
}


function spatialResults(){const body=$('#spatial-results');for(const name of [...new Set(D.spatialCV.map(r=>r.model))]){const tr=document.createElement('tr');[modelLabel(name),...[0,2,4].map(b=>D.spatialCV.find(r=>r.model===name&&r.buffer===b)?.brier.toFixed(5)??'Not available')].forEach(value=>{const td=document.createElement('td');td.textContent=value;tr.append(td);});body.append(tr);}}
function pointsResults(split){const body=$('#points-results');body.replaceChildren();for(const r of D.pointsMetrics.filter(r=>r.split===split).sort((a,b)=>a.rmse-b.rmse)){const tr=document.createElement('tr');for(const value of [modelLabel(r.model),r.rmse.toFixed(4),r.mae.toFixed(4)]){const td=document.createElement('td');td.textContent=value;tr.append(td);}body.append(tr);}$('#compute-note').textContent=`${D.compute.successful_runs} completed H100 runs; ${D.compute.boosting_candidates_fitted} tree candidates. At least US$${D.compute.measured_gpu_usd_lower_bound.toFixed(2)} of measured GPU allocation. Paid jobs were stopped when remaining credit reached the user’s limit. See the compute record for total Modal usage, including interrupted work, before credits.`;}
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
const rows=p.metrics.filter(r=>r.split===split&&r.stage===stage).sort((a,b)=>a.rmse-b.rmse),body=$('#possession-results');body.replaceChildren();
for(const r of rows){const tr=document.createElement('tr');if(r.model===selected)tr.className='selected';for(const value of [modelLabel(r.model),r.rmse.toFixed(5),r.mae.toFixed(5)]){const td=document.createElement('td');td.textContent=value;tr.append(td);}body.append(tr);}
const pair=p.bootstrap.find(r=>r.split===split&&r.stage===stage&&r.model===selected);
$('#possession-note').textContent=`${number(rows[0].states)} recorded states in ${rows[0].games} games. ${modelLabel(selected)} was selected on validation entry state MSE; training ends August 9. `+(pair?`Selected model minus training stage mean MSE: ${pair.mse_difference.toFixed(5)} (95% game bootstrap interval ${pair.lower.toFixed(5)} to ${pair.upper.toFixed(5)}). Negative favours the selected model. `:'This interval selected the model and is not independent confirmation. ')+'This is a screened subset of reused 2025 data.';
const chart=$('#possession-chart');chart.replaceChildren();chart.append(svg('title',{id:'possession-chart-title'},'Mean predicted and observed remaining points by period clock'));
const groups=p.summary.filter(r=>r.split===split&&r.stage===stage).sort((a,b)=>a.clock_bin-b.clock_bin),clock=['2 to 5','5 to 24','24 to 60','60 to 120','120 to 300','300 to 600'];
const top=Math.max(1.5,Math.ceil(Math.max(...groups.flatMap(r=>[r.mean_predicted,r.mean_observed]))*2)/2),x=i=>65+i*110,y=v=>205-v/top*165;
for(let i=0;i<=3;i++){const v=top*i/3;chart.append(svg('line',{x1:55,x2:630,y1:y(v),y2:y(v),stroke:'#e3e6e7'}));label(chart,46,y(v)+4,v.toFixed(1),{'text-anchor':'end'});}
label(chart,55,20,'Remaining points');label(chart,340,271,'Period clock remaining (seconds)',{'text-anchor':'middle'});
for(let i=0;i<6;i++)label(chart,x(i),228,clock[i],{'text-anchor':'middle'});
for(const [key,fill] of [['mean_predicted','#28677a'],['mean_observed','#b76639']]){
chart.append(svg('path',{d:groups.map((r,i)=>(i?'L':'M')+x(r.clock_bin)+' '+y(r[key])).join(' '),stroke:fill,'stroke-width':2,fill:'none'}));
for(const r of groups){const point=svg('circle',{cx:x(r.clock_bin),cy:y(r[key]),r:4,fill});point.append(svg('title',{},`${clock[r.clock_bin]} seconds: ${r[key].toFixed(3)} points; ${number(r.states)} states`));chart.append(point);}}
for(const r of groups)label(chart,x(r.clock_bin),245,`n=${number(r.states)}`,{'text-anchor':'middle','font-size':10});
const calibration=$('#possession-calibration');calibration.replaceChildren();for(const r of p.calibration.filter(r=>r.split===split&&r.stage===stage&&r.model===selected)){const tr=document.createElement('tr');for(const value of [r.prediction_bin,number(r.states),r.mean_prediction.toFixed(3),r.observed_remaining_points.toFixed(3)]){const td=document.createElement('td');td.textContent=value;tr.append(td);}calibration.append(tr);}
}
async function start(){const r=await fetch('assets/data.json');if(!r.ok)throw Error('Data request failed');D=await r.json();for(const [id,name] of Object.entries(D.teams).sort((a,b)=>a[1].localeCompare(b[1]))){const o=document.createElement('option');o.value=id;o.textContent=name;$('#team').append(o);}$('#metric').addEventListener('change',()=>{const gp=['gp','uncertainty'].includes($('#metric').value);if(gp)$('#team').value='all';$('#team').disabled=gp;renderCourt();});$('#team').addEventListener('change',renderCourt);$('#size').addEventListener('change',renderCourt);$('#unpin').addEventListener('click',()=>{pinned=false;$('#unpin').hidden=true;});$('#court').addEventListener('keydown',e=>{const moves={ArrowLeft:[0,-1],ArrowRight:[0,1],ArrowUp:[1,0],ArrowDown:[-1,0]};if(!moves[e.key]||!current)return;e.preventDefault();const [di,dj]=moves[e.key];selectCell(cells.find(c=>c.i===current.i+di&&c.j===current.j+dj),true);});$('#evaluation').addEventListener('change',results);$('#geometry').addEventListener('change',geometry);$('#buffer').addEventListener('change',geometry);$('#mesh-location').addEventListener('change',geometry);$('#followup-period').addEventListener('change',followupResults);$('#possession-period').addEventListener('change',possessionResults);$('#possession-stage').addEventListener('change',possessionResults);renderCourt();drawBand();results();geometry();spatialResults();followupResults();possessionResults();document.body.dataset.ready='true';}
start().catch(e=>{$('#load-error').hidden=false;console.error(e);});
