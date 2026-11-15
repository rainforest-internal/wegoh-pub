package io.wegoh.app.ui

import io.wegoh.app.TripRouteStop
import io.wegoh.app.nativeauth.TripCar
import io.wegoh.app.nativeauth.TripDetail
import io.wegoh.app.nativeauth.TripRouteItem
import io.wegoh.app.nativeauth.TripRouteStatus
import io.wegoh.app.nativeauth.TripStatusProgress
import io.wegoh.app.nativeauth.TripCompanionPosition
import io.wegoh.app.nativeauth.TripDisplay
import org.junit.Assert.assertEquals
import org.junit.Test

class TripCompanionProgressTest {
    private val car=TripCar("car-2","사용자B 차","driver-2","사용자B",4,isMine=false,iRide=false,passengers=emptyList(),ordinal=2)
    private fun display(vararg companions: TripCompanionPosition)=TripDisplay(emptyList(),null,null,null,companions.toList())

    @Test fun distanceIsRoundedToHalfKilometreWithDirection() {
        assertEquals(listOf("2호차","약 3km 앞"),companionProgressLabels(display(TripCompanionPosition("car-2",null,3200.0,"ahead")),car))
        assertEquals(listOf("2호차","약 3.5km 뒤"),companionProgressLabels(display(TripCompanionPosition("car-2",null,3400.0,"behind")),car))
        assertEquals(listOf("2호차","1km 이내"),companionProgressLabels(display(TripCompanionPosition("car-2",null,600.0,"ahead")),car))
    }

    @Test fun missingOrStalePositionShowsNoLocation() {
        assertEquals(listOf("2호차","위치 없음"),companionProgressLabels(display(TripCompanionPosition("car-2","최근 공유 위치 없음",null,null)),car))
        assertEquals(listOf("2호차","위치 없음"),companionProgressLabels(display(),car))
        assertEquals(listOf("2호차","위치 없음"),companionProgressLabels(null,car))
        assertEquals(listOf("사용자B 차","위치 없음"),companionProgressLabels(null,car.copy(ordinal=null)))
    }

    private val join=TripRouteItem("course","join","coast")
    private val beach=TripRouteItem("course","beach","coast")
    private fun moving(phase: String,target: TripRouteItem,meters: Int,fraction: Double?)=
        car.copy(routeStatus=TripRouteStatus(phase,progress=TripStatusProgress(target,meters,fraction)))

    @Test fun serverRouteProgressShowsStraightDistanceToTheSharedTarget() {
        val stale=display(TripCompanionPosition("car-2",null,3200.0,"ahead"))
        assertEquals(listOf("2호차","합류 지점까지 직선 약 3km"),companionProgressLabels(stale,moving("pickup",join,3200,null)))
        assertEquals(listOf("2호차","다음 장소까지 직선 1km 이내"),companionProgressLabels(stale,moving("shared",beach,600,0.7)))
        assertEquals(listOf("2호차","다음 장소까지 직선 약 1.5km"),companionProgressLabels(null,moving("shared",beach,1400,0.2)))
        assertEquals(listOf("2호차","합류 지점 도착"),companionProgressLabels(stale,car.copy(routeStatus=TripRouteStatus("waiting"))))
        assertEquals(listOf("2호차","내리는 곳으로 이동 중"),companionProgressLabels(stale,car.copy(routeStatus=TripRouteStatus("drop"))))
        assertEquals(listOf("2호차","주행 완료"),companionProgressLabels(stale,car.copy(routeStatus=TripRouteStatus("done"))))
        assertEquals(listOf("2호차","약 3km 앞"),companionProgressLabels(stale,car.copy(routeStatus=TripRouteStatus("shared"))))
    }

    @Test fun sharedCarsAreMarkedBetweenTheirPreviousAndTargetCourseStops() {
        val mine=TripCar("car-1","사용자A 차","driver-1","사용자A",4,isMine=true,iRide=false,passengers=emptyList(),ordinal=1)
        val signal=TripRouteItem("signal","s".repeat(32))
        val stops=listOf(TripRouteStop(join,"합류",36.6,126.4),TripRouteStop(signal,"휴게소",36.7,126.4),TripRouteStop(beach,"해변",36.8,126.4))
        fun trip(vararg others: TripCar)=TripDetail("trip","여행","",emptyList(),listOf(mine)+others)
        val marker=tripCompanionMarkers(trip(moving("shared",beach,1200,0.5)),stops).single()
        assertEquals("2",marker.label);assertEquals(1f,marker.position,0.001f);assertEquals("2호차 해변 가는 중",marker.description)
        assertEquals(emptyList<TripCompanionMarker>(),tripCompanionMarkers(trip(moving("pickup",join,1200,null)),stops))
        assertEquals(emptyList<TripCompanionMarker>(),tripCompanionMarkers(trip(moving("shared",join,1200,0.5)),stops))
        assertEquals(emptyList<TripCompanionMarker>(),tripCompanionMarkers(trip(moving("shared",TripRouteItem("course","far","other"),1200,0.5)),stops))
    }

    @Test fun sharedTripScoreIsAppendedAsSingleNumber() {
        assertEquals(listOf("2호차","약 3km 앞","92점"),companionProgressLabels(display(TripCompanionPosition("car-2",null,3200.0,"ahead")),car,92))
        assertEquals(listOf("2호차","위치 없음","0점"),companionProgressLabels(null,car,0))
        assertEquals(listOf("2호차","1km 이내"),companionProgressLabels(display(TripCompanionPosition("car-2",null,600.0,"ahead")),car,null))
        assertEquals(listOf("2호차","다음 장소까지 직선 1km 이내","80점"),companionProgressLabels(null,moving("shared",beach,600,0.7),80))
    }
}
