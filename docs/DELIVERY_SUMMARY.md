# Delivery summary — AgentTrust

**Work order:** `Metropolis_AgentTrust_开发工单_v1.md` (Monad Metropolis, Track 4 — Trust /
Identity / AI Infrastructure). Deadline 2026-10-14 12:00.

This file is the self-check the work order §8 asks for. It states what is finished, what has
been verified and how, what has **not** been executed, and the exact owner actions still
outstanding. Nothing below is rounded up.

---

## 1. Verification evidence (all reproducible)

| # | Check | Command | Result |
| --- | --- | --- | --- |
| 1 | Divergence library + orchestrator + platform tests | `pytest tests/ -q` | **231 passed** (3.5 s) |
| 2 | Contract test suite | `cd contracts && npm test` | **37 passing** (6 s) — includes the 4 cross-language attestation-encoding tests |
| 3 | Contracts compile | `cd contracts && npm run compile` | clean, no warnings |
| 4 | End-to-end demo | `python scripts/demo/run_demo.py --cohort offline --chain dry-run --no-color` | 3 tasks, 3 real verdicts, real `D_total` / `D_rel` |
| 5 | Panel renders from the real feed | `node tests/panel_render_harness.mjs` | **12/12 checks passed** |
| 6 | Panel static assets reachable | `cd frontend && python -m http.server` + `curl` | `index.html` / `app.js` / `styles.css` / `records.json` / `cohort.json` / logo → all **200** |
| 7 | Deployment verifier fails closed | `python scripts/verify_deployment.py --address 0x…0001 --rpc https://testnet-rpc.monad.xyz` | exit **1**, `FAIL: no contract bytecode`, no output file written |
| 8 | Monad Testnet RPC live | `eth_chainId` on `https://testnet-rpc.monad.xyz` | **`0x279f` = 10143** |
| 9 | README local links/images resolve | link check over the four markdown files | 12/12 local targets exist |
| 10 | Work order §3 structure complete | directory check | every listed path present |
| 11 | **Contract actually deployed** | `python scripts/verify_deployment.py` + `npm run verify:deployed` | registry `0x4479D6…7053`, bytecode `13302` bytes, chain **10143**, frozen constants `400/300/300`, `1500/3000`, `kRounds 3` all read back ✅ |
| 12 | **Live chain write path exercised** | `python .tmp/chain_state.py` | 2 cohort lifecycles finalised on chain — **Approved** (`D_rel` 0.289) and **Escalated** (`D_rel` 3.975), both read back with matching divergence |
| 13 | **Gas measured, not guessed** | `python .tmp/gas_probe.py` | full 3-task live demo **~1.31 MON** at estimated limit vs **~4.59 MON** under the old blanket 3M limit |
| 14 | **Panel publicly reachable** | `check-host.net` probe from 5 external nodes (PT/RS/RU/SE/GB) | all **HTTP 200**, resolved to real Vercel edge IPs (`64.29.17.x` / `216.198.79.x`) — i.e. no Vercel login wall |
| 15 | **Panel serves the right page** | `api.microlink.io` fetch of the live URL | title `AgentTrust - Pre-Execution Verification Panel`; page text contains `D_total = 0.4·D_disc + 0.3·D_traj + 0.3·D_end` |
| 16 | **Panel sub-resources reachable** | `check-host.net` probe of `/data/deployment.json` | HTTP 200 from DE/NL/US nodes |

**Demo output** (`artifacts/latest-record.json`, `frontend/data/records.json`):

| task | rounds | `D_total` | `D_rel` | decision |
| --- | --- | --- | --- | --- |
| `warehouse-pick-001` | 1 | 0.1445 | 0.2890 | **Approved** |
| `arm-reach-boundary-002` | 3 | 0.9046 | 1.8092 | **Escalated** (K rounds exhausted) |
| `unauthorized-override-003` | 1 | 1.3911 | 3.9746 | **Escalated** (`D_rel > θ_high`, significant W) |

