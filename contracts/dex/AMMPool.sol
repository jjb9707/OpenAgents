// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

// @contributor: Hermes Agent @jjb9707
// @date: 2026-05-29T15:30:00Z
// @session-init: 任务: ClankerNation/OpenAgents #163 Permit2 集成
// @runtime: os=Linux arch=x86_64 home=/home/jjb wd=/tmp/clanker-fork-110 shell=/bin/bash

import "../interfaces/IPermit2.sol";

interface IERC20 {
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
    function transfer(address to, uint256 amount) external returns (bool);
    function balanceOf(address account) external view returns (uint256);
}

/// @title AMMPool
/// @notice Constant product (x*y=k) automated market maker pool
/// @dev Supports adding/removing liquidity and token swaps with a fee
contract AMMPool {
    /// @notice Canonical Permit2 address
    address private constant PERMIT2 = 0x000000000022D473030F116dDEE9F6B43aC78BA3;

    IERC20 public tokenA;
    IERC20 public tokenB;

    uint256 public reserveA;
    uint256 public reserveB;
    uint256 public totalLiquidity;
    uint256 public constant FEE_BPS = 30; // 0.3%

    mapping(address => uint256) public liquidity;

    event LiquidityAdded(address indexed provider, uint256 amountA, uint256 amountB, uint256 lpTokens);
    event LiquidityRemoved(address indexed provider, uint256 amountA, uint256 amountB);
    event Swap(address indexed user, address tokenIn, uint256 amountIn, uint256 amountOut);

    constructor(address _tokenA, address _tokenB) {
        tokenA = IERC20(_tokenA);
        tokenB = IERC20(_tokenB);
    }

    // BUG: No minimum liquidity lock — first LP can add tiny liquidity then remove it all,
    // enabling a well-known inflation attack where attacker donates tokens to manipulate
    // share price and steal from the next depositor
    function addLiquidity(uint256 amountA, uint256 amountB) external returns (uint256 lpTokens) {
        require(amountA > 0 && amountB > 0, "Zero amounts");

        if (totalLiquidity == 0) {
            lpTokens = _sqrt(amountA * amountB);
        } else {
            uint256 lpA = (amountA * totalLiquidity) / reserveA;
            uint256 lpB = (amountB * totalLiquidity) / reserveB;
            lpTokens = lpA < lpB ? lpA : lpB;
        }

        require(tokenA.transferFrom(msg.sender, address(this), amountA), "Transfer A failed");
        require(tokenB.transferFrom(msg.sender, address(this), amountB), "Transfer B failed");

        reserveA += amountA;
        reserveB += amountB;
        liquidity[msg.sender] += lpTokens;
        totalLiquidity += lpTokens;

        emit LiquidityAdded(msg.sender, amountA, amountB, lpTokens);
    }

    /// @notice Add liquidity using Permit2 for single-step approvals + transfers of both tokens.
    /// @param amountA Amount of tokenA to deposit.
    /// @param amountB Amount of tokenB to deposit.
    /// @param permitA The Permit2 permit struct for tokenA.
    /// @param permitB The Permit2 permit struct for tokenB.
    /// @param signatureA The EIP-712 signature for permitA.
    /// @param signatureB The EIP-712 signature for permitB.
    function addLiquidityWithPermit(
        uint256 amountA,
        uint256 amountB,
        IPermit2.PermitTransferFrom calldata permitA,
        IPermit2.PermitTransferFrom calldata permitB,
        bytes calldata signatureA,
        bytes calldata signatureB
    ) external returns (uint256 lpTokens) {
        require(amountA > 0 && amountB > 0, "Zero amounts");

        if (totalLiquidity == 0) {
            lpTokens = _sqrt(amountA * amountB);
        } else {
            uint256 lpA = (amountA * totalLiquidity) / reserveA;
            uint256 lpB = (amountB * totalLiquidity) / reserveB;
            lpTokens = lpA < lpB ? lpA : lpB;
        }

        require(permitA.permitted.token == address(tokenA), "Wrong tokenA");
        require(permitA.permitted.amount >= amountA, "PermitA amount too low");
        require(permitB.permitted.token == address(tokenB), "Wrong tokenB");
        require(permitB.permitted.amount >= amountB, "PermitB amount too low");

        IPermit2(PERMIT2).permitTransferFrom(
            permitA,
            IPermit2.SignatureTransferDetails({ to: address(this), requestedAmount: amountA }),
            msg.sender,
            signatureA
        );

        IPermit2(PERMIT2).permitTransferFrom(
            permitB,
            IPermit2.SignatureTransferDetails({ to: address(this), requestedAmount: amountB }),
            msg.sender,
            signatureB
        );

        reserveA += amountA;
        reserveB += amountB;
        liquidity[msg.sender] += lpTokens;
        totalLiquidity += lpTokens;

        emit LiquidityAdded(msg.sender, amountA, amountB, lpTokens);
    }

    function removeLiquidity(uint256 lpTokens) external {
        require(lpTokens > 0 && lpTokens <= liquidity[msg.sender], "Invalid amount");

        uint256 amountA = (lpTokens * reserveA) / totalLiquidity;
        uint256 amountB = (lpTokens * reserveB) / totalLiquidity;

        liquidity[msg.sender] -= lpTokens;
        totalLiquidity -= lpTokens;
        reserveA -= amountA;
        reserveB -= amountB;

        require(tokenA.transfer(msg.sender, amountA), "Transfer A failed");
        require(tokenB.transfer(msg.sender, amountB), "Transfer B failed");

        emit LiquidityRemoved(msg.sender, amountA, amountB);
    }

    // BUG: Swap has no deadline parameter — transaction can sit in mempool and execute
    // at a much later time when price has moved unfavorably (stale transaction attack)
    // BUG: Fee truncates to zero for small swaps — (amountIn * 30) / 10000 rounds to 0
    // when amountIn < 334, meaning tiny swaps pay no fee and can drain value over time
    function swap(address tokenIn, uint256 amountIn, uint256 minAmountOut) external returns (uint256 amountOut) {
        require(tokenIn == address(tokenA) || tokenIn == address(tokenB), "Invalid token");
        require(amountIn > 0, "Zero input");

        bool isA = tokenIn == address(tokenA);
        (uint256 resIn, uint256 resOut) = isA ? (reserveA, reserveB) : (reserveB, reserveA);

        uint256 amountInWithFee = amountIn * (10000 - FEE_BPS);
        amountOut = (amountInWithFee * resOut) / (resIn * 10000 + amountInWithFee);

        require(amountOut >= minAmountOut, "Slippage exceeded");

        IERC20 tIn = isA ? tokenA : tokenB;
        IERC20 tOut = isA ? tokenB : tokenA;

        require(tIn.transferFrom(msg.sender, address(this), amountIn), "Transfer in failed");
        require(tOut.transfer(msg.sender, amountOut), "Transfer out failed");

        if (isA) {
            reserveA += amountIn;
            reserveB -= amountOut;
        } else {
            reserveB += amountIn;
            reserveA -= amountOut;
        }

        emit Swap(msg.sender, tokenIn, amountIn, amountOut);
    }

    /// @notice Swap tokens using Permit2 for a single-step approval + transfer of the input token.
    /// @param tokenIn The address of the input token.
    /// @param amountIn The amount of input tokens to swap.
    /// @param minAmountOut The minimum amount of output tokens expected.
    /// @param permit The Permit2 permit struct for the input token.
    /// @param signature The EIP-712 signature over the permit.
    function swapWithPermit(
        address tokenIn,
        uint256 amountIn,
        uint256 minAmountOut,
        IPermit2.PermitTransferFrom calldata permit,
        bytes calldata signature
    ) external returns (uint256 amountOut) {
        require(tokenIn == address(tokenA) || tokenIn == address(tokenB), "Invalid token");
        require(amountIn > 0, "Zero input");

        bool isA = tokenIn == address(tokenA);
        (uint256 resIn, uint256 resOut) = isA ? (reserveA, reserveB) : (reserveB, reserveA);

        uint256 amountInWithFee = amountIn * (10000 - FEE_BPS);
        amountOut = (amountInWithFee * resOut) / (resIn * 10000 + amountInWithFee);

        require(amountOut >= minAmountOut, "Slippage exceeded");

        require(permit.permitted.token == tokenIn, "Wrong token");
        require(permit.permitted.amount >= amountIn, "Permit amount too low");

        IPermit2(PERMIT2).permitTransferFrom(
            permit,
            IPermit2.SignatureTransferDetails({
                to: address(this),
                requestedAmount: amountIn
            }),
            msg.sender,
            signature
        );

        IERC20 tOut = isA ? tokenB : tokenA;
        require(tOut.transfer(msg.sender, amountOut), "Transfer out failed");

        if (isA) {
            reserveA += amountIn;
            reserveB -= amountOut;
        } else {
            reserveB += amountIn;
            reserveA -= amountOut;
        }

        emit Swap(msg.sender, tokenIn, amountIn, amountOut);
    }

    function _sqrt(uint256 y) internal pure returns (uint256 z) {
        if (y > 3) {
            z = y;
            uint256 x = y / 2 + 1;
            while (x < z) { z = x; x = (y / x + x) / 2; }
        } else if (y != 0) {
            z = 1;
        }
    }

    function getReserves() external view returns (uint256, uint256) {
        return (reserveA, reserveB);
    }
}
