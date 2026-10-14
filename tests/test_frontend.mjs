import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import vm from 'node:vm';

class Element {
  children = [];
  disabled = false;
  hidden = false;
  value = '50';
  _text = '';
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text; }
  append(...children) { this.children.push(...children); }
}

const tick = () => new Promise(resolve => setImmediate(resolve));

async function panel() {
  const nodes = new Map();
  const document = {hidden: false, createElement: () => new Element(),
    getElementById: id => {
      if (!nodes.has(id)) nodes.set(id, new Element());
      return nodes.get(id);
    }};
  const state = {
    conveyor: {running: false, port: 'FAKE', connected: true, busy: false, status: {}},
    camera: {error: null, fps: 24, in_frame: 2, tracking: true, model: 'conveyor-yolo11n.pt'},
    counts: {Pin: 2, Piston: 1, Shatun: 3}, total: 6, tracked: 2,
    labels: {Pin: 'Шпилька', Piston: 'Поршень', Shatun: 'Шатун'},
    report: {team: 'Технопарк-33', directory: 'reports/conveyor', updated_at: '2026-10-14T12:00:00+03:00'}
  };
  const requests = [];
  const env = {state, failState: false, startResult: {ok: true}};
  const fetch = async (path, options = {}) => {
    requests.push({path, options});
    if (path === '/api/state') {
      if (env.failState) throw new Error('disconnected');
      return {ok: true, json: async () => state};
    }
    return {ok: true, json: async () => env.startResult};
  };
  vm.runInNewContext(readFileSync(new URL('../frontend/app.js', import.meta.url), 'utf8'),
    {document, fetch, confirm: () => true, setInterval: () => 0});
  await tick();
  return {env, nodes, requests, node: id => document.getElementById(id)};
}

test('API fields produce Russian counters and valid tracking status', async () => {
  const p = await panel();
  assert.match(p.node('tracked').textContent, /в кадре: 2/);
  assert.doesNotMatch(p.node('model').textContent, /недоступен|undefined/);
  assert.deepEqual(p.node('counts').children.map(row => row.children[0].textContent),
    ['Шпилька', 'Поршень', 'Шатун']);
  assert.equal(p.node('total').textContent, '6');
  assert.equal(p.node('team').textContent, 'Технопарк-33');
  assert.equal(p.node('report-links').hidden, false);
});

test('zero and invalid speeds never send START', async () => {
  const p = await panel();
  for (const speed of ['0', '', '301', '1.5']) {
    p.node('speed').value = speed;
    p.node('start').onclick();
    await tick();
  }
  assert.equal(p.requests.filter(request => request.path === '/api/start').length, 0);
  assert.match(p.node('belt-error').textContent, /скорость/);
});

test('START disables repeat launch immediately and leaves STOP available', async () => {
  const p = await panel();
  p.node('start').onclick();
  assert.equal(p.node('start').disabled, true);
  assert.equal(p.node('stop').disabled, false);
  await tick();
  assert.equal(JSON.parse(p.requests.find(request => request.path === '/api/start').options.body).speed, 50);
});

test('failed command is displayed and reset is disabled while moving', async () => {
  const p = await panel();
  p.env.startResult = {ok: false, error: 'Мотор не ответил'};
  p.env.state.conveyor.running = true;
  p.node('start').onclick();
  await tick();
  assert.equal(p.node('belt-error').textContent, 'Мотор не ответил');
  assert.equal(p.node('belt-error').hidden, false);
  assert.equal(p.node('reset').disabled, true);
});

test('lost backend disables launch and report failure is visible', async () => {
  const p = await panel();
  p.env.state.report.error = 'Нет места на диске';
  p.node('stop').onclick();
  await tick();
  assert.equal(p.node('start').disabled, true);
  assert.equal(p.node('report-error').textContent, 'Нет места на диске');
  assert.equal(p.node('report-links').hidden, true);
  p.env.failState = true;
  p.node('stop').onclick();
  await tick();
  assert.equal(p.node('belt-state').textContent, 'панель недоступна');
  assert.equal(p.node('start').disabled, true);
});
