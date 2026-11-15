package io.wegoh.app

import io.wegoh.app.nativeauth.TripDetail
import io.wegoh.app.nativeauth.TripList
import io.wegoh.app.ui.AppDestination
import io.wegoh.app.ui.PlatformRoutes
import org.junit.Assert.*
import org.junit.Test

class TripsPageStateTest {
    private val list=TripList(emptyList(),emptyList())
    @Test fun invitationActionsRequireCurrentIdleList() {
        assertFalse(TripsPageState().canRespond)
        assertFalse(TripsPageState(list=list).canRespond)
        assertFalse(TripsPageState(list=list,isCurrent=true,busy=true).canRespond)
        assertTrue(TripsPageState(list=list,isCurrent=true).canRespond)
    }
    @Test fun suspensionDisablesActionsAndKeepsOnlyAuthorizedSnapshot() {
        val detail=TripDetail("a".repeat(32),"여행","",emptyList(),emptyList())
        val state=TripsPageState(AccountReadStatus.READY,list,detail.id,detail,isCurrent=true,busy=true)
        val retained=state.suspended(true)
        assertSame(list,retained.list);assertSame(detail,retained.detail)
        assertFalse(retained.busy);assertFalse(retained.isCurrent);assertFalse(retained.canRespond)
        assertEquals(TripsPageState(),state.suspended(false))
    }
    @Test fun menuHasFiveTypedRootsInFixedOrder() {
        assertEquals(listOf("trips","car","courses","music","profile"),PlatformRoutes.primary)
        assertEquals(listOf("여행","리모컨","경로","음악","프로필"),PlatformRoutes.primary.map {PlatformRoutes.titles[it]})
        assertTrue(PlatformRoutes.titles.keys.all {AppDestination.fromId(it)!=null})
    }
}
