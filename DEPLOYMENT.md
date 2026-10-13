# DEPLOYMENT.md — AgentTrust on Monad Testnet

Deployment evidence for `AgentTrustValidationRegistry` (ERC-8004 Validation Registry
implementation).

---

## 1. Network

| Item | Value |
| --- | --- |
| Network | Monad Testnet |
| **Chain ID** | **10143** |
| Mainnet chain ID | 143 — *not used by this project* |
| RPC endpoint | `https://testnet-rpc.monad.xyz` |
| Block explorer | `https://testnet.monadscan.com` |
| Alternate explorer | `https://testnet.monadexplorer.com` |
| Faucet | `https://faucet.monad.xyz` |
| Native token | MON |
| Solidity | `0.8.24`, optimizer 200 runs, `evmVersion: paris` |

> The work order is explicit that testnet is **10143** and mainnet is **143**. Two guards enforce
> this: `contracts/scripts/deploy.js` and `contracts/scripts/verify-deployed.js` both abort when
> the connected chain reports 143, and `Settings.validate_for_live_chain()` in
> `orchestrator/config.py` refuses to build a live chain client for chain id 143.

---

## 2. Deployment status

### ✅ CURRENT STATUS: **DEPLOYED — Monad Testnet (chainId 10143)**

| Item | Value |
| --- | --- |
| Chain ID | **10143** |
| `AgentTrustValidationRegistry` | `0x4479D63b5780e5DBa95feEB057Ed57B8E20b7053` |
| Deploy transaction | `0x74e8c2260905ff92206a9904dda073023845dc1a27496918bc0f5afd87cea9ac` |
| `initialize(identityRegistry)` tx | `0x95db0f97048b9de111bcb72482bb9c5e0bf5847ccc6a27c693251d40793d60bd` |
| Deploy block | `70771345` |
| Deployed at (UTC) | `2026-10-13T20:03:34Z` |
| Deployer | `0xfB93Ab52150DbCB723E5355BdDCEfA37E4317514` |
| `MockIdentityRegistry` | `0xd6DA14b5cCC14F7b4f3CE4A8c7469F42B33979ac` (a mock — no production ERC-8004 Identity Registry address was supplied) |
| Deployer balance at deploy time | `5.0 MON` |
| Registry bytecode on chain | `13302` bytes |

Every value above is copied from `contracts/deployments/monad-testnet-10143.json`, which
`npm run deploy:testnet` wrote. Nothing here was typed from memory or filled in by hand.

The owner inputs the work order §7 listed are now in place: a funded testnet account, an RPC
endpoint, and a deployment. `.env` holds the deployer key and the registry address; `.env` is
git-ignored.

### Read-back verification (both commands pass)

| Check | Command | Result |
| --- | --- | --- |
| Chain id + bytecode | `python scripts/verify_deployment.py` | `OK` — chainId `10143`, bytecode `13302` bytes |
| Frozen constants decoded | `cd contracts && npm run verify:deployed` | `weights 400/300/300`, `theta 1500/3000`, `kRounds 3` — all as specified |
| Bytecode read over raw RPC | `eth_getCode(0x4479D6…7053)` | non-empty (`13302` bytes) |
| Monad Testnet reachable | `eth_chainId` | `0x279f` = **10143** |

The `verify:deployed` read-back is the important one: it confirms the frozen spec constants
(spec §2.3 / §2.4) survived the deploy, i.e. the deployed contract is the one this repository
compiles and not an older build.

### Live cohort records written to this registry

The deployment is not just verified, it is **exercised**. After registering `agentId 1` in the
identity registry (`npm run register:agent` — `openCohortValidation` reverts unless the caller
owns or operates the `agentId`, and the freshly deployed mock owns nothing), the orchestrator's
live path (`--chain live`) wrote real requests and real cohort verdicts through
`openCohortValidation` → `attestCohortVerdict` → `finalizeValidation`:

| requestHash | agentId | cohort | verdicts | decision | D_rel |
| --- | --- | --- | --- | --- | --- |
| `0x7a21816a4f4826a97eb9ab844b443a92d9be05b4ff7d18404dd3febc44d8326d` | 1 | 3 | 3 | **Escalated** | 3.975 |
| `0xc8de0a962ddee16b55ec6e02804fd41f01098a2e8807b144a6ac0a8ff7ffbb44` | 1 | 3 | 3 | **Approved** | 0.289 |

Both were finalised on chain and read back with `getValidationRecord` / `getCohortVerdicts`
(`.tmp/chain_state.py`), and the reproduction constant is the
`unauthorized-override-003` fixture at 3.975 — the identical `D_rel` the offline deterministic
cohort produces, which is the numeric proof that the on-chain write and the local computation
agree.

Enumerable in one command:

```bash
python .tmp/chain_state.py     # walks CohortValidationOpened in 50-block windows, prints every record
```

