package io.wegoh.app

import io.wegoh.app.nativeauth.*
import org.junit.Assert.*
import org.junit.Test
import java.time.LocalDate

class TripPlanStateTest {
    private val owner=TripMember("team-"+"a".repeat(40),"사용자A",true,true,true,hasVehicle=true)
    private val memberC=TripMember("team-"+"b".repeat(40),"사용자C",true,false,false)
    private val memberD=TripMember("team-"+"c".repeat(40),"사용자D",true,false,false)
    private val carId="d".repeat(32)
    private val pickup=TripPlace("합정역 2번 출구","e".repeat(32),"pickup",37.5,127.0,selectedBy=listOf(memberC.id,memberD.id))
    private val drop=TripPlace("안목 커피거리","f".repeat(32),"drop",37.0,128.0,selectedBy=listOf(memberD.id))
    private val car=TripCar(carId,"사용자A 차",owner.id,owner.name,4,true,false,
        listOf(TripPassenger(memberC.id,memberC.name,false),TripPassenger(memberD.id,memberD.name,false)),listOf(pickup,drop))
    private val course=TripCourse("gangneung","강릉 바다 한 바퀴",1,2,owner.name,true,true,emptyList(),
        listOf(TripCourseStop("beach","경포해변",37.1,128.1),TripCourseStop("coffee","안목 커피거리",37.0,128.0)))
    private fun trip()=TripDetail("a".repeat(32),"강릉 바다 여행","",listOf(owner,memberC,memberD),listOf(car),state="planned",revision=1,courses=listOf(course))

    @Test fun acceptedMemberCanAddCourseWithoutEditingRights() {
        val member=trip().copy(members=listOf(owner.copy(isMe=false),memberC.copy(isMe=true)))
        assertFalse(member.canEdit)
        assertTrue(canPerformTripAction(member,TripAction.AddCourse("gangneung")))
        assertTrue(canPerformTripAction(member.copy(state="active"),TripAction.AddCourse("gangneung")))
        assertFalse(canPerformTripAction(member,TripAction.EditIntro("새 이름","")))
        assertFalse(canPerformTripAction(member.copy(state="completed"),TripAction.AddCourse("gangneung")))
        assertFalse(canPerformTripAction(member.copy(members=listOf(memberC.copy(isMe=true,accepted=false))),TripAction.AddCourse("gangneung")))
    }

