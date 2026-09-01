// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {AccessControl} from "openzeppelin-contracts/contracts/access/AccessControl.sol";

/// @title Who may read which path
/// @notice One record of who a person has shared a folder with, and who they
///         have stopped sharing it with. knos reads it before it answers a
///         teammate's agent.
///
///         The permission itself is OpenZeppelin's. This contract only names
///         the roles: one role per owner and path, so sharing `./src` says
///         nothing about anyone else's `./src`.
contract Access is AccessControl {
    /// @notice Someone was given access to a path.
    event Shared(address indexed owner, string path, address indexed reader);

    /// @notice Someone's access to a path was taken back.
    event Unshared(address indexed owner, string path, address indexed reader);

    constructor() {
        _grantRole(DEFAULT_ADMIN_ROLE, msg.sender);
    }

    /// @notice The role that means "may read this owner's copy of this path".
    /// @dev Scoped by owner as well as path, so two people sharing folders of
    ///      the same name never share each other's readers.
    function roleFor(address owner, string calldata path) public pure returns (bytes32) {
        return keccak256(abi.encode(owner, path));
    }

    /// @notice Let someone read one of your paths.
    /// @dev The caller becomes that role's admin on first use, so only they
    ///      can hand it out or take it back afterwards.
    function share(string calldata path, address reader) external {
        bytes32 role = roleFor(msg.sender, path);
        if (getRoleAdmin(role) == DEFAULT_ADMIN_ROLE) {
            _setRoleAdmin(role, keccak256(abi.encode(msg.sender)));
            _grantRole(keccak256(abi.encode(msg.sender)), msg.sender);
        }
        _grantRole(role, reader);
        emit Shared(msg.sender, path, reader);
    }

    /// @notice Stop someone reading one of your paths.
    function unshare(string calldata path, address reader) external {
        bytes32 role = roleFor(msg.sender, path);
        _revokeRole(role, reader);
        emit Unshared(msg.sender, path, reader);
    }

    /// @notice Whether one person may read another's path, right now.
    function mayRead(address owner, string calldata path, address reader)
        external
        view
        returns (bool)
    {
        return hasRole(roleFor(owner, path), reader);
    }
}