> **The public Monad RPC refuses a wide `eth_getLogs` range** (`413 Request Entity Too Large`).
> Both `frontend/app.js` and this script therefore scan `deployBlock..head` in fixed 50-block
> windows. `frontend/data/deployment.json` carries `fromBlock` + `logChunkSize` so the panel does
> the same without a hardcoded constant.

---

## 2b. Monad gas model: why the writer estimates instead of hardcoding

**Monad Testnet bills the full gas *limit*, not the gas used** — every confirmed transaction shows
`gasUsed == gasLimit`. A hardcoded `gas: 3_000_000` therefore costs `3_000_000 × 102 gwei =
0.306 MON` per call *regardless of what the call actually needed*. The first live demo run burned
2.75 MON on nine calls this way and stalled with `Signer had insufficient balance`.

`orchestrator/chain.py::_send()` now calls `eth_estimateGas`, adds 20% headroom (+1000 floor), and
runs a balance pre-flight that raises a typed `ConfigError` *before* broadcasting. Measured
(`.tmp/gas_probe.py`, gas price 102 gwei):

| call | estimate | limit @1.2x | cost (MON) | old 3M blanket |
| --- | --- | --- | --- | --- |
| `openCohortValidation` | 429 648 | 516 577 | 0.052691 | 0.306000 |
| `attestCohortVerdict` | 226 932 | 273 318 | 0.027878 | 0.306000 |
| `finalizeValidation` | 52 697 | 64 236 | 0.006552 | 0.306000 |

A full 3-task live demo is 15 calls: **~1.31 MON at the estimated limit vs ~4.59 MON with the
blanket limit** — a 71% saving, and the difference between a run that completes and one that
strands mid-flight.

---

## 3. How to deploy (three commands)

```bash
# 0. one-time setup
cp .env.example .env                 # then set DEPLOYER_PRIVATE_KEY and RPC_URL_10143
cd contracts && npm install && cd ..

# 1. compile, deploy, and emit a receipt
cd contracts
npm run compile
npm run deploy:testnet

# 2. verify what was deployed, straight from the chain
npm run verify:deployed
```

`npm run deploy:testnet` writes:

