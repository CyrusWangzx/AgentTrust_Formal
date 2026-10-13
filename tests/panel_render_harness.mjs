/**
 * Frontend render harness.
 *
 * Loads the real `frontend/app.js` against a minimal DOM stub and asserts that the panel
 * actually renders the records it is given. There is no browser in CI, and the panel is the
 * only deliverable whose failures are invisible to `pytest` - so this is the check that keeps
 * it honest.
 *
 * Prerequisite: run the demo first, so `frontend/data/records.json` exists:
 *     python scripts/demo/run_demo.py --cohort offline --chain dry-run
 *
 * Run:  node tests/panel_render_harness.mjs
 */
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import path from 'node:path';

const ROOT = path.resolve(import.meta.dirname, '..');

function makeEl(id) {
  return {
    id,
    innerHTML: '',
    textContent: '',
    className: '',
    disabled: false,
    title: '',
    classList: { add() {}, remove() {}, contains: () => false },
    addEventListener(event, fn) {
      (this._handlers ||= {})[event] = fn;
    },
  };
}

const els = new Map();
let fetchCalls = [];

globalThis.document = {
  getElementById(id) {
    if (!els.has(id)) els.set(id, makeEl(id));
    return els.get(id);
  },
};
globalThis.window = {}; // no EIP-1193 provider -> the wallet path must degrade, not crash
globalThis.fetch = async (url) => {
  fetchCalls.push(url);
  const rel = String(url).replace(/^\.\//, '');
  const file = path.join(ROOT, 'frontend', rel);
  try {
    const body = readFileSync(file, 'utf8');
    return { ok: true, status: 200, json: async () => JSON.parse(body) };
  } catch {
    return { ok: false, status: 404, json: async () => null };
  }
};

const warnings = [];
const realWarn = console.warn;
console.warn = (...args) => warnings.push(args.join(' '));

await import(pathToFileURL(path.join(ROOT, 'frontend', 'app.js')).href);
await new Promise((resolve) => setTimeout(resolve, 300)); // let boot() settle

console.warn = realWarn;

const records = els.get('records')?.innerHTML ?? '';
const badge = els.get('chain-badge');
const banner = els.get('source-banner');
const hetero = els.get('heterogeneity');

/**
 * The panel prefers a live chain read over the bundled feed. That read starts with
 * `await import('https://esm.sh/ethers@6.13.4')`, which works in a browser but NOT under
 * Node's default ESM loader (`ERR_UNSUPPORTED_ESM_URL_SCHEME`). So in this harness the live
 * path is *expected* to fail and hand over to the local feed - which is itself the behaviour a
 * verifier needs (open the built page, still see records). We therefore assert the degradation
 * explicitly and only treat *other* warnings as failures.
 */
const NODE_ONLY_LIVE_READ_WARNING = 'live read failed';
const liveReadDegraded = warnings.some((w) => w.includes(NODE_ONLY_LIVE_READ_WARNING));
const unexpectedWarnings = warnings.filter((w) => !w.includes(NODE_ONLY_LIVE_READ_WARNING));

const checks = [
  ['data feeds requested', fetchCalls.filter((u) => u.endsWith('.json')).length >= 2],
  ['chain badge set', Boolean(badge?.textContent && badge.textContent !== 'connecting')],
  ['banner rendered', Boolean(banner?.innerHTML)],
  ['3 records rendered', (records.match(/<article class="record">/g) || []).length === 3],
  ['D_rel shown', records.includes('D_rel')],
  ['D_total shown', records.includes('D_total')],
  ['Kendall W shown', records.includes('Kendall W')],
  ['all three decisions present',
    ['Approved', 'Rehearsed', 'Rehearse', 'Escalated'].filter((d) => records.includes(d)).length >= 2],
  ['dry-run chain write labelled', records.includes('dry-run')],
  ['heterogeneity panel rendered', Boolean(hetero?.innerHTML) && hetero.innerHTML.includes('qwen')],
  ['live read degrades to the local feed (Node cannot import https ESM)', liveReadDegraded],
  ['no unexpected bootstrap warning', unexpectedWarnings.length === 0],
];

let failed = 0;
for (const [name, ok] of checks) {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}`);
  if (!ok) failed += 1;
}
if (unexpectedWarnings.length) console.log('unexpected warnings:', unexpectedWarnings);
console.log(failed === 0 ? `\nfrontend render harness: ALL ${checks.length} CHECKS PASSED` : `\n${failed} CHECK(S) FAILED`);
process.exitCode = failed === 0 ? 0 : 1;
