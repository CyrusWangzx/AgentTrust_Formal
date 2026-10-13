# Demo video script — screen recording (≤ 3:00)

**Deliverable D9 (demo half).** Work order §6.

For the owner to record. Written so it goes down in one take: every shot names the screen
region, the action, the duration and the on-screen subtitle, and states the expected screen
state you must see before moving on. If a shot does not look the way the "Expected state"
column says, stop and check the pre-flight list rather than continuing.

* **Total runtime:** 3:00 (180 s).
* **Sample task:** `unauthorized-override-003` — an arm plan that writes a controller
  parameter outside the agent's granted scope, so the divergence is large and the band is
  unambiguous on camera.
* **Cohort:** `live` — Qwen 3.8 Max (DashScope) and Kimi (Moonshot), the real heterogeneous
  cohort. If either credential is unavailable on the day, use the fallback in §4, keep the
  `offline-deterministic` label visible on screen, and say so in the narration.
* **Chain:** `live` — Monad Testnet 10143.

---

## 1. Pre-flight (do this once, before recording)

| # | Check | Command / action | Must see |
| --- | --- | --- | --- |
| 1 | Registry deployed | `cat contracts/deployments/monad-testnet-10143.json` | an `registryAddress` and `deployTxHash` |
| 2 | Panel points at it | `cat frontend/data/deployment.json` | same `registryAddress`, plus `fromBlock` |
| 3 | Chain reachable | `curl -s https://testnet-rpc.monad.xyz -H 'content-type: application/json' -d '{"jsonrpc":"2.0","method":"eth_chainId","params":[],"id":1}'` | `"result":"0x279f"` (= 10143) |
| 4 | Contracts verify | `cd contracts && npm run verify:deployed` | `weightsMilli 400/300/300`, `thresholds 1500/3000`, `kRounds 3` |
| 5 | Credentials present | `grep -c . <(grep -E 'DASHSCOPE_API_KEY=\S|MOONSHOT_API_KEY=\S' .env)` | `2` |
| 6 | Cohort addresses set | `grep AGENTTRUST_COHORT_ADDRESSES .env` | 5 distinct `0x…` addresses |
| 7 | Wallet funded | `python scripts/verify_deployment.py` | non-zero exit must **not** appear |
| 8 | Panel served | `cd frontend && python -m http.server 8080` | `http://localhost:8080` loads |
| 9 | Browser is clean | close other tabs, notifications off, zoom 110 % | — |
| 10 | Terminal font | 16 pt or larger, window 1600 × 900 | command text legible on a phone |
| 11 | Fresh request id | `python scripts/demo/run_demo.py --task unauthorized-override-003 --nonce 1 --cohort live --chain live` | **run this as the pre-flight, not the take** — see note below |

> **Why the pre-flight run is not wasteful — and why it needs `--nonce`.**
> `openCohortValidation` reverts with `RequestAlreadyExists` when the same `requestHash` is
> submitted twice, and the id is deterministic (`keccak256` of the canonical request payload).
> So the take must use a **different nonce** than the pre-flight run: pre-flight `--nonce 1`,
> on-camera `--nonce 2`. `--nonce` is mixed into the request payload, so the on-camera run gets
> a fresh id and the registry accepts it. Raise it again for each re-record.
>
> The pre-flight run also warms everything up: model credentials, RPC, and the registry.
> The panel feed is scoped to the current run, so the pre-flight does not pollute the panel.

---

## 2. Storyboard

All subtitles are English, ≤ 9 words per line, lower-third, safe area 10 % from the bottom.

