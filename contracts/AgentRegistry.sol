// @contributor: Hermes Agent @jjb9707
// @date: 2026-05-29T16:00:00Z
// @session-init: 任务: ClankerNation/OpenAgents #172 AgentRegistry frontrun fix
// @runtime: os=Linux arch=x86_64 home=/home/jjb wd=/tmp/clanker-fork-110 shell=/bin/bash
// SPDX-License-Identifier: MIT
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

    /// @dev Counter for generating unique agent IDs (prevents frontrun collisions).
    uint256 public agentCounter;

    event AgentRegistered(bytes32 indexed agentId, address indexed owner, string name);
    event AgentDeactivated(bytes32 indexed agentId);
    event ReputationUpdated(bytes32 indexed agentId, uint256 newReputation);

    constructor(uint256 _registrationFee) Ownable(msg.sender) {
        registrationFee = _registrationFee;
        minReputation = 0;
        agentCounter = 0;
    }

    function registerAgent(string calldata name, string calldata endpoint) external payable returns (bytes32) {
        require(msg.value >= registrationFee, "Insufficient fee");
        require(bytes(name).length > 0 && bytes(name).length <= 64, "Invalid name");

        // Use incrementing counter to prevent frontrun collisions:
        // two registrations in the same block with the same name get different IDs.
        agentCounter++;
        bytes32 agentId = keccak256(abi.encodePacked(block.chainid, address(this), agentCounter));

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
