package io.wegoh.app

import io.wegoh.app.nativeauth.TripRouteItem
import io.wegoh.app.ui.tripNextRemainingLabels
import io.wegoh.app.ui.tripRemainingLabels
import org.junit.Assert.*
import org.junit.Test

class TripLiveNavigationTest {
    private val stops=listOf(
        TripRouteStop(TripRouteItem("course","first","route"),"출발",37.0,127.0),
        TripRouteStop(TripRouteItem("course","second","route"),"다음 장소",37.0,127.1),
        TripRouteStop(TripRouteItem("course","last","route"),"마지막 장소",37.0,127.2))
    private val initial=TripDrivingState(arrived=setOf(stops.first().key))
    private fun target(index: Int,meters: Double,seconds: Int)=TripNavigationUpdate(targets=listOf(
        TripNavigationTarget(stops[index].lat!!,stops[index].lng!!,meters,seconds)),receivedAtMillis=1000)
    @Test fun unavailablePositionHidesCurrentMarkerWithoutDeletingConfirmedHistoryAndRecovers() {
        val visible=applyTripNavigation(stops,initial,TripNavigationUpdate(position=TripPosition(37.0,127.05)))
        assertNotNull(tripRouteMarker(stops,visible))
        val unavailable=applyTripNavigation(stops,visible,TripNavigationUpdate(positionUnavailable=true))
        assertNull(unavailable.position)
        assertNull(unavailable.distanceMeters)
        assertNull(tripRouteMarker(stops,unavailable))
        assertNull(tripRouteStripProgress(stops,unavailable,false).marker)
        assertEquals(visible.arrived,unavailable.arrived)
        assertEquals(visible.skipped,unavailable.skipped)
        assertEquals(visible.targetKey,unavailable.targetKey)
        val recovered=applyTripNavigation(stops,unavailable,TripNavigationUpdate(position=TripPosition(37.0,127.06)))
        assertFalse(recovered.positionUnavailable)
        assertEquals(TripPosition(37.0,127.06),recovered.position)
        assertNotNull(tripRouteMarker(stops,recovered))
    }
    @Test fun providerLossUsesOnlyTheOtherFreshSourceAndExpiryRemovesPosition() {
        val sources=TripPositionSources()
        val navi=TripPosition(37.0,127.05)
        val fused=TripPosition(37.0,127.06)
        sources.navi(navi,1000);sources.fused(fused,1000)
        sources.fused(null,0)
        assertEquals(navi,sources.current(2000))
        sources.fused(fused,2000);sources.navi(null,0)
        assertEquals(fused,sources.current(3000))
        assertNull(sources.current(17001))
        sources.navi(navi,18000)
        assertEquals(navi,sources.current(18000))
        sources.clear()
        assertNull(sources.current(18000))
    }
    private val station=TripRouteStop(TripRouteItem("course","station","route"),"서울역",37.5547,126.9706)
    private val cafe=TripRouteStop(TripRouteItem("signal","cafe"),"센터커피 서울역점",37.5551,126.9708)
    private val stationGuidance=TripNavigationUpdate(targets=listOf(TripNavigationTarget(station.lat!!,station.lng!!,27000.0,1860)),receivedAtMillis=1000)
    @Test fun naviTargetBelongsToTheClosestStopNotAnEarlierNearbySignal() {
        // #2: 손들기 장소(서울역점 카페)가 서울역 50m 옆에, 경로상 서울역 앞에 들어왔다. 내비는 여전히 서울역 안내 중이다.
        val route=listOf(stops.first(),cafe,station)
        // 분할 경로(v2)는 서버가 진행을 정하므로 localProgress=false로 적용한다.
        val drive=applyTripNavigation(route,initial,stationGuidance,localProgress=false)
        assertEquals(station.key,drive.targetKey)
        assertEquals(cafe,tripNextStop(route,drive))
        // 다음 장소(카페)는 내비 안내 대상이 아니므로 서울역 안내값을 붙이지 않는다(카드·D 대시보드·공유 경로 카드 공통 조건).
        assertEquals(emptyList<String>(),tripNextRemainingLabels(drive,cafe))
        assertEquals(listOf("27.0km 남음","31분 남음"),tripNextRemainingLabels(drive,station))
    }
    @Test fun markerStaysBeforeTheNextStopWhileNaviGuidesToALaterStop() {
        // 내비는 서울역을 안내하지만 다음 장소는 그 앞의 손들기 장소(센터커피)다. 서울역 안내 거리로 표식을 놓으면 카페 위에 그려진다.
        val route=listOf(stops.first(),cafe,station)
        val drive=applyTripNavigation(route,initial,stationGuidance,localProgress=false)
        val marker=tripRouteMarker(route,drive)!!
        assertTrue("$marker",marker>0f && marker<1f)
        // 위치가 있으면 지난 장소와 다음 장소 사이에 투영한다.
        val moving=applyTripNavigation(route,drive,TripNavigationUpdate(position=TripPosition(37.0,127.0),receivedAtMillis=2000),localProgress=false)
        assertEquals(station.key,moving.targetKey)
        assertTrue(tripRouteMarker(route,moving)!!<1f)
    }
    @Test fun markerStaysBetweenTheStartAndTheFirstPendingStopWhileNaviGuidesFurther() {
        // 실기 재현: 아직 도착한 장소가 없고 띠에는 '출발'이 그려진다. 표식은 '출발'과 센터커피 사이여야 한다.
        val route=listOf(cafe,station)
        val drive=applyTripNavigation(route,TripDrivingState(),stationGuidance,localProgress=false)
        assertEquals(station.key,drive.targetKey)
        val progress=tripRouteStripProgress(route,drive,planned=false)
        assertTrue(progress.showStart)
        assertTrue("${progress.marker}",progress.marker!!>0f && progress.marker!!<1f)
    }
    @Test fun localProgressKeepsANewSignalNextToTheNaviDestinationPending() {
        // v1(localProgress=true)에서 naviAtMillis==0이어도 내비 좌표 100m 안의 앞선 손들기 장소는 지나쳤다고 볼 수 없다.
        val route=listOf(stops.first(),cafe,station)
        val drive=applyTripNavigation(route,initial,stationGuidance)
        assertEquals(station.key,drive.targetKey)
        assertTrue(drive.skipped.isEmpty())
        assertEquals(cafe,tripNextStop(route,drive))
        assertEquals(emptyList<String>(),tripNextRemainingLabels(drive,cafe))
    }
    @Test fun loopCourseLastStopMatchesNaviEvenThoughTheStartSharesItsCoordinates() {
        val start=TripRouteStop(TripRouteItem("course","start","loop"),"출발",37.0,127.0)
        val middle=TripRouteStop(TripRouteItem("course","middle","loop"),"중간",37.0,127.1)
        val end=TripRouteStop(TripRouteItem("course","end","loop"),"도착",37.0,127.0)
        val route=listOf(start,middle,end)
        val update=TripNavigationUpdate(targets=listOf(TripNavigationTarget(end.lat!!,end.lng!!,9000.0,600)),receivedAtMillis=1000)
        listOf(true,false).forEach {local->
            val drive=applyTripNavigation(route,TripDrivingState(arrived=setOf(start.key,middle.key)),update,localProgress=local)
            assertEquals(end.key,drive.targetKey)
            assertEquals(9000.0,drive.distanceMeters!!,0.0)
            assertEquals(listOf("9.0km 남음","10분 남음"),tripNextRemainingLabels(drive,tripNextStop(route,drive)))
        }
    }
    @Test fun arrivedStopCloserToTheNaviPointDoesNotHideTheRemainingStop() {
        // 지난 장소가 내비 좌표에 더 가깝게 겹쳐 있어도 남은 장소가 그 안내의 대상이다.
        val passed=TripRouteStop(TripRouteItem("course","passed","route"),"지난 장소",37.5547,126.9706)
        val route=listOf(passed,cafe)
        val drive=applyTripNavigation(route,TripDrivingState(arrived=setOf(passed.key)),stationGuidance,localProgress=false)
        assertEquals(cafe.key,drive.targetKey)
        assertEquals(27000.0,drive.distanceMeters!!,0.0)
        assertEquals(listOf("27.0km 남음","31분 남음"),tripNextRemainingLabels(drive,cafe))
    }
    @Test fun equallyCloseStopsWithoutATargetMatchTheEarlierRouteStop() {
        val first=TripRouteStop(TripRouteItem("course","a","route"),"앞 장소",37.5547,126.9706)
        val second=TripRouteStop(TripRouteItem("signal","b"),"뒤 장소",37.5547,126.9706)
        val route=listOf(first,second)
        val drive=applyTripNavigation(route,TripDrivingState(),stationGuidance,localProgress=false)
        assertEquals(first.key,drive.targetKey)
        assertEquals(listOf("27.0km 남음","31분 남음"),tripNextRemainingLabels(drive,tripNextStop(route,drive)))
    }
    @Test fun fakeNaviDistanceAndTimeUpdateWithoutAnAppNavigationCommand() {
        val far=applyTripNavigation(stops,initial,target(1,98000.0,1800))
        assertEquals(stops[1].key,far.targetKey);assertEquals(TripDrivingPhase.FAR,far.phase)
        assertEquals(listOf("98.0km 남음","30분 남음"),tripRemainingLabels(far))
        val near=applyTripNavigation(stops,far,target(1,250.0,60))
        assertEquals(TripDrivingPhase.NEAR,near.phase)
        assertEquals(listOf("250m 남음","1분 남음"),tripRemainingLabels(near))
        val arrived=applyTripNavigation(stops,near,target(1,40.0,8))
        assertEquals(TripDrivingPhase.ARRIVED,arrived.phase)
        assertTrue(stops[1].key in arrived.arrived)
        assertEquals(stops[2],tripNextStop(stops,arrived))
    }
    @Test fun fakeCurrentLocationMovesRouteMarkerWhileFreshNaviDistanceRemainsAuthoritative() {
        val far=applyTripNavigation(stops,initial,target(1,5000.0,500))
        val half=applyTripNavigation(stops,far,TripNavigationUpdate(position=TripPosition(37.0,127.05,90.0),receivedAtMillis=1500))
        val next=applyTripNavigation(stops,half,TripNavigationUpdate(position=TripPosition(37.0,127.075,90.0),receivedAtMillis=2000))
        assertEquals(0.5f,tripRouteMarker(stops,half)!!,0.001f)
        assertEquals(0.75f,tripRouteMarker(stops,next)!!,0.001f)
        assertEquals(5000.0,next.distanceMeters!!,0.0);assertEquals(500,next.remainingSeconds)
        assertEquals(90.0,next.position!!.heading!!,0.0)
    }
    @Test fun segmentRouteLocationOnlyUpdatesMovePositionAndRemainingDistance() {
        val restored=TripDrivingState(arrived=setOf(stops.first().key))
        val first=applyTripNavigation(stops,restored,TripNavigationUpdate(position=TripPosition(37.0,127.02),receivedAtMillis=1000),localProgress=false)
        val second=applyTripNavigation(stops,first,TripNavigationUpdate(position=TripPosition(37.0,127.06),receivedAtMillis=2500),localProgress=false)
        assertEquals(stops[1].key,second.targetKey)
        assertEquals(TripPosition(37.0,127.06),second.position)
        assertTrue(second.distanceMeters!!<first.distanceMeters!!)
        assertNotEquals(tripRemainingLabels(first),tripRemainingLabels(second))
    }
    @Test fun existingExternalGuidanceAdoptsTheFirstPendingTripWaypointBeforeTheDestination() {
        val firstLocation=applyTripNavigation(stops,TripDrivingState(),TripNavigationUpdate(position=TripPosition(37.0,127.05),receivedAtMillis=500))
        val snapshot=target(1,5000.0,500).copy(targets=listOf(
            TripNavigationTarget(stops[2].lat!!,stops[2].lng!!,15000.0,1500),
            TripNavigationTarget(stops[1].lat!!,stops[1].lng!!,5000.0,500)))
        val adopted=applyTripNavigation(stops,firstLocation,snapshot)
        assertEquals(stops[1].key,adopted.targetKey)
        assertEquals(stops[1],tripNextStop(stops,adopted))
        assertEquals(5000.0,adopted.distanceMeters!!,0.0)
        assertTrue(stops[0].key in adopted.skipped)
        assertTrue(adopted.arrived.isEmpty())
    }
    @Test fun unrelatedExternalGuidanceDoesNotReplaceTheTripsNextPlace() {
        val location=applyTripNavigation(stops,initial,TripNavigationUpdate(position=TripPosition(37.0,127.05),receivedAtMillis=500))
        val unrelated=applyTripNavigation(stops,location,TripNavigationUpdate(targets=listOf(TripNavigationTarget(38.0,128.0,500.0,60)),receivedAtMillis=1000))
        assertEquals(location,unrelated)
        assertEquals(stops[1],tripNextStop(stops,unrelated))
    }
    @Test fun firstNaviRoadDistanceReplacesNearbyStraightLineWithoutMarkingTheStopSkipped() {
        val near=applyTripNavigation(stops,initial,TripNavigationUpdate(position=TripPosition(37.001,127.1),receivedAtMillis=500))
        assertEquals(TripDrivingPhase.NEAR,near.phase)
        val road=applyTripNavigation(stops,near,target(1,2000.0,300))
        assertEquals(TripDrivingPhase.FAR,road.phase)
        assertTrue(road.skipped.isEmpty())
    }
    @Test fun markerUsesDistanceWhenThePreviousStopWasSkipped() {
        val jumped=applyTripNavigation(stops,TripDrivingState(skipped=setOf(stops[0].key)).navigate(stops[1]),
            target(1,18000.0,1900).copy(position=TripPosition(36.5,126.5)))
        val later=applyTripNavigation(stops,jumped,target(1,9000.0,950).copy(position=TripPosition(36.6,126.6),receivedAtMillis=9000))
        assertEquals(0.5f,tripRouteMarker(stops,later)!!,0.001f)
    }
    @Test fun markerMovesFromTheStartTowardTheFirstStop() {
        val fresh=TripDrivingState()
        val far=applyTripNavigation(stops,fresh,target(0,10000.0,600))
        val half=applyTripNavigation(stops,far,target(0,5000.0,300))
        assertEquals(-1.0f,tripRouteMarker(stops,far)!!,0.001f)
        assertEquals(-0.5f,tripRouteMarker(stops,half)!!,0.001f)
    }
    @Test fun segmentRouteLeavingTheFirstStopAreaKeepsItAsTheNextStop() {
        val near=applyTripNavigation(stops,TripDrivingState(),TripNavigationUpdate(position=TripPosition(37.001,127.0),receivedAtMillis=1000),localProgress=false)
        val away=applyTripNavigation(stops,near,TripNavigationUpdate(position=TripPosition(37.172,127.0),receivedAtMillis=2000),localProgress=false)
        assertEquals(TripDrivingPhase.NEAR,near.phase)
        assertEquals(TripDrivingPhase.FAR,away.phase)
        assertEquals(stops[0].key,away.targetKey)
        assertTrue(away.skipped.isEmpty())
        assertEquals(TripRouteStripProgress(true,0f),tripRouteStripProgress(stops,away,planned=false))
    }
    @Test fun segmentRouteNaviDestinationAheadDoesNotSkipUnconfirmedStops() {
        val ahead=applyTripNavigation(stops,TripDrivingState(),target(2,8000.0,600),localProgress=false)
        assertEquals(stops[2].key,ahead.targetKey)
        assertTrue(ahead.skipped.isEmpty())
    }
    @Test fun routeStripShowsTheStartWhenTheCarIsBeforeASkippedFirstStop() {
        val near=TripDrivingState().navigate(stops[0]).distance(200.0)
        val skipped=applyTripNavigation(stops,near,TripNavigationUpdate(position=TripPosition(37.172,127.0),receivedAtMillis=1000))
        assertEquals(TripDrivingPhase.SKIPPED,skipped.phase)
        assertTrue(tripRouteMarker(stops,skipped)!!<0f)
        val progress=tripRouteStripProgress(stops,skipped,planned=false)
        assertTrue(progress.showStart)
        assertEquals(0f,progress.marker!!,0.001f)
    }
    @Test fun routeStripMarkerAlwaysStaysOnTheDrawnNodes() {
        val states=listOf(TripDrivingState(),initial,TripDrivingState().navigate(stops[0]).distance(200.0).distance(5000.0),
            applyTripNavigation(stops,TripDrivingState(),target(0,10000.0,600)),applyTripNavigation(stops,initial,target(1,10000.0,600)),
            applyTripNavigation(stops,initial,target(1,40.0,8)),TripDrivingState(arrived=stops.map {it.key}.toSet()))
        states.forEach {drive->
            val progress=tripRouteStripProgress(stops,drive,planned=false)
            val nodes=stops.size+if(progress.showStart)1 else 0
            progress.marker?.let {assertTrue("$drive -> $it",it in 0f..(nodes-1).toFloat())}
        }
        assertEquals(TripRouteStripProgress(false,null),tripRouteStripProgress(stops,initial,planned=true))
    }
    @Test fun remainingDistanceMovesMarkerWhenLocationCallbackIsNotAvailable() {
        val far=applyTripNavigation(stops,initial,target(1,10000.0,600))
        val half=applyTripNavigation(stops,far,target(1,5000.0,300))
        assertEquals(0.0f,tripRouteMarker(stops,far)!!,0.001f)
        assertEquals(0.5f,tripRouteMarker(stops,half)!!,0.001f)
    }
    @Test fun locationFallbackEntersNearThenArrives() {
        val near=applyTripNavigation(stops,initial,TripNavigationUpdate(position=TripPosition(37.001,127.1),receivedAtMillis=1000))
        assertEquals(TripDrivingPhase.NEAR,near.phase)
        assertTrue(near.distanceMeters!! in 100.0..120.0)
        val arrived=applyTripNavigation(stops,near,TripNavigationUpdate(position=TripPosition(37.0002,127.1),receivedAtMillis=2000))
        assertEquals(TripDrivingPhase.ARRIVED,arrived.phase)
    }
    @Test fun staleNaviDistanceFallsBackToCurrentPositionWithoutInventedEta() {
        val far=applyTripNavigation(stops,initial,target(1,5000.0,500))
        val location=applyTripNavigation(stops,far,TripNavigationUpdate(position=TripPosition(37.001,127.1),receivedAtMillis=7000))
        assertTrue(location.distanceMeters!!<200.0);assertNull(location.remainingSeconds)
    }
    @Test fun actualOemArrivalRequiresMatchingTripTarget() {
        val near=applyTripNavigation(stops,initial,target(1,250.0,60))
        val unknown=applyTripNavigation(stops,near,TripNavigationUpdate(targets=listOf(TripNavigationTarget(38.0,128.0,0.0,0)),arrived=true,receivedAtMillis=1100))
        assertEquals(TripDrivingPhase.NEAR,unknown.phase)
        val arrived=applyTripNavigation(stops,near,target(1,250.0,60).copy(arrived=true))
        assertEquals(TripDrivingPhase.ARRIVED,arrived.phase)
    }
    @Test fun lastStopArrivalEndsCourseWithoutCallingServerOrStartingAnotherRoute() {
        val beforeLast=initial.copy(arrived=stops.take(2).map {it.key}.toSet())
        val arrived=applyTripNavigation(stops,beforeLast,target(2,30.0,3))
        assertEquals(TripDrivingPhase.ROUTE_END,arrived.phase);assertNull(tripNextStop(stops,arrived))
        assertEquals(2f,tripRouteMarker(stops,arrived)!!,0.001f)
    }
    @Test fun newOemTargetAfterArrivalAdvancesVisibleNextPlace() {
        val arrived=applyTripNavigation(stops,initial,target(1,40.0,8))
        val next=applyTripNavigation(stops,arrived,target(2,6000.0,720))
        assertEquals(stops[2].key,next.targetKey);assertEquals(TripDrivingPhase.FAR,next.phase)
        assertTrue(stops[1].key in next.arrived)
    }
    @Test fun arrivalCardRemainsWhileNaviStillReportsTheArrivedWaypointFirst() {
        val arrived=applyTripNavigation(stops,initial,target(1,40.0,8))
        val snapshot=target(1,30.0,5).copy(targets=target(1,30.0,5).targets!!+target(2,6000.0,720).targets!!)
        assertEquals(arrived,applyTripNavigation(stops,arrived,snapshot))
    }
    @Test fun invalidReadingsDoNotChangeVisibleDrivingState() {
        val invalid=TripNavigationUpdate(position=TripPosition(Double.NaN,127.0),targets=listOf(TripNavigationTarget(37.0,127.1,-1.0,-1)))
        assertEquals(initial,applyTripNavigation(stops,initial,invalid))
    }
}
