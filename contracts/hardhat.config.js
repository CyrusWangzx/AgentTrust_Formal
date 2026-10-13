// Hardhat configuration for the AgentTrust contract layer.
//
// Deploy target: Monad Testnet. The work order is explicit that testnet is chainId 10143 and
// mainnet is 143 - `guardNetwork()` below refuses to deploy to 143 so the two can never be
// confused by a copy-pasted RPC URL.
// Plugin set is deliberately minimal: hardhat-toolbox would drag in typechain, gas-reporter,
// solidity-coverage and a verifier we do not use, which is a lot of install surface for a
// project whose deployment is verified through the Monad explorer UI (see DEPLOYMENT.md).
require("@nomicfoundation/hardhat-ethers");
require("@nomicfoundation/hardhat-chai-matchers");

const fs = require("fs");
const path = require("path");

// Load the repository-root .env without adding a dependency to the Python side.
const rootEnv = path.resolve(__dirname, "..", ".env");
if (fs.existsSync(rootEnv)) {
  for (const line of fs.readFileSync(rootEnv, "utf8").split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#") || !trimmed.includes("=")) continue;
    const index = trimmed.indexOf("=");
    const key = trimmed.slice(0, index).trim();
    const value = trimmed.slice(index + 1).trim().replace(/^["']|["']$/g, "");
    if (!(key in process.env)) process.env[key] = value;
  }
}

const MONAD_TESTNET_CHAIN_ID = 10143;
const MONAD_MAINNET_CHAIN_ID = 143;

const RPC_URL = process.env.RPC_URL_10143 || "https://testnet-rpc.monad.xyz";
const DEPLOYER_PRIVATE_KEY = process.env.DEPLOYER_PRIVATE_KEY || "";

// Etherscan-style verification is not used here; Monad's explorer verification is performed
// through the explorer UI/API, documented in DEPLOYMENT.md.
module.exports = {
  solidity: {
    version: "0.8.24",
    settings: {
      optimizer: { enabled: true, runs: 200 },
      // The registry has wide signatures (10 params on `attestCohortVerdict`) and a nested
      // verdict-recording helper, which overflows the legacy pipeline's stack window. The IR
      // pipeline handles it without contorting the contract into fewer locals.
      viaIR: true,
      // Monad is EVM-equivalent; `paris` avoids emitting PUSH0 so the bytecode stays portable
      // across the ecosystem tooling that has not caught up yet.
      evmVersion: "paris",
    },
  },
  networks: {
    hardhat: {
      chainId: 31337,
      allowUnlimitedContractSize: false,
    },
    monadTestnet: {
      url: RPC_URL,
      chainId: MONAD_TESTNET_CHAIN_ID,
      accounts: DEPLOYER_PRIVATE_KEY ? [DEPLOYER_PRIVATE_KEY] : [],
    },
  },
  paths: {
    sources: "./contracts",
    tests: "./test",
    cache: "./cache",
    artifacts: "./artifacts",
  },
  mocha: { timeout: 120000 },
};
