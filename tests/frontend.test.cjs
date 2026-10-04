const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

class Element {
  constructor(tag = 'div') { this.tagName = tag.toUpperCase(); this.children = []; this.value = ''; this.dataset = {}; this.hidden = false; this.textContent = ''; this.className = ''; this.attrs = {}; this.style = {}; this.classList = { add() {}, toggle() {} }; }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = items; }
  setAttribute(key, value) { this.attrs[key] = value; }
  querySelectorAll() { return []; }
  focus() {}
  get firstChild() { return this.children[0]; }
  get lastChild() { return this.children.at(-1); }
}
function setup(storage = {}) {
  const elements = new Map();
  const context = vm.createContext({
    console, URL, AbortController, Intl, Date, Math, Set, Object, JSON, Number, String,
    setTimeout, clearTimeout, setInterval: () => {},
    localStorage: { getItem: key => storage[key] ?? null, setItem: (key, value) => storage[key] = value },
    document: { getElementById: id => { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); },
      createElement: tag => new Element(tag), createElementNS: (_, tag) => new Element(tag), querySelectorAll: () => [], body: { style: {} } },
    location: { href: 'http://localhost/' }, history: { replaceState() {} }, navigator: {},
    fetch: async () => ({ ok: true, json: async () => ({}) }),
  });
  let source = fs.readFileSync(path.join(__dirname, '../suraksha/web/app.js'), 'utf8');
  source = source.slice(0, source.lastIndexOf('boot().catch('));
  vm.runInContext(source, context);
  return { context, elements, run: script => vm.runInContext(script, context) };
}

test('corrupt local persistence does not prevent initialization', () => {
  const app = setup({ 'suraksha-saved': '42', 'suraksha-checks': '[]' });
  assert.equal(app.run('state.saved.size'), 0);
  assert.equal(app.run('Array.isArray(state.checks)'), false);
});

test('saved district toggle persists and renders safely', () => {
  const app = setup();
  app.run(`state.districts = [{id:'PUNE', name_en:'<Pune>', state:'Maharashtra'}]; state.risks = []; toggleSaved('PUNE');`);
  assert.equal(app.run("state.saved.has('PUNE')"), true);
  assert.equal(app.elements.get('saved-count').textContent, 1);
  app.run("toggleSaved('PUNE')");
  assert.equal(app.run("state.saved.has('PUNE')"), false);
});

test('explorer filters unknown hazards rather than treating them as zero', () => {
  const app = setup();
  app.run(`state.districts = [{id:'PUNE',name_en:'Pune',state:'Maharashtra'},{id:'NAGPUR',name_en:'Nagpur',state:'Maharashtra'}];
    state.risks = [{id:'PUNE',hazards:{heat:{score:70}}}]; $('band-filter').value='unknown'; renderExplorer();`);
  assert.equal(app.elements.get('district-rows').children.length, 1);
  assert.equal(app.run("overall(riskFor('NAGPUR'))"), null);
  assert.equal(app.elements.get('district-rows').children[0].children[0].children[0].textContent, 'Nagpur');
});

test('comparison rejects duplicates and more than four districts', () => {
  const app = setup();
  app.run("state.compare=['PUNE','NAGPUR','CHENNAI','JAIPUR']; addCompare('PATNA'); addCompare('PUNE');");
  assert.equal(app.run('state.compare.length'), 4);
  app.run('clearTimeout(notify.timer)');
});

test('empty charts show a readable fallback and tables preserve zero', () => {
  const app = setup();
  app.run("drawChart('forecast-chart',[],['tavg','precipitation']); renderDataTable('forecast-table',[{day:'2026-10-03',tavg:0,tmax:null,precipitation:0}]);");
  assert.equal(app.elements.get('forecast-chart').children[0].textContent, 'No chart data yet.');
  const row = app.elements.get('forecast-table').children[0].children[1].children[0];
  assert.equal(row.children[1].textContent, '0.0');
  assert.equal(row.children[2].textContent, '—');
});

