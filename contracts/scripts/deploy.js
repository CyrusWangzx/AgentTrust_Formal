// Deploy AgentTrustValidationRegistry (ERC-8004 Validation Registry implementation) to
// Monad Testnet, then emit a machine-readable receipt that DEPLOYMENT.md and the frontend read.
//
//   npx hardhat run scripts/deploy.js --network monadTestnet
//
// Required env (see .env.example):
//   RPC_URL_10143               Monad Testnet RPC
//   DEPLOYER_PRIVATE_KEY        funded testnet key, never committed
//   IDENTITY_REGISTRY_ADDRESS   optional; falls back to deploying MockIdentityRegistry
//
// The script never writes a placeholder address: if the deployment does not happen, no
// receipt is produced (quality redline 1).

const fs = require("fs");
const path = require("path");
const hre = require("hardhat");

const MONAD_TESTNET_CHAIN_ID = 10143;
const MONAD_MAINNET_CHAIN_ID = 143;
const REPO_ROOT = path.resolve(__dirname, "..", "..");

function explorerTx(chainId, hash) {
  const base =
    chainId === MONAD_TESTNET_CHAIN_ID
      ? process.env.EXPLORER_URL_10143 || "https://testnet.monadscan.com"
      : "";
  return base ? `${base.replace(/\/$/, "")}/tx/${hash}` : "";
}

function explorerAddress(chainId, address) {
  const base =
    chainId === MONAD_TESTNET_CHAIN_ID
      ? process.env.EXPLORER_URL_10143 || "https://testnet.monadscan.com"
      : "";
  return base ? `${base.replace(/\/$/, "")}/address/${address}` : "";
}

async function main() {
  const network = await hre.ethers.provider.getNetwork();
  const chainId = Number(network.chainId);

  if (chainId === MONAD_MAINNET_CHAIN_ID) {
    throw new Error(
      "refusing to deploy to Monad mainnet (143). The work order requires Monad Testnet (10143)."
    );
  }

  const [deployer] = await hre.ethers.getSigners();
  if (!deployer) {
    throw new Error(
      "no signer: set DEPLOYER_PRIVATE_KEY (and RPC_URL_10143) before deploying to Monad Testnet"
    );
  }

  const balance = await hre.ethers.provider.getBalance(deployer.address);
  console.log(`network            : ${network.name} (chainId ${chainId})`);
  console.log(`deployer           : ${deployer.address}`);
  console.log(`deployer balance   : ${hre.ethers.formatEther(balance)} MON`);
  if (balance === 0n) {
    throw new Error(
      "deployer has zero balance: get testnet MON from the faucet (https://faucet.monad.xyz)"
    );
  }

  // ---------------------------------------------------------------- identity registry
  let identityAddress = process.env.IDENTITY_REGISTRY_ADDRESS || "";
  let identityTxHash = null;
  if (!identityAddress) {
    console.log("\nno IDENTITY_REGISTRY_ADDRESS set: deploying MockIdentityRegistry");
    const Mock = await hre.ethers.getContractFactory("MockIdentityRegistry");
    const mock = await Mock.deploy();
    await mock.waitForDeployment();
    identityAddress = await mock.getAddress();
    identityTxHash = mock.deploymentTransaction().hash;
    console.log(`MockIdentityRegistry : ${identityAddress}`);
  } else {
    console.log(`\nusing existing Identity Registry: ${identityAddress}`);
  }

  // ---------------------------------------------------------------- validation registry
  console.log("\ndeploying AgentTrustValidationRegistry ...");
  const Factory = await hre.ethers.getContractFactory("AgentTrustValidationRegistry");
  const registry = await Factory.deploy();
  await registry.waitForDeployment();
  const registryAddress = await registry.getAddress();
  const deployTxHash = registry.deploymentTransaction().hash;
  console.log(`AgentTrustValidationRegistry : ${registryAddress}`);

  console.log("\ninitialize(identityRegistry) ...");
  const initTx = await registry.initialize(identityAddress);
  const initReceipt = await initTx.wait();

  // The panel enumerates this registry's `CohortValidationOpened` events, so it needs to know
  // how far back to look. Anything earlier than the deploy block belongs to some other contract
  // at the same address (or to nothing at all).
  let deployBlock = registry.deploymentTransaction().blockNumber;
  if (deployBlock === null || deployBlock === undefined) {
    deployBlock = (await registry.deploymentTransaction().wait()).blockNumber;
  }

  const receipt = {
    project: "AgentTrust",
    contract: "AgentTrustValidationRegistry",
    standard: "ERC-8004 Validation Registry",
    network: {
      name: "Monad Testnet",
      chainId,
      rpcUrl: hre.network.config.url,
    },
    deployer: deployer.address,
    registryAddress,
    registryExplorerUrl: explorerAddress(chainId, registryAddress),
    deployBlock,
    deployTxHash,
    deployExplorerUrl: explorerTx(chainId, deployTxHash),
    initializeTxHash: initTx.hash,
    initializeExplorerUrl: explorerTx(chainId, initTx.hash),
    initializeBlock: initReceipt.blockNumber,
    identityRegistryAddress: identityAddress,
    identityRegistryTxHash: identityTxHash,
    identityRegistryIsMock: !process.env.IDENTITY_REGISTRY_ADDRESS,
    deployedAt: new Date().toISOString(),
    solidity: "0.8.24",
  };

  const outDir = path.join(__dirname, "..", "deployments");
  fs.mkdirSync(outDir, { recursive: true });
  const outFile = path.join(outDir, `monad-testnet-${chainId}.json`);
  fs.writeFileSync(outFile, JSON.stringify(receipt, null, 2));
  console.log(`\nreceipt written to ${outFile}`);

  // Publish the ABI + address where the Python chain client and the frontend expect them.
  const abiDir = path.join(__dirname, "..", "abis");
  fs.mkdirSync(abiDir, { recursive: true });
  const artifact = await hre.artifacts.readArtifact("AgentTrustValidationRegistry");
  fs.writeFileSync(
    path.join(abiDir, "AgentTrustValidationRegistry.json"),
    JSON.stringify(artifact.abi, null, 2)
  );
  const frontendDir = path.join(REPO_ROOT, "frontend", "data");
  fs.mkdirSync(frontendDir, { recursive: true });
  fs.writeFileSync(
    path.join(frontendDir, "deployment.json"),
    JSON.stringify(
      {
        chainId,
        rpcUrl: hre.network.config.url,
        explorerUrl: process.env.EXPLORER_URL_10143 || "https://testnet.monadscan.com",
        registryAddress,
        deployTxHash,
        fromBlock: deployBlock,
        // The public Monad RPC refuses a wide `eth_getLogs` range (413), so the panel scans the
        // deploy-block-to-head range in windows of this size. Verified working at 50.
        logChunkSize: 50,
        deployedAt: receipt.deployedAt,
        abi: artifact.abi,
      },
      null,
      2
    )
  );

  console.log("\n---------------------------------------------");
  console.log(`  Registry : ${registryAddress}`);
  console.log(`  Tx       : ${deployTxHash}`);
  console.log(`  Explorer : ${receipt.registryExplorerUrl}`);
  console.log("---------------------------------------------");
  console.log("\nnext: append this address to DEPLOYMENT.md and to .env as AGENTTRUST_REGISTRY_ADDRESS");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
