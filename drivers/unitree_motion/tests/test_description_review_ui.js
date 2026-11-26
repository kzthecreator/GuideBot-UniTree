const fs=require('fs'), vm=require('vm'), assert=require('assert');
const nodes=new Map(), calls=[];
function element(id){if(!nodes.has(id))nodes.set(id,{value:'',checked:false,append(){},replaceChildren(){}});return nodes.get(id);}
const detail={name:'Custom',description:'保留描述',frames:3,sha256:'new',version:2,status:'draft',description_review:{pending:true,previous_frames:2,new_frames:3},timing_profile:{minimum_total_ms:2000}};
const context=vm.createContext({document:{getElementById:element,createElement:()=>({})},setInterval(){},fetch:async(path,options)=>{
 if(options&&options.body)calls.push({path,payload:JSON.parse(options.body)});
 return {ok:true,json:async()=>path==='/api/motions'?{items:[{name:'Custom',available:true,recorded:true}]}:detail};
}});
const html=fs.readFileSync(`${__dirname}/../../../tools/motion/motion_timing_ui.html`,'utf8');
vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1],context);
(async()=>{
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(element('description').value,'保留描述',element('message').textContent);
 assert.match(element('descriptionReview').textContent,/旧帧数 2，新帧数 3/);
 vm.runInContext('eligible=true;buttons()',context);
 assert.equal(element('confirm').disabled,true);
 element('description').value='修改后的三帧描述';element('description').oninput();
 assert.equal(vm.runInContext('eligible',context),false);
 element('reviewed').checked=true;
 await element('saveDescription').onclick();
 assert.equal(calls[0].path,'/api/description');
 assert.equal(calls[0].payload.description,'修改后的三帧描述');
 assert.equal(calls[0].payload.description_reviewed,true);
 console.log('Description review UI passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