test('coordinate plot supplies keyboard accessible district points', () => {
  const app = setup();
  app.run("state.districts=[{id:'PUNE',name_en:'Pune',state:'Maharashtra',lat:18.52,lon:73.86}];renderPlot();");
  const svg = app.elements.get('geo-plot').children[0];
  const point = svg.children.find(el => el.attrs.role === 'button');
  assert.equal(point.attrs.tabindex, 0);
  assert.match(point.attrs['aria-label'], /unknown/);
  assert.equal(typeof point.onkeydown, 'function');
});

test('mission brief renders coverage and missing hazards without claiming confidence', async () => {
  const app = setup();
  app.run("state.selected='PUNE'; state.generation=1;");
  app.context.fetch = async () => ({ok:true,json:async()=>({demo:true,coverage:{percent:10,scored_hazard_days:2},timeline:[{day:'2026-10-03',overall:null,known_hazards:0}],priorities:[],limitations:['No data means unknown.']})});
  await app.run('loadMission()');
  assert.match(app.elements.get('mission-content').children[0].textContent,/Not confidence/);
  assert.equal(app.run('state.mission.demo'),true);
});

test('English chat leaves script detection enabled and selected regional language is explicit', async () => {
  const app = setup();let payload;
  app.context.fetch = async (_,options) => {payload=JSON.parse(options.body);return {ok:true,json:async()=>({reply:'ok'})};};
  app.run("$('language').value='en'");await app.run("sendChat('पुणे')");assert.equal(payload.language,null);
  app.run("$('language').value='ur'");await app.run("sendChat('Pune')");assert.equal(payload.language,'ur');
});

test('failed refresh clears previously loaded scores instead of relabelling them', async () => {
  const app = setup();
  app.run(`state.day='2040-01-01'; state.districts=[{id:'PUNE',name_en:'Pune',state:'Maharashtra',lat:18.52,lon:73.86}]; state.risks=[{id:'PUNE',hazards:{heat:{score:90}}}]; $('connection').append(document.createElement('span'));`);
  app.context.fetch = async () => ({ok:false,status:503});
  await app.run('refresh()');
  assert.equal(app.run('state.risks.length'),0);
  assert.equal(app.elements.get('error-banner').hidden,false);
  assert.equal(app.elements.get('refresh').disabled,false);
  assert.match(app.elements.get('watchlist-list').children[0].textContent,/unavailable/);
});

test('coverage inspector identifies missing districts and preserves known zero', () => {
  const app=setup();
  app.run(`state.day='2040-01-01'; state.districts=[{id:'PUNE',name_en:'Pune',state:'Maharashtra'},{id:'NAGPUR',name_en:'Nagpur',state:'Maharashtra'}]; renderMetrics({day:state.day,districts:2,covered:1,unknown:1,high:0,fully_covered:0,partial:1,hazard_coverage:{heat:{covered:1,unknown:1,missing_district_ids:['NAGPUR']}}});`);
  const card=app.elements.get('hazard-coverage').children[0];
  card.children.at(-1).onclick();
  assert.equal(app.elements.get('district-rows').children.length,1);
  assert.match(app.elements.get('result-count').textContent,/missing selected hazard/);
  app.run(`renderDistrictCoverage({risks:{[today()]:{heat:{score:0}}}})`);
  const row=app.elements.get('district-coverage').children[0].children[1].children[0];
  assert.equal(row.children[1].textContent,'0/100');
  assert.equal(row.children[2].textContent,'Unknown');
});

test('calendar date has ISO components regardless of locale formatting', () => {
  const app=setup();
  assert.match(app.run('today()'),/^\d{4}-\d{2}-\d{2}$/);
  assert.match(app.run('dateOffset(1)'),/^\d{4}-\d{2}-\d{2}$/);
});

test('API failure is surfaced instead of parsing an error as success', async () => {
  const app = setup();
  app.context.fetch = async () => ({ ok: false, status: 503 });
  await assert.rejects(app.run("api('/api/health')"), /503/);
});
