package io.wegoh.app

import org.junit.Assert.*
import org.junit.Test

class FirstRunPermissionStateTest {
    @Test fun newInstallWaitsForWalkthroughCompletion() {
        val state=FirstRunPermissionState(false) {fail("Must not persist before a choice")}
        assertFalse(state.shouldShow(walkthroughCompleted=false,connected=false,allGranted=false))
        assertTrue(state.shouldShow(walkthroughCompleted=true,connected=false,allGranted=false))
    }

    @Test fun skippingWalkthroughDoesNotSkipPermissions() {
        var walkthroughCompleted=false
        val onWalkthroughComplete={walkthroughCompleted=true}
        val state=FirstRunPermissionState(false) {}
        onWalkthroughComplete()
        assertTrue(state.shouldShow(walkthroughCompleted,connected=false,allGranted=false))
        assertFalse(state.completed)
    }

    @Test fun existingInstallWithCompletedWalkthroughGetsPermissionEntry() {
        val state=FirstRunPermissionState(false) {}
        assertTrue(state.shouldShow(walkthroughCompleted=true,connected=false,allGranted=false))
    }

    @Test fun connectedInstallDoesNotNeedWalkthroughMarker() {
        val state=FirstRunPermissionState(false) {}
        assertTrue(state.shouldShow(walkthroughCompleted=false,connected=true,allGranted=false))
    }

    @Test fun allPermissionsGrantedSkipsEntry() {
        val state=FirstRunPermissionState(false) {}
        assertFalse(state.shouldShow(walkthroughCompleted=true,connected=false,allGranted=true))
        assertFalse(state.shouldShow(walkthroughCompleted=false,connected=true,allGranted=true))
    }

    @Test fun laterPersistsCompletionAcrossRelaunch() {
        var saved=false
        val state=FirstRunPermissionState(saved) {saved=true}
        state.complete()
        assertFalse(state.shouldShow(walkthroughCompleted=true,connected=false,allGranted=false))
        val relaunched=FirstRunPermissionState(saved) {fail("Already complete")}
        assertFalse(relaunched.shouldShow(walkthroughCompleted=true,connected=true,allGranted=false))
    }

    @Test fun deniedOrPartiallyGrantedRequestStillContinues() {
        val state=FirstRunPermissionState(false) {}
        state.complete()
        assertFalse(state.shouldShow(walkthroughCompleted=true,connected=true,allGranted=false))
    }

    @Test fun skippedGrantedPermissionsAreNotPromptedAfterRevocation() {
        var saved=false
        val state=FirstRunPermissionState(saved) {saved=true}
        assertTrue(state.eligible(walkthroughCompleted=false,connected=true))
        assertFalse(state.shouldShow(walkthroughCompleted=false,connected=true,allGranted=true))
        state.skipGranted(walkthroughCompleted=false,connected=true,allGranted=true)
        assertFalse(FirstRunPermissionState(saved) {}.shouldShow(walkthroughCompleted=true,connected=true,allGranted=false))
    }

    @Test fun automaticSkipDoesNotCompleteAnUnfinishedWalkthroughOrMissingPermissions() {
        val state=FirstRunPermissionState(false) {fail("Not eligible for automatic completion")}
        state.skipGranted(walkthroughCompleted=false,connected=false,allGranted=true)
        state.skipGranted(walkthroughCompleted=true,connected=false,allGranted=false)
        assertFalse(state.completed)
    }

    @Test fun completionIsSavedOnlyOnce() {
        var writes=0
        val state=FirstRunPermissionState(false) {writes++}
        state.complete()
        state.complete()
        assertEquals(1,writes)
    }
}
