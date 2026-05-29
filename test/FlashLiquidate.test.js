const { expect } = require("chai");
const { ethers } = require("hardhat");

describe("LendingPool - flashLiquidate", function () {
  let owner, user, liquidator;
  let collateralToken, borrowToken;
  let priceFeed, pool;
  
  const COLLATERAL_AMOUNT = ethers.parseEther("1000");
  const BORROW_AMOUNT = ethers.parseEther("500");
  
  beforeEach(async function () {
    [owner, user, liquidator] = await ethers.getSigners();

    // Deploy tokens with 18 decimals
    const MockERC20 = await ethers.getContractFactory("MockERC20");
    collateralToken = await MockERC20.deploy("Collateral", "COL", 18);
    borrowToken = await MockERC20.deploy("Borrow", "BRW", 18);

    // Deploy mock price feed (1:1 pricing for simplicity)
    const MockPriceFeed = await ethers.getContractFactory("MockPriceFeed");
    priceFeed = await MockPriceFeed.deploy();

    // Deploy pool
    const LendingPool = await ethers.getContractFactory("LendingPool");
    pool = await LendingPool.deploy(priceFeed.target, collateralToken.target, borrowToken.target);
    await pool.waitForDeployment();

    // Fund user with collateral
    await collateralToken.mint(user.address, COLLATERAL_AMOUNT);

    // User deposits collateral
    await collateralToken.connect(user).approve(pool.target, COLLATERAL_AMOUNT);
    await pool.connect(user).deposit(COLLATERAL_AMOUNT);

    // User borrows
    await borrowToken.mint(pool.target, BORROW_AMOUNT); // seed pool with borrow tokens
    await pool.connect(user).borrow(BORROW_AMOUNT);

    // Set price to make position underwater (collateral value < 150% of debt)
    // debt = 500, threshold = 150%, so min healthy collateral value = 500 * 1.5 = 750
    // Set collateral price to 1 (collateral value = 1000 * 1 = 1000)
    // 1000 >= 750 → healthy
    // Drop collateral price to 0.6 → collateral value = 1000 * 0.6 = 600
    // 600 < 750 → unhealthy → liquidatable
    await priceFeed.setPrice(collateralToken.target, ethers.parseEther("1"));
    await priceFeed.setPrice(borrowToken.target, ethers.parseEther("1"));

    // Fund liquidator with borrow tokens for fee payment
    await borrowToken.mint(liquidator.address, ethers.parseEther("1000"));
    await borrowToken.connect(liquidator).approve(pool.target, ethers.parseEther("1000"));
  });

  async function makeUnhealthy() {
    // Drop collateral price to 0.6 → liquidatable
    await priceFeed.setPrice(collateralToken.target, ethers.parseEther("0.6"));
  }

  it("should liquidate a position without upfront capital", async function () {
    await makeUnhealthy();

    const tx = await pool.connect(liquidator).flashLiquidate(user.address);
    await tx.wait();

    // Verify position closed
    const pos = await pool.getPosition(user.address);
    expect(pos.collateral).to.equal(0);
    expect(pos.debt).to.equal(0);

    // Liquidator got the collateral
    const collBalance = await collateralToken.balanceOf(liquidator.address);
    expect(collBalance).to.equal(COLLATERAL_AMOUNT);
  });

  it("should reject liquidation of a healthy position", async function () {
    // Price is still 1:1 → healthy
    await expect(
      pool.connect(liquidator).flashLiquidate(user.address)
    ).to.be.revertedWith("Position healthy");
  });

  it("should collect 0.09% flash loan fee", async function () {
    await makeUnhealthy();

    // Pool has 0 borrow tokens before (all borrowed out)
    const poolBefore = await borrowToken.balanceOf(pool.target);

    await pool.connect(liquidator).flashLiquidate(user.address);

    // Pool gets debt back + extra fee = 500 + 0.45 = 500.45
    const poolAfter = await borrowToken.balanceOf(pool.target);
    const expectedFee = (BORROW_AMOUNT * 9n) / 10000n; // 0.09%
    expect(poolAfter - poolBefore).to.equal(BORROW_AMOUNT + expectedFee);
  });

  it("should allow anyone to liquidate", async function () {
    await makeUnhealthy();

    const randomGuy = (await ethers.getSigners())[5];
    await borrowToken.mint(randomGuy.address, ethers.parseEther("1000"));
    await borrowToken.connect(randomGuy).approve(pool.target, ethers.parseEther("1000"));

    await expect(
      pool.connect(randomGuy).flashLiquidate(user.address)
    ).to.not.be.reverted;
  });

  it("should update totalBorrowed and totalDeposits correctly", async function () {
    await makeUnhealthy();

    const tx = await pool.connect(liquidator).flashLiquidate(user.address);
    await tx.wait();

    expect(await pool.totalBorrowed()).to.equal(0);
    expect(await pool.totalDeposits()).to.equal(0);
  });

  it("should emit Liquidated event", async function () {
    await makeUnhealthy();

    await expect(pool.connect(liquidator).flashLiquidate(user.address))
      .to.emit(pool, "Liquidated")
      .withArgs(user.address, liquidator.address, BORROW_AMOUNT);
  });

  it("should let liquidator profit from the liquidation", async function () {
    await makeUnhealthy();

    // Set collateral price to 0.74 → collateral value = 740, debt value = 500
    // 740 < 750 threshold → unhealthy → liquidatable
    // Liquidator: gets 1000 collateral, pays back 500 + 0.45 fee
    // Net: 1000 collateral - 500.45 borrow tokens
    
    await priceFeed.setPrice(collateralToken.target, ethers.parseEther("0.74"));
    
    await pool.connect(liquidator).flashLiquidate(user.address);
    
    const collBalance = await collateralToken.balanceOf(liquidator.address);
    const borrowSpent = ethers.parseEther("1000") - await borrowToken.balanceOf(liquidator.address);
    
    // Liquidator has all the collateral
    expect(collBalance).to.equal(COLLATERAL_AMOUNT);
    // Paid debt + fee
    expect(borrowSpent).to.equal(BORROW_AMOUNT + (BORROW_AMOUNT * 9n) / 10000n);
  });
});