    @Test fun newTripHasExactlyThreeConditionalTodos() {
        val overview=tripPlanOverview(trip().copy(members=listOf(owner),cars=emptyList(),courses=emptyList()))
        assertEquals(listOf("초대하기","차 추가","경로 추가"),overview.todos.map {it.action})
        assertEquals(listOf("3","0","1","0"),overview.menu.map {it.count})
        assertEquals(listOf("할 일 3","없음","차 미정 1명","없음"),overview.menu.map {it.subtitle})
    }
    @Test fun approvedMembersCountAcceptedOnlyAndSeatsExcludeDrivers() {
        val driverD=TripMember("team-"+"1".repeat(40),"사용자D",true,false,false)
        val driverE=TripMember("team-"+"2".repeat(40),"사용자E",true,false,false)
        val memberB=TripMember("team-"+"3".repeat(40),"사용자B",true,false,false)
        val pendingE=TripMember("team-"+"4".repeat(40),"사용자E",false,false,false)
        val data=trip().copy(members=trip().members+listOf(driverD,driverE,memberB,pendingE),cars=listOf(car,
            car.copy(id="1".repeat(32),name="사용자D 차",driverId=driverD.id,driverName=driverD.name,isMine=false,passengers=emptyList()),
            car.copy(id="2".repeat(32),name="사용자E 차",driverId=driverE.id,driverName=driverE.name,seats=3,isMine=false,passengers=emptyList())))
        val overview=tripPlanOverview(data)
        assertTrue(overview.todos.isEmpty())
        assertEquals(listOf("","3","6","1"),overview.menu.map {it.count})
        assertEquals(listOf("할 일 없음","빈자리 9석","초대 대기 1명\n차 미정 1명",""),overview.menu.map {it.subtitle})
    }
    @Test fun pendingInviteDoesNotCompleteInviteTodo() {
        val pending=memberC.copy(accepted=false)
        val state=tripPlanOverview(trip().copy(members=listOf(owner,pending),cars=emptyList(),courses=emptyList()))
        assertEquals(3,state.todos.size)
        assertEquals(1,state.accepted)
        assertEquals(1,state.pending)
    }
    @Test fun allAssignedSubtitleAndNoExtraTodos() {
        assertEquals("탈 차 선택 완료",tripPlanOverview(trip()).menu[2].subtitle)
        assertEquals(listOf(TripPlanTab.ROUTE),tripPlanOverview(trip().copy(courses=emptyList())).todos.map {it.tab})
    }
    @Test fun missingOptionalFieldsDoNotInventPeopleCarsOrRoutes() {
        val empty=trip().copy(members=emptyList(),cars=emptyList(),courses=null)
        assertEquals("0",tripPlanOverview(empty).menu[2].count)
        assertFalse(TripRouteOrder.isComplete(empty))
    }
    @Test fun independentNullableDatesAndCountdownUseCalendarDays() {
        assertEquals("날짜 미정",tripDateLabel(null,null))
        assertTrue(tripDateLabel(null,"2026-11-15").endsWith("까지"))
    }
    @Test fun routeChipsAndChecklistShareMyStopLabels() {
        val driver=tripMyStops(trip())
        assertTrue(driver.driving && driver.chosen)
        assertEquals("합정역 2번 출구" to "안목 커피거리",driver.label("pickup") to driver.label("drop"))
        val bare=tripMyStops(trip().copy(cars=listOf(car.copy(places=emptyList()))))
        assertEquals("해당 없음" to "해당 없음",bare.label("pickup") to bare.label("drop"))
        val two=tripMyStops(trip().copy(cars=listOf(car.copy(places=listOf(pickup,pickup.copy(name="망원역",id="9".repeat(32)),drop)))))
        assertEquals("합정역 2번 출구 외 1곳",two.label("pickup"))
        val rider=trip().copy(members=listOf(owner.copy(isMe=false),memberC.copy(isMe=true)),cars=listOf(car.copy(isMine=false,iRide=true)))
        val riding=tripMyStops(rider)
        assertFalse(riding.driving || riding.chosen)
        assertEquals("합정역 2번 출구" to "미정",riding.label("pickup") to riding.label("drop"))
        assertFalse(tripPreparationChecks(rider)[2].done)
        val noCar=tripMyStops(rider.copy(cars=emptyList()))
        assertEquals("미정" to "미정",noCar.label("pickup") to noCar.label("drop"))
    }
    @Test fun plannedTripIsCalledPreparingEverywhereWithDaysAsExtraInfo() {
        val today=LocalDate.of(2026,11,8)
        assertEquals("준비 중",tripStateLabel("planned",null,today))
        assertEquals("준비 중",tripStateLabel("planned","2026-11-01",today))
        assertEquals("준비 중 · 오늘",tripStateLabel("planned","2026-11-08",today))
        assertEquals("준비 중 · 7일 후",tripStateLabel("planned","2026-11-15",today))
        assertEquals("진행 중",tripStateLabel("active","2026-11-15",today))
        assertEquals("지난 여행",tripStateLabel("completed",null,today))
        assertEquals("지난 여행",tripStateLabel("cancelled",null,today))
    }
    @Test fun removingPickupPreservesSourceAndInsertingReturnsBeforeCourse() {
        val trip=trip()
        val order=TripRouteOrder.initial(trip,car)
        assertEquals(listOf("pickup","course","course"),order.map {it.type})
        val removed=TripRouteOrder.remove(order,0)
        assertEquals(listOf(pickup),TripRouteOrder.outside(removed,car.places.orEmpty()))
        assertEquals(2,car.places?.size)
        assertEquals(listOf(memberC.id,memberD.id),pickup.selectedBy)
        assertEquals(order,TripRouteOrder.add(removed,pickup,trip))
    }
    @Test fun dropAtCourseIsAttachedAndRemovingDropKeepsCourse() {
        val trip=trip()
        val order=TripRouteOrder.initial(trip,car)
        assertEquals(drop.id,order.last().dropRef)
        val removed=TripRouteOrder.remove(order,order.lastIndex)
        assertEquals("coffee",removed.last().ref)
        assertNull(removed.last().dropRef)
        assertTrue(TripRouteOrder.preservesCourses(removed,trip))
        assertEquals(listOf(drop),TripRouteOrder.outside(removed,car.places.orEmpty()))
        assertEquals(order,TripRouteOrder.add(removed,drop,trip))
    }
    @Test fun ordinaryCourseCannotBeRemovedAndDropWithoutHostGoesLast() {
        val trip=trip()
        val order=TripRouteOrder.initial(trip,car)
        assertEquals(order,TripRouteOrder.remove(order,1))
        val elsewhere=drop.copy(id="1".repeat(32),lat=35.0)
        val added=TripRouteOrder.add(order,elsewhere,trip)
        assertEquals(TripRouteItem("drop",checkNotNull(elsewhere.id)),added.last())
        assertEquals(added,TripRouteOrder.add(added,elsewhere,trip))
        assertFalse(TripRouteOrder.preservesCourses(added.filter {it.ref!="beach"},trip))
    }
    @Test fun movingPreservesAttachedDropAndBounds() {
        val order=TripRouteOrder.initial(trip(),car)
        val moved=TripRouteOrder.move(order,order.lastIndex,-1)
        assertEquals(drop.id,moved[1].dropRef)
        assertEquals(moved,TripRouteOrder.move(moved,0,-1))
        assertEquals(moved,TripRouteOrder.move(moved,moved.lastIndex,1))
    }
    @Test fun sameStopIdInTwoPacksIsNotTheSameRouteItem() {
        val data=trip().copy(courses=listOf(course,course.copy(packId="second")))
        assertEquals(4,TripRouteOrder.courseItems(data).map {it.key}.distinct().size)
    }
    @Test fun nearAndPassedThresholdsRequireAnActualApproach() {
        val target=TripRouteOrder.resolve(TripRouteOrder.initial(trip(),car),trip(),car)[1]
        val started=TripDrivingState().navigate(target)
        assertEquals(TripDrivingPhase.FAR,started.distance(1001.0).phase)
        assertEquals(TripDrivingPhase.FAR,started.distance(300.01).phase)
        val near=started.distance(300.0)
        assertEquals(TripDrivingPhase.NEAR,near.phase)
        assertEquals(TripDrivingPhase.NEAR,near.distance(1000.0).phase)
        val skipped=near.distance(1000.01)
        assertEquals(TripDrivingPhase.SKIPPED,skipped.phase)
        assertEquals(setOf(target.key),skipped.skipped)
        assertEquals(skipped,skipped.distance(200.0))
        assertEquals(started,started.distance(Double.NaN))
        assertEquals(started,started.distance(-1.0))
    }
    @Test fun routeStripShowsTheActiveSegmentWithoutInventingProgressBeforeNavigation() {
        val stops=TripRouteOrder.resolve(TripRouteOrder.initial(trip(),car),trip(),car)
        assertNull(tripRouteMarker(stops,TripDrivingState()))
        // 첫 장소가 아직 남아 있으면 그 뒤 장소를 안내 중이어도 표식은 첫 장소 앞에 둔다.
        assertEquals(-0.5f,tripRouteMarker(stops,TripDrivingState().navigate(stops[1]).distance(200.0)))
        val near=TripDrivingState(arrived=setOf(stops[0].key)).navigate(stops[1]).distance(200.0)
        assertEquals(0.5f,tripRouteMarker(stops,near))
        assertEquals(1f,tripRouteMarker(stops,near.arrive(false)))
    }
    @Test fun routeStripRestoresConfirmedStopsAndDoesNotPlaceOtherCourseTargets() {
        val stops=TripRouteOrder.resolve(TripRouteOrder.initial(trip(),car),trip(),car)
        val restored=TripDrivingState(arrived=setOf(stops[0].key))
        assertEquals(0f,tripRouteMarker(stops,restored))
        assertNull(tripRouteMarker(stops,TripDrivingState(targetKey="course:other:stop")))
        assertNull(tripRouteMarker(emptyList(),restored))
    }
    @Test fun arrivalLaterAndCourseCompletionNeverNavigateByThemselves() {
        val target=TripRouteOrder.resolve(TripRouteOrder.initial(trip(),car),trip(),car)[1]
        val near=TripDrivingState().navigate(target).distance(200.0)
        val arrived=near.arrive(false)
        assertEquals(TripDrivingPhase.ARRIVED,arrived.phase)
        assertEquals(target.key,arrived.later().targetKey)
        assertEquals(TripDrivingPhase.LATER,arrived.later().phase)
        val routeEnd=near.arrive(true)
        assertEquals(TripDrivingPhase.ROUTE_END,routeEnd.phase)
        val complete=routeEnd.complete(course.packId)
        assertEquals(TripDrivingPhase.ROUTE_COMPLETE,complete.phase)
        assertEquals(target.key,complete.targetKey)
        assertEquals(setOf(target.key),complete.arrived)
    }
    @Test fun busyMembersBlockStartWhileOwnRunningTripOnlyNeedsConfirmation() {
        val data=trip()
        val running=data.copy(startConflict=TripStartConflict(listOf(TripActiveTrip("9".repeat(32),"지난 여행",true)),emptyList()))
        val busy=data.copy(startConflict=TripStartConflict(emptyList(),listOf(memberC.id,memberD.id)))
        assertEquals(tripCanStart(data),tripCanStart(running))
        assertFalse(tripCanStart(busy))
        assertEquals(listOf(memberC.name,memberD.name),tripBusyMemberNames(busy))
        assertEquals(emptyList<String>(),tripBusyMemberNames(running))
    }
    @Test fun lifecycleAndDriverPermissionsFailClosed() {
        val data=trip()
        assertTrue(canPerformTripAction(data,TripAction.Start(1)))
        assertFalse(canPerformTripAction(data,TripAction.Finish(1)))
        assertFalse(canPerformTripAction(data,TripAction.Start(2)))
        assertFalse(canPerformTripAction(data.copy(state=null),TripAction.Start(1)))
        assertFalse(canPerformTripAction(data.copy(state="completed"),TripAction.EditIntro("여행","")))
        assertFalse(canPerformTripAction(data.copy(members=data.members.map {it.copy(isOwner=false)}),TripAction.Start(1)))
        assertFalse(canPerformTripAction(data,TripAction.EditCar(carId,"사용자A 차",1)))
    }
    @Test fun pickupAndDropWithoutACourseArriveNormallyWithoutOfferingCourseCompletion() {
        val data=trip().copy(courses=emptyList())
        val stops=TripRouteOrder.resolve(TripRouteOrder.initial(data,car),data,car)
        var drive=TripDrivingState()
        for(stop in stops) {
            drive=tripArriveAtStop(stops,drive.navigate(stop).distance(100.0))
            assertEquals(TripDrivingPhase.ARRIVED,drive.phase)
            assertTrue(stop.key in drive.arrived)
            assertNull(drive.completedCourse)
        }
        assertNull(tripNextStop(stops,drive))
    }
    @Test fun courseEndStillRequiresTheLastRemainingStopInThatCourse() {
        val stops=TripRouteOrder.resolve(TripRouteOrder.initial(trip(),car),trip(),car)
        var drive=TripDrivingState()
        for((index,stop) in stops.withIndex()) {
            drive=tripArriveAtStop(stops,drive.navigate(stop).distance(100.0))
            assertEquals(if(index==stops.lastIndex)TripDrivingPhase.ROUTE_END else TripDrivingPhase.ARRIVED,drive.phase)
        }
    }
    @Test fun serverCompletionSkipsFinishedCourseAfterReopeningWithoutStartingNavigation() {
        val data=trip().copy(courses=listOf(course.copy(completedCarIds=listOf(carId)),
            course.copy(packId="jumunjin",title="주문진 맛집 코스")))
        val restored=reconcileTripDriving(data,TripDrivingState())
        val stops=TripRouteOrder.resolve(TripRouteOrder.initial(data,car),data,car)
        assertEquals("jumunjin",tripNextStop(stops,restored)?.item?.courseId)
        assertNull(restored.targetKey)
        assertEquals(TripDrivingPhase.LATER,restored.phase)
    }
    @Test fun missingCourseIdIsResolvedOnlyWhenTheStopIsUnambiguous() {
        val saved=car.copy(routeOrder=listOf(TripRouteItem("course","beach"),TripRouteItem("course","coffee")))
        assertTrue(TripRouteOrder.preservesCourses(TripRouteOrder.initial(trip(),saved),trip()))
        val ambiguous=trip().copy(courses=listOf(course,course.copy(packId="second")))
        assertFalse(TripRouteOrder.preservesCourses(TripRouteOrder.initial(ambiguous,saved),ambiguous))
    }
    @Test fun savedSignalStopResolvesAndCanBeRemovedAndAddedWithoutChangingCourses() {
        val signal=TripPlace("함께 정한 휴게소",pickup.id,"signal",37.15,128.15)
        val signalItem=TripRouteItem("signal",checkNotNull(signal.id))
        val ordinary=TripRouteOrder.initial(trip(),car)
        val saved=car.copy(places=listOf(signal)+car.places.orEmpty(),routeOrder=ordinary+signalItem)
        val data=trip().copy(cars=listOf(saved))
        val order=TripRouteOrder.initial(data,saved)
        assertEquals(ordinary+signalItem,order)
        val stops=TripRouteOrder.resolve(order,data,saved)
        assertEquals(pickup.name,stops.first().name)
        val stop=stops.last()
        assertEquals(signal.name,stop.name);assertEquals("손들기",stop.kind)
        assertEquals(signal.lat,stop.lat);assertTrue(stop.canNavigate)
        assertTrue(stop.people.isEmpty());assertNull(tripStopCourse(stop,stops))
        val removed=TripRouteOrder.remove(order,order.lastIndex)
        assertEquals(listOf(signal),TripRouteOrder.outside(removed,saved.places.orEmpty()))
        assertEquals(order,TripRouteOrder.add(removed,signal,data))
        assertTrue(TripRouteOrder.preservesCourses(order,data))
        assertEquals(order,TripRouteOrder.add(order,signal,data))
    }
    @Test fun courseCompletionDoesNotCompleteAnAgreedSignalOrStartItsNavigation() {
        val signal=TripPlace("함께 정한 휴게소","1".repeat(32),"signal",37.15,128.15)
        val saved=car.copy(places=car.places.orEmpty()+signal,routeOrder=listOf(
            TripRouteItem("course","beach",course.packId),TripRouteItem("signal",checkNotNull(signal.id)),
            TripRouteItem("course","coffee",course.packId)))
        val data=trip().copy(cars=listOf(saved),courses=listOf(course.copy(completedCarIds=listOf(carId))))
        val stops=TripRouteOrder.resolve(TripRouteOrder.initial(data,saved),data,saved)
        val restored=reconcileTripDriving(data,TripDrivingState())
        assertEquals(stops[1],tripNextStop(stops,restored))
        assertNull(restored.targetKey);assertEquals(TripDrivingPhase.LATER,restored.phase)
        val arrived=tripArriveAtStop(stops,TripDrivingState().navigate(stops[1]).distance(100.0))
        assertEquals(TripDrivingPhase.ARRIVED,arrived.phase)
        assertNull(arrived.completedCourse)
        val unresolved=saved.copy(places=car.places)
        assertFalse(TripRouteOrder.resolve(listOf(stops[1].item),data,unresolved).single().canNavigate)
    }
}
