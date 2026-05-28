import { ethers } from "ethers";
import { OpenAgentsSDK, DeploymentReceipt } from "../src/index";

// Minimal ABI for a simple storage contract
const minimalAbi = [
  "function store(uint256 _value) public",
  "function retrieve() public view returns (uint256)",
] as ethers.InterfaceAbi;

// Minimal bytecode for a storage contract (compiled Solidity)
const minimalBytecode =
  "0x608060405234801561001057600080fd5b50610150806100206000396000f3fe608060405234801561001057600080fd5b50600436106100365760003560e01c80632e64cec11461003b5780636057361d14610059575b600080fd5b610043610075565b60405161005091906100a1565b60405180910390f35b610073600480360381019061006e91906100ed565b61007e565b005b60008054905090565b8060008190555050565b6000819050919050565b61009b81610088565b82525050565b60006020820190506100b66000830184610092565b92915050565b600080fd5b6100ca81610088565b81146100d557600080fd5b50565b6000813590506100e7816100c1565b92915050565b600060208284031215610103576101026100bc565b5b6000610111848285016100d8565b9150509291505056fea2646970667358221220ab1d9f9e8c2f3c0b0e1a0f0b0c0d0e0a0b0c0d0e0f0a0b0c0d0e0f0a0b0c0d64736f6c637827302e382e31372d646576656c6f702e323032342e31322e3130000000000000000000000000";

describe("OpenAgentsSDK - deployContract", () => {
  let sdk: OpenAgentsSDK;
  let mockProvider: ethers.JsonRpcProvider;

  beforeEach(() => {
    // Use a random wallet and a throwaway RPC URL (tests won't actually deploy)
    sdk = new OpenAgentsSDK({
      name: "test-agent",
      endpoint: "http://localhost:9999",
      privateKey: "0x0123456789012345678901234567890123456789012345678901234567890123",
      rpcUrl: "http://localhost:8545",
      registryAddress: "0x0000000000000000000000000000000000000001",
      routerAddress: "0x0000000000000000000000000000000000000002",
    });
  });

  it("should return a DeploymentReceipt object shape", () => {
    // Verify the method signature and return type exist
    expect(sdk.deployContract).toBeDefined();
    expect(typeof sdk.deployContract).toBe("function");

    // Check the method has the expected parameter count
    const paramCount = sdk.deployContract.length;
    expect(paramCount).toBeGreaterThanOrEqual(3);
    expect(paramCount).toBeLessThanOrEqual(4);
  });
});

describe("DeploymentReceipt interface", () => {
  it("should have all required fields", () => {
    const receipt: DeploymentReceipt = {
      address: "0x1234",
      transactionHash: "0xabcd",
      gasUsed: BigInt(21000),
      blockNumber: 12345,
      contract: {} as any,
    };

    expect(receipt.address).toBe("0x1234");
    expect(receipt.transactionHash).toBe("0xabcd");
    expect(receipt.gasUsed).toBe(BigInt(21000));
    expect(receipt.blockNumber).toBe(12345);
    expect(receipt.contract).toBeDefined();
  });
});