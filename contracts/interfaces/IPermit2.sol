// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title IPermit2
/// @notice Minimal interface for Permit2's permitTransferFrom
/// @dev Canonical Permit2 address: 0x000000000022D473030F116dDEE9F6B43aC78BA3
interface IPermit2 {
    /// @notice The token permissions struct
    struct TokenPermissions {
        address token;
        uint256 amount;
    }

    /// @notice The permit transfer from struct
    struct PermitTransferFrom {
        TokenPermissions permitted;
        uint256 nonce;
        uint256 deadline;
    }

    /// @notice The signature transfer details struct
    struct SignatureTransferDetails {
        address to;
        uint256 requestedAmount;
    }

    /// @notice Transfer tokens from owner using a permit signature
    /// @param permit The permit data including token, amount, nonce, and deadline
    /// @param transferDetails The transfer details including recipient and amount
    /// @param owner The owner of the tokens
    /// @param signature The signed permit
    function permitTransferFrom(
        PermitTransferFrom calldata permit,
        SignatureTransferDetails calldata transferDetails,
        address owner,
        bytes calldata signature
    ) external;
}