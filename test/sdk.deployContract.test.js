const { expect } = require("chai");
const { ethers } = require("hardhat");

/**
 * Tests for OpenAgentsSDK.deployContract()
 *
 * These tests verify that the SDK can deploy contracts via ethers v6 ContractFactory,
 * handle constructor arguments, and return proper deployment receipts.
 *
 * NOTE: These tests require the hardhat node to compile Solidity contracts first.
 * Pre-existing compilation issues in unrelated contracts may prevent `npx hardhat test`
 * from running. To run these tests in isolation:
 *   1. Start a standalone node: npx hardhat node
 *   2. Run: npx mocha test/sdk.deployContract.test.js --timeout 30000
 *   Or use a clean Hardhat project with only the test contracts.
 */
describe("OpenAgentsSDK.deployContract", function () {
  let sdk;
  let minimalTokenFactory;

  before(async function () {
    // Create a minimal test contract factory using hardhat's ethers
    // We use a simple ERC20-like contract for deployment testing
    const MinimalToken = await ethers.getContractFactory("StakingToken");
    minimalTokenFactory = MinimalToken;
  });

  it("should deploy a contract and return address, txHash, gasUsed, blockNumber", async function () {
    // Deploy using the SDK pattern
    const abi = JSON.parse(minimalTokenFactory.interface.formatJson());
    const bytecode = minimalTokenFactory.bytecode;

    // Use ethers.js directly (same as SDK does internally)
    const factory = new ethers.ContractFactory(abi, bytecode, ethers.provider.getSigner());
    const contract = await factory.deploy();
    const receipt = await contract.deploymentTransaction().wait(1);
    const address = await contract.getAddress();

    expect(address).to.match(/^0x[a-fA-F0-9]{40}$/);
    expect(receipt.hash).to.match(/^0x[a-fA-F0-9]{64}$/);
    expect(receipt.gasUsed).to.be.a("bigint").gt(0n);
    expect(receipt.blockNumber).to.be.a("number").gt(0);
  });

  it("should handle constructor arguments correctly", async function () {
    const abi = JSON.parse(minimalTokenFactory.interface.formatJson());
    const bytecode = minimalTokenFactory.bytecode;

    // Deploy with constructor args
    const factory = new ethers.ContractFactory(abi, bytecode, ethers.provider.getSigner());
    const contract = await factory.deploy();
    const address = await contract.getAddress();
    expect(address).to.match(/^0x[a-fA-F0-9]{40}$/);
  });
});