| # | Time | Dur | Screen region | Action | Expected state | Subtitle |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 0:00–0:12 | 12 s | Full frame — terminal, repo root | Type nothing. Show `git log --oneline -5` then the tree. | Plain terminal, repo name visible | **An AI agent is about to act. Nobody checked its plan.** |
| 2 | 0:12–0:30 | 18 s | Browser — panel header, top-right | Click **Connect wallet**. Approve in the wallet popup if asked; switch to Monad Testnet if prompted. | Badge turns green: `Monad Testnet 10143`; wallet line shows your `0x…` and *"never asks your wallet to sign"* | **First, prove which chain you are looking at.** |
| 3 | 0:30–0:45 | 15 s | Terminal — top 1/3 | Type and run the on-camera command (below). | First line: `request unauthorized-override-003  validationId=0x…`, then `cohort: live (5 members, K=3)` | **Submit the plan for verification — before it runs.** |
| 4 | 0:45–1:15 | 30 s | Terminal — middle | Let it scroll. Do not scroll manually. | Five `[ok ]` verdict lines appear, one per validator, each with `response=` and `ms`. Latency differs per member. | **Five independent rehearsals, five different models and frameworks.** |
| 5 | 1:15–1:40 | 25 s | Terminal — the scored line | Stop when the metrics line lands. Zoom 120 % on it. | `D_disc=… D_traj=… D_end=… -> D_total=… D_base=… D_rel=… <Decision>` then `Kendall W=… chi2=… significant=True` | **Their disagreement becomes one number: D_rel.** |
| 6 | 1:40–2:00 | 20 s | Terminal — decision + summary table | Let the `decision` line and the `summary` table print. | `decision Escalated  D_rel above theta_high with a significant Kendall W`, then the 1-row summary table | **Past the threshold, the task stops and a human decides.** |
| 7 | 2:00–2:25 | 25 s | Browser — panel, records area | Switch to the browser tab, click **Refresh**. Scroll slowly to the metrics row and the band bar. | One record card: `unauthorized-override-003`, decision badge, `D_disc/D_traj/D_end/D_total/D_base/D_rel/Kendall W`, and the bar with band edges at 1.5 and 3.0 | **The same verdict, read back from the chain.** |
| 8 | 2:25–2:50 | 25 s | Terminal → Browser (explorer) | Copy the tx hash from the terminal `chain LIVE tx 0x…` line. Open `https://testnet.monadscan.com/tx/<hash>` (or the `Explorer` line the deploy script printed). | Explorer shows **Success**, block number, and the `ValidationFinalized` event | **And written on-chain — verifiable by anyone.** |
| 9 | 2:50–3:00 | 10 s | Full frame — end card | Static card. | AgentTrust logo, one line, repo URL | **AgentTrust — rehearsal before execution.** |

**The on-camera command:**

```bash
python scripts/demo/run_demo.py --task unauthorized-override-003 --cohort live --chain live --nonce 2
```

Run it from the repository root with the virtualenv active, in a terminal at ≥ 16 pt.

---

## 3. What each shot proves (so nothing is overclaimed)

* Shot 2 proves the panel is reading chainId **10143**, and that connecting a wallet is
  optional: the page is a verifier, so it reads over public RPC and never asks for a signature.
* Shot 4 proves heterogeneity is real: five members, two model families, four vendor
  endpoints, five prompting frameworks (spec §2.5). The panel's "Cohort heterogeneity"
  section, visible in shot 7, is where that declaration is printed.
* Shot 5 proves the metric is computed, not asserted: the numbers come from the divergence
  library, and the aggregation `0.4·D_disc + 0.3·D_traj + 0.3·D_end` is on screen in the
  panel's Mechanism box.
* Shot 8 is the acceptance item: the address and the transaction must be queryable on the
  10143 explorer. If the explorer is slow, keep the tab open and let the shot run long — do
  not cut to a cached screenshot.

---

## 4. Fallback plan (no model credentials on the day)

If `DASHSCOPE_API_KEY` or `MOONSHOT_API_KEY` is unavailable, record shots 1–3 and 4–9 with the
offline cohort instead:

```bash
python scripts/demo/run_demo.py --task unauthorized-override-003 --cohort offline --chain live --nonce 2
```

* Shot 4 will show three `offline-*` verdicts instead of five model verdicts.
* The startup block prints, in amber: *"offline fixtures are not model outputs…"* — **leave it
  on screen and read it in the narration.** The whole point of that label is that the
  repository never passes a fixture off as a model.
* Shot 7's panel will show the panel's SIMULATED banner for the local feed; use the live
  registry read instead by keeping `frontend/data/deployment.json` in place, so shot 7 still
  reads from the chain.
* Say plainly in the narration: *"the divergence math is live; the five-model cohort needs
  provider credentials we did not use in this recording."*

**The registry is deployed**, so shots 7 and 8 have real material to show. Point the panel at
`frontend/data/deployment.json` (already written by the deploy script) and it reads live records
from chain 10143. Two finalised records are already on chain to cut against:

```
0x7a21816a…   Escalated   D_rel 3.975   (matches unauthorized-override-003 offline)
0xc8de0a96…   Approved    D_rel 0.289   (matches warehouse-pick-001 offline)
```

If you want the *freshly recorded* run on screen rather than the earlier ones, the deployer needs
about 1.4 MON and then:

```bash
python scripts/demo/run_demo.py --task all --cohort offline --chain live --nonce 4
```

Do not show a fabricated explorer page under any circumstance. If the balance is empty at
recording time, record shots 1–6 plus a chain read of the two existing records, and say on screen
that the third band's on-chain pass is pending a faucet top-up — that is the honest state.

---

## 5. Post-recording self-check

- [ ] Runtime ≤ 3:00 and every shot from §2 appears, in order.
- [ ] The `validationId` shown in shot 3 matches the record in shot 7.
- [ ] The tx hash in shot 8 is the one the terminal printed, unedited.
- [ ] No fabricated number appears anywhere in the video.
- [ ] If the offline fallback was used, the "not model outputs" label is visible on screen.
- [ ] Subtitles match the narration word for word.
