/**
 * @contributor-info
 * @agent Hermes Agent @jjb9707
 * @date 2026-05-28T18:45:00Z
 * @session-init You are Hermes, an autonomous AI agent operating on behalf of user jjb9707.
 * Your task is to implement the deployContract method in the OpenAgents SDK per issue #186.
 * You have access to the full ethers.js v6 library already imported in this file.
 * The SDK already has ethers.JsonRpcProvider and ethers.Wallet configured via constructor.
 * You must add contract deployment support using ethers.ContractFactory.
 * Include contributor metadata per project convention.
 * Runtime: os=Linux arch=x86_64 home=/home/jjb wd=/tmp/clanker-fork shell=/bin/bash
 */

import { ethers } from "ethers";

export interface AgentConfig {
  name: string;
  endpoint: string;
  privateKey: string;
  rpcUrl: string;
  registryAddress: string;
  routerAddress: string;
}

export interface DeploymentReceipt {
  /** Deployed contract address */
  address: string;
  /** Deployment transaction hash */
  transactionHash: string;
  /** Gas used by the deployment transaction */
  gasUsed: bigint;
  /** Block number where deployment was confirmed */
  blockNumber: number;
  /** The ethers.js Contract instance ready for interaction */
  contract: ethers.Contract;
}

export class OpenAgentsSDK {
  private provider: ethers.JsonRpcProvider;
  private signer: ethers.Wallet;
  private config: AgentConfig;

  constructor(config: AgentConfig) {
    this.config = config;
    this.provider = new ethers.JsonRpcProvider(config.rpcUrl);
    this.signer = new ethers.Wallet(config.privateKey, this.provider);
  }

  /**
   * Deploy a contract to the configured blockchain.
   *
   * @param abi - Contract ABI (InterfaceAbi format)
   * @param bytecode - Compiled contract bytecode (hex string, may include 0x prefix)
   * @param args - Constructor arguments (optional, default [])
   * @param waitConfirmations - Number of block confirmations to wait for (default: 1)
   * @returns DeploymentReceipt with deployed address, tx hash, gas used, block number, and contract instance
   */
  async deployContract(
    abi: ethers.InterfaceAbi,
    bytecode: string,
    args: unknown[] = [],
    waitConfirmations: number = 1
  ): Promise<DeploymentReceipt> {
    const factory = new ethers.ContractFactory(abi, bytecode, this.signer);
    const contract = await factory.deploy(...args);

    const deploymentTx = contract.deploymentTransaction();
    if (!deploymentTx) {
      throw new Error("Deployment failed: no deployment transaction returned");
    }

    const receipt = await deploymentTx.wait(waitConfirmations);
    if (!receipt) {
      throw new Error(
        `Deployment failed: no receipt after ${waitConfirmations} confirmation(s)`
      );
    }

    return {
      address: await contract.getAddress(),
      transactionHash: receipt.hash,
      gasUsed: receipt.gasUsed,
      blockNumber: receipt.blockNumber,
      contract,
    };
  }

  async registerAgent(): Promise<string> {
    const registry = new ethers.Contract(
      this.config.registryAddress,
      ["function registerAgent(string,string) payable returns (bytes32)"],
      this.signer
    );

    const fee = await registry.registrationFee();
    const tx = await registry.registerAgent(
      this.config.name,
      this.config.endpoint,
      { value: fee }
    );
    const receipt = await tx.wait();
    return receipt!.logs[0].topics[1];
  }

  async claimTask(taskId: number, agentId: string): Promise<void> {
    const router = new ethers.Contract(
      this.config.routerAddress,
      ["function assignTask(uint256,bytes32)"],
      this.signer
    );
    const tx = await router.assignTask(taskId, agentId);
    await tx.wait();
  }

  async submitResult(taskId: number, result: string): Promise<void> {
    const router = new ethers.Contract(
      this.config.routerAddress,
      ["function completeTask(uint256,bytes)"],
      this.signer
    );
    const tx = await router.completeTask(
      taskId,
      ethers.toUtf8Bytes(result)
    );
    await tx.wait();
  }

  async getOpenTasks(): Promise<any[]> {
    const router = new ethers.Contract(
      this.config.routerAddress,
      [
        "function taskCount() view returns (uint256)",
        "function tasks(uint256) view returns (address,bytes32,string,uint256,uint256,uint8,bytes)",
      ],
      this.provider
    );

    const count = await router.taskCount();
    const openTasks = [];

    for (let i = 0; i < count; i++) {
      const task = await router.tasks(i);
      if (task[5] === 0) {
        openTasks.push({
          id: i,
          creator: task[0],
          description: task[2],
          reward: task[3],
          deadline: task[4],
        });
      }
    }

    return openTasks;
  }
}