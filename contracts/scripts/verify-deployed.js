// Verify that the registry recorded in DEPLOYMENT.md really is deployed on Monad Testnet.
//
//   npx hardhat run scripts/verify-deployed.js --network monadTestnet
//
// Reads AGENTTRUST_REGISTRY_ADDRESS (or contracts/deployments/monad-testnet-10143.json) and
// checks: chain id is 10143, the address has bytecode, and the frozen constants read back
// from the contract match spec 2.3 / 2.4. Fails loudly rather than printing a guess.

const fs = require("fs");
const path = require("path");
const hre = require("hardhat");

const MONAD_TESTNET_CHAIN_ID = 10143;
const MONAD_MAINNET_CHAIN_ID = 143;

function readReceipt() {
  const file = path.join(__dirname, "..", "deployments", `monad-testnet-${MONAD_TESTNET_CHAIN_ID}.json`);
  if (!fs.existsSync(file)) return null;
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

async function main() {
  const network = await hre.ethers.provider.getNetwork();
  const chainId = Number(network.chainId);

  console.log(`network  : ${network.name} (chainId ${chainId})`);
  if (chainId !== MONAD_TESTNET_CHAIN_ID) {
    throw new Error(
      chainId === MONAD_MAINNET_CHAIN_ID
        ? "refusing to verify against Monad mainnet (143); the work order requires testnet 10143"
        : `unexpected chainId ${chainId}; expected ${MONAD_TESTNET_CHAIN_ID}`
    );
  }

  const receipt = readReceipt();
  const address = process.env.AGENTTRUST_REGISTRY_ADDRESS || receipt?.registryAddress;
  if (!address) {
    throw new Error(
      "no registry address: set AGENTTRUST_REGISTRY_ADDRESS or run scripts/deploy.js first"
    );
  }

  const code = await hre.ethers.provider.getCode(address);
  const deployed = code && code !== "0x";
  console.log(`registry : ${address}`);
  console.log(`bytecode : ${deployed ? `${(code.length - 2) / 2} bytes` : "NONE (not deployed)"}`);
  if (!deployed) {
    throw new Error(`no contract bytecode at ${address} on chainId ${chainId}`);
  }

  const registry = await hre.ethers.getContractAt("AgentTrustValidationRegistry", address);
  const [w1, w2, w3] = await registry.weightsMilli();
  const [thetaLow, thetaHigh] = await registry.thresholdsMilli();
  const kRounds = await registry.kRounds();
  const identityRegistry = await registry.getIdentityRegistry();

  console.log(`identity : ${identityRegistry}`);
  console.log(`kRounds  : ${kRounds}`);
  console.log(`weights  : ${w1}/${w2}/${w3} (expect 400/300/300)`);
  console.log(`theta    : ${thetaLow}/${thetaHigh} (expect 1500/3000)`);

  const problems = [];
  if (Number(w1) !== 400 || Number(w2) !== 300 || Number(w3) !== 300) {
    problems.push("aggregation weights do not match spec 2.3");
  }
  if (Number(thetaLow) !== 1500 || Number(thetaHigh) !== 3000) {
    problems.push("decision thresholds do not match spec 2.4");
  }
  if (problems.length) throw new Error("verification failed:\n  - " + problems.join("\n  - "));

  const explorerTx = receipt?.deployExplorerUrl || "";
  console.log("\nOK - deployed and constants verified");
  if (explorerTx) console.log(`deploy tx : ${explorerTx}`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
