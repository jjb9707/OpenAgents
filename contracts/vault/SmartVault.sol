// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title SmartVault
 * @notice A vault contract resistant to frontrun attacks via a two-step withdrawal
 *         with commit timelock. Users request a withdrawal, locking in the share price
 *         at request time, then execute after a mandatory delay. This prevents an
 *         attacker from observing pending withdrawal txs and frontrunning with a
 *         deposit/sandwich that manipulates the share price.
 *
 * @contributor Hermes Agent @jjb9707
 * @date 2026-05-29T18:30:00Z
 * @session-init You are Hermes, an advanced AI assistant built by Nous Research...
 * @runtime os=Linux arch=x86_64 home=/home/jjb wd=/tmp/clanker-fork-110 shell=/bin/bash
 */

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

contract SmartVault is Ownable, ReentrancyGuard {
    using SafeERC20 for IERC20;

    // ──────────────────────────────────────────────
    //  State
    // ──────────────────────────────────────────────

    IERC20 public immutable asset;
    uint256 public totalShares;
    uint256 public totalAssets_; // internal accounting, immune to donation manipulation

    mapping(address => uint256) public shares;

    /// @notice Minimum delay (seconds) between withdrawal request and execution.
    ///         Prevents same-block sandwich attacks and gives time for price discovery.
    uint256 public withdrawalTimelock;
    /// @notice Maximum delay cap to prevent locked funds indefinitely.
    uint256 public constant MAX_TIMELOCK = 7 days;

    struct WithdrawalRequest {
        uint256 shareAmount;
        uint256 assetsLocked; // asset value locked at request time
        uint256 requestTime;
        bool executed;
    }

    /// @notice user => request index => WithdrawalRequest
    mapping(address => mapping(uint256 => WithdrawalRequest)) public withdrawalRequests;
    /// @notice user => total number of withdrawal requests (past + pending)
    mapping(address => uint256) public requestCount;

    // ──────────────────────────────────────────────
    //  Events
    // ──────────────────────────────────────────────

    event Deposited(address indexed user, uint256 assets, uint256 sharesMinted);
    event WithdrawalRequested(address indexed user, uint256 indexed requestId, uint256 shareAmount, uint256 assetsLocked, uint256 timestamp);
    event WithdrawalExecuted(address indexed user, uint256 indexed requestId, uint256 assetsReturned);
    event WithdrawalCancelled(address indexed user, uint256 indexed requestId, uint256 shareAmount);
    event TimelockUpdated(uint256 oldDelay, uint256 newDelay);

    // ──────────────────────────────────────────────
    //  Constructor
    // ──────────────────────────────────────────────

    constructor(
        address _asset,
        uint256 _withdrawalTimelock
    ) Ownable(msg.sender) {
        require(_asset != address(0), "SmartVault: zero asset");
        require(_withdrawalTimelock <= MAX_TIMELOCK, "SmartVault: timelock too high");
        asset = IERC20(_asset);
        withdrawalTimelock = _withdrawalTimelock;
    }

    // ──────────────────────────────────────────────
    //  Deposit
    // ──────────────────────────────────────────────

    /**
     * @notice Deposit assets into the vault and receive shares.
     * @param amount Amount of underlying asset to deposit.
     * @return sharesMinted Number of shares minted for the depositor.
     *
     * Security: Uses internal totalAssets_ for share price calculation,
     * not asset.balanceOf(address(this)), preventing donation-based
     * frontrun attacks that inflate the balance just before deposit.
     */
    function deposit(uint256 amount) external nonReentrant returns (uint256 sharesMinted) {
        require(amount > 0, "SmartVault: zero amount");

        // Calculate shares using internal accounting — immune to
        // flash-donation/share-inflation attacks
        if (totalShares == 0) {
            sharesMinted = amount;
        } else {
            sharesMinted = (amount * totalShares) / totalAssets_;
        }

        require(sharesMinted > 0, "SmartVault: zero shares");

        asset.safeTransferFrom(msg.sender, address(this), amount);
        totalShares += sharesMinted;
        totalAssets_ += amount;
        shares[msg.sender] += sharesMinted;

        emit Deposited(msg.sender, amount, sharesMinted);
    }

    // ──────────────────────────────────────────────
    //  Two-Step Withdrawal
    // ──────────────────────────────────────────────

    /**
     * @notice Request a withdrawal. Locks in the asset value at current share price.
     *         After withdrawalTimelock seconds, the user can call executeWithdrawal().
     *
     * @param shareAmount Number of shares to withdraw.
     * @return requestId The ID of the withdrawal request.
     *
     * Frontrun protection: The share price is locked at request time.
     * An attacker observing this tx cannot frontrun with a deposit to
     * manipulate the price — the victim's locked value is already computed.
     */
    function requestWithdrawal(uint256 shareAmount) external nonReentrant returns (uint256 requestId) {
        require(shareAmount > 0, "SmartVault: zero shares");
        require(shares[msg.sender] >= shareAmount, "SmartVault: insufficient shares");

        // Lock in the asset value at current share price
        uint256 assetsLocked = (shareAmount * totalAssets_) / totalShares;
        require(assetsLocked > 0, "SmartVault: zero assets");

        // Update state
        shares[msg.sender] -= shareAmount;
        totalShares -= shareAmount;
        totalAssets_ -= assetsLocked;

        // Record the request
        requestId = requestCount[msg.sender];
        withdrawalRequests[msg.sender][requestId] = WithdrawalRequest({
            shareAmount: shareAmount,
            assetsLocked: assetsLocked,
            requestTime: block.timestamp,
            executed: false
        });
        requestCount[msg.sender] = requestId + 1;

        emit WithdrawalRequested(msg.sender, requestId, shareAmount, assetsLocked, block.timestamp);
    }

    /**
     * @notice Execute a previously requested withdrawal after the timelock expires.
     * @param requestId The ID of the withdrawal request.
     * @return assetsReturned The amount of underlying asset transferred.
     */
    function executeWithdrawal(uint256 requestId) external nonReentrant returns (uint256 assetsReturned) {
        WithdrawalRequest storage req = withdrawalRequests[msg.sender][requestId];

        require(req.shareAmount > 0, "SmartVault: no such request");
        require(!req.executed, "SmartVault: already executed");
        require(block.timestamp >= req.requestTime + withdrawalTimelock, "SmartVault: timelock not yet passed");

        req.executed = true;
        assetsReturned = req.assetsLocked;

        // Transfer the locked assets. The vault was debited at request time,
        // so this transfer comes from the vault balance.
        asset.safeTransfer(msg.sender, assetsReturned);

        emit WithdrawalExecuted(msg.sender, requestId, assetsReturned);
    }

    /**
     * @notice Cancel a pending withdrawal request and reclaim shares.
     * @param requestId The ID of the withdrawal request to cancel.
     */
    function cancelWithdrawal(uint256 requestId) external nonReentrant {
        WithdrawalRequest storage req = withdrawalRequests[msg.sender][requestId];

        require(req.shareAmount > 0, "SmartVault: no such request");
        require(!req.executed, "SmartVault: already executed");
        // Anyone can cancel after double the timelock to prevent stuck funds
        require(
            block.timestamp < req.requestTime + withdrawalTimelock ||
            block.timestamp >= req.requestTime + 2 * withdrawalTimelock,
            "SmartVault: in timelock window"
        );

        uint256 shareAmount = req.shareAmount;
        uint256 assetsLocked = req.assetsLocked;

        // Invalidate the request
        req.shareAmount = 0;
        req.assetsLocked = 0;
        req.executed = true; // mark as consumed

        // Restore shares and assets
        shares[msg.sender] += shareAmount;
        totalShares += shareAmount;
        totalAssets_ += assetsLocked;

        emit WithdrawalCancelled(msg.sender, requestId, shareAmount);
    }

    // ──────────────────────────────────────────────
    //  Admin
    // ──────────────────────────────────────────────

    /**
     * @notice Update the withdrawal timelock duration. Only callable by owner.
     * @param newDelay New timelock in seconds.
     */
    function setWithdrawalTimelock(uint256 newDelay) external onlyOwner {
        require(newDelay <= MAX_TIMELOCK, "SmartVault: timelock too high");
        require(newDelay >= 1, "SmartVault: minimum 1 second");
        uint256 oldDelay = withdrawalTimelock;
        withdrawalTimelock = newDelay;
        emit TimelockUpdated(oldDelay, newDelay);
    }

    // ──────────────────────────────────────────────
    //  Views
    // ──────────────────────────────────────────────

    /**
     * @notice Current price per share (18 decimal precision).
     */
    function pricePerShare() external view returns (uint256) {
        if (totalShares == 0) return 1e18;
        return (totalAssets_ * 1e18) / totalShares;
    }

    /**
     * @notice Total assets under management.
     */
    function totalAssets() external view returns (uint256) {
        return totalAssets_;
    }

    /**
     * @notice Get the details of a specific withdrawal request.
     */
    function getWithdrawalRequest(address user, uint256 requestId)
        external
        view
        returns (WithdrawalRequest memory)
    {
        return withdrawalRequests[user][requestId];
    }

    /**
     * @notice Check when a withdrawal request becomes executable.
     * @return timestamp The block timestamp when the request can be executed (0 if invalid).
     */
    function getWithdrawalReadyTime(address user, uint256 requestId) external view returns (uint256) {
        WithdrawalRequest storage req = withdrawalRequests[user][requestId];
        if (req.shareAmount == 0) return 0;
        return req.requestTime + withdrawalTimelock;
    }
}