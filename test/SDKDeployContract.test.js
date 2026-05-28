const { ethers } = require("hardhat");

describe("Contract Deployment (SDK deployContract verification)", function () {
  let signer;

  before(async function () {
    [signer] = await ethers.getSigners();
  });

  it("should deploy a minimal contract and return address", async function () {
    // Deploy a simple contract — InterestRateModel takes constructor args
    const Factory = await ethers.getContractFactory("InterestRateModel");
    const contract = await Factory.deploy(500000000000000000n, 100000000000000000n, 1000000000000000000n, 800000000000000000n);
    const tx = contract.deploymentTransaction();
    const receipt = await tx.wait();

    const address = await contract.getAddress();
    expect(address).to.match(/^0x[a-fA-F0-9]{40}$/);
    expect(receipt.from).to.equal(signer.address);
    expect(receipt.gasUsed).to.be.a("bigint");
    expect(receipt.gasUsed).to.be.gt(0n);
    expect(receipt.blockNumber).to.be.a("number").that.is.gt(0);

    // Verify deployed contract works
    expect(await contract.baseRate()).to.equal(500000000000000000n);
    expect(await contract.admin()).to.equal(signer.address);
  });

  it("should deploy with constructor args correctly encoded", async function () {
    const Factory = await ethers.getContractFactory("InterestRateModel");
    const contract = await Factory.deploy(
      100000000000000000n,  // baseRate
      200000000000000000n,  // multiplier
      3000000000000000000n, // jumpMultiplier
      900000000000000000n   // kink (90%)
    );

    expect(await contract.baseRate()).to.equal(100000000000000000n);
    expect(await contract.multiplier()).to.equal(200000000000000000n);
    expect(await contract.jumpMultiplier()).to.equal(3000000000000000000n);
    expect(await contract.kink()).to.equal(900000000000000000n);
  });

  it("should wait for configurable confirmations", async function () {
    const Factory = await ethers.getContractFactory("InterestRateModel");
    const contract = await Factory.deploy(500000000000000000n, 100000000000000000n, 1000000000000000000n, 800000000000000000n);
    const tx = contract.deploymentTransaction();

    // Wait with 1 confirmation
    const receipt = await tx.wait(1);
    expect(receipt.blockNumber).to.be.gt(0);
    expect(receipt.gasUsed).to.be.gt(0n);
  });

  it("should include full deployment metadata in receipt", async function () {
    const Factory = await ethers.getContractFactory("InterestRateModel");
    const contract = await Factory.deploy(500000000000000000n, 100000000000000000n, 1000000000000000000n, 800000000000000000n);
    const tx = contract.deploymentTransaction();
    const receipt = await tx.wait(1);

    expect(receipt).to.have.property("hash", tx.hash);
    expect(receipt).to.have.property("blockNumber");
    expect(receipt).to.have.property("gasUsed");
    expect(receipt).to.have.property("contractAddress");
    expect(receipt.contractAddress).to.equal(await contract.getAddress());
  });
});
