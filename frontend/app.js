/**
 * AgentTrust verification panel.
 *
 * Two data sources, and the panel is explicit about which one it is using:
 *
 *   1. LIVE   - `data/deployment.json` carries a registry address, so records are read
 *               straight from the ERC-8004 Validation Registry on Monad Testnet (10143).
 *   2. LOCAL  - otherwise `data/records.json` (the dry-run ledger feed written by the demo)
 *               is rendered and the banner says SIMULATED out loud.
 *
 * The ethers import is dynamic on purpose: if the CDN is unreachable the panel still renders
 * the local feed instead of showing nothing.
 */

const DECISION_META = {
  Approved: { cls: 'decision-approved', label: 'Approved' },
  Rehearse: { cls: 'decision-rehearse', label: 'Rehearse' },
  Rejected: { cls: 'decision-rejected', label: 'Rejected' },
  Escalated: { cls: 'decision-escalated', label: 'Escalated' },
  InsufficientValidators: { cls: 'decision-insufficient', label: 'Insufficient validators' },
  InsufficientBaseline: { cls: 'decision-insufficient', label: 'Insufficient baseline' },
};

const DECISION_ORDINAL = {
  0: 'None', 1: 'Approved', 2: 'Rejected', 3: 'Escalated',
  4: 'InsufficientValidators', 5: 'InsufficientBaseline',
};

const THETA_LOW = 1.5;
const THETA_HIGH = 3.0;

const state = { mode: 'local', feed: null, deployment: null, chainRecords: null };

/* ------------------------------------------------------------------ helpers */
const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
));
const num = (value, digits = 4) => (
  value === null || value === undefined ? 'n/a' : Number(value).toFixed(digits)
);
const shortId = (value) => (value ? `${String(value).slice(0, 10)}...${String(value).slice(-6)}` : 'n/a');

async function fetchJson(path) {
  try {
    const response = await fetch(path, { cache: 'no-store' });
    if (!response.ok) return null;
    return await response.json();
  } catch {
    return null; // missing file is a normal state, not an error
  }
}

function decisionBadge(decision) {
  const meta = DECISION_META[decision] || { cls: 'decision-insufficient', label: decision || 'None' };
  return `<span class="decision ${meta.cls}">${esc(meta.label)}</span>`;
}

function metric(label, value) {
  return `<div class="metric"><div class="k">${esc(label)}</div><div class="v">${esc(value)}</div></div>`;
}

/* ------------------------------------------------------------------ render */
function renderBanner(kind, html) {
  const banner = $('source-banner');
  banner.className = `banner banner-${kind}`;
  banner.innerHTML = html;
}

function renderConstants(chainConstants) {
  const node = $('constants-line');
  if (!chainConstants) {
    node.textContent = 'Frozen constants from the specification: w = 0.4/0.3/0.3, theta_low = 1.5, theta_high = 3.0.';
    return;
  }
  node.innerHTML =
    `Read back from the deployed registry at <code>${esc(shortId(chainConstants.address))}</code>: ` +
    `weights <code>${chainConstants.w1}/${chainConstants.w2}/${chainConstants.w3}</code> ` +
    `(x1000), thresholds <code>${chainConstants.thetaLow}/${chainConstants.thetaHigh}</code> (x1000), ` +
    `K = <code>${esc(chainConstants.kRounds)}</code>.`;
}

function renderMetrics(reading) {
  if (!reading) return '';
  return `
    <div class="metrics">
      ${metric('D_disc', num(reading.D_disc))}
      ${metric('D_traj', num(reading.D_traj))}
      ${metric('D_end', num(reading.D_end))}
      ${metric('D_total', num(reading.D_total))}
      ${metric('D_base', num(reading.D_base))}
      ${metric('D_rel', num(reading.D_rel))}
      ${metric('Kendall W', reading.kendall ? num(reading.kendall.W) : 'n/a')}
    </div>`;
}