The `unauthorized-override-003` figure is the one to remember: **3.9746 offline == 3.975 on chain**
(`0x7a21816a…`). The local computation and the on-chain record agree to three decimals, which is
what makes the deployed write path trustworthy rather than merely present.

---

## 2. Deliverables

| # | Deliverable | Status | Notes |
| --- | --- | --- | --- |
| D1 | GitHub repository — README, LICENSE, `.env.example` | ✅ | README carries logo lockup, mechanism diagram, the §2 formulas verbatim, quickstart, testnet-evidence section, team |
| D2 | Contract layer — ERC-8004 Validation Registry + deploy scripts | ✅ | `AgentTrustValidationRegistry` + `DivergenceLib`; on-chain decision re-derivation; 37 tests; mainnet-143 guards |
| D3 | Divergence library + unit tests | ✅ | `D_disc`/`D_traj`/`D_end`/`D_total`/`D_rel` + Kendall's W; `calibrate.py` slot present and non-blocking |
| D4 | Orchestration — fan-out, verdict collection, thresholds, K-round machine | ✅ | threaded fan-out, fail-closed `INSUFFICIENT_VALIDATORS` / `INSUFFICIENT_BASELINE` |
| D5 | Heterogeneous validator config + triad declaration | ✅ | 5 live members (Qwen ×3 / Kimi ×2) across 4 endpoints and 5 frameworks; offline fixture cohort for credential-free runs |
| D6 | Verification panel reading Monad Testnet | ✅ **DEPLOYED** | **<https://agenttrust-panel.vercel.app>** — reads the registry's own `CohortValidationOpened` events in 50-block windows. Verified publicly reachable from 5 external nodes (HTTP 200) and content-checked (page title + rendered `D_total` formula). Node DOM harness: 12/12 |
| D7 | Testnet deployment evidence | ✅ **DEPLOYED** | registry `0x4479D63b5780e5DBa95feEB057Ed57B8E20b7053` on chain 10143, deploy block `70771345`; `DEPLOYMENT.md` carries the receipt and the two live cohort records |
| D8 | End-to-end demo script | ✅ | `python scripts/demo/run_demo.py`, one command, five stages; `--chain live` writes through to the deployed registry |
| D9 | Demo + pitch video scripts | ✅ | `docs/DEMO_SCRIPT.md` (180 s storyboard, 9 shots), `docs/PITCH_SCRIPT.md` (120 s, 30/45/30/15, EN + 中文对照) |

---

## 3. Deviations and judgement calls (flagged, not hidden)

1. **"Connect wallet" is a chain connection, not a signature.** Work order §6's demo storyboard
   opens with a wallet shot. This panel is a read-only verifier, so its wallet button requests
   accounts and switches the network to 10143 but never prompts for a signature — the request
   itself is signed server-side by the requester key. `docs/DEMO_SCRIPT.md` shot 2 records it on
   those terms and the README says so. *If you want a wallet that signs on camera, say so and I
   will add an in-browser requester path — it is a real change, not a cosmetic one.*
2. ~~**`docs/architecture.png` is generated, not the referenced source asset.**~~ **Resolved.**
   The supplied architecture diagram (`AgentTrust / Monad 上的无许可信任验证基础设施`, 3300×2090) has
   replaced the self-drawn stand-in, and its generator `docs/make_architecture.py` was removed
   from the repository so nothing can regenerate over the official asset. The README's Mechanism
   section now maps each of the diagram's four layers to the code that implements it, and states
   plainly which layer (the behaviour-anomaly system) is product context rather than shipped code.
3. ~~**The logo lockup is composed in markdown.**~~ **Resolved.** The 2000×650 lockup — the exact
   filename the work order names, `AgentTrust_logo_lockup_2000.png` — was supplied and is now the
   README header. The lossless 1024×1024 PNG stays as the icon; a JPEG of the same artwork was
   also supplied and is deliberately not used.
