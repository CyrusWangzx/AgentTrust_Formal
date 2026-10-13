// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {DivergenceLib} from "../libraries/DivergenceLib.sol";

/// @title DivergenceLibHarness
/// @notice Exposes `DivergenceLib`'s internal pure functions so the tests can assert the
///         on-chain constants and decision rule against the off-chain Python values.
/// @dev Test-only. Keeps `DivergenceLib` `internal` so no extra gas or surface ships with it.
contract DivergenceLibHarness {
    function total(uint16 dDiscMilli, uint16 dTrajMilli, uint16 dEndMilli) external pure returns (uint16) {
        return DivergenceLib.total(dDiscMilli, dTrajMilli, dEndMilli);
    }

    function relative(uint16 dTotalMilli, uint16 dBaseMilli) external pure returns (uint16) {
        return DivergenceLib.relative(dTotalMilli, dBaseMilli);
    }

    function decide(uint16 dRelMilli, bool concordanceSignificant) external pure returns (uint8) {
        return DivergenceLib.decide(dRelMilli, concordanceSignificant);
    }

    function band(uint16 dRelMilli) external pure returns (uint8) {
        return DivergenceLib.band(dRelMilli);
    }

    function chi2CriticalMilli(uint32 df) external pure returns (uint16) {
        return DivergenceLib.chi2CriticalMilli(df);
    }

    function constants()
        external
        pure
        returns (
            uint16 w1,
            uint16 w2,
            uint16 w3,
            uint16 thetaLow,
            uint16 thetaHigh,
            uint8 approved,
            uint8 rejected,
            uint8 escalated,
            uint8 insufficientValidators,
            uint8 insufficientBaseline
        )
    {
        return (
            DivergenceLib.W1_DISC_MILLI,
            DivergenceLib.W2_TRAJ_MILLI,
            DivergenceLib.W3_END_MILLI,
            DivergenceLib.THETA_LOW_MILLI,
            DivergenceLib.THETA_HIGH_MILLI,
            DivergenceLib.DECISION_APPROVED,
            DivergenceLib.DECISION_REJECTED,
            DivergenceLib.DECISION_ESCALATED,
            DivergenceLib.DECISION_INSUFFICIENT_VALIDATORS,
            DivergenceLib.DECISION_INSUFFICIENT_BASELINE
        );
    }
}