function renderRelBar(dRel) {
  if (dRel === null || dRel === undefined) return '';
  const pct = Math.max(0, Math.min(100, (Number(dRel) / (THETA_HIGH * 1.6)) * 100));
  const lowPct = (THETA_LOW / (THETA_HIGH * 1.6)) * 100;
  const highPct = (THETA_HIGH / (THETA_HIGH * 1.6)) * 100;
  return `
    <div class="bar" title="D_rel = ${num(dRel)} (theta_low ${THETA_LOW} / theta_high ${THETA_HIGH})">
      <span style="width:${pct}%"></span>
    </div>
    <div class="small muted">Band edges at ${THETA_LOW} and ${THETA_HIGH} (${lowPct.toFixed(0)}% / ${highPct.toFixed(0)}% of the scale).</div>`;
}

function renderVerdicts(verdicts) {
  if (!verdicts || verdicts.length === 0) return '<p class="muted small">No verdicts recorded.</p>';
  const rows = verdicts.map((v) => {
    const offline = String(v.provider || '').includes('offline');
    const providerCell = offline
      ? `<span class="tag tag-offline">${esc(v.provider)}</span>`
      : esc(`${v.model || ''} @ ${v.provider || ''}`);
    const status = v.error
      ? `<span class="tag tag-error" title="${esc(v.error)}">failed</span>`
      : '<span class="tag">ok</span>';
    return `
      <tr>
        <td>${esc(v.agent)}</td>
        <td>${providerCell}</td>
        <td class="num">${esc(v.response)}</td>
        <td class="truncate" title="${esc((v.actions || []).join(' -> '))}">${esc((v.actions || []).join(' -> '))}</td>
        <td class="truncate" title="${esc(JSON.stringify(v.terminal))}">${esc(JSON.stringify(v.terminal))}</td>
        <td class="num">${esc(v.latency_ms ?? '')}</td>
        <td>${status}</td>
      </tr>`;
  }).join('');
  return `
    <table>
      <thead>
        <tr>
          <th>Validator</th><th>Model @ endpoint</th><th class="num">Response</th>
          <th>Rehearsed actions</th><th>Terminal state</th><th class="num">ms</th><th>Status</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>`;
}

function renderRounds(record) {
  const rounds = record.rounds || [];
  if (rounds.length === 0) return '';
  return `
    <div>
      <div class="round-title">Rehearsal rounds (${rounds.length} of K = ${esc(record.kRounds ?? record.max_rounds ?? 3)})</div>
      <div class="rounds">
        ${rounds.map((r) => `
          <div>
            <div class="panel-head" style="margin-bottom:6px">
              <h3 style="margin:0">Round ${esc(r.round)} &middot; ${decisionBadge(r.decision)}</h3>
              <span class="muted small">cohort size ${esc(r.divergence?.cohort_size ?? 'n/a')}</span>
            </div>
            ${renderMetrics(r.divergence)}
            ${renderVerdicts(r.verdicts)}
            ${(r.divergence?.degraded || []).length
              ? `<p class="notes">Degradations applied: ${(r.divergence.degraded || []).map(esc).join('; ')}</p>`
              : ''}
          </div>`).join('')}
      </div>
    </div>`;
}

function renderChain(record) {
  const chain = record.chain || {};
  if (!chain.mode) return '';
  if (chain.mode === 'live' && chain.txHash) {
    const link = chain.explorerUrl
      ? `<a href="${esc(chain.explorerUrl)}" target="_blank" rel="noopener">${esc(shortId(chain.txHash))}</a>`
      : esc(shortId(chain.txHash));
    return `<p class="small">Chain write: <span class="tag">live</span> tx ${link} on chain ${esc(chain.chainId)}</p>`;
  }
  return `<p class="small muted">Chain write: <span class="tag tag-offline">dry-run</span> no transaction was sent (${esc(chain.note || '')})</p>`;
}

