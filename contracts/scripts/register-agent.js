// Registers the demo agent id in the ERC-8004 Identity Registry, so that
// `AgentTrustValidationRegistry.openCohortValidation` can enforce the standard's
// "MUST be called by the owner or operator of agentId" rule.
//
// Why this is a separate step: the deploy script only deploys the Mock Identity Registry when
// no production one is configured. A freshly deployed mock has `nextAgentId == 1` and owns
// nothing, so `ownerOf(1)` reverts with "unknown agent" and every cohort request is rejected
// before a single verdict is recorded. Registering one agent makes the registry usable.
//
// Idempotent: if the requested agent id is already owned by the deployer it exits 0 without
// sending anything.
//
// Usage:
//   npm run register:agent                    # registers agentId 1 (the demo's agent)
//   AGENTTRUST_AGENT_ID=7 npm run register:agent

const fs = require("fs");
const path = require("path");

const IDENTITY_ABI = [
  "function nextAgentId() view returns (uint256)",
  "function ownerOf(uint256) view returns (address)",
  "function register(address to, string agentURI) returns (uint256)",
  "function agentURIOf(uint256) view returns (string)",
];

async function main() {
  const hre = require("hardhat");
  const { ethers } = hre;
  const chainId = Number((await hre.ethers.provider.getNetwork()).chainId);
  if (chainId === 143) {
    throw new Error("refusing to run against Monad mainnet (143): this project is testnet-only");
  }

  const [signer] = await ethers.getSigners();
  if (!signer) {
    throw new Error("no signer: set DEPLOYER_PRIVATE_KEY (and RPC_URL_10143) before running this");
  }

  // The identity registry address comes from .env, or from the deploy receipt.
  const receiptPath = path.join(__dirname, "..", "deployments", `monad-testnet-${chainId}.json`);
  const receipt = fs.existsSync(receiptPath)
    ? JSON.parse(fs.readFileSync(receiptPath, "utf8"))
    : null;
  const identityAddress = process.env.IDENTITY_REGISTRY_ADDRESS || receipt?.identityRegistryAddress;
  if (!identityAddress) {
    throw new Error(
      "no identity registry address: set IDENTITY_REGISTRY_ADDRESS or deploy first " +
        "(npm run deploy:testnet)"
    );
  }

  const agentId = BigInt(process.env.AGENTTRUST_AGENT_ID || "1");
  const identity = new ethers.Contract(identityAddress, IDENTITY_ABI, signer);

  console.log(`network  : monadTestnet (chainId ${chainId})`);
  console.log(`signer   : ${signer.address}`);
  console.log(`identity : ${identityAddress}`);
  console.log(`agentId  : ${agentId}`);

  let owner = null;
  try {
    owner = await identity.ownerOf(agentId);
  } catch {
    owner = null; // not registered yet - that is the normal first-run state
  }

  if (owner && owner.toLowerCase() === signer.address.toLowerCase()) {
    console.log("\nalready registered to the signer - nothing to do");
    console.log(`explorer : ${explorer(chainId, identityAddress)}`);
    return;
  }
  if (owner) {
    throw new Error(
      `agent ${agentId} is owned by ${owner}, not by ${signer.address}. ` +
        "Registering it again is not possible: agent ids are sequential. Set " +
        "AGENTTRUST_AGENT_ID to a free id, or use a signer that owns it."
    );
  }

  const next = await identity.nextAgentId();
  if (BigInt(next) !== agentId) {
    console.log(
      `\nnote     : the next id this registry will mint is ${next}, not ${agentId}. ` +
        `The id you get back is the one to put in task payloads.`
    );
  }

  const tx = await identity.register(signer.address, `agenttrust://demo-agent/${agentId}`);
  const rc = await tx.wait();
  const minted = await identity.ownerOf(agentId);

  console.log("\nregistered");
  console.log(`  agentId : ${agentId}`);
  console.log(`  owner   : ${minted}`);
  console.log(`  tx      : ${tx.hash}`);
  console.log(`  block   : ${rc.blockNumber}`);
  console.log(`  explorer: ${explorer(chainId, tx.hash, "tx")}`);
}

function explorer(chainId, value, kind = "address") {
  const base = process.env.EXPLORER_URL_10143 || "https://testnet.monadscan.com";
  return `${base.replace(/\/$/, "")}/${kind}/${value}`;
}

main().catch((error) => {
  console.error(`\n${error.message}`);
  process.exitCode = 1;
});
