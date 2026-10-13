// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {IIdentityRegistry} from "../interfaces/IIdentityRegistry.sol";

/// @title MockIdentityRegistry
/// @notice Minimal ERC-8004 Identity Registry used by the tests and by a first testnet
///         deployment so the Validation Registry's agent-operator check has something real to
///         query. Mirrors the ERC-721 ownership surface the spec relies on.
/// @dev Test/demo infrastructure. ERC-8004's production Identity Registry is a deployed
///      singleton per chain; point `IDENTITY_REGISTRY_ADDRESS` at it instead of this mock.
contract MockIdentityRegistry is IIdentityRegistry {
    event AgentRegistered(uint256 indexed agentId, address indexed owner, string agentURI);

    uint256 public nextAgentId = 1;

    mapping(uint256 => address) private _owners;
    mapping(uint256 => address) private _approvals;
    mapping(address => mapping(address => bool)) private _operatorApprovals;
    mapping(uint256 => string) private _agentURIs;
    mapping(uint256 => address) private _agentWallets;

    /// @notice Mints a new agent id owned by `to`.
    function register(address to, string calldata agentURI) external returns (uint256 agentId) {
        require(to != address(0), "owner required");
        agentId = nextAgentId++;
        _owners[agentId] = to;
        _agentURIs[agentId] = agentURI;
        _agentWallets[agentId] = to;
        emit AgentRegistered(agentId, to, agentURI);
    }

    function setApprovalForAll(address operator, bool approved) external {
        _operatorApprovals[msg.sender][operator] = approved;
    }

    function approve(address spender, uint256 agentId) external {
        require(_owners[agentId] == msg.sender, "not owner");
        _approvals[agentId] = spender;
    }

    function ownerOf(uint256 agentId) external view override returns (address) {
        address agentOwner = _owners[agentId];
        require(agentOwner != address(0), "unknown agent");
        return agentOwner;
    }

    function getApproved(uint256 agentId) external view override returns (address) {
        return _approvals[agentId];
    }

    function isApprovedForAll(address owner, address operator)
        external
        view
        override
        returns (bool)
    {
        return _operatorApprovals[owner][operator];
    }

    function getAgentWallet(uint256 agentId) external view override returns (address) {
        return _agentWallets[agentId];
    }

    function agentURIOf(uint256 agentId) external view returns (string memory) {
        return _agentURIs[agentId];
    }
}