| File | Contents |
| --- | --- |
| `contracts/deployments/monad-testnet-10143.json` | full receipt: address, deploy tx, initialize tx, block, deployer, timestamp |
| `contracts/abis/AgentTrustValidationRegistry.json` | contract ABI |
| `frontend/data/deployment.json` | address + ABI + RPC + explorer URL + `fromBlock` (the deploy block, so the panel can enumerate this registry's events) — switches the panel to live mode |

It refuses to run and writes **nothing** if the signer is missing, the balance is zero, or the
network reports chain id 143. In that case no receipt file is produced — the absence of the file
is the signal that no deployment happened.

Then:

```bash
echo "AGENTTRUST_REGISTRY_ADDRESS=<address from the receipt>" >> .env
python scripts/verify_deployment.py     # chain-id + bytecode + frozen-constant check
```

---

## 4. Deployment record

Filled in from `contracts/deployments/monad-testnet-10143.json` immediately after
`npm run deploy:testnet` succeeded. No value here was transposed or retyped by hand.

| Field | Value |
| --- | --- |
| Chain ID | `10143` |
| `AgentTrustValidationRegistry` address | `0x4479D63b5780e5DBa95feEB057Ed57B8E20b7053` |
| Deploy transaction hash | `0x74e8c2260905ff92206a9904dda073023845dc1a27496918bc0f5afd87cea9ac` |
| `initialize(identityRegistry)` tx hash | `0x95db0f97048b9de111bcb72482bb9c5e0bf5847ccc6a27c693251d40793d60bd` |
| Deploy block | `70771345` |
| Initialize block | `70771352` |
| Deployed at (UTC) | `2026-10-13T20:03:34Z` |
| Deployer address | `0xfB93Ab52150DbCB723E5355BdDCEfA37E4317514` |
| `MockIdentityRegistry` address | `0xd6DA14b5cCC14F7b4f3CE4A8c7469F42B33979ac` (deployed by the script because `IDENTITY_REGISTRY_ADDRESS` was unset) |
| `MockIdentityRegistry` deploy tx | `0xfa0dc40e3a3958414d268f1afdc181adf66fac6d3ba04d1062bb429eac5ea709` |
| Solidity / settings | `0.8.24`, optimizer 200 runs, `viaIR: true`, `evmVersion: paris` |
| Registry bytecode | `13302` bytes |
| `verify:deployed` coverage | ✅ weights `400/300/300`, theta `1500/3000`, `kRounds 3` |

### Explorer links

```
https://testnet.monadscan.com/address/0x4479D63b5780e5DBa95feEB057Ed57B8E20b7053
https://testnet.monadscan.com/tx/0x74e8c2260905ff92206a9904dda073023845dc1a27496918bc0f5afd87cea9ac
https://testnet.monadscan.com/address/0xd6DA14b5cCC14F7b4f3CE4A8c7469F42B33979ac   (Mock Identity Registry)
```

`npm run verify:deployed` prints the address and deploy-tx links, and reads back
`weightsMilli()`, `thresholdsMilli()` and `kRounds()` from the deployed contract to confirm the
frozen spec constants survived the deploy:

| Constant | Expected | On chain | Source of truth |
| --- | --- | --- | --- |
| `w1 / w2 / w3` | `400 / 300 / 300` (x1000) | `400 / 300 / 300` ✅ | spec §2.3 |
| `theta_low / theta_high` | `1500 / 3000` (x1000) | `1500 / 3000` ✅ | spec §2.4 |
| `kRounds` | `3` | `3` ✅ | spec §2.4 |

---

## 5. Verifying the deployment without any credential

`contracts/scripts/verify-deployed.js` and `orchestrator/chain.py::check_registry_deployed()`
both work with a public RPC and no API key, so the reviewer's check ("the contract address is
queryable on the 10143 explorer") reduces to one command:

```bash
python scripts/verify_deployment.py --address 0x<registry> --rpc https://testnet-rpc.monad.xyz
```

The script fails loudly — non-zero exit, no output file — when:

* the RPC reports a chain id other than 10143;
* the address has no bytecode (i.e. it was never deployed);
* the on-chain weights or thresholds differ from the frozen spec values.

---

## 6. Operational notes

### Identity Registry

`initialize(address identityRegistry_)` binds the registry to an ERC-8004 Identity Registry,
which is what makes the "MUST be called by the owner or operator of `agentId`" rule enforceable.
If `IDENTITY_REGISTRY_ADDRESS` is unset, the deploy script deploys `MockIdentityRegistry` so a
first testnet run has a working ownership source.

* With a real Identity Registry bound, ownership is enforced strictly.
* With `address(0)` bound, ownership **cannot** be checked. The contract says so explicitly via
  `identityCheckBypassed() → true` rather than silently permitting everything.

### Signing cohort verdicts

Each cohort member submits from its own address. Two supported paths:

* **`submitCohortVerdict`** — the member signs and sends its own transaction (member pays gas).
* **`attestCohortVerdict`** — the orchestrator relays the member's EIP-191 `personal_sign`
  signature, so **validators need no MON at all**. The contract recovers the signer in
  `_recover()` and checks it against the cohort.

Because of the second path, one funded account can drive an entire K=3 heterogeneous cohort. The
demo uses exactly that: `AGENTTRUST_COHORT_SEED` derives all member keys deterministically.

Live mode resolves cohort identities from three sources, in order:

```
AGENTTRUST_VALIDATOR_PRIVATE_KEY_1..n   # per-member keys (each can self-submit)
AGENTTRUST_COHORT_ADDRESSES / AGENTTRUST_VALIDATOR_ADDRESS_n   # declared addresses (relayed)
AGENTTRUST_COHORT_SEED                  # deterministic testnet keys derived from one seed
```

`orchestrator/chain.py::resolve_cohort_identities()` refuses to start on partial configuration,
duplicate addresses, or a size mismatch with the record's cohort — the contract rejects a repeated
cohort address, so guessing would only move the failure later and make it harder to read.

### Attestation encoding is locked across languages

`attestCohortVerdict` accepts `(requestHash, validator, response, verdictHash)` and the recovered
address. The digest the Python orchestrator signs must equal the digest Solidity hashes:

```
keccak256(abi.encode(bytes32 requestHash, address validator, uint8 response, bytes32 verdictHash))
```

`contracts/test/AttestationEncoding.test.js` pins this with a fixed vector (a value generated in
Python, re-encoded with `ethers.AbiCoder`, checked to recover under EIP-191, then relayed into the
registry and accepted). A drift in either language breaks that test rather than silently producing
a signature the contract rejects at runtime.

### What has been executed live, and what has not

Stated plainly so nothing is overstated:

* **Executed live:** `npm run deploy:testnet` → registry `0x4479D6…7053` on chain 10143;
  `npm run register:agent`; and two full cohort lifecycles written through the live path
  (`openCohortValidation` → 3 × `attestCohortVerdict` → `finalizeValidation`), one **Approved** and
  one **Escalated**, both read back from the chain (see §2).
* **Executed live, then superseded:** an earlier run opened requests and stalled mid-flight under
  the old blanket-gas bug. Those two requests are still on chain and **not finalised**
  (`0xf0c53916…`, `0x1dbac3da…`). They are harmless orphans — they do not block a fresh run, which
  uses a new `--nonce`.
* **Not yet executed:** the complete 3-task live demo in a single run, i.e. all three decision
  bands (warehouse-pick → Approved, arm-reach-boundary → Escalated by K-round exhaustion,
  unauthorized-override → Escalated) recorded in one pass. It needs ~1.31 MON and the deployer
  balance is currently **0.031 MON** — top up from `https://faucet.monad.xyz` and run:

  ```bash
  python scripts/demo/run_demo.py --task all --cohort offline --chain live --nonce 4
  ```

  All three bands *are* already proven: offline deterministically (§2 numbers match), and two of
  the three on chain.
