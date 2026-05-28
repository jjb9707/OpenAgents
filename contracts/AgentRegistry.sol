// SPDX-License-Identifier: MIT
// @contributor: Hermes Agent @jjb9707
// @date: 2026-05-29T22:36:06Z
// @session-init: 自动赏金猎人 — 每2小时扫描。扫描 ClankerNation/OpenAgents 仓库的未认领赏金，自动 claim 并提 PR。
//   阶段一：扫描 open bounty issues，过滤出 comments < 15、assignee == null、未认领的
//   阶段二：选最优标的（按金额排序，最高且未认领）
//   阶段三：自动执行全流程 — /claim → fork → clone → 实现 → commit → push → PR
//   钱包地址: 0x2FC9393BBC82CC87b9E916ba5959e48FEA24eF78 (Base USDC)
//   黑名单: 跳过 MRG/GSSOC/hackathon，跳过 comments >= 15
//   去重: 检查 seen_issues.json 避免重复 claim
// @runtime: os=Linux arch=x86_64 home=/home/jjb wd=/home/jjb shell=/bin/bash
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/access/Ownable.sol";

contract AgentRegistry is Ownable {
    struct Agent {
        address owner;
        string name;
        string endpoint;
        uint256 reputation;
        uint256 tasksCompleted;
        uint256 registeredAt;
        bool active;
    }

    mapping(bytes32 => Agent) public agents;
    mapping(address => bytes32[]) public ownerAgents;
    bytes32[] public agentIds;

    uint256 public registrationFee;
    uint256 public minReputation;

    uint256 public constant MAX_BATCH_SIZE = 50;

    event AgentRegistered(bytes32 indexed agentId, address indexed owner, string name);
    event AgentDeactivated(bytes32 indexed agentId);
    event ReputationUpdated(bytes32 indexed agentId, uint256 newReputation);

    constructor(uint256 _registrationFee) Ownable(msg.sender) {
        registrationFee = _registrationFee;
        minReputation = 0;
    }

    function registerAgent(string calldata name, string calldata endpoint) external payable returns (bytes32) {
        require(msg.value >= registrationFee, "Insufficient fee");
        require(bytes(name).length > 0 && bytes(name).length <= 64, "Invalid name");

        bytes32 agentId = keccak256(abi.encodePacked(msg.sender, name, block.timestamp));

        require(agents[agentId].registeredAt == 0, "Agent exists");

        agents[agentId] = Agent({
            owner: msg.sender,
            name: name,
            endpoint: endpoint,
            reputation: 100,
            tasksCompleted: 0,
            registeredAt: block.timestamp,
            active: true
        });

        ownerAgents[msg.sender].push(agentId);
        agentIds.push(agentId);

        emit AgentRegistered(agentId, msg.sender, name);
        return agentId;
    }

    function batchRegister(string[] calldata names, string[] calldata endpoints) external payable returns (bytes32[] memory) {
        uint256 count = names.length;
        require(count == endpoints.length, "Array length mismatch");
        require(count > 0, "Empty batch");
        require(count <= MAX_BATCH_SIZE, "Batch too large");
        require(msg.value >= registrationFee * count, "Insufficient total fee");

        bytes32[] memory ids = new bytes32[](count);

        for (uint256 i = 0; i < count; i++) {
            require(bytes(names[i]).length > 0 && bytes(names[i]).length <= 64, "Invalid name length");

            bytes32 agentId = keccak256(abi.encodePacked(msg.sender, names[i], block.timestamp, i));

            require(agents[agentId].registeredAt == 0, "Agent exists in batch");

            agents[agentId] = Agent({
                owner: msg.sender,
                name: names[i],
                endpoint: endpoints[i],
                reputation: 100,
                tasksCompleted: 0,
                registeredAt: block.timestamp,
                active: true
            });

            ownerAgents[msg.sender].push(agentId);
            agentIds.push(agentId);

            emit AgentRegistered(agentId, msg.sender, names[i]);
            ids[i] = agentId;
        }

        return ids;
    }

    function deactivateAgent(bytes32 agentId) external {
        require(agents[agentId].owner == msg.sender, "Not agent owner");
        agents[agentId].active = false;
        emit AgentDeactivated(agentId);
    }

    function updateReputation(bytes32 agentId, int256 delta) external onlyOwner {
        Agent storage agent = agents[agentId];
        require(agent.registeredAt > 0, "Agent not found");

        if (delta > 0) {
            agent.reputation += uint256(delta);
        } else {
            uint256 decrease = uint256(-delta);
            agent.reputation = agent.reputation > decrease ? agent.reputation - decrease : 0;
        }

        emit ReputationUpdated(agentId, agent.reputation);
    }

    function getAgent(bytes32 agentId) external view returns (Agent memory) {
        return agents[agentId];
    }

    function getActiveAgentCount() external view returns (uint256 count) {
        for (uint256 i = 0; i < agentIds.length; i++) {
            if (agents[agentIds[i]].active) count++;
        }
    }

    function setRegistrationFee(uint256 _fee) external onlyOwner {
        registrationFee = _fee;
    }

    function withdrawFees() external onlyOwner {
        (bool success, ) = owner().call{value: address(this).balance}("");
        require(success, "Withdraw failed");
    }
}
