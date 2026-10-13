// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

/// @title Minimal Identity Registry interface (ERC-8004)
/// @notice Only the read surface AgentTrust needs: proving who owns an `agentId`.
/// @dev ERC-8004 defines the Identity Registry as ERC-721 with URIStorage, so `ownerOf`
///      and the ERC-721 approval surface are the authoritative ownership signals.
interface IIdentityRegistry {
    function ownerOf(uint256 agentId) external view returns (address);

    function getApproved(uint256 agentId) external view returns (address);

    function isApprovedForAll(address owner, address operator) external view returns (bool);

    function getAgentWallet(uint256 agentId) external view returns (address);
}