function renderRecord(record) {
  return `
    <article class="record">
      <div class="record-head">
        <span class="task">${esc(record.task?.task_id || 'unnamed task')}</span>
        ${decisionBadge(record.final_decision)}
        <span class="id" title="${esc(record.validationId)}">${esc(shortId(record.validationId))}</span>
        <span class="spacer"></span>
        <span class="muted small">${esc(record.round_count ?? (record.rounds || []).length)} round(s)</span>
      </div>
      <div class="record-body">
        <div class="muted small">${esc(record.task?.description || '').slice(0, 400)}</div>
        ${renderMetrics({
          D_disc: record.rounds?.at(-1)?.divergence?.D_disc,
          D_traj: record.rounds?.at(-1)?.divergence?.D_traj,
          D_end: record.rounds?.at(-1)?.divergence?.D_end,
          D_total: record.d_total,
          D_base: record.d_base,
          D_rel: record.d_rel,
          kendall: record.rounds?.at(-1)?.divergence?.kendall,
        })}
        ${renderRelBar(record.d_rel)}
        ${record.escalation_reason ? `<p class="reason">${esc(record.escalation_reason)}</p>` : ''}
        ${renderRounds(record)}
        ${renderChain(record)}
      </div>
    </article>`;
}

function renderRecords(records) {
  const container = $('records');
  $('record-count').textContent = records.length
    ? `${records.length} record(s)`
    : '';
  if (records.length === 0) {
    container.innerHTML = '';
    $('empty-state').classList.remove('hidden');
    return;
  }
  $('empty-state').classList.add('hidden');
  container.innerHTML = records.slice().reverse().map(renderRecord).join('');
}

function renderHeterogeneity(cohort) {
  const node = $('heterogeneity');
  if (!cohort) {
    node.innerHTML = '<p class="muted small">No cohort declaration available. Run the demo to produce one.</p>';
    return;
  }
  const hetero = cohort.heterogeneity || {};
  const live = cohort.live_heterogeneity || hetero;
  const families = (live.model_families || []).join(', ') || 'n/a';
  const providers = (live.providers || []).join(', ') || 'n/a';
  const frameworks = (live.frameworks || []).join(', ') || 'n/a';
  const ok = live.ok ? '<span class="verdict-ok">constraints satisfied</span>'
    : '<span class="verdict-warn">constraints not satisfied</span>';
  const strict = live.strict_ok ? 'yes' : 'no';
  const notes = (live.notes || []).concat(hetero.applicable === false ? [hetero.reason] : []);
  node.innerHTML = `
    <div class="hetero-card">
      <div class="k">Members</div>
      <div>${esc(cohort.member_count ?? 0)} (${esc(cohort.cohort_mode || (cohort.offline ? 'offline' : 'live'))}), min usable ${esc(cohort.min_usable ?? 2)}</div>
      <div class="k" style="margin-top:8px">Triad status</div>
      <div>${ok} &middot; all families distinct: ${strict}</div>
    </div>
    <div class="hetero-card">
      <div class="k">Model families</div>
      <div>${esc(families)}</div>
    </div>
    <div class="hetero-card">
      <div class="k">Vendor endpoints</div>
      <div>${esc(providers)}</div>
    </div>
    <div class="hetero-card">
      <div class="k">Prompt frameworks</div>
      <div>${esc(frameworks)}</div>
    </div>
    ${notes.length ? `<ul class="notes" style="grid-column:1/-1">${notes.map((n) => `<li>${esc(n)}</li>`).join('')}</ul>` : ''}`;
}

/* ------------------------------------------------------------------ chain read */
/**
 * Read every validation this registry knows about, straight from the chain.
 *
 * The ids come from the registry's own `CohortValidationOpened` events, not from a local
 * index file - a verifier who opens the deployed page with nothing but `deployment.json`
 * must still see the records.
 *
 * The public Monad RPC refuses a wide `eth_getLogs` range (`413 Request Entity Too Large`), so
 * the scan walks the deploy-block-to-head range in fixed-size chunks, a few chunks at a time.
 * `logChunkSize` in `deployment.json` tunes the window; the values below are the ones that
 * were verified against `https://testnet-rpc.monad.xyz`.
 */
