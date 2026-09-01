// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Test} from "forge-std/Test.sol";
import {Access} from "../src/Access.sol";

contract AccessTest is Test {
    Access internal access;

    address internal owner = address(0xA11CE);
    address internal reader = address(0xB0B);
    address internal stranger = address(0xCA7);

    function setUp() public {
        access = new Access();
    }

    function test_nobodyCanReadUntilShared() public view {
        assertFalse(access.mayRead(owner, "./src", reader));
    }

    function test_shareThenRead() public {
        vm.prank(owner);
        access.share("./src", reader);
        assertTrue(access.mayRead(owner, "./src", reader));
    }

    function test_unshareStopsTheRead() public {
        vm.startPrank(owner);
        access.share("./src", reader);
        assertTrue(access.mayRead(owner, "./src", reader));
        access.unshare("./src", reader);
        vm.stopPrank();
        assertFalse(access.mayRead(owner, "./src", reader));
    }

    function test_sharingOnePathDoesNotShareAnother() public {
        vm.prank(owner);
        access.share("./src", reader);
        assertFalse(access.mayRead(owner, "./docs", reader));
    }

    function test_myFolderIsNotYourFolderOfTheSameName() public {
        vm.prank(owner);
        access.share("./src", reader);
        assertFalse(access.mayRead(stranger, "./src", reader));
    }

    function test_aStrangerCannotShareMyPath() public {
        vm.prank(owner);
        access.share("./src", reader);

        // The stranger's call names their own path, not the owner's, so the
        // owner's reader list is untouched either way.
        vm.prank(stranger);
        access.share("./src", stranger);
        assertFalse(access.mayRead(owner, "./src", stranger));
    }

    function test_aStrangerCannotRevokeMyReader() public {
        vm.prank(owner);
        access.share("./src", reader);

        vm.prank(stranger);
        access.unshare("./src", reader);

        assertTrue(access.mayRead(owner, "./src", reader));
    }

    function test_eventsSayWhatHappened() public {
        vm.expectEmit(true, true, true, true);
        emit Access.Shared(owner, "./src", reader);
        vm.prank(owner);
        access.share("./src", reader);

        vm.expectEmit(true, true, true, true);
        emit Access.Unshared(owner, "./src", reader);
        vm.prank(owner);
        access.unshare("./src", reader);
    }

    function testFuzz_onlyTheSharedReaderMayRead(address other) public {
        vm.assume(other != reader);
        vm.prank(owner);
        access.share("./src", reader);
        assertFalse(access.mayRead(owner, "./src", other));
    }
}
