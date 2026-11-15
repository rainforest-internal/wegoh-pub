package io.wegoh.app

import io.wegoh.app.ui.*
import java.time.Instant
import org.junit.Assert.*
import org.junit.Test

class VehicleCourseLibraryStateTest {
    private fun course(id: String,starred: Boolean=false)=CourseLibraryItem(PublishedPack(id,1,id,"사용자F","실제 경로",2,"a".repeat(64)),
        listOf("바다","호수"),starred,2,null,null,false,false,null,listOf("간월암","대천"))
    private val recommended=course("recommended")
    private val saved=course("saved",true)
    private val news=course("news")
    private val library=CourseLibrary(listOf(recommended),listOf(saved),listOf(CourseLibraryNews(news,"1",Instant.EPOCH,false)),
        emptyList(),listOf("바다","호수"),emptyList(),1)
    private val state=WegoState(setupAllowed=true,
        accountDiscovery=AccountDiscoveryState(AccountReadStatus.READY,listOf(recommended.published),library=library),
        accountCourses=AccountCourseState(AccountCourseStatus.READY,listOf(AccountCourse(course("mine").published,true,listOf("숲")))) )
    @Test fun everyTabUsesItsActualAccountCollectionRatherThanInstalledPacks() {
        fun ids(tab: VehicleCourseFeedTab)=vehicleCourseLibraryState(state,tab,emptySet()).courses.map {it.key}
        assertEquals(listOf("recommended@1"),ids(VehicleCourseFeedTab.RECOMMENDED))
        assertEquals(listOf("news@1"),ids(VehicleCourseFeedTab.SUBSCRIPTIONS))
        assertEquals(listOf("mine@1"),ids(VehicleCourseFeedTab.MINE))
        assertEquals(listOf("saved@1"),ids(VehicleCourseFeedTab.SAVED))
        assertTrue(vehicleCourseLibraryState(state,VehicleCourseFeedTab.SUBSCRIPTIONS,emptySet()).courses.single().isNew)
    }
    @Test fun tagChoicesIntersectAndNeverNavigateToADifferentScreen() {
        val feed=vehicleCourseLibraryState(state,VehicleCourseFeedTab.RECOMMENDED,setOf("#바다","호수"))
        assertEquals(listOf("recommended@1"),vehicleCourseFeedCards(feed).map {it.key})
        assertTrue(vehicleCourseFeedCards(feed.copy(selectedTags=setOf("바다","숲"))).isEmpty())
        assertEquals(1,vehicleCourseFeedCards(feed.copy(selectedTags=emptySet())).size)
    }
    @Test fun recommendedSortOrderIsALabelNotAStatusNotice() {
        assertEquals("별표 많은 순",vehicleCourseLibraryState(state,VehicleCourseFeedTab.RECOMMENDED,emptySet()).sortLabel)
        listOf(VehicleCourseFeedTab.SUBSCRIPTIONS,VehicleCourseFeedTab.MINE,VehicleCourseFeedTab.SAVED).forEach {
            assertNull(vehicleCourseLibraryState(state,it,emptySet()).sortLabel)
        }
    }
    @Test fun permissionLoadingStaleAndActiveExecutionAreNotAnEmptyReadyList() {
        val unavailable=state.copy(accountDiscovery=AccountDiscoveryState(AccountReadStatus.PERMISSION_REQUIRED))
        assertEquals(AccountReadStatus.PERMISSION_REQUIRED,vehicleCourseLibraryState(unavailable,VehicleCourseFeedTab.RECOMMENDED,emptySet()).status)
        val stale=state.copy(accountDiscovery=state.accountDiscovery.copy(isCurrent=false))
        assertFalse(vehicleCourseLibraryState(stale,VehicleCourseFeedTab.SAVED,emptySet()).isCurrent)
        assertTrue(vehicleCourseLibraryState(state.copy(active=true),VehicleCourseFeedTab.RECOMMENDED,emptySet()).courses.none {it.canOpen || it.canAdd})
        assertEquals(listOf("숲"),vehicleCourseLibraryState(state,VehicleCourseFeedTab.MINE,emptySet()).courses.single().tags)
    }
}