const DEFAULT_LOG_CHUNK = 50;
const LOG_FETCH_CONCURRENCY = 6;
const MAX_LOG_CHUNKS = 4000;

function chunkStarts(from, to, size) {
  const starts = [];
  for (let start = from; start <= to; start += size) {
    if (starts.length >= MAX_LOG_CHUNKS) break;
    starts.push(start);
  }
  return starts;
}

async function collectValidationIds(registry, deployment, feed) {
  const ids = new Set();
  const from = Number(deployment.fromBlock ?? 0);
  const size = Number(deployment.logChunkSize ?? DEFAULT_LOG_CHUNK) || DEFAULT_LOG_CHUNK;
  const latest = await registry.runner.provider.getBlockNumber();
  const spans = chunkStarts(from, latest, size);
  const notes = [];
  let failedChunks = 0;
  let scanned = 0;

  for (let i = 0; i < spans.length; i += LOG_FETCH_CONCURRENCY) {
    const batch = spans.slice(i, i + LOG_FETCH_CONCURRENCY);
    const results = await Promise.all(batch.map(async (start) => {
      const end = Math.min(start + size - 1, latest);
      try {
        return await registry.queryFilter(registry.filters.CohortValidationOpened(), start, end);
      } catch (error) {
        failedChunks += 1;
        notes.push(`blocks ${start}-${end}: ${error.shortMessage || error.message}`);
        return [];
      }
    }));
    for (const logs of results) {
      scanned += 1;
      for (const log of logs) {
        const id = log?.args?.requestHash ?? log?.args?.[0];
        if (id) ids.add(String(id));
      }
    }
  }

  // The local feed is unioned in as a convenience, so an event that predates `fromBlock` - or a
  // chunk the RPC refused - does not silently drop a record.
  let fromFeed = 0;
  for (const record of feed?.records || []) {
    if (record.validationId && !ids.has(String(record.validationId))) {
      ids.add(String(record.validationId));
      fromFeed += 1;
    }
  }

  const source = `events ${scanned}/${spans.length} chunks of ${size} blocks`
    + (fromFeed ? ` + ${fromFeed} from the local index` : "")
    + (failedChunks ? ` (${failedChunks} chunk(s) refused)` : "");
  return { ids: [...ids], source, notes, scannedBlocks: scanned * size, failedChunks };
}

async function readFromChain(deployment, feed) {
  const ethers = await import('https://esm.sh/ethers@6.13.4');
  const provider = new ethers.JsonRpcProvider(deployment.rpcUrl, deployment.chainId);
  const network = await provider.getNetwork();
  if (Number(network.chainId) !== Number(deployment.chainId)) {
    throw new Error(`RPC reports chainId ${network.chainId}, expected ${deployment.chainId}`);
  }
  const registry = new ethers.Contract(deployment.registryAddress, deployment.abi, provider);

  const [w1, w2, w3] = await registry.weightsMilli();
  const [thetaLow, thetaHigh] = await registry.thresholdsMilli();
  const kRounds = await registry.kRounds();
  const constants = {
    address: deployment.registryAddress,
    w1: Number(w1), w2: Number(w2), w3: Number(w3),
    thetaLow: Number(thetaLow), thetaHigh: Number(thetaHigh),
    kRounds: Number(kRounds),
  };

  const { ids, source, notes } = await collectValidationIds(registry, deployment, feed);
  const records = [];
  for (const id of ids) {
    try {
      const record = await registry.getValidationRecord(id);
      const verdicts = await registry.getCohortVerdicts(id);
      records.push(chainRecordToView(id, record, verdicts));
    } catch (error) {
      console.warn(`chain read failed for ${id}: ${error.message}`);
      notes.push(`record ${shortId(id)}: ${error.shortMessage || error.message}`);
    }
  }
  return { constants, records, indexSource: source, indexNotes: notes };
}

