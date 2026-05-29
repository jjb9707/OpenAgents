const { expect } = require("chai");
const { ethers } = require("hardhat");

// Canonical Permit2 address
const PERMIT2_ADDRESS = "0x000000000022D473030F116dDEE9F6B43aC78BA3";

describe("Permit2 Integration", function () {
  let owner, user, liquidator;
  let mockToken, mockTokenB, mockCollateral, mockBorrow;
  let staking, lending, ammPool;
  let mockPriceFeed;

  before(async function () {
    [owner, user, liquidator] = await ethers.getSigners();

    // Deploy mock tokens
    const MockERC20 = await ethers.getContractFactory("MockERC20");
    mockToken = await MockERC20.deploy("Staking", "STK", 18);
    mockTokenB = await MockERC20.deploy("TokenB", "TKB", 18);
    mockCollateral = await MockERC20.deploy("Collateral", "COL", 18);
    mockBorrow = await MockERC20.deploy("Borrow", "BRW", 18);

    // Deploy mock price feed
    const MockPriceFeed = await ethers.getContractFactory("MockPriceFeed");
    mockPriceFeed = await MockPriceFeed.deploy();
    // Default price: 1:1
    await mockPriceFeed.setPrice(mockCollateral.target, ethers.parseEther("1"));
    await mockPriceFeed.setPrice(mockBorrow.target, ethers.parseEther("1"));

    // Deploy contracts
    const StakingRewards = await ethers.getContractFactory("StakingRewards");
    staking = await StakingRewards.deploy(mockToken.target, mockTokenB.target);

    const LendingPool = await ethers.getContractFactory("LendingPool");
    lending = await LendingPool.deploy(
      mockPriceFeed.target,
      mockCollateral.target,
      mockBorrow.target
    );

    const AMMPool = await ethers.getContractFactory("AMMPool");
    ammPool = await AMMPool.deploy(mockToken.target, mockTokenB.target);

    // Mint tokens
    const mintAmount = ethers.parseEther("10000");
    await mockToken.mint(user.address, mintAmount);
    await mockTokenB.mint(user.address, mintAmount);
    await mockCollateral.mint(user.address, mintAmount);
    await mockBorrow.mint(user.address, mintAmount);
    await mockBorrow.mint(liquidator.address, mintAmount);

    // Deploy MockPermit2 at the canonical Permit2 address using hardhat_setCode
    const MockPermit2Factory = await ethers.getContractFactory("MockPermit2");
    const mockPermit2Impl = await MockPermit2Factory.deploy();

    // Set the code at the canonical Permit2 address
    await ethers.provider.send("hardhat_setCode", [
      PERMIT2_ADDRESS,
      await ethers.provider.getCode(mockPermit2Impl.target),
    ]);

    // Approve Permit2 address for all tokens on behalf of user
    const approveAmount = ethers.parseEther("100000");
    await mockToken.connect(user).approve(PERMIT2_ADDRESS, approveAmount);
    await mockTokenB.connect(user).approve(PERMIT2_ADDRESS, approveAmount);
    await mockCollateral.connect(user).approve(PERMIT2_ADDRESS, approveAmount);
    await mockBorrow.connect(user).approve(PERMIT2_ADDRESS, approveAmount);
    await mockBorrow.connect(liquidator).approve(PERMIT2_ADDRESS, approveAmount);

    // Setup LendingPool position: seed borrow tokens to the pool, then user deposits and borrows
    const depositAmount = ethers.parseEther("1000");
    const borrowAmount = ethers.parseEther("400"); // 40% LTV, well under 150% threshold
    // Mint borrow tokens to the lending pool so it can lend them out
    await mockBorrow.mint(lending.target, ethers.parseEther("10000"));
    await mockCollateral.connect(user).approve(lending.target, depositAmount);
    await lending.connect(user).deposit(depositAmount);
    await lending.connect(user).borrow(borrowAmount);

    // Setup AMMPool with initial liquidity for swaps
    const initialLiq = ethers.parseEther("1000");
    await mockToken.connect(user).approve(ammPool.target, initialLiq);
    await mockTokenB.connect(user).approve(ammPool.target, initialLiq);
    await ammPool.connect(user).addLiquidity(initialLiq, initialLiq);
  });

  describe("Fallback - Standard transferFrom", function () {
    it("StakingRewards.stake() works with standard approval", async function () {
      const amount = ethers.parseEther("100");
      await mockToken.connect(user).approve(staking.target, amount);
      await expect(staking.connect(user).stake(amount))
        .to.emit(staking, "Staked")
        .withArgs(user.address, amount);
      expect(await staking.balanceOf(user.address)).to.equal(amount);
    });

    it("LendingPool.deposit() works with standard approval", async function () {
      const amount = ethers.parseEther("50");
      await mockCollateral.connect(user).approve(lending.target, amount);
      await expect(lending.connect(user).deposit(amount))
        .to.emit(lending, "Deposited")
        .withArgs(user.address, amount);
    });

    it("LendingPool.repay() works with standard approval", async function () {
      const amount = ethers.parseEther("10");
      await mockBorrow.connect(user).approve(lending.target, amount);
      await expect(lending.connect(user).repay(amount))
        .to.emit(lending, "Repaid")
        .withArgs(user.address, amount);
    });

    it("AMMPool.addLiquidity() works with standard approval", async function () {
      const amount = ethers.parseEther("50");
      await mockToken.connect(user).approve(ammPool.target, amount);
      await mockTokenB.connect(user).approve(ammPool.target, amount);
      await expect(ammPool.connect(user).addLiquidity(amount, amount))
        .to.emit(ammPool, "LiquidityAdded");
    });

    it("AMMPool.swap() works with standard approval", async function () {
      const amountIn = ethers.parseEther("10");
      await mockToken.connect(user).approve(ammPool.target, amountIn);
      await expect(ammPool.connect(user).swap(mockToken.target, amountIn, 1))
        .to.emit(ammPool, "Swap");
    });
  });

  describe("Permit2 - stakeWithPermit", function () {
    it("should stake tokens via Permit2 permitTransferFrom", async function () {
      const amount = ethers.parseEther("200");
      const permit = {
        permitted: {
          token: mockToken.target,
          amount: amount,
        },
        nonce: 1,
        deadline: Math.floor(Date.now() / 1000) + 3600,
      };
      const signature = "0x" + "01".repeat(65);

      await staking.connect(user).stakeWithPermit(amount, permit, signature);

      // Verify the stake went through (100 from fallback test + 200 now)
      expect(await staking.balanceOf(user.address)).to.equal(amount + ethers.parseEther("100"));
    });

    it("should reject wrong token in permit", async function () {
      const amount = ethers.parseEther("50");
      const permit = {
        permitted: {
          token: mockTokenB.target, // wrong token
          amount: amount,
        },
        nonce: 2,
        deadline: Math.floor(Date.now() / 1000) + 3600,
      };
      const signature = "0x" + "01".repeat(65);

      await expect(
        staking.connect(user).stakeWithPermit(amount, permit, signature)
      ).to.be.revertedWith("Wrong token");
    });

    it("should reject insufficient permit amount", async function () {
      const amount = ethers.parseEther("50");
      const permit = {
        permitted: {
          token: mockToken.target,
          amount: ethers.parseEther("10"), // less than amount
        },
        nonce: 3,
        deadline: Math.floor(Date.now() / 1000) + 3600,
      };
      const signature = "0x" + "01".repeat(65);

      await expect(
        staking.connect(user).stakeWithPermit(amount, permit, signature)
      ).to.be.revertedWith("Permit amount too low");
    });
  });

  describe("Permit2 - depositWithPermit", function () {
    it("should deposit collateral via Permit2", async function () {
      const amount = ethers.parseEther("300");
      const permit = {
        permitted: {
          token: mockCollateral.target,
          amount: amount,
        },
        nonce: 4,
        deadline: Math.floor(Date.now() / 1000) + 3600,
      };
      const signature = "0x" + "01".repeat(65);

      await expect(lending.connect(user).depositWithPermit(amount, permit, signature))
        .to.emit(lending, "Deposited")
        .withArgs(user.address, amount);
    });

    it("should reject wrong token in deposit permit", async function () {
      const amount = ethers.parseEther("50");
      const permit = {
        permitted: {
          token: mockBorrow.target,
          amount: amount,
        },
        nonce: 5,
        deadline: Math.floor(Date.now() / 1000) + 3600,
      };
      const signature = "0x" + "01".repeat(65);

      await expect(
        lending.connect(user).depositWithPermit(amount, permit, signature)
      ).to.be.revertedWith("Wrong token");
    });
  });

  describe("Permit2 - repayWithPermit", function () {
    it("should repay borrowed tokens via Permit2", async function () {
      const amount = ethers.parseEther("50");
      const permit = {
        permitted: {
          token: mockBorrow.target,
          amount: amount,
        },
        nonce: 6,
        deadline: Math.floor(Date.now() / 1000) + 3600,
      };
      const signature = "0x" + "01".repeat(65);

      await expect(lending.connect(user).repayWithPermit(amount, permit, signature))
        .to.emit(lending, "Repaid")
        .withArgs(user.address, amount);
    });
  });

  describe("Permit2 - liquidateWithPermit", function () {
    it("should liquidate an underwater position via Permit2", async function () {
      // User has: 1000 + 50 + 300 = 1350 collateral deposited, ~340 borrowed (400-10-50)
      // Set collateral price to 0 to make position unhealthy
      await mockPriceFeed.setPrice(mockCollateral.target, 0);

      const pos = await lending.getPosition(user.address);
      expect(pos.debt).to.be.gt(0);

      const permit = {
        permitted: {
          token: mockBorrow.target,
          amount: pos.debt,
        },
        nonce: 7,
        deadline: Math.floor(Date.now() / 1000) + 3600,
      };
      const signature = "0x" + "01".repeat(65);

      await expect(
        lending.connect(liquidator).liquidateWithPermit(user.address, permit, signature)
      ).to.emit(lending, "Liquidated");
    });
  });

  describe("Permit2 - addLiquidityWithPermit", function () {
    it("should add liquidity via Permit2 for both tokens", async function () {
      const amount = ethers.parseEther("30");
      const permitA = {
        permitted: {
          token: mockToken.target,
          amount: amount,
        },
        nonce: 8,
        deadline: Math.floor(Date.now() / 1000) + 3600,
      };
      const permitB = {
        permitted: {
          token: mockTokenB.target,
          amount: amount,
        },
        nonce: 9,
        deadline: Math.floor(Date.now() / 1000) + 3600,
      };
      const sig = "0x" + "01".repeat(65);

      await expect(
        ammPool.connect(user).addLiquidityWithPermit(amount, amount, permitA, permitB, sig, sig)
      ).to.emit(ammPool, "LiquidityAdded");
    });
  });

  describe("Permit2 - swapWithPermit", function () {
    it("should swap tokens via Permit2", async function () {
      const amountIn = ethers.parseEther("5");
      const permit = {
        permitted: {
          token: mockToken.target,
          amount: amountIn,
        },
        nonce: 10,
        deadline: Math.floor(Date.now() / 1000) + 3600,
      };
      const signature = "0x" + "01".repeat(65);

      await expect(
        ammPool.connect(user).swapWithPermit(mockToken.target, amountIn, 1, permit, signature)
      ).to.emit(ammPool, "Swap");
    });
  });

  describe("Error handling", function () {
    it("should revert stakeWithPermit on zero amount", async function () {
      const permit = {
        permitted: {
          token: mockToken.target,
          amount: 0,
        },
        nonce: 11,
        deadline: Math.floor(Date.now() / 1000) + 3600,
      };
      const signature = "0x" + "01".repeat(65);

      await expect(
        staking.connect(user).stakeWithPermit(0, permit, signature)
      ).to.be.revertedWith("Cannot stake 0");
    });

    it("should reject swapWithPermit with invalid token", async function () {
      const amountIn = ethers.parseEther("5");
      const permit = {
        permitted: {
          token: mockCollateral.target,
          amount: amountIn,
        },
        nonce: 12,
        deadline: Math.floor(Date.now() / 1000) + 3600,
      };
      const signature = "0x" + "01".repeat(65);

      await expect(
        ammPool.connect(user).swapWithPermit(mockCollateral.target, amountIn, 1, permit, signature)
      ).to.be.revertedWith("Invalid token");
    });
  });
});