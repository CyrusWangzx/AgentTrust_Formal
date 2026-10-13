// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

/// @title DivergenceLib - the on-chain mirror of the off-chain divergence constants
/// @notice AgentTrust computes divergence off-chain in deterministic Python and stores only the
///         reading plus the final decision on-chain (spec 2.1). This library exists so the
///         *decision rule itself* is verifiable on-chain: `finalizeValidation` recomputes the
///         decision from `D_rel` and reverts when the orchestrator's claimed decision disagrees
///         with what the frozen thresholds imply.
/// @dev All values are fixed-point `milli` integers (value x 1000) because the EVM has no
///      floats. These constants are the on-chain single source of truth for spec 2.3 / 2.4 and
///      are asserted against the Python values in `contracts/test/DivergenceLib.test.js`.
library DivergenceLib {
    /// @notice Aggregation weights `w = (w1, w2, w3)` for (D_disc, D_traj, D_end), x1000.
    uint16 internal constant W1_DISC_MILLI = 400;
    uint16 internal constant W2_TRAJ_MILLI = 300;
    uint16 internal constant W3_END_MILLI = 300;

    /// @notice Decision thresholds on `D_rel`, x1000. Frozen spec values 1.5 and 3.0.
    uint16 internal constant THETA_LOW_MILLI = 1500;
    uint16 internal constant THETA_HIGH_MILLI = 3000;

    /// @notice Decision ordinals written to storage. 0 means "not finalised".
    uint8 internal constant DECISION_NONE = 0;
    uint8 internal constant DECISION_APPROVED = 1;
    uint8 internal constant DECISION_REJECTED = 2;
    uint8 internal constant DECISION_ESCALATED = 3;
    uint8 internal constant DECISION_INSUFFICIENT_VALIDATORS = 4;
    uint8 internal constant DECISION_INSUFFICIENT_BASELINE = 5;

    error InvalidDBase(uint16 dBaseMilli);
    error DecisionMismatch(uint8 claimed, uint8 implied);

    /// @notice `D_total = 0.4*D_disc + 0.3*D_traj + 0.3*D_end`, in milli, rounded to nearest.
    /// @dev Scale arithmetic: both the readings and the weights are x1000, so the numerator is
    ///      `1e6 * sum(w_i * D_i)` -- i.e. 1000x too large for a milli result. Dividing by 1000
    ///      (with +500 for round-half-up) therefore yields `D_total` in milli.
    ///      Intermediates use uint256 to rule out overflow on saturated inputs.
    function total(uint16 dDiscMilli, uint16 dTrajMilli, uint16 dEndMilli)
        internal
        pure
        returns (uint16)
    {
        uint256 numerator = uint256(dDiscMilli) * W1_DISC_MILLI
            + uint256(dTrajMilli) * W2_TRAJ_MILLI
            + uint256(dEndMilli) * W3_END_MILLI;
        uint256 value = (numerator + 500) / 1000;
        return value > type(uint16).max ? type(uint16).max : uint16(value);
    }

    /// @notice `D_rel = D_total / D_base`, in milli.
    /// @dev Reverts instead of dividing by zero: spec 2.3 requires an explicit failure and the
    ///      orchestration layer maps it to the INSUFFICIENT_BASELINE state.
    function relative(uint16 dTotalMilli, uint16 dBaseMilli) internal pure returns (uint16) {
        if (dBaseMilli == 0) revert InvalidDBase(dBaseMilli);
        uint256 value = (uint256(dTotalMilli) * 1e6) / uint256(dBaseMilli) / 1000;
        return value > type(uint16).max ? type(uint16).max : uint16(value);
    }

    /// @notice The terminal decision implied by `D_rel` plus Kendall's W significance.
    ///
    /// @dev Band mapping, and why the mid band maps to Escalated rather than "Rehearse":
    ///
    ///      * `D_rel <= theta_low (1.5)`            -> Approved  (收敛，放行)
    ///      * `theta_low < D_rel <= theta_high (3.0)` -> Escalated (部分收敛，K 轮耗尽后转人工)
    ///      * `D_rel > theta_high`                   -> Escalated when W is significant,
    ///                                                  otherwise Rejected
    ///
    ///      `finalizeValidation` is only reachable once the K-round state machine has
    ///      terminated, so a mid-band reading recorded on-chain means "the cohort never
    ///      converged within K rounds" - which the spec routes to a human. The off-chain
    ///      machine's intermediate `Rehearse` action is a flow state, not a terminal decision,
    ///      and is therefore never written here.
    function decide(uint16 dRelMilli, bool concordanceSignificant) internal pure returns (uint8) {
        if (dRelMilli <= THETA_LOW_MILLI) return DECISION_APPROVED;
        if (dRelMilli <= THETA_HIGH_MILLI) return DECISION_ESCALATED;
        return concordanceSignificant ? DECISION_ESCALATED : DECISION_REJECTED;
    }

    /// @notice Tri-level band of `D_rel`, independent of W. Useful for panels and tests.
    /// @return 0 = approved band, 1 = rehearsal band, 2 = reject band.
    function band(uint16 dRelMilli) internal pure returns (uint8) {
        if (dRelMilli <= THETA_LOW_MILLI) return 0;
        if (dRelMilli <= THETA_HIGH_MILLI) return 1;
        return 2;
    }

    /// @notice Reverts unless `claimed` equals the decision the frozen thresholds imply.
    function requireDecision(uint16 dRelMilli, bool concordanceSignificant, uint8 claimed)
        internal
        pure
    {
        uint8 implied = decide(dRelMilli, concordanceSignificant);
        if (claimed != implied) revert DecisionMismatch(claimed, implied);
    }

    error DegreesOfFreedomOutOfRange(uint32 df);

    /// @notice Upper-tail chi-square critical value at alpha = 0.05, x1000, for `df` in 1..12.
    ///
    /// @dev Inlined deliberately. The significance test for Kendall's W is
    ///      `chi^2 = m(n-1)W` with `df = n - 1`, and `n` is the number of ranked criteria the
    ///      cohort is ordered on - four in this implementation, so `df` is 3. Publishing the
    ///      table on-chain lets `finalizeValidation` decide the Escalated-vs-Rejected branch
    ///      itself instead of trusting a flag supplied by the caller.
    function chi2CriticalMilli(uint32 df) internal pure returns (uint16) {
        if (df == 0 || df > 12) revert DegreesOfFreedomOutOfRange(df);
        // 3.841  5.991  7.815  9.488 11.070 12.592 14.067 15.507 16.919 18.307 19.675 21.026
        uint16[12] memory table = [
            uint16(3841), 5991, 7815, 9488, 11070, 12592, 14067, 15507, 16919, 18307, 19675, 21026
        ];
        return table[df - 1];
    }
}