function chainRecordToView(id, record, verdicts) {
  const toView = (v) => ({
    agent: v.validator,
    provider: 'on-chain',
    model: '',
    response: Number(v.response),
    actions: [],
    terminal: null,
    latency_ms: '',
    error: null,
    tag: v.tag,
    verdictURI: v.verdictURI,
  });
  const divergence = {
    D_disc: Number(record.divergence.dDiscMilli) / 1000,
    D_traj: Number(record.divergence.dTrajMilli) / 1000,
    D_end: Number(record.divergence.dEndMilli) / 1000,
    D_total: Number(record.divergence.dTotalMilli) / 1000,
    D_rel: Number(record.divergence.dRelMilli) / 1000,
    D_base: Number(record.dBaseMilli) / 1000,
    cohort_size: Number(record.cohortSize),
    kendall: {
      W: Number(record.divergence.kendallWMilli) / 1000,
      chi_square: Number(record.divergence.chiSquareMilli) / 1000,
    },
    degraded: [],
  };
  return {
    validationId: id,
    task: { task_id: record.requestURI, description: `on-chain request, agentId ${record.agentId}` },
    d_base: divergence.D_base,
    d_total: divergence.D_total,
    d_rel: divergence.D_rel,
    round_count: Number(record.roundsRun),
    final_decision: DECISION_ORDINAL[Number(record.decision)] || 'None',
    escalation_reason: '',
    rounds: [{
      round: Number(record.roundsRun),
      decision: DECISION_ORDINAL[Number(record.decision)] || 'None',
      divergence,
      verdicts: (verdicts || []).map(toView),
    }],
    chain: {
      mode: 'live',
      simulated: false,
      chainId: 10143,
      registryAddress: null,
      txHash: null,
      note: 'read from the registry contract - the write transactions are in the deploy and cohort records, not this view',
    },
  };
}

/* ------------------------------------------------------------------ wallet */
/**
 * Read-only wallet connection.
 *
 * The panel is a verifier, not an executor: it never asks a wallet to sign anything. The
 * optional "Connect wallet" button exists so an operator can confirm from their own account
 * that the registry they are looking at really is the one deployed on Monad Testnet 10143.
 *
 * If no EIP-1193 provider is present the panel degrades to the public-RPC read path, which
 * needs no wallet at all - verification must never depend on having an extension installed.
 */
const TESTNET_CHAIN_ID = 10143;
const TESTNET_CHAIN_HEX = '0x279f';
const TESTNET_PARAMS = {
  chainId: TESTNET_CHAIN_HEX,
  chainName: 'Monad Testnet',
  nativeCurrency: { name: 'MON', symbol: 'MON', decimals: 18 },
  rpcUrls: ['https://testnet-rpc.monad.xyz'],
  blockExplorerUrls: ['https://testnet.monadscan.com'],
};

function setWalletLine(kind, html) {
  const node = $('wallet-line');
  node.className = `wallet-line wallet-line-${kind}`;
  node.innerHTML = html;
}

