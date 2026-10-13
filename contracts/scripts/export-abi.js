// Export the compiled ABIs the Python chain client and the frontend panel both consume.
//
//   npx hardhat run scripts/export-abi.js
//
// Writes:
//   contracts/abis/AgentTrustValidationRegistry.json
//   contracts/abis/MockIdentityRegistry.json
//   frontend/data/abi.json

const fs = require("fs");
const path = require("path");
const hre = require("hardhat");

const REPO_ROOT = path.resolve(__dirname, "..", "..");

async function main() {
  const abiDir = path.join(__dirname, "..", "abis");
  fs.mkdirSync(abiDir, { recursive: true });

  const combined = {};
  for (const name of ["AgentTrustValidationRegistry", "MockIdentityRegistry"]) {
    const artifact = await hre.artifacts.readArtifact(name);
    fs.writeFileSync(path.join(abiDir, `${name}.json`), JSON.stringify(artifact.abi, null, 2));
    combined[name] = artifact.abi;
    console.log(`wrote ${path.join(abiDir, `${name}.json`)}`);
  }

  const frontendData = path.join(REPO_ROOT, "frontend", "data");
  fs.mkdirSync(frontendData, { recursive: true });
  fs.writeFileSync(path.join(frontendData, "abi.json"), JSON.stringify(combined, null, 2));
  console.log(`wrote ${path.join(frontendData, "abi.json")}`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
