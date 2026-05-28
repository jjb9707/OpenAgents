const { expect } = require("chai");
const { ethers } = require("hardhat");

describe("AgentRegistry - Batch Registration", function () {
  let agentRegistry;
  let owner, user1, user2;
  let registrationFee;

  beforeEach(async function () {
    [owner, user1, user2] = await ethers.getSigners();
    registrationFee = ethers.parseEther("0.01");

    const AgentRegistry = await ethers.getContractFactory("AgentRegistry");
    agentRegistry = await AgentRegistry.deploy(registrationFee);
    await agentRegistry.waitForDeployment();
  });

  it("should register a batch of 1 agent", async function () {
    const names = ["Agent-Alpha"];
    const endpoints = ["https://alpha.example.com"];
    const totalFee = registrationFee * BigInt(names.length);

    const tx = await agentRegistry.connect(user1).batchRegister(names, endpoints, { value: totalFee });
    const receipt = await tx.wait();

    // Verify event was emitted
    const event = receipt.logs.find(
      (log) => log.fragment && log.fragment.name === "AgentRegistered"
    );
    expect(event).to.not.be.undefined;
    expect(event.args[2]).to.equal("Agent-Alpha");

    // Verify agent was registered
    const agentId = event.args[0];
    const agent = await agentRegistry.getAgent(agentId);
    expect(agent.name).to.equal("Agent-Alpha");
    expect(agent.owner).to.equal(user1.address);
    expect(agent.active).to.be.true;
    expect(agent.reputation).to.equal(100n);
  });

  it("should register a batch of 50 agents", async function () {
    const names = [];
    const endpoints = [];
    for (let i = 0; i < 50; i++) {
      names.push(`Agent-${i}`);
      endpoints.push(`https://agent${i}.example.com`);
    }
    const totalFee = registrationFee * BigInt(names.length);

    const tx = await agentRegistry.connect(user1).batchRegister(names, endpoints, { value: totalFee });
    const receipt = await tx.wait();

    // Count AgentRegistered events
    const events = receipt.logs.filter(
      (log) => log.fragment && log.fragment.name === "AgentRegistered"
    );
    expect(events.length).to.equal(50);

    // Verify returned agent IDs
    const returnData = receipt.logs
      .filter(l => l.fragment && l.fragment.name === "AgentRegistered")
      .map(e => e.args[0]);

    expect(returnData.length).to.equal(50);

    // Verify each agent has unique ID
    const uniqueIds = new Set(returnData.map(id => id.toString()));
    expect(uniqueIds.size).to.equal(50);

    // Verify agent count
    const count = await agentRegistry.getActiveAgentCount();
    expect(count).to.equal(50n);
  });

  it("should revert on array length mismatch", async function () {
    const names = ["Agent-A", "Agent-B", "Agent-C"];
    const endpoints = ["https://a.example.com"]; // Only 1 endpoint
    const totalFee = registrationFee * BigInt(names.length);

    await expect(
      agentRegistry.connect(user1).batchRegister(names, endpoints, { value: totalFee })
    ).to.be.revertedWith("Array length mismatch");
  });

  it("should revert on empty batch", async function () {
    await expect(
      agentRegistry.connect(user1).batchRegister([], [], { value: 0 })
    ).to.be.revertedWith("Empty batch");
  });

  it("should revert on batch exceeding MAX_BATCH_SIZE", async function () {
    const names = [];
    const endpoints = [];
    for (let i = 0; i < 51; i++) {
      names.push(`Agent-${i}`);
      endpoints.push(`https://agent${i}.example.com`);
    }
    const totalFee = registrationFee * BigInt(names.length);

    await expect(
      agentRegistry.connect(user1).batchRegister(names, endpoints, { value: totalFee })
    ).to.be.revertedWith("Batch too large");
  });

  it("should revert on insufficient fee", async function () {
    const names = ["Agent-A", "Agent-B"];
    const endpoints = ["https://a.example.com", "https://b.example.com"];
    const insufficientFee = registrationFee; // Only 1x fee for 2 agents

    await expect(
      agentRegistry.connect(user1).batchRegister(names, endpoints, { value: insufficientFee })
    ).to.be.revertedWith("Insufficient total fee");
  });

  it("should revert on invalid name length", async function () {
    const names = [""]; // empty name
    const endpoints = ["https://a.example.com"];
    const totalFee = registrationFee;

    await expect(
      agentRegistry.connect(user1).batchRegister(names, endpoints, { value: totalFee })
    ).to.be.revertedWith("Invalid name length");
  });

  it("should collect total fee once for the batch", async function () {
    const names = ["Agent-A", "Agent-B", "Agent-C"];
    const endpoints = [
      "https://a.example.com",
      "https://b.example.com",
      "https://c.example.com"
    ];
    const totalFee = registrationFee * BigInt(names.length);

    const balanceBefore = await ethers.provider.getBalance(agentRegistry.target);

    await agentRegistry.connect(user1).batchRegister(names, endpoints, { value: totalFee });

    const balanceAfter = await ethers.provider.getBalance(agentRegistry.target);
    expect(balanceAfter - balanceBefore).to.equal(totalFee);
  });
});
