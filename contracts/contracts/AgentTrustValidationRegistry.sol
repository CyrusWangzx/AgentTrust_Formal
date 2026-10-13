// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {IValidationRegistry} from "./interfaces/IValidationRegistry.sol";
import {IIdentityRegistry} from "./interfaces/IIdentityRegistry.sol";
import {DivergenceLib} from "./libraries/DivergenceLib.sol";

/// @title AgentTrust Validation Registry
/// @notice An ERC-8004 Validation Registry implementation whose "validator" is not a single
///         staked party but a *cohort of 3-5 heterogeneous validation agents* that rehearse a
///         task independently before it executes.
///
///         Division of labour (spec 2.1): the divergence maths runs off-chain in deterministic
///         Python; this contract stores the per-validator verdicts, the divergence readings and
///         the final decision, and independently re-derives the decision from `D_rel` so the
///         orchestrator cannot claim an outcome the frozen thresholds do not support.
///
/// @dev Implements the ERC-8004 Validation Registry surface verbatim (single-validator path)
///      and adds the cohort path. Both paths emit the standard `ValidationRequest` /
///      `ValidationResponse` events, so ERC-8004 indexers see a uniform stream.
contract AgentTrustValidationRegistry is IValidationRegistry {
    // ------------------------------------------------------------------ constants
    /// @notice A cohort of 3-5 agents is the target (spec 2.2). Two is the recorded floor,
    ///         so a degraded run is still auditable instead of silently dropped.
    uint8 public constant MIN_COHORT_SIZE = 2;
    uint8 public constant MAX_COHORT_SIZE = 5;

    /// @notice ERC-8004 caps the response at 100.
    uint8 public constant MAX_RESPONSE = 100;

    /// @notice Default number of rehearsal rounds (spec 2.4, K = 3).
    uint8 public constant DEFAULT_K_ROUNDS = 3;

    /// @notice Largest supported number of ranked objects for the Kendall's W significance
    ///         lookup (df = rankedObjects - 1 must be <= 12).
    uint8 public constant MAX_RANKED_OBJECTS = 13;

    // ------------------------------------------------------------------ types
    /// @notice The divergence readings recorded alongside a decision (all x1000).
    struct DivergenceInput {
        uint16 dDiscMilli;
        uint16 dTrajMilli;
        uint16 dEndMilli;
        uint16 dTotalMilli;
        uint16 dRelMilli;
        uint16 kendallWMilli;
        uint32 chiSquareMilli;
    }

    /// @notice One validation agent's verdict inside a cohort round.
    struct VoterVerdict {
        address validator;
        uint8 response;      // ERC-8004 response, 0..100
        bytes32 verdictHash; // commitment to the agent's structured VerdictJSON
        string verdictURI;   // off-chain rehearsal artifact
        string tag;          // ERC-8004 tag, e.g. "soft" / "hard"
        uint16 dDiscMilli;   // per-verdict layer magnitudes, x1000
        uint16 dTrajMilli;
        uint16 dEndMilli;
        uint64 submittedAt;
    }

    /// @notice The full AgentTrust record for one cohort validation request.
    struct ValidationRecord {
        uint256 agentId;
        address requester;
        string requestURI;
        uint16 dBaseMilli;
        uint8 cohortSize;
        uint8 kRounds;
        uint8 roundsRun;
        bool finalized;
        uint8 decision;
        DivergenceInput divergence;
        uint64 openedAt;
        uint64 finalizedAt;
    }

    /// @notice State of a request opened through the standard single-validator path.
    struct StandardRequest {
        address validatorAddress;
        uint256 agentId;
        string requestURI;
        uint8 response;
        bytes32 responseHash;
        string tag;
        uint64 lastUpdate;
        bool exists;
    }

    // ------------------------------------------------------------------ storage
    /// @notice The Identity Registry this Validation Registry is bound to (ERC-8004).
    address public identityRegistry;

    /// @notice Contract owner: may grant/revoke relayer rights and change `kRounds`.
    address public owner;

    /// @notice Default K used for new cohort requests (spec 2.4).
    uint8 public kRounds = DEFAULT_K_ROUNDS;

    /// @notice Addresses allowed to finalise on behalf of a requester (the orchestrator).
    mapping(address => bool) public isOrchestrator;

    mapping(bytes32 => ValidationRecord) private _records;
    mapping(bytes32 => VoterVerdict[]) private _cohortVerdicts;
    mapping(bytes32 => address[]) private _cohort;
    mapping(bytes32 => mapping(address => bool)) private _hasVoted;

    mapping(bytes32 => StandardRequest) private _standard;
    mapping(uint256 => bytes32[]) private _agentValidations;
    mapping(address => bytes32[]) private _validatorRequests;

    bool private _initialized;

    // ------------------------------------------------------------------ events
    /// @notice AgentTrust-specific: a cohort request was opened.
    event CohortValidationOpened(
        bytes32 indexed requestHash,
        uint256 indexed agentId,
        address indexed requester,
        uint8 cohortSize,
        uint8 kRounds,
        uint16 dBaseMilli,
        string requestURI
    );

    /// @notice AgentTrust-specific: one cohort verdict was recorded.
    event VerdictRecorded(
        bytes32 indexed requestHash,
        address indexed validator,
        uint8 response,
        bytes32 verdictHash,
        string verdictURI,
        string tag,
        uint16 dDiscMilli,
        uint16 dTrajMilli,
        uint16 dEndMilli
    );

    /// @notice AgentTrust-specific: the round produced a decision and the divergence reading.
    event DivergenceRecorded(
        bytes32 indexed requestHash,
        uint16 dDiscMilli,
        uint16 dTrajMilli,
        uint16 dEndMilli,
        uint16 dTotalMilli,
        uint16 dRelMilli,
        uint16 kendallWMilli,
        uint32 chiSquareMilli
    );

    /// @notice AgentTrust-specific: the request reached a terminal decision.
    event ValidationFinalized(
        bytes32 indexed requestHash,
        uint256 indexed agentId,
        uint8 decision,
        uint8 roundsRun,
        uint8 rankedObjects
    );

    event OrchestratorUpdated(address indexed orchestrator, bool allowed);
    event KRoundsUpdated(uint8 kRounds);

    // ------------------------------------------------------------------ errors
    error AlreadyInitialized();
    error NotInitialized();
    error ZeroAddress();
    error InvalidAgentOperator(uint256 agentId, address caller);
    error RequestAlreadyExists(bytes32 requestHash);
    error UnknownRequest(bytes32 requestHash);
    error CohortSizeOutOfRange(uint256 provided);
    error DuplicateCohortMember(address member);
    error NotACohortMember(bytes32 requestHash, address caller);
    error AlreadyVoted(bytes32 requestHash, address validator);
    error NotRequesterOrOrchestrator(address caller);
    error AlreadyFinalized(bytes32 requestHash);
    error IncompleteCohort(uint256 recorded, uint256 required, uint8 roundsRun, uint8 kRounds);
    error ResponseOutOfRange(uint8 response);
    error RankedObjectsOutOfRange(uint8 rankedObjects);
    error InvalidDecision(uint8 decision);

    // ------------------------------------------------------------------ modifiers
    modifier onlyOwner() {
        if (msg.sender != owner) revert NotRequesterOrOrchestrator(msg.sender);
        _;
    }

    modifier initialized() {
        if (identityRegistry == address(0) && !_initialized) revert NotInitialized();
        _;
    }

    // ------------------------------------------------------------------ setup
    /// @notice Binds this registry to an Identity Registry (ERC-8004 `initialize`).
    /// @param identityRegistry_ Identity Registry address. May be `address(0)` for a
    ///        standalone deployment, in which case agent-operator checks are skipped and
    ///        `identityCheckBypassed()` reports `true`.
    function initialize(address identityRegistry_) external override {
        if (_initialized) revert AlreadyInitialized();
        _initialized = true;
        owner = msg.sender;
        identityRegistry = identityRegistry_;
        emit OrchestratorUpdated(msg.sender, true);
        isOrchestrator[msg.sender] = true;
    }

    /// @notice `true` when no Identity Registry is bound, so ownership checks are skipped.
    function identityCheckBypassed() external view returns (bool) {
        return identityRegistry == address(0);
    }

    /// @notice Grants or revokes the right to finalise on a requester's behalf.
    function setOrchestrator(address orchestrator, bool allowed) external onlyOwner {
        if (orchestrator == address(0)) revert ZeroAddress();
        isOrchestrator[orchestrator] = allowed;
        emit OrchestratorUpdated(orchestrator, allowed);
    }

    /// @notice Sets the default K for new cohort requests. Does not affect open requests.
    function setKRounds(uint8 newK) external onlyOwner {
        require(newK >= 1 && newK <= 10, "kRounds out of range");
        kRounds = newK;
        emit KRoundsUpdated(newK);
    }

    // ================================================================== ERC-8004 surface
    /// @inheritdoc IValidationRegistry
    function getIdentityRegistry() external view override returns (address) {
        return identityRegistry;
    }

    /// @inheritdoc IValidationRegistry
    /// @dev Single-validator path. AgentTrust's cohort path is `openCohortValidation`; this
    ///      exists so the registry is a drop-in ERC-8004 Validation Registry.
    function validationRequest(
        address validatorAddress,
        uint256 agentId,
        string calldata requestURI,
        bytes32 requestHash
    ) external override initialized {
        if (validatorAddress == address(0)) revert ZeroAddress();
        if (_standard[requestHash].exists || _records[requestHash].requester != address(0)) {
            revert RequestAlreadyExists(requestHash);
        }
        _requireAgentOperator(agentId, msg.sender);

        _standard[requestHash] = StandardRequest({
            validatorAddress: validatorAddress,
            agentId: agentId,
            requestURI: requestURI,
            response: 0,
            responseHash: bytes32(0),
            tag: "",
            lastUpdate: uint64(block.timestamp),
            exists: true
        });
        _agentValidations[agentId].push(requestHash);
        _validatorRequests[validatorAddress].push(requestHash);

        emit ValidationRequest(validatorAddress, agentId, requestURI, requestHash);
    }

    /// @inheritdoc IValidationRegistry
    function validationResponse(
        bytes32 requestHash,
        uint8 response,
        string calldata responseURI,
        bytes32 responseHash,
        string calldata tag
    ) external override initialized {
        StandardRequest storage request = _standard[requestHash];
        if (!request.exists) revert UnknownRequest(requestHash);
        if (msg.sender != request.validatorAddress) {
            revert NotACohortMember(requestHash, msg.sender);
        }
        if (response > MAX_RESPONSE) revert ResponseOutOfRange(response);

        request.response = response;
        request.responseHash = responseHash;
        request.tag = tag;
        request.lastUpdate = uint64(block.timestamp);

        emit ValidationResponse(
            msg.sender, request.agentId, requestHash, response, responseURI, responseHash, tag
        );
    }

    /// @inheritdoc IValidationRegistry
    /// @dev Resolves either path: a standard single-validator request, else the most recent
    ///      cohort verdict. This keeps indexers working across both.
    function getValidationStatus(bytes32 requestHash)
        external
        view
        override
        returns (
            address validatorAddress,
            uint256 agentId,
            uint8 response,
            bytes32 responseHash,
            string memory tag,
            uint256 lastUpdate
        )
    {
        StandardRequest storage request = _standard[requestHash];
        if (request.exists) {
            return (
                request.validatorAddress,
                request.agentId,
                request.response,
                request.responseHash,
                request.tag,
                request.lastUpdate
            );
        }
        ValidationRecord storage record = _records[requestHash];
        if (record.requester == address(0)) revert UnknownRequest(requestHash);
        VoterVerdict[] storage verdicts = _cohortVerdicts[requestHash];
        if (verdicts.length == 0) {
            return (address(0), record.agentId, 0, bytes32(0), "", record.openedAt);
        }
        VoterVerdict storage last = verdicts[verdicts.length - 1];
        return (
            last.validator,
            record.agentId,
            last.response,
            last.verdictHash,
            last.tag,
            last.submittedAt
        );
    }

    /// @inheritdoc IValidationRegistry
    /// @dev Averages ERC-8004 responses across every request recorded against `agentId`,
    ///      optionally filtered by validator set and tag. The accumulation is split across
    ///      private helpers because a single-pass loop over both request paths overflows the
    ///      EVM stack ("stack too deep") under the 0.8.24 codegen.
    function getSummary(
        uint256 agentId,
        address[] calldata validatorAddresses,
        string calldata tag
    ) external view override returns (uint64 count, uint8 averageResponse) {
        (uint256 total, uint64 n) = _summarise(agentId, validatorAddresses, tag);
        count = n;
        averageResponse = n == 0 ? 0 : uint8(total / n);
    }

    /// @inheritdoc IValidationRegistry
    function getAgentValidations(uint256 agentId)
        external
        view
        override
        returns (bytes32[] memory requestHashes)
    {
        return _agentValidations[agentId];
    }

    /// @inheritdoc IValidationRegistry
    function getValidatorRequests(address validatorAddress)
        external
        view
        override
        returns (bytes32[] memory requestHashes)
    {
        return _validatorRequests[validatorAddress];
    }

    // ================================================================== cohort surface
    /// @notice Opens a cohort validation request: 3-5 heterogeneous agents will rehearse
    ///         `requestURI` independently and each submit a verdict.
    /// @param requestHash ERC-8004 request commitment (keccak256 of the off-chain payload).
    ///        Doubles as AgentTrust's `validationId`.
    /// @param agentId The agent whose execution is being validated (ERC-8004 `agentId`).
    /// @param requestURI Pointer to the off-chain task payload.
    /// @param dBaseMilli Baseline difficulty `D_base` x1000. `0` is allowed and means the
    ///        baseline is unavailable, which forces an INSUFFICIENT_BASELINE decision.
    /// @param kRounds_ Maximum rehearsal rounds before escalating to a human. `0` uses the
    ///        contract default of 3.
    /// @param cohort The validation agent addresses. Must be `MIN_COHORT_SIZE..MAX_COHORT_SIZE`
    ///        and free of duplicates.
    function openCohortValidation(
        bytes32 requestHash,
        uint256 agentId,
        string calldata requestURI,
        uint16 dBaseMilli,
        uint8 kRounds_,
        address[] calldata cohort
    ) external initialized {
        if (_records[requestHash].requester != address(0) || _standard[requestHash].exists) {
            revert RequestAlreadyExists(requestHash);
        }
        if (cohort.length < MIN_COHORT_SIZE || cohort.length > MAX_COHORT_SIZE) {
            revert CohortSizeOutOfRange(cohort.length);
        }
        _requireAgentOperator(agentId, msg.sender);

        for (uint256 i = 0; i < cohort.length; i++) {
            address member = cohort[i];
            if (member == address(0)) revert ZeroAddress();
            for (uint256 j = i + 1; j < cohort.length; j++) {
                if (cohort[j] == member) revert DuplicateCohortMember(member);
            }
            _cohort[requestHash].push(member);
            _validatorRequests[member].push(requestHash);
            // The requester names each validator, so the standard event is emitted per member.
            emit ValidationRequest(member, agentId, requestURI, requestHash);
        }

        uint8 resolvedK = kRounds_ == 0 ? kRounds : kRounds_;
        _records[requestHash] = ValidationRecord({
            agentId: agentId,
            requester: msg.sender,
            requestURI: requestURI,
            dBaseMilli: dBaseMilli,
            cohortSize: uint8(cohort.length),
            kRounds: resolvedK,
            roundsRun: 0,
            finalized: false,
            decision: DivergenceLib.DECISION_NONE,
            divergence: DivergenceInput(0, 0, 0, 0, 0, 0, 0),
            openedAt: uint64(block.timestamp),
            finalizedAt: 0
        });
        _agentValidations[agentId].push(requestHash);

        emit CohortValidationOpened(
            requestHash, agentId, msg.sender, uint8(cohort.length), resolvedK, dBaseMilli, requestURI
        );
    }

    /// @notice Records one cohort member's verdict. Callable directly by that member.
    /// @param requestHash The request being answered.
    /// @param response ERC-8004 response score, 0..100.
    /// @param verdictHash Commitment to the agent's structured VerdictJSON.
    /// @param verdictURI Off-chain location of the rehearsal artifact.
    /// @param tag ERC-8004 tag, `soft` for round 1 and typically `hard` after a re-run.
    /// @param dDiscMilli Per-verdict action-layer magnitude x1000 (audit metadata).
    /// @param dTrajMilli Per-verdict trajectory-layer magnitude x1000 (audit metadata).
    /// @param dEndMilli Per-verdict terminal-layer magnitude x1000 (audit metadata).
    function submitCohortVerdict(
        bytes32 requestHash,
        uint8 response,
        bytes32 verdictHash,
        string calldata verdictURI,
        string calldata tag,
        uint16 dDiscMilli,
        uint16 dTrajMilli,
        uint16 dEndMilli
    ) external {
        _recordVerdict(
            requestHash, msg.sender, response, verdictHash, verdictURI, tag,
            dDiscMilli, dTrajMilli, dEndMilli
        );
    }

    /// @notice Relayed verdict: the orchestrator submits a verdict signed by a cohort member,
    ///         so validation agents do not need to hold gas.
    /// @dev Verifies an EIP-191 `personal_sign` signature by `validator` over
    ///      `keccak256(abi.encode(requestHash, validator, response, verdictHash))`.
    function attestCohortVerdict(
        bytes32 requestHash,
        address validator,
        uint8 response,
        bytes32 verdictHash,
        string calldata verdictURI,
        string calldata tag,
        uint16 dDiscMilli,
        uint16 dTrajMilli,
        uint16 dEndMilli,
        bytes calldata signature
    ) external {
        bytes32 digest = keccak256(abi.encode(requestHash, validator, response, verdictHash));
        if (_recover(digest, signature) != validator) {
            revert NotACohortMember(requestHash, validator);
        }
        _recordVerdict(
            requestHash, validator, response, verdictHash, verdictURI, tag,
            dDiscMilli, dTrajMilli, dEndMilli
        );
    }

    /// @notice Finalises a cohort request once the cohort has answered or K rounds are spent.
    ///
    /// @dev This is where the frozen thresholds are enforced on-chain. The contract:
    ///      1. rejects a claimed decision the `D_rel` band does not imply;
    ///      2. recomputes the Kendall's W significance test itself from the chi-square lookup,
    ///         so the caller cannot pick the branch;
    ///      3. forces INSUFFICIENT_VALIDATORS when fewer than `MIN_COHORT_SIZE` verdicts exist;
    ///      4. forces INSUFFICIENT_BASELINE when `D_base` is zero (spec 2.3's divide-by-zero).
    ///
    /// @param requestHash The request to finalise.
    /// @param decision Claimed decision ordinal (see `DivergenceLib.DECISION_*`).
    /// @param roundsRun How many rehearsal rounds were executed.
    /// @param rankedObjects `n` for the Kendall's W significance test. Degrees of freedom are
    ///        `n - 1` and must be `<= 12` (the on-chain lookup table range).
    /// @param divergence The divergence readings for the final round.
    function finalizeValidation(
        bytes32 requestHash,
        uint8 decision,
        uint8 roundsRun,
        uint8 rankedObjects,
        DivergenceInput calldata divergence
    ) external {
        ValidationRecord storage record = _records[requestHash];
        if (record.requester == address(0)) revert UnknownRequest(requestHash);
        if (record.finalized) revert AlreadyFinalized(requestHash);
        if (msg.sender != record.requester && !isOrchestrator[msg.sender]) {
            revert NotRequesterOrOrchestrator(msg.sender);
        }
        if (rankedObjects < 2 || rankedObjects > MAX_RANKED_OBJECTS) {
            revert RankedObjectsOutOfRange(rankedObjects);
        }

        uint256 recorded = _cohortVerdicts[requestHash].length;
        bool cohortComplete = recorded >= record.cohortSize;
        bool roundsSpent = roundsRun >= record.kRounds;
        if (!cohortComplete && !roundsSpent) {
            revert IncompleteCohort(recorded, record.cohortSize, roundsRun, record.kRounds);
        }

        if (recorded < MIN_COHORT_SIZE) {
            // Failing closed: not enough independent witnesses to reach any decision.
            if (decision != DivergenceLib.DECISION_INSUFFICIENT_VALIDATORS) {
                revert DivergenceLib.DecisionMismatch(
                    decision, DivergenceLib.DECISION_INSUFFICIENT_VALIDATORS
                );
            }
        } else if (record.dBaseMilli == 0) {
            if (decision != DivergenceLib.DECISION_INSUFFICIENT_BASELINE) {
                revert DivergenceLib.DecisionMismatch(
                    decision, DivergenceLib.DECISION_INSUFFICIENT_BASELINE
                );
            }
        } else {
            bool significant = divergence.chiSquareMilli
                > uint32(DivergenceLib.chi2CriticalMilli(rankedObjects - 1));
            DivergenceLib.requireDecision(divergence.dRelMilli, significant, decision);
        }

        record.finalized = true;
        record.decision = decision;
        record.roundsRun = roundsRun;
        record.divergence = divergence;
        record.finalizedAt = uint64(block.timestamp);

        emit DivergenceRecorded(
            requestHash,
            divergence.dDiscMilli,
            divergence.dTrajMilli,
            divergence.dEndMilli,
            divergence.dTotalMilli,
            divergence.dRelMilli,
            divergence.kendallWMilli,
            divergence.chiSquareMilli
        );
        emit ValidationFinalized(requestHash, record.agentId, decision, roundsRun, rankedObjects);
    }

    // ================================================================== views for the panel
    /// @notice Full AgentTrust record for a request.
    function getValidationRecord(bytes32 requestHash)
        external
        view
        returns (ValidationRecord memory)
    {
        ValidationRecord memory record = _records[requestHash];
        if (record.requester == address(0)) revert UnknownRequest(requestHash);
        return record;
    }

    /// @notice The cohort addresses named for a request.
    function getCohort(bytes32 requestHash) external view returns (address[] memory) {
        return _cohort[requestHash];
    }

    /// @notice Every verdict recorded for a request, in submission order.
    function getCohortVerdicts(bytes32 requestHash)
        external
        view
        returns (VoterVerdict[] memory)
    {
        return _cohortVerdicts[requestHash];
    }

    /// @notice Convenience: the terminal decision ordinal, or 0 when not finalised.
    function decisionOf(bytes32 requestHash) external view returns (uint8) {
        return _records[requestHash].decision;
    }

    /// @notice Convenience: `D_rel` x1000, or 0 when not finalised.
    function relativeDivergenceOf(bytes32 requestHash) external view returns (uint16) {
        return _records[requestHash].divergence.dRelMilli;
    }

    /// @notice The frozen weights, exposed so the panel can print the formula from chain state.
    function weightsMilli() external pure returns (uint16 w1, uint16 w2, uint16 w3) {
        return (
            DivergenceLib.W1_DISC_MILLI,
            DivergenceLib.W2_TRAJ_MILLI,
            DivergenceLib.W3_END_MILLI
        );
    }

    /// @notice The frozen thresholds, exposed for the same reason.
    function thresholdsMilli() external pure returns (uint16 thetaLow, uint16 thetaHigh) {
        return (DivergenceLib.THETA_LOW_MILLI, DivergenceLib.THETA_HIGH_MILLI);
    }

    // ================================================================== internals
    function _recordVerdict(
        bytes32 requestHash,
        address validator,
        uint8 response,
        bytes32 verdictHash,
        string calldata verdictURI,
        string calldata tag,
        uint16 dDiscMilli,
        uint16 dTrajMilli,
        uint16 dEndMilli
    ) private {
        ValidationRecord storage record = _records[requestHash];
        if (record.requester == address(0)) revert UnknownRequest(requestHash);
        if (record.finalized) revert AlreadyFinalized(requestHash);
        if (!_isCohortMember(requestHash, validator)) {
            revert NotACohortMember(requestHash, validator);
        }
        if (_hasVoted[requestHash][validator]) revert AlreadyVoted(requestHash, validator);
        if (response > MAX_RESPONSE) revert ResponseOutOfRange(response);
        if (_cohortVerdicts[requestHash].length >= record.cohortSize) {
            revert IncompleteCohort(
                _cohortVerdicts[requestHash].length, record.cohortSize, record.roundsRun, record.kRounds
            );
        }

        _hasVoted[requestHash][validator] = true;
        _cohortVerdicts[requestHash].push(
            VoterVerdict({
                validator: validator,
                response: response,
                verdictHash: verdictHash,
                verdictURI: verdictURI,
                tag: tag,
                dDiscMilli: dDiscMilli,
                dTrajMilli: dTrajMilli,
                dEndMilli: dEndMilli,
                submittedAt: uint64(block.timestamp)
            })
        );

        // Emit the standard ERC-8004 event so generic indexers pick cohort verdicts up too.
        emit ValidationResponse(
            validator, record.agentId, requestHash, response, verdictURI, verdictHash, tag
        );
        emit VerdictRecorded(
            requestHash, validator, response, verdictHash, verdictURI, tag,
            dDiscMilli, dTrajMilli, dEndMilli
        );
    }

    /// @dev Enforces ERC-8004's "owner or operator of agentId" rule when an Identity Registry
    ///      is bound. Without one the check cannot be made, and
    ///      `identityCheckBypassed()` says so explicitly rather than pretending it passed.
    function _requireAgentOperator(uint256 agentId, address caller) private view {
        address registry = identityRegistry;
        if (registry == address(0)) return;
        IIdentityRegistry identity = IIdentityRegistry(registry);
        address agentOwner = identity.ownerOf(agentId);
        if (caller == agentOwner) return;
        if (identity.getApproved(agentId) == caller) return;
        if (identity.isApprovedForAll(agentOwner, caller)) return;
        revert InvalidAgentOperator(agentId, caller);
    }

    function _isCohortMember(bytes32 requestHash, address candidate) private view returns (bool) {
        address[] storage members = _cohort[requestHash];
        for (uint256 i = 0; i < members.length; i++) {
            if (members[i] == candidate) return true;
        }
        return false;
    }

    /// @dev `true` when `needle` passes the optional validator filter. An empty filter
    ///      means "no filter", which is why it returns `true` rather than `false`.
    function _passesValidatorFilter(address[] calldata haystack, address needle)
        private
        pure
        returns (bool)
    {
        if (haystack.length == 0) return true;
        for (uint256 i = 0; i < haystack.length; i++) {
            if (haystack[i] == needle) return true;
        }
        return false;
    }

    /// @dev Accumulates `(sum of responses, count)` across both request paths for `agentId`.
    function _summarise(
        uint256 agentId,
        address[] calldata validatorAddresses,
        string calldata tag
    ) private view returns (uint256 total, uint64 n) {
        bytes32[] storage hashes = _agentValidations[agentId];
        for (uint256 i = 0; i < hashes.length; i++) {
            (uint256 subtotal, uint64 subcount) = _summariseRequest(hashes[i], validatorAddresses, tag);
            total += subtotal;
            n += subcount;
        }
    }

    function _summariseRequest(
        bytes32 requestHash,
        address[] calldata validatorAddresses,
        string calldata tag
    ) private view returns (uint256 total, uint64 n) {
        StandardRequest storage request = _standard[requestHash];
        if (request.exists) {
            if (bytes(request.tag).length == 0) return (0, 0); // not yet answered
            if (keccak256(bytes(request.tag)) != keccak256(bytes(tag)) && bytes(tag).length > 0) {
                return (0, 0);
            }
            if (!_passesValidatorFilter(validatorAddresses, request.validatorAddress)) return (0, 0);
            return (request.response, 1);
        }
        VoterVerdict[] storage verdicts = _cohortVerdicts[requestHash];
        for (uint256 j = 0; j < verdicts.length; j++) {
            if (bytes(tag).length > 0 && keccak256(bytes(verdicts[j].tag)) != keccak256(bytes(tag))) {
                continue;
            }
            if (!_passesValidatorFilter(validatorAddresses, verdicts[j].validator)) continue;
            total += verdicts[j].response;
            n += 1;
        }
    }

    /// @dev EIP-191 personal-sign recovery.
    function _recover(bytes32 digest, bytes calldata signature) private pure returns (address) {
        if (signature.length != 65) revert NotACohortMember(bytes32(0), address(0));
        bytes32 r;
        bytes32 s;
        uint8 v;
        // solhint-disable-next-line no-inline-assembly
        assembly {
            r := calldataload(signature.offset)
            s := calldataload(add(signature.offset, 32))
            v := byte(0, calldataload(add(signature.offset, 64)))
        }
        bytes32 prefixed = keccak256(abi.encodePacked("\x19Ethereum Signed Message:\n32", digest));
        return ecrecover(prefixed, v, r, s);
    }
}