4. **The `Rejected` band is covered by unit tests, not by the sample demo tasks.** With the
   shipped offline cohort the validators disagree *coherently* (Kendall's W is significant), so
   the top band resolves to `Escalated`. `tests/test_core.py` covers `Rejected` directly and the
   contract suite covers it on-chain.
5. **`--nonce` was added to the demo.** `openCohortValidation` reverts with
   `RequestAlreadyExists` on a repeated `requestHash`, and the id is deterministic by design. A
   re-run against the same registry therefore needs a fresh nonce; without this, a re-recorded
   demo would revert on camera. Documented in the README and in the demo script's pre-flight.
6. **Two defects were found by the panel harness and fixed** (details in §5).
7. **Live writes are relayed, not self-submitted, so one funded account drives the whole cohort.**
   `attestCohortVerdict` lets the orchestrator relay a validator's EIP-191 signature, so the
   cohort's five members never need MON. The demo therefore derives all member keys from a single
   `AGENTTRUST_COHORT_SEED` instead of asking for five funded addresses. The self-submit path
   (`submitCohortVerdict`) is still implemented and still taken whenever a member address *is* the
   sending account (as in the Hardhat tests).
8. **Monad bills the full gas limit, so the writer estimates.** A hardcoded limit costs the same
   whether the call needs 52 697 gas or 429 648 (`finalizeValidation` vs `openCohortValidation`).
   Details and measured numbers in `DEPLOYMENT.md` §2b.
9. **The Vercel deployment needed two non-obvious settings.** (a) Vercel CLI 64 no longer has
   `--name`, and `--project` only *selects* an existing project — so the project was created
   through the REST API first (`agenttrust-panel`), then deployed into it. (b) The new project
   came up with **Deployment Protection (Vercel Authentication) enabled**, which would have put a
   login wall in front of every judge; it was turned off via
   `PATCH /v9/projects/agenttrust-panel {"ssoProtection": null}`. Both are recorded because a
   re-deploy from scratch would hit them again.
10. **`*.vercel.app` is not reachable from the machine that deployed it.** Local DNS resolves
    `agenttrust-panel.vercel.app` to `128.242.250.157` (a Meta range) and every request times out
    — the classic signature of DNS interference on mainland networks. This is a *local network*
    fact only: five external nodes and a third-party page fetcher all reach the site over HTTP
    200. The README therefore also documents the local `python -m http.server` fallback, so a
    reviewer on a blocked network is never stuck.

---

## 4. Owner actions still outstanding

| # | Action | Why it is the owner's | Status |
| --- | --- | --- | --- |
| 1 | Fund a Monad Testnet account from `https://faucet.monad.xyz` | Needs a key you control | ✅ done — `0xfB93Ab…7514`, 5.0 MON at deploy |
| 2 | Add real `DASHSCOPE_API_KEY` / `MOONSHOT_API_KEY` to `.env` | Credentials | ⏳ the demo runs on the offline fixture cohort without them; `--cohort live` needs them |
| 3 | Set cohort identities for live submissions | On-chain identities | ✅ done via `AGENTTRUST_COHORT_SEED` (relayed path — members need no MON) |
| 4 | `cd contracts && npm run deploy:testnet` then fill `DEPLOYMENT.md` §4 from the receipt | Needs #1 | ✅ done — receipt in `contracts/deployments/monad-testnet-10143.json`, §4 filled from it |
| 5 | **Top up the deployer (~1.4 MON)** and re-run the full 3-task live demo | Funds | ⏳ balance is **0.031 MON** — see the run command below |
| 6 | Create the GitHub repo and push | I have not run any `git` command: the standing instruction is not to commit or push without an explicit go-ahead | ⏳ |
| 7 | Deploy `frontend/` to Vercel or GitHub Pages | Account authorisation; the directory is a static site as-is | ✅ done — <https://agenttrust-panel.vercel.app> (project `agenttrust-panel`, team `cyrus-2117`); Vercel Authentication was turned **off** so judges are not stopped by a login wall |
| 8 | Record the two videos from `docs/DEMO_SCRIPT.md` and `docs/PITCH_SCRIPT.md` | Needs #5–#7 done first | ⏳ |

The one command that closes #5:

```bash
python scripts/demo/run_demo.py --task all --cohort offline --chain live --nonce 4
```

`frontend/data/deployment.json` is already written by the deploy script, so the panel is already
reading live 10143 records with no further edit.

---

## 5. Defects found and fixed during self-check

### Found by the Node DOM harness (`render app.js` against a stub document)

1. **The panel showed every historical run.** `LedgerWriter` published the frontend feed from
   the whole append-only ledger, so a second run rendered 9 records instead of 3. The feed is
   now scoped to the writer's own session; `ledger.jsonl` still keeps the full audit history,
   and the feed reports both counts. Regression test added.
2. **Records carried an empty `chain` block,** so the panel could not label a record's chain
   status. The dry-run receipt is now embedded in each published record, which also makes every
   ledger line self-describing. Regression test added.

### Found only by actually sending transactions

These were invisible to every offline test; the live run surfaced each one in turn:

3. **`resolve_cohort_addresses()` was called but never defined.** The live path would die with a
   `NameError` the moment it tried to map cohort members to addresses. Replaced by the full
   three-source `resolve_cohort_identities()` (per-member keys → declared addresses → seed
   derivation), with refusal on partial config, duplicate addresses, and size mismatch.
4. **The demo ignored `--chain live`.** `scripts/demo/run_demo.py` constructed a `LedgerWriter`
   unconditionally, so the flag parsed fine and did nothing — a silent lie. Now routed through
   `make_chain_writer(settings)`.
5. **`openCohortValidation` reverted on the freshly deployed mock.** `MockIdentityRegistry` owns
   no agents, so `_requireAgentOperator` failed before a single verdict could be written. Added
   `contracts/scripts/register-agent.js` (`npm run register:agent`), which registers `agentId 1`
   to the deployer and is idempotent.
6. **`web3.exceptions.MismatchedABI` on `attestCohortVerdict`.** The relayed-verdict arguments
   were assembled by splicing the signer address into a positional list and put it one slot early.
   Rebuilt as an explicit named tuple; the registry then accepted the relayed verdict.
7. **The panel's `eth_getLogs` was refused with `413 Request Entity Too Large`** by the public
   RPC on a wide range. Replaced the single wide query with a windowed scan (50 blocks, 6
   concurrent, `MAX_LOG_CHUNKS` cap), and `deploy.js` now emits `fromBlock` + `logChunkSize` into
   `frontend/data/deployment.json` so nothing is hardcoded.
8. **`Web3RPCError: Signer had insufficient balance` mid-demo.** Root cause: `_send()` hardcoded
   `gas: 3_000_000`, and Monad bills the full limit (confirmed `gasUsed == gasLimit == 3M` on every
   confirmed tx). Nine calls burned 2.75 MON and the run stranded. `_send()` now estimates gas,
   adds 20% headroom, and runs a balance pre-flight that raises a typed `ConfigError` before
   broadcasting. Measured cost drops from `0.306 MON/call` to `0.0527 / 0.0279 / 0.0066`.

---

## 6. How to reproduce everything in one pass

```bash
# Python
pip install -r requirements.txt
pytest tests/ -q                                                      # 231 passed
python scripts/demo/run_demo.py --cohort offline --chain dry-run --no-color

# Contracts
cd contracts && npm install && npm test && cd ..                      # 37 passing
cd contracts && npm run verify:deployed && cd ..                      # frozen constants read back

# Panel
node tests/panel_render_harness.mjs                                   # 12/12 checks
cd frontend && python -m http.server 8080                             # open :8080

# Network (no credential needed)
python scripts/verify_deployment.py --address 0x4479D63b5780e5DBa95feEB057Ed57B8E20b7053 \
    --rpc https://testnet-rpc.monad.xyz
python .tmp/chain_state.py                                            # enumerate live records
```
