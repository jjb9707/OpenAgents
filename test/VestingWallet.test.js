const { expect } = require("chai");
const { ethers } = require("hardhat");

describe("VestingWallet - migrateToken", function () {
  let owner, beneficiary;
  let tokenA, tokenB;
  let vestingWallet;
  let MockERC20;
  const totalAllocation = ethers.parseEther("10000");

  beforeEach(async function () {
    [owner, beneficiary] = await ethers.getSigners();

    const block = await ethers.provider.getBlock("latest");
    const now = block.timestamp;

    // Start goes now, cliff at +100, vesting at +1000
    const start = now + 10;
    const cliffDuration = 100;
    const vestingDuration = 1000;

    MockERC20 = await ethers.getContractFactory("MockERC20");
    tokenA = await MockERC20.deploy("TokenA", "TKA");
    tokenB = await MockERC20.deploy("TokenB", "TKB");

    const VestingWallet = await ethers.getContractFactory("VestingWallet", owner);
    vestingWallet = await VestingWallet.deploy(
      beneficiary.address,
      tokenA.target,
      start,
      cliffDuration,
      vestingDuration,
      totalAllocation,
      true
    );
    await vestingWallet.waitForDeployment();

    await tokenA.mint(vestingWallet.target, totalAllocation);
    await tokenB.mint(vestingWallet.target, totalAllocation);

    // Store vesting params for test access
    this.start = start;
    this.cliffDuration = cliffDuration;
    this.vestingDuration = vestingDuration;
  });

  it("should allow owner to migrate to new token", async function () {
    await expect(vestingWallet.connect(owner).migrateToken(tokenB.target))
      .to.emit(vestingWallet, "TokenMigrated")
      .withArgs(tokenA.target, tokenB.target, totalAllocation);

    const newToken = await vestingWallet.token();
    expect(newToken).to.equal(tokenB.target);
  });

  it("should reject migration from non-owner", async function () {
    await expect(
      vestingWallet.connect(beneficiary).migrateToken(tokenB.target)
    ).to.be.revertedWith("Vesting: not owner");
  });

  it("should reject migration to zero address", async function () {
    await expect(
      vestingWallet.connect(owner).migrateToken("0x0000000000000000000000000000000000000000")
    ).to.be.revertedWith("Vesting: zero address");
  });

  it("should reject migration to the same token", async function () {
    await expect(
      vestingWallet.connect(owner).migrateToken(tokenA.target)
    ).to.be.revertedWith("Vesting: same token");
  });

  it("should reject migration when new token has insufficient balance", async function () {
    const tinyAmount = ethers.parseEther("1");
    const tokenC = await MockERC20.deploy("TokenC", "TKC");
    await tokenC.mint(vestingWallet.target, tinyAmount);

    await expect(
      vestingWallet.connect(owner).migrateToken(tokenC.target)
    ).to.be.revertedWith("Vesting: insufficient new token balance");
  });

  it("should allow claims with the new token after migration", async function () {
    const cliffEnd = this.start + this.cliffDuration + 1;
    await ethers.provider.send("evm_setNextBlockTimestamp", [cliffEnd]);
    await ethers.provider.send("evm_mine");

    await vestingWallet.connect(owner).migrateToken(tokenB.target);

    await expect(vestingWallet.connect(beneficiary).release()).to.not.be.reverted;

    const benBalanceB = await tokenB.balanceOf(beneficiary.address);
    expect(benBalanceB).to.be.gt(0);
  });

  it("should work after partial release", async function () {
    // Fast forward to halfway through vesting
    const midPoint = this.start + this.cliffDuration + 500;
    await ethers.provider.send("evm_setNextBlockTimestamp", [midPoint]);
    await ethers.provider.send("evm_mine");

    await vestingWallet.connect(beneficiary).release();
    const released = await vestingWallet.released();
    expect(released).to.be.gt(0);

    const remaining = totalAllocation - released;
    await tokenB.mint(vestingWallet.target, remaining);

    await expect(vestingWallet.connect(owner).migrateToken(tokenB.target))
      .to.emit(vestingWallet, "TokenMigrated")
      .withArgs(tokenA.target, tokenB.target, remaining);

    // Fast forward to vesting end
    const end = this.start + this.vestingDuration;
    await ethers.provider.send("evm_setNextBlockTimestamp", [end]);
    await ethers.provider.send("evm_mine");

    await vestingWallet.connect(beneficiary).release();
    const benBalanceB = await tokenB.balanceOf(beneficiary.address);
    expect(benBalanceB).to.be.gt(0);
  });
});