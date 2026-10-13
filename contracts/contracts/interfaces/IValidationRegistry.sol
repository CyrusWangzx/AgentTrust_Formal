// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

/// @title ERC-8004 Validation Registry interface
/// @notice Verbatim interface from the ERC-8004 "Trustless Agents" specification
///         (Validation Registry section). Field names, order and mutability are not
///         modified - AgentTrust implements this standard rather than inventing its own.
/// @dev    Authoritative reference: https://eips.ethereum.org/EIPS/eip-8004
interface IValidationRegistry {
    /// @notice Emitted when an agent opens a validation request.
    event ValidationRequest(
        address indexed validatorAddress,
        uint256 indexed agentId,
        string requestURI,
        bytes32 indexed requestHash
    );

    /// @notice Emitted when a validator answers a validation request.
    event ValidationResponse(
        address indexed validatorAddress,
        uint256 indexed agentId,
        bytes32 indexed requestHash,
        uint8 response,
        string responseURI,
        bytes32 responseHash,
        string tag
    );

    /// @notice Sets the Identity Registry address. Called once at deployment time.
    function initialize(address identityRegistry_) external;

    /// @notice Requests validation of `agentId` by `validatorAddress`.
    /// @dev MUST be called by the owner or operator of `agentId`.
    ///      `requestHash` identifies the request (keccak256 of the off-chain payload).
    function validationRequest(
        address validatorAddress,
        uint256 agentId,
        string calldata requestURI,
        bytes32 requestHash
    ) external;

    /// @notice Answers a validation request. `response` is 0-100 (0 = failed, 100 = passed).
    /// @dev MUST be called by the `validatorAddress` named in the original request.
    ///      MAY be called multiple times for the same `requestHash`.
    function validationResponse(
        bytes32 requestHash,
        uint8 response,
        string calldata responseURI,
        bytes32 responseHash,
        string calldata tag
    ) external;

    /// @notice Last recorded status of a request.
    function getValidationStatus(bytes32 requestHash)
        external
        view
        returns (
            address validatorAddress,
            uint256 agentId,
            uint8 response,
            bytes32 responseHash,
            string memory tag,
            uint256 lastUpdate
        );

    /// @notice Aggregated validation statistics for an agent.
    /// @param agentId mandatory; `validatorAddresses` and `tag` are optional filters.
    function getSummary(
        uint256 agentId,
        address[] calldata validatorAddresses,
        string calldata tag
    ) external view returns (uint64 count, uint8 averageResponse);

    /// @notice Every request hash opened against `agentId`.
    function getAgentValidations(uint256 agentId) external view returns (bytes32[] memory requestHashes);

    /// @notice Every request hash assigned to `validatorAddress`.
    function getValidatorRequests(address validatorAddress)
        external
        view
        returns (bytes32[] memory requestHashes);

    /// @notice Address of the Identity Registry this Validation Registry is bound to.
    function getIdentityRegistry() external view returns (address);
}
