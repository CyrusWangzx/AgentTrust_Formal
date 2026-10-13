// AgentTrust contract-layer tests.
//
// Two things are being proven here:
//   1. the ERC-8004 Validation Registry surface behaves as the specification says;
//   2. the frozen AgentTrust constants (w = 0.4/0.3/0.3, theta = 1.5/3.0) are byte-identical
//      to the off-chain Python values, and `finalizeValidation` really does re-derive the
//      decision instead of trusting the caller.

const { expect } = require("chai");
const { ethers } = require("hardhat");

const DECISION = {
  NONE: 0,
  APPROVED: 1,
  REJECTED: 2,
  ESCALATED: 3,
  INSUFFICIENT_VALIDATORS: 4,
  INSUFFICIENT_BASELINE: 5,
};

const MILLI = 1000;

function divergence({
  dDisc = 0,
  dTraj = 0,
  dEnd = 0,
  dTotal = 0,
  dRel = 0,
  w = 0,
  chiSquare = 0,
} = {}) {
  return { dDiscMilli: dDisc, dTrajMilli: dTraj, dEndMilli: dEnd, dTotalMilli: dTotal, dRelMilli: dRel, kendallWMilli: w, chiSquareMilli: chiSquare };
}

async function deployRegistry() {
  const identity = await (await ethers.getContractFactory("MockIdentityRegistry")).deploy();
  await identity.waitForDeployment();
  const registry = await (await ethers.getContractFactory("AgentTrustValidationRegistry")).deploy();
  await registry.waitForDeployment();
  await registry.initialize(await identity.getAddress());
  return { registry, identity };
}

describe("DivergenceLib - on-chain mirror of the frozen spec constants", function () {
  let harness;

  before(async function () {
    harness = await (await ethers.getContractFactory("DivergenceLibHarness")).deploy();
    await harness.waitForDeployment();
  });

  it("publishes w = (0.4, 0.3, 0.3) and theta = (1.5, 3.0) as spec 2.3/2.4 require", async function () {
    const c = await harness.constants();
    expect(c.w1).to.equal(400);
    expect(c.w2).to.equal(300);
    expect(c.w3).to.equal(300);
    expect(c.thetaLow).to.equal(1500);
    expect(c.thetaHigh).to.equal(3000);
  });

  it("total() matches 0.4*D_disc + 0.3*D_traj + 0.3*D_end", async function () {
    expect(await harness.total(1000, 0, 0)).to.equal(400);
    expect(await harness.total(0, 2000, 0)).to.equal(600);
    expect(await harness.total(0, 0, 5000)).to.equal(1500);
    expect(await harness.total(250, 250, 250)).to.equal(250);
  });

  it("total() agrees with float arithmetic across a sweep of inputs", async function () {
    // Parity check against the off-chain Python/JS computation. The contract rounds to the
    // nearest milli; the tolerance is exactly half a milli unit.
    const samples = [];
    for (const d of [0, 1, 7, 125, 999, 1000, 1500, 3000, 9999, 40000]) {
      for (const t of [0, 3, 250, 1000, 2750, 12000]) {
        for (const e of [0, 1, 500, 1000, 7777]) samples.push([d, t, e]);
      }
    }
    for (const [d, t, e] of samples) {
      const expected = Math.round(0.4 * (d / 1000) * 1000 + 0.3 * (t / 1000) * 1000 + 0.3 * (e / 1000) * 1000);
      const actual = Number(await harness.total(d, t, e));
      expect(Math.abs(actual - expected)).to.be.at.most(1);
    }
  });

  it("relative() divides by D_base and reverts on a zero baseline", async function () {
    expect(await harness.relative(3000, 1500)).to.equal(2000);
    await expect(harness.relative(1000, 0)).to.be.revertedWithCustomError(
      harness,
      "InvalidDBase"
    );
  });

  it("band() follows the inclusive lower edge of the spec", async function () {
    expect(await harness.band(1499)).to.equal(0);
    expect(await harness.band(1500)).to.equal(0); // 1.5 -> approved
    expect(await harness.band(1501)).to.equal(1);
    expect(await harness.band(3000)).to.equal(1); // 3.0 -> rehearsal band
    expect(await harness.band(3001)).to.equal(2);
  });

  it("decide() maps bands onto terminal decisions", async function () {
    expect(await harness.decide(1500, false)).to.equal(DECISION.APPROVED);
    // A mid-band reading only reaches finalize() after K rounds were spent -> human.
    expect(await harness.decide(2000, false)).to.equal(DECISION.ESCALATED);
    expect(await harness.decide(5000, false)).to.equal(DECISION.REJECTED);
    expect(await harness.decide(5000, true)).to.equal(DECISION.ESCALATED);
  });

  it("chi2CriticalMilli() matches the Python alpha=0.05 table", async function () {
    expect(await harness.chi2CriticalMilli(1)).to.equal(3841);
    expect(await harness.chi2CriticalMilli(3)).to.equal(7815);
    expect(await harness.chi2CriticalMilli(12)).to.equal(21026);
    await expect(harness.chi2CriticalMilli(13)).to.be.revertedWithCustomError(
      harness,
      "DegreesOfFreedomOutOfRange"
    );
  });
});

