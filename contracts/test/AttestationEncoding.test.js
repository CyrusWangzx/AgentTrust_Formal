// Cross-language encoding lock for the relayed-verdict attestation.
//
// The one thing that can silently disagree between the Python orchestrator and the Solidity
// registry is the ABI encoding of the attestation digest. A mismatch is invisible off chain and
// only shows up as a reverted `attestCohortVerdict` on a live network - which is exactly how it
// would be discovered during a recording. These tests pin it down.
//
// The fixture values are produced by `orchestrator/chain.py`:
//
//   key        = derive_cohort_key("agenttrust-attestation-fixture", 1)
//   digest     = verdict_attestation_digest(requestHash, address, 66, verdictHash)
//   signature  = sign_verdict_attestation(requestHash, address, 66, verdictHash, key)
//
// `keccak256(abi.encode(requestHash, validator, response, verdictHash))` is recomputed here
// with ethers' ABI coder; if either side ever changes, this fails.

const { expect } = require("chai");
const { ethers } = require("hardhat");

const REQUEST_HASH = "0x" + "11".repeat(32);
const VERDICT_HASH = "0x" + "22".repeat(32);
const RESPONSE = 66;
const MEMBER = "0xe136E882DEa32113F60A190a78F19A93Bc2297D4";
const PY_DIGEST = "0x4f646467622b802cf8a880b3abbe94670d09bc30fb90c39de412a05328209cd3";
const PY_SIGNATURE =
  "0x5d62c1b55a1d9e570025777ff279c9e2103e448159d20f92eca54a7483986f920121e8db51d94314dc8766a038dd4be1d5ca69b8aaa3159c4b8ddeaee02d299d1c";

describe("attestation encoding (Python <-> Solidity)", function () {
  it("agrees on keccak256(abi.encode(requestHash, validator, response, verdictHash))", function () {
    const encoded = ethers.AbiCoder.defaultAbiCoder().encode(
      ["bytes32", "address", "uint8", "bytes32"],
      [REQUEST_HASH, MEMBER, RESPONSE, VERDICT_HASH]
    );
    expect(ethers.keccak256(encoded)).to.equal(PY_DIGEST);
  });

  it("produces a signature that recovers to the cohort member under EIP-191", function () {
    expect(ethers.verifyMessage(ethers.getBytes(PY_DIGEST), PY_SIGNATURE)).to.equal(
      ethers.getAddress(MEMBER)
    );
  });

  it("is accepted by the registry as a relayed verdict", async function () {
    const Registry = await ethers.getContractFactory("AgentTrustValidationRegistry");
    const registry = await Registry.deploy();
    await registry.waitForDeployment();
    const identity = await (await ethers.getContractFactory("MockIdentityRegistry")).deploy();

    const [requester] = await ethers.getSigners();
    const agentId = 1n;
    await (await identity.register(requester.address, "agenttrust://test")).wait();
    await (await registry.initialize(await identity.getAddress())).wait();

    // MIN_COHORT_SIZE is 2, so a one-member cohort is not a valid request.
    const filler = ethers.Wallet.createRandom().address;
    await (
      await registry.openCohortValidation(
        REQUEST_HASH, agentId, "fixture task", 350, 1, [MEMBER, filler]
      )
    ).wait();

    // The member never sends a transaction - the requester relays its signature. This is the
    // property that lets validation agents run without gas.
    await (
      await registry.attestCohortVerdict(
        REQUEST_HASH,
        MEMBER,
        RESPONSE,
        VERDICT_HASH,
        "offline://fixture",
        "soft",
        5000,
        6000,
        2271,
        PY_SIGNATURE
      )
    ).wait();

    const verdicts = await registry.getCohortVerdicts(REQUEST_HASH);
    expect(verdicts.length).to.equal(1);
    expect(verdicts[0].validator).to.equal(ethers.getAddress(MEMBER));
    expect(verdicts[0].response).to.equal(RESPONSE);
    expect(verdicts[0].verdictHash).to.equal(VERDICT_HASH);
  });

  it("rejects a signature that belongs to a validator outside the cohort", async function () {
    const Registry = await ethers.getContractFactory("AgentTrustValidationRegistry");
    const registry = await Registry.deploy();
    await registry.waitForDeployment();
    const identity = await (await ethers.getContractFactory("MockIdentityRegistry")).deploy();

    const [requester] = await ethers.getSigners();
    await (await identity.register(requester.address, "agenttrust://test")).wait();
    await (await registry.initialize(await identity.getAddress())).wait();

    const a = ethers.Wallet.createRandom().address;
    const b = ethers.Wallet.createRandom().address;
    await (
      await registry.openCohortValidation(REQUEST_HASH, 1n, "fixture task", 350, 1, [a, b])
    ).wait();

    await expect(
      registry.attestCohortVerdict(
        REQUEST_HASH,
        MEMBER, // not a declared cohort member
        RESPONSE,
        VERDICT_HASH,
        "offline://fixture",
        "soft",
        5000,
        6000,
        2271,
        PY_SIGNATURE
      )
    ).to.be.reverted;
  });
});