async function connectWallet() {
  const button = $('connect-wallet');
  const provider = window.ethereum;

  if (!provider) {
    setWalletLine(
      'warn',
      'No browser wallet detected (<code>window.ethereum</code> is absent). This panel keeps ' +
      'reading the registry over public RPC, which needs no wallet.'
    );
    return;
  }

  button.disabled = true;
  try {
    const accounts = await provider.request({ method: 'eth_requestAccounts' });
    const address = accounts && accounts[0];
    if (!address) throw new Error('the wallet returned no account');

    const before = await provider.request({ method: 'eth_chainId' });
    if (String(before).toLowerCase() !== TESTNET_CHAIN_HEX) {
      setWalletLine('pending', `Wallet is on chain ${esc(before)}; switching to Monad Testnet 10143&hellip;`);
      try {
        await provider.request({
          method: 'wallet_switchEthereumChain',
          params: [{ chainId: TESTNET_CHAIN_HEX }],
        });
      } catch (switchError) {
        // 4902 = unknown chain; some wallets use -32603 instead.
        const code = switchError && switchError.code;
        if (code === 4902 || code === -32603) {
          await provider.request({ method: 'wallet_addEthereumChain', params: [TESTNET_PARAMS] });
        } else {
          throw switchError;
        }
      }
    }

    const after = await provider.request({ method: 'eth_chainId' });
    const reported = parseInt(after, 16);
    if (reported !== TESTNET_CHAIN_ID) {
      throw new Error(`wallet reports chain ${reported}, expected ${TESTNET_CHAIN_ID}`);
    }

    setWalletLine(
      'ok',
      `<code>${esc(address)}</code> connected on <code>Monad Testnet ${TESTNET_CHAIN_ID}</code>. ` +
      'Read-only: this panel never asks your wallet to sign a transaction.'
    );
    button.textContent = shortId(address);
  } catch (error) {
    setWalletLine(
      'warn',
      `Wallet connection failed: ${esc(error && error.message ? error.message : String(error))}. ` +
      'The RPC read path is unaffected.'
    );
  } finally {
    button.disabled = false;
  }
}

/* ------------------------------------------------------------------ boot */
async function boot() {
  const badge = $('chain-badge');
  const [feed, deployment, cohort] = await Promise.all([
    fetchJson('./data/records.json'),
    fetchJson('./data/deployment.json'),
    fetchJson('./data/cohort.json'),
  ]);

  state.feed = feed;
  state.deployment = deployment && deployment.registryAddress ? deployment : null;

  if (state.deployment) {
    try {
      const { constants, records, indexSource, indexNotes } = await readFromChain(state.deployment, feed);
      badge.className = 'badge badge-live';
      badge.textContent = `Monad Testnet 10143`;
      const notes = (indexNotes || []).length
        ? `<ul class="notes">${indexNotes.slice(0, 5).map((n) => `<li>${esc(n)}</li>`).join('')}</ul>`
        : '';
      renderBanner(
        'live',
        `LIVE - reading the ERC-8004 Validation Registry at ` +
        `<code>${esc(state.deployment.registryAddress)}</code> on Monad Testnet (chainId ${esc(state.deployment.chainId)}). ` +
        `Deploy tx: <code>${esc(shortId(state.deployment.deployTxHash))}</code>. ` +
        `Record index: ${esc(indexSource)}.${notes}`
      );
      renderConstants(constants);
      renderRecords(records);
      renderHeterogeneity(cohort);
      $('footer-build').textContent = `live chain read - ${new Date().toISOString()}`;
      return;
    } catch (error) {
      console.warn('live read failed, falling back to the local feed:', error);
      renderBanner('error', `Live chain read failed (${esc(error.message)}). Showing the local feed instead.`);
    }
  }

  const records = feed?.records || [];
  badge.className = 'badge badge-sim';
  badge.textContent = feed ? `chainId ${feed.chainId} - simulated` : 'no feed';
  if (!state.deployment) {
    renderBanner(
      'sim',
      'SIMULATED - these records come from the dry-run ledger ' +
      '(<code>frontend/data/records.json</code>); no transaction was sent. ' +
      'Deploy the registry and add <code>frontend/data/deployment.json</code> to switch this panel to live chain reads.'
    );
  }
  renderConstants(null);
  renderRecords(records);
  renderHeterogeneity(cohort || records.at(-1)?.heterogeneity ? (cohort || { heterogeneity: records.at(-1).heterogeneity }) : null);
  $('footer-build').textContent = feed ? `local feed generated ${feed.generatedAt}` : '';
}

$('refresh').addEventListener('click', () => window.location.reload());
$('connect-wallet').addEventListener('click', connectWallet);
boot();