describe("AgentTrustValidationRegistry - ERC-8004 surface", function () {
  let registry, identity, owner, agentOwner, validator, other;

  beforeEach(async function () {
    [owner, agentOwner, validator, other] = await ethers.getSigners();
    ({ registry, identity } = await deployRegistry());
  });

  it("exposes the bound identity registry", async function () {
    expect(await registry.getIdentityRegistry()).to.equal(await identity.getAddress());
  });

  it("supports the standard single-validator request/response cycle", async function () {
    await identity.register(agentOwner.address, "ipfs://agent");
    const requestHash = ethers.keccak256(ethers.toUtf8Bytes("req-standard"));

    await expect(
      registry.connect(agentOwner).validationRequest(validator.address, 1, "ipfs://payload", requestHash)
    )
      .to.emit(registry, "ValidationRequest")
      .withArgs(validator.address, 1, "ipfs://payload", requestHash);

    await expect(
      registry.connect(validator).validationResponse(requestHash, 92, "ipfs://evidence", ethers.ZeroHash, "soft")
    )
      .to.emit(registry, "ValidationResponse")
      .withArgs(validator.address, 1, requestHash, 92, "ipfs://evidence", ethers.ZeroHash, "soft");

    const status = await registry.getValidationStatus(requestHash);
    expect(status.validatorAddress).to.equal(validator.address);
    expect(status.agentId).to.equal(1);
    expect(status.response).to.equal(92);
    expect(status.tag).to.equal("soft");
  });

  it("rejects a request from a non-operator of the agent", async function () {
    await identity.register(agentOwner.address, "ipfs://agent");
    const requestHash = ethers.keccak256(ethers.toUtf8Bytes("req-foreign"));
    await expect(
      registry.connect(other).validationRequest(validator.address, 1, "ipfs://payload", requestHash)
    ).to.be.revertedWithCustomError(registry, "InvalidAgentOperator");
  });

  it("rejects a response from anyone but the named validator", async function () {
    await identity.register(agentOwner.address, "ipfs://agent");
    const requestHash = ethers.keccak256(ethers.toUtf8Bytes("req-impersonate"));
    await registry.connect(agentOwner).validationRequest(validator.address, 1, "ipfs://payload", requestHash);
    await expect(
      registry.connect(other).validationResponse(requestHash, 10, "", ethers.ZeroHash, "")
    ).to.be.revertedWithCustomError(registry, "NotACohortMember");
  });

  it("caps the response at 100", async function () {
    await identity.register(agentOwner.address, "ipfs://agent");
    const requestHash = ethers.keccak256(ethers.toUtf8Bytes("req-range"));
    await registry.connect(agentOwner).validationRequest(validator.address, 1, "ipfs://payload", requestHash);
    await expect(
      registry.connect(validator).validationResponse(requestHash, 101, "", ethers.ZeroHash, "")
    ).to.be.revertedWithCustomError(registry, "ResponseOutOfRange");
  });

  it("aggregates responses through getSummary with tag filtering", async function () {
    await identity.register(agentOwner.address, "ipfs://agent");
    const h1 = ethers.keccak256(ethers.toUtf8Bytes("agg-1"));
    const h2 = ethers.keccak256(ethers.toUtf8Bytes("agg-2"));
    await registry.connect(agentOwner).validationRequest(validator.address, 1, "u", h1);
    await registry.connect(agentOwner).validationRequest(validator.address, 1, "u", h2);
    await registry.connect(validator).validationResponse(h1, 80, "", ethers.ZeroHash, "soft");
    await registry.connect(validator).validationResponse(h2, 100, "", ethers.ZeroHash, "hard");

    let summary = await registry.getSummary(1, [], "");
    expect(summary.count).to.equal(2);
    expect(summary.averageResponse).to.equal(90);

    summary = await registry.getSummary(1, [], "hard");
    expect(summary.count).to.equal(1);
    expect(summary.averageResponse).to.equal(100);

    summary = await registry.getSummary(1, [validator.address], "");
    expect(summary.count).to.equal(2);
  });
});

