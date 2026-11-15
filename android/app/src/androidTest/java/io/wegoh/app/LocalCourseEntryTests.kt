package io.wegoh.app

import android.test.InstrumentationTestCase

/** Selection identity, account detachment and local runtime ownership; no network or SDK calls. */
@Suppress("DEPRECATION")
class LocalCourseEntryTests: InstrumentationTestCase() {
    private fun pack()=instrumentation.targetContext.assets.open("packs/01-city-story.json").use {PackCodec.decode(PackCodec.read(it))}
    fun testEqualAccountBytesCannotAcquireLocalAuthority() {
        val local=pack();val account=local.copy()
        assertEquals(local,account)
        assertTrue(courseSelection(account,listOf(local),account) is CourseSelection.Account)
        assertNull(courseSelection(local.copy(),listOf(local),account))
        val projected=localCourseEntryState(WegoState(packs=listOf(account),selectedKey=account.key,active=true),
            listOf(local),CourseSelection.Account(account),CourseOwner.Account("private",1),null,null)
        assertNull(projected.selected)
        assertFalse(projected.active)
        assertEquals(listOf(local),projected.packs)
        assertEquals(AccountCourseState(),projected.accountCourses)
    }
    fun testCourseLabelCannotGrantAccountAuthority() {
        val local=pack().copy(source=CoursesRepository.SOURCE)
        assertTrue(courseSelection(local,listOf(local),null) is CourseSelection.Local)
        val owner=CourseOwner.Local(local.key)
        val state=WegoState(packs=listOf(local),selectedKey=local.key,active=true,
            navigation="안내 시작 확인",navigationPhase=NavigationPhase.ACTIVE,history=listOf("local"))
        val visible=localCourseEntryState(state,listOf(local),CourseSelection.Local(local),owner,owner,owner)
        assertSame(local,visible.selected)
        assertTrue(visible.active)
        assertEquals(NavigationPhase.ACTIVE,visible.navigationPhase)
        assertEquals(listOf("local"),visible.history)
    }
    fun testOtherOwnerRuntimeIsRemovedWithoutMutatingOriginal() {
        val local=pack();val account=CourseOwner.Account("private",2)
        val state=WegoState(packs=listOf(local),selectedKey=local.key,active=true,
            navigation="private navigation",navigationPhase=NavigationPhase.ACTIVE,history=listOf("private"),
            navigationBusy=true,sharingVisits=true,visitSharingAllowed=true)
        val visible=localCourseEntryState(state,listOf(local),CourseSelection.Local(local),account,account,account)
        assertSame(local,visible.selected)
        assertFalse(visible.active)
        assertFalse(visible.navigationBusy)
        assertEquals(NavigationPhase.IDLE,visible.navigationPhase)
        assertTrue(visible.history.isEmpty())
        assertFalse(visible.sharingVisits)
        assertFalse(visible.visitSharingAllowed)
        assertTrue(state.active)
        assertEquals(listOf("private"),state.history)
    }
}
