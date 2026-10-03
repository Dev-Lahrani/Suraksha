const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
function setup() {
  const handlers = {}, writes = [];
  const context = {URL, Response, self:{location:{origin:'https://suraksha.test'},addEventListener:(name,handler)=>handlers[name]=handler,clients:{claim:async()=>{}}},
    caches:{open:async()=>({addAll:async()=>{},put:async(key)=>writes.push(key)}),keys:async()=>[],match:async()=>new Response('cached shell')},
    fetch:async()=>new Response('network shell')};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../suraksha/web/sw.js'),'utf8'),context);
  return {handlers,writes,context};
}
test('API, webhook and external requests are never intercepted',()=>{
  const {handlers}=setup();
  for(const url of ['https://suraksha.test/api/risk-map','https://suraksha.test/api/chat','https://suraksha.test/webhook/whatsapp','https://external.test/app.js']) {
    let intercepted=false;handlers.fetch({request:{url,method:'GET',mode:'cors'},respondWith:()=>intercepted=true});assert.equal(intercepted,false);
  }
});
test('app shell offline fallback works for a shared district URL',async()=>{
  const {handlers,context}=setup();context.fetch=async()=>{throw new Error('offline');};let response;
  handlers.fetch({request:{url:'https://suraksha.test/?district=PUNE',method:'GET',mode:'navigate'},respondWith:p=>response=p});
  assert.equal(await (await response).text(),'cached shell');
});
test('successful asset responses are cached by shell path only',async()=>{
  const {handlers,writes}=setup();let response;const waits=[];
  handlers.fetch({request:{url:'https://suraksha.test/styles.css',method:'GET',mode:'cors'},respondWith:p=>response=p,waitUntil:p=>waits.push(p)});
  await response;await Promise.all(waits);assert.deepEqual(writes,['/styles.css']);
});
