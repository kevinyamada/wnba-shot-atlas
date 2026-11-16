'use strict';
(()=>{
const script=document.currentScript,source=script?.dataset.source||'assets/recovery.json';
const q=s=>document.querySelector(s),format=n=>Number(n).toLocaleString('en-CA');
const names=['Frozen clock','Expanded clock','Frozen context','Expanded context','Frozen Markov','Expanded Markov','Frozen average','Expanded average'];
const labels={'Frozen clock':'Clock rule · original training','Expanded clock':'Clock rule · expanded training','Frozen context':'Context model · original training','Expanded context':'Context model · expanded training','Frozen Markov':'Markov model · original training','Expanded Markov':'Markov model · expanded training','Frozen average':'Average · original training','Expanded average':'Average · expanded training'};
let data;
function conclusion(r,reference){
if(r.lower<=0&&r.upper>=0)return `The change versus ${reference} is uncertain on these games.`;
return r.upper<0?`Recorded error is lower than ${reference} on these games.`:`Recorded error is higher than ${reference} on these games.`;
}
function render(){
const policy=q('#recovery-policy').value,split=q('#recovery-period').value,cohort=q('#recovery-cohort').value,stage=q('#recovery-stage').value;
const selected=data.metrics.filter(r=>r.policy===policy&&r.split===split&&r.cohort===cohort&&r.stage===stage);
const coverage=data.coverage.find(r=>r.policy===policy);
const count=q('#recovery-counts');count.textContent=`${format(coverage.original_entry_states)} original entry states + ${format(coverage.added_entry_states)} recovered = ${format(coverage.total_entry_states)} total. Usable tails were added in ${coverage.periods_with_added_states} periods. These are inferred episodes, not official possession counts.`;
const visible=q('#recovery-all-models').checked?names:names.slice(0,4),body=q('#recovery-results');body.replaceChildren();
for(const name of visible){const r=selected.find(r=>r.model===name);if(!r)throw Error('Missing recovery metric');const tr=document.createElement('tr');tr.dataset.model=name;for(const v of [labels[name],r.rmse.toFixed(5),r.mae.toFixed(5)]){const td=document.createElement('td');td.textContent=v;tr.append(td);}body.append(tr);}
const find=baseline=>data.bootstrap.find(r=>r.policy===policy&&r.split===split&&r.cohort===cohort&&r.stage===stage&&r.model==='Expanded context'&&r.baseline===baseline);
const refit=find('Frozen context'),clock=find('Frozen clock');
q('#recovery-note').textContent=`${format(selected[0].states)} identical recorded states in ${selected[0].games} games per model. `+conclusion(refit,'the original context model')+' '+conclusion(clock,'the original simple clock rule')+' Training always ends August 9. These are reused 2025 benchmarks.';
q('#recovery-detail-note').textContent=`Expanded context minus original context squared error difference: ${refit.mse_difference.toFixed(6)} (95% game bootstrap interval ${refit.lower.toFixed(6)} to ${refit.upper.toFixed(6)}). Expanded context minus original clock rule: ${clock.mse_difference.toFixed(6)} (${clock.lower.toFixed(6)} to ${clock.upper.toFixed(6)}). Negative favours expanded context. Intervals condition on this screened sample and do not cover uncertainty in inferred boundaries.`;
window.recoveryCheck={data,render,rows:visible,policy,split,cohort,stage};
}
async function start(){
if(!q('#recovery'))return;
const response=await fetch(source);if(!response.ok)throw Error('Recovery data request failed');data=await response.json();
if(data.source.only_data_source!=='Data (1).zip'||data.source.archive_sha256!=='22a86860e179ce40ed34648c592bbd384297ddd5833000117973308a915a2120')throw Error('Unexpected recovery source');
for(const id of ['policy','period','cohort','stage','all-models'])q('#recovery-'+id).addEventListener('change',render);
render();document.body.dataset.recoveryReady='true';
}
start().catch(error=>{const el=q('#recovery-error');if(el)el.hidden=false;console.error(error);});
})();
