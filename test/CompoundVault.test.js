// @contributor: Hermes Agent @jjb9707
// @date: 2026-05-29T05:39:43Z
// @session-init: [REDACTED]
// @runtime: os=Linux arch=x86_64 home=/home/jjb wd=/tmp/clanker-fork-110 shell=/bin/bash

const { expect } = require("chai");
const { ethers } = require("hardhat");

describe("CompoundVault", function () {
  let vault, baseToken, rewardToken, strategy, owner;
  const ONE_ETH = ethers.parseEther("1");
  const DEPOSIT_AMOUNT = ethers.parseEther("100");

  beforeEach(async function () {
    [owner] = await ethers.getSigners();

    // Deploy mock tokens
    const MockERC20 = await ethers.getContractFactory("MockERC20");
    baseToken = await MockERC20.deploy("Base Token", "BASE");
    rewardToken = await MockERC20.deploy("Reward Token", "RWD");

    // Deploy mock strategy
    const MockStrategy = await ethers.getContractFactory("MockStrategy");
    strategy = await MockStrategy.deploy(
      await baseToken.getAddress(),
      await rewardToken.getAddress()
    );

    // Deploy vault
    const CompoundVault = await ethers.getContractFactory("CompoundVault");
    vault = await CompoundVault.deploy(
      await baseToken.getAddress(),
      await rewardToken.getAddress(),
      await strategy.getAddress(),
      owner.address,
      1000 // 10% fee
    );

    // Mint base tokens to owner and deposit into vault
    await baseToken.mint(owner.address, DEPOSIT_AMOUNT);
    await baseToken.connect(owner).approve(await vault.getAddress(), DEPOSIT_AMOUNT);
    await vault.connect(owner).deposit(DEPOSIT_AMOUNT);
  });

  describe("deposit", function () {
    it("should initialize price per share to 1e18", async function () {
      const pps = await vault.pricePerShare();
      expect(pps).to.equal(ethers.parseEther("1"));
    });
  });

  describe("compound - positive yield", function () {
    it("should increase share price on positive yield", async function () {
      await rewardToken.mint(await vault.getAddress(), ONE_ETH);

      // Pre-fund strategy with profit tokens (10 BASE)
      await baseToken.mint(await strategy.getAddress(), ethers.parseEther("10"));
      await strategy.setYield(0, 0); // POSITIVE

      const priceBefore = await vault.pricePerShare();
      await vault.connect(owner).compound();
      const priceAfter = await vault.pricePerShare();

      expect(priceAfter > priceBefore).to.be.true;
    });

    it("should emit Compounded event", async function () {
      await rewardToken.mint(await vault.getAddress(), ONE_ETH);
      await baseToken.mint(await strategy.getAddress(), ethers.parseEther("10"));
      await strategy.setYield(0, 0); // POSITIVE

      await expect(vault.connect(owner).compound()).to.emit(vault, "Compounded")
        .withArgs(ethers.parseEther("10"), ethers.parseEther("1.1"));
    });
  });

  describe("compound - zero yield", function () {
    it("should not change share price", async function () {
      await rewardToken.mint(await vault.getAddress(), ONE_ETH);
      await strategy.setYield(1, 0); // ZERO (only vault's tokens returned)

      const priceBefore = await vault.pricePerShare();
      await vault.connect(owner).compound();
      const priceAfter = await vault.pricePerShare();

      // With zero yield, no tokens are gained or lost from vault's perspective
      // Vault sent base tokens to strategy, strategy returned them, net = 0
      expect(priceAfter).to.equal(priceBefore);
    });
  });

  describe("compound - negative yield", function () {
    it("should decrease share price", async function () {
      await rewardToken.mint(await vault.getAddress(), ONE_ETH);
      await strategy.setYield(2, ethers.parseEther("5")); // NEGATIVE, burn 5 BASE

      const priceBefore = await vault.pricePerShare();
      await vault.connect(owner).compound();
      const priceAfter = await vault.pricePerShare();

      expect(priceAfter < priceBefore).to.be.true;
    });

    it("should increase totalLoss", async function () {
      await rewardToken.mint(await vault.getAddress(), ONE_ETH);
      await strategy.setYield(2, ethers.parseEther("5"));

      const lossBefore = await vault.totalLoss();
      await vault.connect(owner).compound();
      const lossAfter = await vault.totalLoss();

      expect(lossAfter > lossBefore).to.be.true;
    });

    it("should emit StrategyLoss event", async function () {
      await rewardToken.mint(await vault.getAddress(), ONE_ETH);
      await strategy.setYield(2, ethers.parseEther("5"));

      await expect(vault.connect(owner).compound()).to.emit(vault, "StrategyLoss");
    });
  });

  describe("compound - edge cases", function () {
    it("should do nothing when no rewards and no base tokens", async function () {
      const priceBefore = await vault.pricePerShare();
      await vault.connect(owner).compound();
      const priceAfter = await vault.pricePerShare();
      expect(priceAfter).to.equal(priceBefore);
    });
  });
});