describe("AgentTrustValidationRegistry - cohort path", function () {
  const requestHash = () => ethers.keccak256(ethers.toUtf8Bytes("cohort-request"));

  let registry, identity, owner, agentOwner, cohort, outsider;

  beforeEach(async function () {
    const signers = await ethers.getSigners();
    [owner, agentOwner, outsider] = signers;
    cohort = signers.slice(3, 6); // 3 heterogeneous validation agents
    ({ registry, identity } = await deployRegistry());
    await identity.register(agentOwner.address, "ipfs://agent");
  });

  async function openCohort({ dBase = 500, kRounds = 3, members = null } = {}) {
    const hash = requestHash();
    await registry
      .connect(agentOwner)
      .openCohortValidation(hash, 1, "ipfs://task", dBase, kRounds, (members || cohort).map((s) => s.address));
    return hash;
  }

  async function vote(hash, signer, response, tag = "soft") {
    return registry
      .connect(signer)
      .submitCohortVerdict(hash, response, ethers.keccak256(ethers.toUtf8Bytes(signer.address)), "ipfs://v", tag, 100, 200, 300);
  }

  it("opens a cohort request and names every member", async function () {
    const hash = requestHash();
    await expect(
      registry.connect(agentOwner).openCohortValidation(hash, 1, "ipfs://task", 500, 3, cohort.map((s) => s.address))
    )
      .to.emit(registry, "CohortValidationOpened")
      .withArgs(hash, 1, agentOwner.address, 3, 3, 500, "ipfs://task");

    const members = await registry.getCohort(hash);
    expect(members.map((m) => m.toLowerCase())).to.deep.equal(cohort.map((s) => s.address.toLowerCase()));
  });

  it("enforces the cohort size range", async function () {
    await expect(openCohort({ members: [cohort[0]] })).to.be.revertedWithCustomError(
      registry,
      "CohortSizeOutOfRange"
    );
    const six = (await ethers.getSigners()).slice(10, 16);
    await expect(openCohort({ members: six })).to.be.revertedWithCustomError(
      registry,
      "CohortSizeOutOfRange"
    );
  });

  it("rejects duplicate cohort members", async function () {
    await expect(openCohort({ members: [cohort[0], cohort[0], cohort[1]] })).to.be.revertedWithCustomError(
      registry,
      "DuplicateCohortMember"
    );
  });

  it("only lets cohort members vote, once each", async function () {
    const hash = await openCohort();
    await expect(vote(hash, outsider, 50)).to.be.revertedWithCustomError(registry, "NotACohortMember");
    await vote(hash, cohort[0], 90);
    await expect(vote(hash, cohort[0], 90)).to.be.revertedWithCustomError(registry, "AlreadyVoted");
  });

  it("emits the standard ERC-8004 ValidationResponse for each cohort verdict", async function () {
    const hash = await openCohort();
    await expect(vote(hash, cohort[0], 88))
      .to.emit(registry, "ValidationResponse")
      .and.to.emit(registry, "VerdictRecorded");
  });

  it("accepts a relayed verdict carrying the member's EIP-191 signature", async function () {
    const hash = await openCohort();
    const response = 77;
    const verdictHash = ethers.keccak256(ethers.toUtf8Bytes("relayed"));
    const digest = ethers.keccak256(
      ethers.AbiCoder.defaultAbiCoder().encode(
        ["bytes32", "address", "uint8", "bytes32"],
        [hash, cohort[0].address, response, verdictHash]
      )
    );
    const signature = await cohort[0].signMessage(ethers.getBytes(digest));

    await registry
      .connect(outsider)
      .attestCohortVerdict(hash, cohort[0].address, response, verdictHash, "ipfs://v", "soft", 1, 2, 3, signature);

    const verdicts = await registry.getCohortVerdicts(hash);
    expect(verdicts.length).to.equal(1);
    expect(verdicts[0].validator).to.equal(cohort[0].address);
    expect(verdicts[0].response).to.equal(77);
  });

  it("refuses to finalise while the cohort is incomplete and K rounds are unspent", async function () {
    const hash = await openCohort();
    await vote(hash, cohort[0], 90);
    await expect(
      registry.connect(owner).finalizeValidation(hash, DECISION.APPROVED, 1, 4, divergence({ dRel: 500 }))
    ).to.be.revertedWithCustomError(registry, "IncompleteCohort");
  });

  describe("decision verification", function () {
    it("accepts an Approved claim inside the theta_low band", async function () {
      const hash = await openCohort();
      for (const member of cohort) await vote(hash, member, 95);
      await expect(
        registry
          .connect(owner)
          .finalizeValidation(hash, DECISION.APPROVED, 1, 4, divergence({ dDisc: 100, dTraj: 50, dEnd: 50, dTotal: 80, dRel: 160, w: 900, chiSquare: 5200 }))
      )
        .to.emit(registry, "ValidationFinalized")
        .withArgs(hash, 1, DECISION.APPROVED, 1, 4);
      expect(await registry.decisionOf(hash)).to.equal(DECISION.APPROVED);
    });

    it("reverts when the claimed decision contradicts D_rel", async function () {
      const hash = await openCohort();
      for (const member of cohort) await vote(hash, member, 95);
      await expect(
        registry
          .connect(owner)
          .finalizeValidation(hash, DECISION.APPROVED, 1, 4, divergence({ dRel: 9000 }))
      ).to.be.revertedWithCustomError(registry, "DecisionMismatch");
    });

    it("routes a mid-band reading to a human", async function () {
      const hash = await openCohort();
      for (const member of cohort) await vote(hash, member, 60);
      await registry
        .connect(owner)
        .finalizeValidation(hash, DECISION.ESCALATED, 3, 4, divergence({ dRel: 2400 }));
      expect(await registry.decisionOf(hash)).to.equal(DECISION.ESCALATED);
    });

    it("decides Rejected vs Escalated from its own chi-square lookup, not the caller's flag", async function () {
      // chiSquare 5000 is below the df=3 critical value (7815) -> not significant -> Rejected.
      let hash = await openCohort();
      for (const member of cohort) await vote(hash, member, 40);
      await registry
        .connect(owner)
        .finalizeValidation(hash, DECISION.REJECTED, 1, 4, divergence({ dRel: 5000, w: 300, chiSquare: 5000 }));
      expect(await registry.decisionOf(hash)).to.equal(DECISION.REJECTED);

      // Same D_rel, but chiSquare 9000 > 7815 -> significant -> Escalated.
      const hash2 = ethers.keccak256(ethers.toUtf8Bytes("cohort-request-2"));
      await registry
        .connect(agentOwner)
        .openCohortValidation(hash2, 1, "ipfs://task", 500, 3, cohort.map((s) => s.address));
      for (const member of cohort) await vote(hash2, member, 40);
      await registry
        .connect(owner)
        .finalizeValidation(hash2, DECISION.ESCALATED, 1, 4, divergence({ dRel: 5000, w: 900, chiSquare: 9000 }));
      expect(await registry.decisionOf(hash2)).to.equal(DECISION.ESCALATED);
    });

    it("fails closed with InsufficientValidators below the cohort floor", async function () {
      // A 3-member cohort with only 1 verdict: K rounds must be spent to finalise at all.
      const hash = await openCohort();
      await vote(hash, cohort[0], 10);
      await expect(
        registry
          .connect(owner)
          .finalizeValidation(hash, DECISION.APPROVED, 3, 4, divergence({ dRel: 100 }))
      ).to.be.revertedWithCustomError(registry, "DecisionMismatch");

      await registry
        .connect(owner)
        .finalizeValidation(hash, DECISION.INSUFFICIENT_VALIDATORS, 3, 4, divergence({}));
      expect(await registry.decisionOf(hash)).to.equal(DECISION.INSUFFICIENT_VALIDATORS);
    });

    it("fails closed with InsufficientBaseline when D_base is zero", async function () {
      const hash = await openCohort({ dBase: 0 });
      for (const member of cohort) await vote(hash, member, 70);
      await registry
        .connect(owner)
        .finalizeValidation(hash, DECISION.INSUFFICIENT_BASELINE, 1, 4, divergence({}));
      expect(await registry.decisionOf(hash)).to.equal(DECISION.INSUFFICIENT_BASELINE);
    });

    it("refuses a second finalisation", async function () {
      const hash = await openCohort();
      for (const member of cohort) await vote(hash, member, 95);
      await registry.connect(owner).finalizeValidation(hash, DECISION.APPROVED, 1, 4, divergence({ dRel: 100 }));
      await expect(
        registry.connect(owner).finalizeValidation(hash, DECISION.APPROVED, 1, 4, divergence({ dRel: 100 }))
      ).to.be.revertedWithCustomError(registry, "AlreadyFinalized");
    });

    it("restricts finalisation to the requester or a granted orchestrator", async function () {
      const hash = await openCohort();
      for (const member of cohort) await vote(hash, member, 95);
      await expect(
        registry.connect(outsider).finalizeValidation(hash, DECISION.APPROVED, 1, 4, divergence({ dRel: 100 }))
      ).to.be.revertedWithCustomError(registry, "NotRequesterOrOrchestrator");

      await registry.connect(owner).setOrchestrator(outsider.address, true);
      await registry.connect(outsider).finalizeValidation(hash, DECISION.APPROVED, 1, 4, divergence({ dRel: 100 }));
      expect(await registry.decisionOf(hash)).to.equal(DECISION.APPROVED);
    });

    it("rejects a verdict after finalisation", async function () {
      const hash = await openCohort();
      for (const member of cohort) await vote(hash, member, 95);
      await registry.connect(owner).finalizeValidation(hash, DECISION.APPROVED, 1, 4, divergence({ dRel: 100 }));
      await expect(vote(hash, cohort[0], 50)).to.be.revertedWithCustomError(registry, "AlreadyFinalized");
    });

    it("rejects an out-of-range rankedObjects", async function () {
      const hash = await openCohort();
      for (const member of cohort) await vote(hash, member, 95);
      await expect(
        registry.connect(owner).finalizeValidation(hash, DECISION.APPROVED, 1, 99, divergence({ dRel: 100 }))
      ).to.be.revertedWithCustomError(registry, "RankedObjectsOutOfRange");
    });
  });

  it("exposes the frozen formula on-chain for the panel", async function () {
    const [w1, w2, w3] = await registry.weightsMilli();
    const [low, high] = await registry.thresholdsMilli();
    expect([w1, w2, w3]).to.deep.equal([400n, 300n, 300n]);
    expect([low, high]).to.deep.equal([1500n, 3000n]);
  });

  it("resolves getValidationStatus from the newest cohort verdict", async function () {
    const hash = await openCohort();
    await vote(hash, cohort[0], 61, "soft");
    await vote(hash, cohort[1], 88, "hard");
    const status = await registry.getValidationStatus(hash);
    expect(status.validatorAddress).to.equal(cohort[1].address);
    expect(status.response).to.equal(88);
    expect(status.tag).to.equal("hard");
  });

  it("reports identity-check bypass when no identity registry is bound", async function () {
    const bare = await (await ethers.getContractFactory("AgentTrustValidationRegistry")).deploy();
    await bare.waitForDeployment();
    await bare.initialize(ethers.ZeroAddress);
    expect(await bare.identityCheckBypassed()).to.equal(true);
    expect(await bare.getIdentityRegistry()).to.equal(ethers.ZeroAddress);
  });
});
