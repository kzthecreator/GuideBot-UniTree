// Run with: node tests/test_motion_timing_ui.js
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

class Element {
  constructor() { this.children = []; this.style = {}; this.value = ''; this.checked = false; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  setAttribute(name, value) { this[name] = value; }
  addEventListener() {}
}
const nodes = new Map();
function element(id) {
  if (!nodes.has(id)) nodes.set(id, new Element());
  return nodes.get(id);
}
element('phaseBar').children = [new Element(), new Element(), new Element()];
const catalog = [
  {name:'B_Neutral_Rest',type:'pose',profile_saved:true,minimum_total_ms:1000},
  {name:'B_Open_Hold',type:'motion',profile_saved:true,minimum_total_ms:2000},
  {name:'R_Side_Present',type:'motion',profile_saved:true,minimum_total_ms:2000},
];
const storage = new Map();
const context = vm.createContext({
  document:{getElementById:element,createElement:()=>new Element(),querySelectorAll:()=>[]},
  localStorage:{getItem:key=>storage.get(key)??null,setItem:(key,value)=>storage.set(key,value)},
  setInterval(){}, setTimeout(){},
  fetch:async path=>({ok:true,json:async()=>path==='/api/motions'?{items:catalog}:{
    name:'B_Neutral_Rest',type:'pose',category:'basic',frames:1,status:'draft',profile_saved:true,sha256:'fixture',version:1,
    timing_profile:{phase_weights:{transition:1,core:0,hold:1},minimum_total_ms:1000,frame_weights:[]},
  }}),
});
const html = fs.readFileSync(`${__dirname}/../../../tools/motion/motion_timing_ui.html`, 'utf8');
vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], context);
const run = code=>vm.runInContext(code, context);
(async()=>{
  // Let the initial asynchronous catalog and detail requests finish.
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(element('comboSteps').children.length,5);
  assert.match(element('comboSummary').textContent,/规划合计 9.000 s/);
  assert.equal(run('comboSequence().steps.map(step=>step.name).join(",")'),
    'B_Neutral_Rest,B_Open_Hold,B_Neutral_Rest,R_Side_Present,B_Neutral_Rest');
  run('comboSteps[0].total_ms=500; drawCombo()');
  assert.match(element('comboSummary').textContent,/请求合计 8.500 s · 规划合计 9.000 s/);
  assert.equal(run('comboSequence().steps[0].total_ms'),500);
  const first = element('comboSteps').children[0];
  first.children[4].children[1].onclick(); // Move first B_Neutral_Rest down.
  assert.equal(run('comboSteps[0].name'),'B_Open_Hold');
  assert.equal(run('comboSteps[1].name'),'B_Neutral_Rest');
  assert.ok(storage.has('g1-combo-steps'));
  run('busy=true; comboRunning=true; comboActive=3; drawCombo()');
  assert.equal(element('comboPreview').disabled,true);
  assert.equal(element('comboCancel').disabled,false);
  assert.match(element('comboSteps').children[3].className,/active/);
  assert.equal(element('comboSteps').children[0].children[1].disabled,true);
  run('busy=false; comboRunning=false; comboCatalog[0].profile_saved=false; drawCombo()');
  assert.equal(element('comboPreview').disabled,true);
  run(`detail.frames=3; $('transition').value='1'; $('duration').value='4'; $('hold').value='1';
       $('total').value='6000'; $('minimum').value='12000'; updateSummary()`);
  assert.equal(element('coreResult').textContent,'66.7% · 8.000 s');
  console.log('Combination ordering, duration minima, progress, locking, persistence, and single-action ratios passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
