package io.wegoh.app

import io.wegoh.app.nativeauth.*
import java.io.Closeable
import org.junit.Assert.*
import org.junit.Test

class TripsRepositoryEventTest {
    @Test fun profileNameChangesWaitForTravelScreenEntry()=opened {repository,access,_->
        access.listener.onEvent(VehicleEvent("invalidate",listOf("profile"),mapOf("profile" to "3".repeat(32))))
        assertTrue(access.api.details.isEmpty());assertTrue(access.api.lists.isEmpty())
        assertEquals(owner.name,repository.states.value.detail?.members?.first()?.name)
        repository.closeDetail()
        val visibleList=repository.states.value.list
        repository.request(true)
        assertSame(visibleList,repository.states.value.list)
        assertEquals(1,access.api.lists.size)
        val renamed=detail.copy(members=listOf(owner.copy(name="새 이름")),cars=listOf(car.copy(driverName="새 이름")))
        access.api.lists.removeFirst()(Result.success(list.copy(trips=listOf(list.trips.first().copy(ownerName="새 이름")))))
        repository.select(id)
        assertEquals(1,access.api.details.size)
        access.api.details.removeFirst()(Result.success(renamed))
        assertEquals("새 이름",repository.states.value.detail?.members?.first()?.name)
        assertEquals("새 이름",repository.states.value.detail?.cars?.first()?.driverName)
        assertEquals("새 이름",repository.states.value.list?.trips?.first()?.ownerName)
        assertEquals(car.name,repository.states.value.detail?.cars?.first()?.name)
        assertEquals(1,access.clients)
    }
    @Test fun enteringFreshTripDetailAlsoUpdatesItsCachedOwnerName()=opened {repository,access,_->
        repository.closeDetail()
        repository.select(id)
        val renamed=detail.copy(members=listOf(owner.copy(name="새 이름")),cars=listOf(car.copy(driverName="새 이름")))
        access.api.details.removeFirst()(Result.success(renamed))
        assertEquals("새 이름",repository.states.value.detail?.members?.first()?.name)
        assertEquals("새 이름",repository.states.value.list?.trips?.first()?.ownerName)
        assertTrue(access.api.lists.isEmpty())
    }
    @Test fun drivingSpeedChangesOnlyTheLiveScoreWithoutReloadingTheTrip() {
        val course=TripCourse("live-course","해안 코스",version=1,stops=listOf(TripCourseStop("live-stop","바다",37.5,127.0)),completedCarIds=emptyList())
        val trip=detail.copy(cars=listOf(car.copy(places=emptyList())),courses=listOf(course))
        lateinit var speed: (Long,Double?)->Unit
        var current: TripsRepository?=null
        val scores=LocalCourseScores({null},{_,_->},{callback->speed=callback;Closeable {}},changed={key,result->current?.scoreChanged(key,result)})
        opened(trip=trip,scores=scores) {repository,access,_->
            current=repository
            repository.setGear(TripGear.DRIVE);repository.setSetupAllowed(false)
            speed(1000,20.0);speed(1200,20.0)
            assertEquals(100,repository.states.value.liveCourseScore?.score)
            speed(1400,30.0)
            assertEquals(95,repository.states.value.liveCourseScore?.score)
            assertEquals(course.packId,repository.states.value.liveCourseId)
            assertTrue(access.api.details.isEmpty());assertTrue(access.api.lists.isEmpty());assertTrue(access.api.sections.isEmpty())
            assertTrue(access.api.actions.isEmpty());assertFalse(repository.states.value.busy)
        }
    }
    @Test fun scoreSharingUsesChangesOnlyAndForgettingDoesNotQueueAnotherReport() {
        val course=TripCourse("live-course","해안 코스",version=1,stops=listOf(TripCourseStop("live-stop","바다",37.5,127.0)),completedCarIds=emptyList())
        val trip=detail.copy(cars=listOf(car.copy(places=emptyList())),courses=listOf(course))
        lateinit var speed: (Long,Double?)->Unit
        var current: TripsRepository?=null
        val scores=LocalCourseScores({null},{_,_->},{callback->speed=callback;Closeable {}},changed={key,result->current?.scoreChanged(key,result)})
        opened(trip=trip,scores=scores) {repository,access,_->
            current=repository
            speed(1000,10.0);speed(1200,10.0)
            repeat(10) {speed(1400+it*200L,10.0)}
            speed(3600,20.0)
            assertEquals(listOf(null,100,95),access.api.scoreReports.map {it.second.score})
            assertEquals(95,repository.states.value.liveCourseScore?.score)
            val staleSpeed=speed
            repository.forgetScores()
            assertEquals(3,access.api.scoreReports.size)
            assertNull(repository.states.value.liveCourseId)
            assertNull(repository.states.value.liveCourseScore)
            assertTrue(repository.states.value.courseResults.isEmpty())
            staleSpeed(3800,30.0)
            assertNull(repository.states.value.liveCourseScore)
            assertEquals(3,access.api.scoreReports.size)
            repository.setGear(TripGear.DRIVE)
            assertNull(repository.states.value.liveCourseScore?.score)
            speed(4000,10.0)
            assertNull(repository.states.value.liveCourseScore?.score)
            speed(4200,10.0)
            assertEquals(100,repository.states.value.liveCourseScore?.score)
        }
    }
    @Test fun driveModeLoadsAnActiveTripReadOnlyEvenWhenSetupIsRestricted() {
        val access=FakeAccess()
        val repository=TripsRepository(access)
        try {
            repository.setForeground(true);repository.setGear(TripGear.DRIVE)
            access.api.lists.removeFirst()(Result.success(list))
            assertEquals(id,repository.states.value.selectedId)
            access.api.details.removeFirst()(Result.success(detail))
            assertEquals(detail,repository.states.value.detail)
            repository.perform(TripAction.Finish(1)) {}
            assertTrue(access.api.actions.isEmpty())
            assertEquals(0,access.api.completions)
        } finally {repository.close()}
    }
    @Test fun typedLocationChangesCoalesceAndNeverReloadTheTripListDetailOrSignals()=opened {repository,access,_->
        val key="trip.$id.location"
        fun notify()=access.listener.onEvent(VehicleEvent("invalidate",listOf(key),mapOf(key to "1".repeat(32))))
        notify();notify();notify()
        assertEquals(1,access.api.sectionReplies.size)
        assertTrue(access.api.details.isEmpty());assertTrue(access.api.lists.isEmpty());assertTrue(access.api.signals.isEmpty())
        access.api.sectionReplies.removeFirst()(Result.success(detail.copy(locationSharing=true)))
        assertEquals(1,access.api.sectionReplies.size)
        access.api.sectionReplies.removeFirst()(Result.success(detail.copy(locationSharing=true)))
        assertTrue(access.api.sectionReplies.isEmpty())
        assertEquals(listOf("location","location"),access.api.sections)
        assertTrue(repository.states.value.detail?.locationSharing==true)
        val progress=repository.states.value.driving
        val unrelated="trip."+"f".repeat(32)+".music"
        access.listener.onEvent(VehicleEvent("invalidate",listOf(unrelated),mapOf(unrelated to "2".repeat(32))))
        assertTrue(access.api.details.isEmpty());assertTrue(access.api.sectionReplies.isEmpty())
        assertEquals(progress,repository.states.value.driving)
    }
    @Test fun delayedRouteSnapshotCannotRestoreAnOldRemotePolicyOrCarName() {
        val disabled=TripRemotePolicy(false,emptySet(),null)
        val enabled=TripRemotePolicy(true,setOf("hvac.temperature"),"d".repeat(32))
        val original=detail.copy(cars=listOf(car.copy(remotePolicy=disabled)))
        opened(trip=original,startNavigation=false) {repository,access,_->
            val resource="trip.$id.route"
            access.listener.onEvent(VehicleEvent("invalidate",listOf(resource),mapOf(resource to "1".repeat(32))))
            val oldRoute=access.api.sectionReplies.removeFirst()
            repository.request(true)
            val current=original.copy(cars=listOf(car.copy(name="새 차 이름",remotePolicy=enabled)))
            access.api.details.removeFirst()(Result.success(current))
            oldRoute(Result.success(original.copy(cars=listOf(car.copy(remotePolicy=disabled,routeRevision=5)))))
            val result=checkNotNull(repository.states.value.detail).cars.single()
            assertEquals(enabled,result.remotePolicy)
            assertEquals("새 차 이름",result.name)
            assertEquals(5L,result.routeRevision)
        }
    }
    private val id="a".repeat(32)
    private val owner=TripMember("team-"+"a".repeat(40),"사용자A",true,true,true)
    private val place=TripPlace("합정역","b".repeat(32),"pickup",37.5,127.0)
    private val car=TripCar("c".repeat(32),"사용자A 차",owner.id,owner.name,4,true,false,emptyList(),listOf(place))
    private val detail=TripDetail(id,"강릉 여행","",listOf(owner),listOf(car),state="active",revision=1,courses=emptyList())
    private val list=TripList(listOf(TripSummary(id,detail.title,true,owner.name,1,1,state="active")),emptyList())
    private val link=TripInviteLink("a".repeat(43),null)

    private fun opened(cars: Int=1,log: (String)->Unit = {},navigationRequested: ()->Unit = {},
        startNavigation: Boolean=true,observeRoute: (List<TripRouteStop>)->Unit = {},trip: TripDetail?=null,scores: CourseScores?=null,
        locateSignal: ((SignalLocation?)->Unit)->Closeable = {callback->callback(null);Closeable {}},
        observeLocation: ((TripLocationFix)->Unit,(LocationUnavailableReason)->Unit)->Closeable = {_,_->Closeable {}},canShareLocation: (()->Boolean)?=null,
        block: (TripsRepository,FakeAccess,()->Int)->Unit) {
        val access=FakeAccess();var stopped=0
        val repository=TripsRepository(access,{navigationRequested();true},{stopped++},locateSignal=locateSignal,log=log,observeRoute=observeRoute,scores=scores,observeLocation=observeLocation,canShareLocation=canShareLocation)
        try {
            repository.setForeground(true);repository.setCarUxKnown(true);repository.setSetupAllowed(true);repository.setGear(TripGear.PARK);repository.request()
            access.api.lists.removeFirst()(Result.success(list))
            val selected=trip ?: if(cars==1)detail else detail.copy(cars=listOf(car)+List(cars-1) {index->
                car.copy(id=(index+10).toString(16).padStart(32,'0'),driverId="team-"+(index+10).toString(16).padStart(40,'0'),isMine=false)
            })
            repository.select(id);access.api.details.removeFirst()(Result.success(selected))
            if(startNavigation) {
                val ownCar=checkNotNull(selected.myCar)
                val stop=TripRouteOrder.resolve(TripRouteOrder.initial(selected,ownCar),selected,ownCar).first()
                repository.navigate(stop);repository.distance(200.0)
            }
            stopped=0
            block(repository,access,{stopped})
        } finally {repository.close()}
    }
    @Test fun handRaiseSearchUsesTheCarNextStopWithoutSdkGuidanceOrHeading() {
        val next=TripPlace("다음 픽업","d".repeat(32),"pickup",37.55,126.9)
        val nextItem=TripRouteItem("pickup",checkNotNull(next.id))
        val ownCar=car.copy(places=listOf(place,next),routeNext=nextItem,routeNextKnown=true)
        val position=SignalPoint(37.5,126.8)
        opened(startNavigation=false,trip=detail.copy(cars=listOf(ownCar)),locateSignal={reply->
            reply(SignalLocation(position.copy(heading=Double.NaN)));Closeable {}
        }) {repository,access,_->
            repository.refreshSignals();access.api.replySignals(emptyList())
            repository.loadSignalCandidates(TripSignalKind.RESTROOM)
            assertEquals(listOf(Triple(id,TripSignalKind.RESTROOM,SignalLocation(position,SignalPoint(37.55,126.9)))),access.api.candidateRequests)
            val stop=SignalCandidate("쉼터",37.52,126.85,"ahead","경로 위",5000.0,null)
            access.api.candidateReplies.removeFirst()(Result.success(listOf(stop)))
            assertEquals(listOf(stop),repository.states.value.signals.candidates)
            assertFalse(repository.states.value.signals.loading)
            assertEquals(next.name,repository.states.value.detail?.signalRouteStop(repository.states.value.driving)?.name)
        }
    }
    @Test fun handRaiseSearchWithoutRouteOrHeadingKeepsTheExistingRouteAndOffersARequestWithoutPlace() {
        val ownCar=car.copy(routeNextKnown=true)
        opened(startNavigation=false,trip=detail.copy(cars=listOf(ownCar)),locateSignal={reply->
            reply(SignalLocation(SignalPoint(37.5,126.8)));Closeable {}
        }) {repository,access,_->
            repository.refreshSignals();access.api.replySignals(emptyList())
            val before=repository.states.value.detail
            repository.loadSignalCandidates(TripSignalKind.RESTROOM)
            assertTrue(access.api.candidateRequests.isEmpty())
            assertSame(before,repository.states.value.detail)
            assertTrue(repository.states.value.signals.hint.orEmpty().contains("장소 없이"))
            assertFalse(repository.states.value.signals.loading)
        }
    }
    @Test fun shiftingToDriveKeepsTheHandRaiseSearchAndItsResult() {
        lateinit var position: (SignalLocation?)->Unit
        var cancelled=false
        opened(startNavigation=false,locateSignal={reply->
            position=reply;Closeable {cancelled=true}
        }) {repository,access,_->
            repository.refreshSignals();access.api.replySignals(emptyList())
            repository.loadSignalCandidates(TripSignalKind.RESTROOM)
            assertTrue(repository.states.value.signals.loading)
            repository.setGear(TripGear.DRIVE);repository.setSetupAllowed(false)
            assertFalse(cancelled)
            position(SignalLocation(SignalPoint(37.5,126.8,90.0)))
            assertEquals(1,access.api.candidateRequests.size)
            val stop=SignalCandidate("쉼터",37.52,126.85,"ahead","경로 위",5000.0,null)
            access.api.candidateReplies.removeFirst()(Result.success(listOf(stop)))
            assertEquals(listOf(stop),repository.states.value.signals.candidates)
            assertFalse(repository.states.value.signals.loading)
        }
    }
    @Test fun leavingParkAndDriveCancelsHandRaiseSearchAndIgnoresALateLocation() {
        lateinit var position: (SignalLocation?)->Unit
        var cancelled=false
        opened(startNavigation=false,locateSignal={reply->
            position=reply;Closeable {cancelled=true}
        }) {repository,access,_->
            repository.refreshSignals();access.api.replySignals(emptyList())
            repository.loadSignalCandidates(TripSignalKind.RESTROOM)
            assertTrue(repository.states.value.signals.loading)
            repository.setGear(TripGear.OTHER)
            assertTrue(cancelled)
            position(SignalLocation(SignalPoint(37.5,126.8,90.0)))
            assertTrue(access.api.candidateRequests.isEmpty())
            assertFalse(repository.states.value.signals.loading)
            assertTrue(repository.states.value.signals.candidates.isEmpty())
        }
    }
    @Test fun drivingKeepsMyAlreadySentRequestAndLetsMeFinishIt()=opened(startNavigation=false) {repository,access,_->
        val signal=TripSignal("sent-signal",owner.id,TripSignalKind.REST,null,java.time.Instant.now().toString(),"valid",0,0,null)
        repository.refreshSignals();access.api.replySignals(emptyList())
        repository.sendTripSignal(null)
        access.api.sends.removeFirst()(Result.success(signal.id))
        access.api.replySignals(listOf(signal))
        assertEquals(signal.id,repository.states.value.signals.sentId)
        assertEquals(signal,repository.states.value.signals.ongoing)

        repository.setGear(TripGear.DRIVE);repository.setSetupAllowed(false)
        assertEquals(signal.id,repository.states.value.signals.sentId)
        assertEquals(signal,repository.states.value.signals.ongoing)
        assertTrue(repository.states.value.signals.hasActiveSignal)
        repository.sendTripSignal(null)
        assertTrue(access.api.sends.isEmpty())
        repository.setCarUxKnown(false)
        repository.finishTripSignal("cancelled")
        assertTrue(access.api.finished.isEmpty())
        repository.setCarUxKnown(true)
        repository.finishTripSignal("cancelled")
        assertEquals(1,access.api.finished.size)
    }
    @Test fun sendAcknowledgedAfterLeavingParkStillTracksTheOriginalRequest()=opened(startNavigation=false) {repository,access,_->
        val signal=TripSignal("late-sent-signal",owner.id,TripSignalKind.REST,null,java.time.Instant.now().toString(),"valid",0,0,null)
        repository.refreshSignals();access.api.replySignals(emptyList())
        repository.sendTripSignal(null)
        val acknowledge=access.api.sends.removeFirst()
        repository.setGear(TripGear.DRIVE);repository.setSetupAllowed(false)
        assertTrue(repository.states.value.signals.sending)

        acknowledge(Result.success(signal.id))
        access.api.replySignals(listOf(signal))
        assertFalse(repository.states.value.signals.sending)
        assertEquals(signal.id,repository.states.value.signals.sentId)
        assertEquals(signal,repository.states.value.signals.ongoing)
        assertTrue(repository.states.value.signals.hasActiveSignal)
        assertTrue(access.api.sends.isEmpty())
        assertTrue(access.api.finished.isEmpty())
    }
    @Test fun unknownCarUxOrOtherGearCancelsCandidateReadAndIgnoresItsLateReply() {
        for(carUxUnknown in listOf(false,true)) {
            opened(startNavigation=false,locateSignal={reply->
                reply(SignalLocation(SignalPoint(37.5,126.8,90.0)));Closeable {}
            }) {repository,access,_->
                repository.refreshSignals();access.api.replySignals(emptyList())
                repository.loadSignalCandidates(TripSignalKind.RESTROOM)
                assertEquals(1,access.api.candidateRequests.size)
                assertTrue(repository.states.value.signals.loading)
                val lateReply=access.api.candidateReplies.removeFirst()
                if(carUxUnknown) {repository.setGear(TripGear.DRIVE);repository.setSetupAllowed(false);repository.setCarUxKnown(false)}
                else repository.setGear(TripGear.OTHER)
                assertEquals(1,access.api.candidateReadCloses)
                assertFalse(repository.states.value.signals.loading)
                assertTrue(repository.states.value.signals.candidates.isEmpty())

                lateReply(Result.success(listOf(SignalCandidate("늦은 쉼터",37.52,126.85,"ahead","경로 위",5000.0,null))))
                assertFalse(repository.states.value.signals.loading)
                assertTrue(repository.states.value.signals.candidates.isEmpty())
                assertNull(repository.states.value.signals.hint)
                assertTrue(access.api.sends.isEmpty())
                assertTrue(access.api.finished.isEmpty())
            }
        }
    }
    @Test fun navigatingToALaterStopMarksTheStopsBeforeItSkipped() {
        val second=TripPlace("망원동","d".repeat(32),"pickup",37.55,126.9)
        val twoStops=car.copy(places=listOf(place,second))
        val trip=detail.copy(cars=listOf(twoStops))
        val access=FakeAccess();val sent=mutableListOf<String>()
        val repository=TripsRepository(access,{sent+=it.name;true},{})
        try {
            repository.setForeground(true);repository.setSetupAllowed(true);repository.request()
            access.api.lists.removeFirst()(Result.success(list))
            repository.select(id);access.api.details.removeFirst()(Result.success(trip))
            val stops=TripRouteOrder.resolve(TripRouteOrder.initial(trip,twoStops),trip,twoStops)
            assertEquals(2,stops.size)
            repository.navigate(stops[1])
            assertEquals(listOf(stops[1].name),sent)
            assertEquals(stops[1].key,repository.states.value.driving.targetKey)
            assertTrue(stops[0].key in repository.states.value.driving.skipped)
            repository.navigate(stops[0])
            assertEquals(stops[0].key,repository.states.value.driving.targetKey)
            assertFalse(stops[0].key in repository.states.value.driving.skipped)
        } finally {repository.close()}
    }
    @Test fun invalidateBeforeHttpSuccessPreservesSelectionProgressAndLink()=opened {repository,access,stopped->
        val progress=repository.states.value.driving
        var completed=0
        repository.perform(TripAction.CreateLink) {completed++}
        access.invalidate()
        assertTrue(access.api.details.isEmpty())
        assertEquals(progress,repository.states.value.driving)
        access.api.actions.removeFirst()(Result.success(TripActionResult(link)))
        assertEquals(1,completed)
        access.api.details.removeFirst()(Result.success(detail.copy(description="저장됨")))
        assertEquals(id,repository.states.value.selectedId)
        assertEquals("저장됨",repository.states.value.detail?.description)
        assertEquals(progress,repository.states.value.driving)
        assertSame(link,repository.states.value.inviteLink)
        assertEquals(0,stopped())
        assertEquals(1,access.clients)
    }
    @Test fun invalidateDuringRefreshAfterHttpSuccessQueuesAnotherReadWithoutDiscardingToken()=opened {repository,access,stopped->
        repository.perform(TripAction.CreateLink) {}
        access.api.actions.removeFirst()(Result.success(TripActionResult(link)))
        access.invalidate()
        access.api.details.removeFirst()(Result.success(detail))
        assertEquals(1,access.api.details.size)
        access.api.details.removeFirst()(Result.success(detail.copy(description="다른 변경")))
        assertSame(link,repository.states.value.inviteLink)
        assertEquals(id,repository.states.value.selectedId)
        assertEquals(TripDrivingPhase.NEAR,repository.states.value.driving.phase)
        assertEquals(0,stopped())
    }
    @Test fun invalidateAfterRefreshReadsOnlyDetailAndKeepsToken()=opened {repository,access,stopped->
        repository.perform(TripAction.CreateLink) {}
        access.api.actions.removeFirst()(Result.success(TripActionResult(link)))
        access.api.details.removeFirst()(Result.success(detail))
        access.invalidate()
        assertTrue(access.api.lists.isEmpty())
        assertSame(link,repository.states.value.inviteLink)
        access.api.details.removeFirst()(Result.success(detail))
        assertEquals(0,stopped())
    }
    @Test fun authorityRevocationClearsPrivateStateAndIgnoresLateHttpSuccess()=opened {repository,access,stopped->
        var completed=false
        repository.perform(TripAction.CreateLink) {completed=true}
        val reply=access.api.actions.removeFirst()
        access.authority.onInvalidated()
        reply(Result.success(TripActionResult(link)))
        assertFalse(completed)
        assertNull(repository.states.value.inviteLink)
        assertFalse(repository.states.value.isCurrent)
        // 무효화만으로는 철회인지 알 수 없다. 다시 읽기가 동의 없음으로 끝나면 그때 비운다.
        access.api.lists.removeFirst()(Result.failure(NativeSocialFailure(NativeSocialFailure.Kind.CONSENT_REQUIRED)))
        assertEquals(AccountReadStatus.PERMISSION_REQUIRED,repository.states.value.status)
        assertNull(repository.states.value.selectedId)
        assertNull(repository.states.value.detail)
        assertEquals(TripDrivingState(),repository.states.value.driving)
        assertEquals(1,stopped())
    }
    @Test fun transientInvalidationKeepsTheOpenTripAndRereadsInPlace() {
        // 연결이 잠깐 unavailable이 되어 클라이언트만 무효화돼도 열린 여행이 목록으로 튕기지 않는다.
        val logs=mutableListOf<String>()
        opened(log={logs.add(it)}) {repository,access,stopped->
            val clients=access.clients
            access.authority.onInvalidated()
            assertEquals(id,repository.states.value.selectedId)
            assertEquals(detail.id,repository.states.value.detail?.id)
            assertFalse(repository.states.value.isCurrent)
            assertEquals(clients+1,access.clients)
            assertTrue(logs.any {it.startsWith("trip.retain: reason=social_invalidated")})
            assertTrue(logs.none {it.startsWith("trip.clear:")})
            access.api.lists.removeFirst()(Result.success(list))
            assertEquals(id,repository.states.value.selectedId)
            assertNotNull(repository.states.value.detail)
            assertEquals(1,access.api.details.size)
            access.api.details.removeFirst()(Result.success(detail))
            assertTrue(repository.states.value.isCurrent)
            assertEquals(id,repository.states.value.selectedId)
            assertEquals(0,stopped())
        }
    }
    @Test fun invalidationAfterAccountBoundaryChangeStillClears()=opened {repository,access,stopped->
        access.changeAccount()
        access.authority.onInvalidated()
        assertNull(repository.states.value.selectedId)
        assertNull(repository.states.value.detail)
        assertNull(repository.states.value.list)
        assertEquals(1,stopped())
    }
    @Test fun refreshRereadsTheOpenTripWithoutReturningToTheList()=opened {repository,access,_->
        repository.request(true)
        assertEquals(id,repository.states.value.selectedId)
        assertNotNull(repository.states.value.detail)
        assertTrue(access.api.lists.isEmpty())
        access.api.details.removeFirst()(Result.success(detail))
        assertEquals(id,repository.states.value.selectedId)
        // 클라이언트가 이미 무효화된 뒤 누른 새로고침도 다시 열어 같은 여행을 읽는다.
        access.clientAvailable=false
        repository.request(true)
        assertEquals(id,repository.states.value.selectedId)
        assertNotNull(repository.states.value.detail)
        access.api.lists.removeFirst()(Result.success(list))
        access.api.details.removeFirst()(Result.success(detail))
        assertEquals(id,repository.states.value.selectedId)
        assertTrue(repository.states.value.isCurrent)
    }
    @Test fun pickupWithoutCoursesCanArriveAndDoesNotCompleteACourse()=opened {repository,access,_->
        repository.arrive()
        assertEquals(TripDrivingPhase.ARRIVED,repository.states.value.driving.phase)
        assertEquals(1,repository.states.value.driving.arrived.size)
        val arrival=repository.states.value.detail?.display?.timeline?.single()
        assertEquals(place.name,arrival?.name)
        assertEquals("타는 곳 도착",arrival?.kind)
        assertNotNull(java.time.Instant.parse(arrival?.at))
        repository.arrive()
        assertEquals(1,repository.states.value.detail?.display?.timeline?.size)
        repository.completeCourse()
        assertEquals(0,access.api.completions)
    }
    @Test fun refreshThatConfirmsLostTripAccessClearsThePrivateState()=opened {repository,access,stopped->
        repository.perform(TripAction.CreateLink) {}
        access.api.actions.removeFirst()(Result.success(TripActionResult(link)))
        access.api.details.removeFirst()(Result.success(detail))
        access.invalidate()
        access.api.details.removeFirst()(Result.failure(NativeSocialFailure(NativeSocialFailure.Kind.FORBIDDEN)))
        assertNull(repository.states.value.detail)
        assertNull(repository.states.value.selectedId)
        assertNull(repository.states.value.inviteLink)
        assertEquals(TripDrivingState(),repository.states.value.driving)
        assertEquals(1,stopped())
    }

    @Test fun fakeNaviUpdatesActiveTripWhileDrivingWithoutAppNavigation() {
        var monitored: List<TripRouteStop> = emptyList()
        opened(startNavigation=false,observeRoute={monitored=it}) {repository,access,_->
            assertEquals(1,monitored.size)
            assertEquals(TripDrivingPhase.LATER,repository.states.value.driving.phase)
            repository.setGear(TripGear.DRIVE);repository.setSetupAllowed(false)
            val navi=FakeNavi(repository::navigationUpdate)
            navi.target(monitored.single(),98000.0,1800)
            assertEquals(98000.0,repository.states.value.driving.distanceMeters!!,0.0)
            assertEquals(1800,repository.states.value.driving.remainingSeconds)
            navi.target(monitored.single(),250.0,60)
            assertEquals(TripDrivingPhase.NEAR,repository.states.value.driving.phase)
            navi.target(monitored.single(),30.0,5)
            assertEquals(TripDrivingPhase.ARRIVED,repository.states.value.driving.phase)
            assertTrue(monitored.single().key in repository.states.value.driving.arrived)
            assertTrue(access.api.actions.isEmpty());assertEquals(0,access.api.completions)
            repository.setForeground(false)
            val paused=repository.states.value.driving
            navi.target(monitored.single(),5000.0,500)
            assertEquals(paused,repository.states.value.driving)
        }
    }
    @Test fun vehiclePositionReachesParkedTripStateAndDropsAreLogged() {
        val messages=mutableListOf<String>()
        opened(startNavigation=false,log=messages::add) {repository,_,_->
            val point=TripPosition(37.55412,126.96995)
            repository.navigationUpdate(TripNavigationUpdate(position=point))
            assertEquals(point,repository.states.value.driving.position)
            assertTrue(messages.none {it.startsWith("trip.vehicle.location:")})
            repository.setForeground(false)
            repository.navigationUpdate(TripNavigationUpdate(position=TripPosition(37.6,127.0)))
            assertEquals(listOf("trip.vehicle.location: dropped reason=background stage=trip lat=37.600 lng=127.000"),
                messages.filter {it.startsWith("trip.vehicle.location:")})
        }
    }
    private class FakeNavi(private val update: (TripNavigationUpdate)->Unit) {
        fun target(stop: TripRouteStop,meters: Double,seconds: Int) {
            update(TripNavigationUpdate(targets=listOf(TripNavigationTarget(stop.lat!!,stop.lng!!,meters,seconds))))
        }
    }
    @Test fun serverRotationKeepsTripDetailCurrentWithoutReloadOrFailureNotice() {
        val messages=mutableListOf<String>()
        opened(cars=3,log=messages::add) {repository,access,_->
            val attempts=mutableListOf<Pair<VehicleEventsListener,(Result<Closeable>)->Unit>>()
            val rotation=NativeEventRotation({true},{_,listener,reply->attempts.add(listener to reply)},
                {Closeable {}},object: VehicleEventsListener {
                    override fun onEvent(event: VehicleEvent)=access.listener.onEvent(event)
                    override fun onUnavailable()=access.listener.onUnavailable()
                    override fun onClosed()=access.listener.onClosed()
                },{},messages::add)
            rotation.start()
            attempts[0].first.onEvent(VehicleEvent("snapshot",listOf("devices")))
            attempts[0].second(Result.success(Closeable {}))
            val selected=repository.states.value.detail
            attempts[0].first.onClosed(1008)
            assertTrue(repository.states.value.isCurrent)
            assertFalse(repository.states.value.busy)
            assertNull(repository.states.value.notice)
            assertSame(selected,repository.states.value.detail)
            assertTrue(access.api.details.isEmpty())
            attempts[1].second(Result.success(Closeable {}))
            attempts[1].first.onEvent(VehicleEvent("snapshot",listOf("devices")))
            assertTrue(repository.states.value.isCurrent)
            assertEquals(listOf("native.events: reconnected reason=server_rotation"),messages)
            assertEquals(1,access.clients)
            rotation.close()
        }
    }
    @Test fun sendDoesNotRemainPendingWhenEventClientCloses()=opened {repository,access,_->
        repository.refreshSignals();access.api.replySignals(emptyList())
        repository.sendTripSignal(null)
        assertTrue(repository.states.value.signals.sending)
        access.clientAvailable=false
        access.authority.onConnectionLost()
        assertFalse(repository.states.value.signals.sending)
        assertEquals("보내지 못했어요. 다시 눌러 주세요",repository.states.value.signals.hint)
        assertNull(repository.states.value.signals.sentId)
    }
    @Test fun viewModelVoteWorksAndNewSendIsBlockedWhileAnotherRequestIsActive()=opened(cars=3) {repository,access,_->
        showOtherSignal(repository,access)
        val actions=TripsViewModel(repository).actions
        actions.voteSignal("agree")
        assertEquals(listOf("agree"),access.api.votes)
        actions.sendSignal(null)
        assertTrue(access.api.sends.isEmpty())
    }
    @Test fun transientDetailFailureRetriesOnceAndRecoversWithoutClosingSignalClient()=opened(cars=3) {repository,access,_->
        access.invalidate()
        access.api.details.removeFirst()(Result.failure(NativeSocialFailure(NativeSocialFailure.Kind.UNAVAILABLE)))
        assertEquals(1,access.api.details.size)
        assertEquals(1,access.clients)
        access.api.details.removeFirst()(Result.success(checkNotNull(repository.states.value.detail)))
        assertTrue(repository.states.value.isCurrent)
        assertNull(repository.states.value.notice)
    }
    @Test fun voteUsesLastActiveDetailAfterBothTransientDetailReadsFail()=opened(cars=3) {repository,access,_->
        showOtherSignal(repository,access)
        access.invalidate()
        repeat(2) {access.api.details.removeFirst()(Result.failure(NativeSocialFailure(NativeSocialFailure.Kind.UNAVAILABLE)))}
        assertTrue(access.api.details.isEmpty())
        assertFalse(repository.states.value.isCurrent)
        repository.voteTripSignal("agree")
        assertEquals(listOf("agree"),access.api.votes)
        assertTrue(repository.states.value.signals.voting)
        assertEquals(1,access.clients)
        access.api.voteReplies.removeFirst()(Result.success(Unit))
        assertEquals(1,access.api.signals.size)
    }
    @Test fun authorityInvalidationWithoutConnectionChangeReloadsTheTrips()=opened {repository,access,_->
        // 연결 직후 기능 권한 교체가 클라이언트만 무효화하고 연결 상태 알림은 오지 않는다.
        val clients=access.clients
        access.authority.onInvalidated()
        assertEquals(clients+1,access.clients)
        assertEquals(1,access.api.lists.size)
        access.api.lists.removeFirst()(Result.success(list))
        assertEquals(AccountReadStatus.READY,repository.states.value.status)
        assertNotNull(repository.states.value.list)
    }
    @Test fun repeatedInvalidationBeforeAnyLoadStopsAtTheLimit()=opened {_,access,_->
        repeat(INVALIDATION_RELOAD_LIMIT+2) {access.authority.onInvalidated()}
        assertEquals(INVALIDATION_RELOAD_LIMIT,access.api.lists.size)
    }
    @Test fun unrememberedReadReloadsUnderTheSharedLimit() {
        // 읽기는 성공했지만 데이터 경계를 기억하지 못해 비우면 연결 상태 알림이 오지 않는다.
        val logs=mutableListOf<String>()
        opened(startNavigation=false,log={logs.add(it)}) {repository,access,_->
            repository.closeDetail();repository.request(true)
            access.remembers=false
            access.api.lists.removeFirst()(Result.success(list))
            assertEquals(1,access.api.lists.size)
            repeat(INVALIDATION_RELOAD_LIMIT) {access.api.lists.removeFirst()(Result.success(list))}
            assertTrue(access.api.lists.isEmpty())
            assertEquals(AccountReadStatus.CONNECTION_REQUIRED,repository.states.value.status)
            assertTrue(logs.any {it.startsWith("trip.clear: reason=unremembered")})
            assertTrue(logs.contains("trip.reload: skipped reason=limit"))
            assertTrue(logs.none {it.contains(id.take(8))})
            access.remembers=true;repository.request(true)
            access.api.lists.removeFirst()(Result.success(list))
            assertEquals(list,repository.states.value.list)
        }
    }
    @Test fun signalAuthorityLossReloadsTheTrips()=opened {repository,access,_->
        repository.refreshSignals()
        access.api.signals.removeFirst()(Result.failure(NativeSocialFailure(NativeSocialFailure.Kind.AUTHORIZATION_REQUIRED)))
        assertEquals(1,access.api.lists.size)
        access.api.lists.removeFirst()(Result.success(list))
        assertEquals(AccountReadStatus.READY,repository.states.value.status)
        assertEquals(list,repository.states.value.list)
    }
    @Test fun featureLocalSignalRejectionDoesNotReload()=opened {repository,access,_->
        repository.refreshSignals()
        access.api.signals.removeFirst()(Result.failure(NativeSocialFailure(NativeSocialFailure.Kind.FORBIDDEN,httpStatus=403,serverErrorCode="VEHICLE_OWNER_REQUIRED")))
        assertNull(repository.states.value.detail)
        assertTrue(access.api.lists.isEmpty())
    }
    @Test fun transientServerFailureRecoversWithBackoffWithoutDriverInput()=opened {repository,access,_->
        access.invalidate()
        access.api.details.removeFirst()(Result.failure(NativeSocialFailure(NativeSocialFailure.Kind.UNAVAILABLE,httpStatus=502)))
        assertFalse(repository.states.value.isCurrent)
        assertEquals(listOf(TRANSIENT_RECOVERY_BASE_MILLIS),access.scheduled.map {it.first})
        access.scheduled.removeFirst().second()
        access.api.lists.removeFirst()(Result.failure(NativeSocialFailure(NativeSocialFailure.Kind.UNAVAILABLE,httpStatus=502)))
        assertEquals(listOf(TRANSIENT_RECOVERY_BASE_MILLIS*2),access.scheduled.map {it.first})
        access.scheduled.removeFirst().second()
        access.api.lists.removeFirst()(Result.success(list))
        access.api.details.removeFirst()(Result.success(detail))
        assertTrue(repository.states.value.isCurrent)
        assertTrue(access.scheduled.isEmpty())
    }
    @Test fun authorizationFailureIsNotRetriedAutomatically()=opened {repository,access,_->
        access.invalidate()
        access.api.details.removeFirst()(Result.failure(NativeSocialFailure(NativeSocialFailure.Kind.FORBIDDEN,httpStatus=403)))
        assertEquals(AccountReadStatus.PERMISSION_REQUIRED,repository.states.value.status)
        assertTrue(access.scheduled.isEmpty())
    }
    @Test fun transientRecoveryStopsAfterTheAttemptLimit()=opened {repository,access,_->
        access.invalidate()
        access.api.details.removeFirst()(Result.failure(NativeSocialFailure(NativeSocialFailure.Kind.UNAVAILABLE,httpStatus=502)))
        val delays=mutableListOf<Long>()
        while(access.scheduled.isNotEmpty()) {
            val (delay,action)=access.scheduled.removeFirst();delays.add(delay);action()
            access.api.lists.removeFirst()(Result.failure(NativeSocialFailure(NativeSocialFailure.Kind.UNAVAILABLE,httpStatus=503)))
        }
        assertEquals(TRANSIENT_RECOVERY_ATTEMPTS,delays.size)
        assertEquals(TRANSIENT_RECOVERY_MAX_MILLIS,delays.last())
        assertFalse(repository.states.value.isCurrent)
    }
    @Test fun detailHttpFailureDoesNotUseTransportRetry()=opened {repository,access,_->
        access.invalidate()
        access.api.details.removeFirst()(Result.failure(NativeSocialFailure(NativeSocialFailure.Kind.UNAVAILABLE,httpStatus=503)))
        assertTrue(access.api.details.isEmpty())
        assertFalse(repository.states.value.isCurrent)
    }
    @Test fun voteFailureStaysVisibleAcrossSignalPollFailureAndCanRetry()=opened(cars=3) {repository,access,_->
        showOtherSignal(repository,access)
        val overlay=repository.states.value.signals.overlay
        repository.voteTripSignal("agree")
        access.api.voteReplies.removeFirst()(Result.failure(NativeSocialFailure(NativeSocialFailure.Kind.UNAVAILABLE)))
        assertEquals("답을 보내지 못했어요. 다시 눌러 주세요",repository.states.value.signals.result)
        assertFalse(repository.states.value.signals.voting)
        assertNull(repository.states.value.signals.voted)
        repository.refreshSignals()
        access.api.signals.removeFirst()(Result.failure(NativeSocialFailure(NativeSocialFailure.Kind.UNAVAILABLE)))
        assertEquals(overlay,repository.states.value.signals.overlay)
        assertEquals("답을 보내지 못했어요. 다시 눌러 주세요",repository.states.value.signals.result)
        repository.voteTripSignal("agree")
        assertEquals(listOf("agree","agree"),access.api.votes)
        access.api.voteReplies.removeFirst()(Result.success(Unit))
        assertEquals("agree",repository.states.value.signals.voted)
    }
    @Test fun skippedVotesLogFixedConditionsWithoutSendingAnotherRequest() {
        val messages=mutableListOf<String>()
        opened(cars=3,log=messages::add) {repository,access,_->
            showOtherSignal(repository,access)
            repository.voteTripSignal("agree")
            repository.voteTripSignal("agree")
            assertEquals(listOf("agree"),access.api.votes)
            assertEquals("trip.signals: vote skipped reason=voting",messages.last())
            repository.dismissTripSignal()
            repository.voteTripSignal("agree")
            assertEquals("trip.signals: vote skipped reason=signal_missing",messages.last())
        }
    }
    @Test fun unreadyClientLogsSkipAndShowsRetryMessageUntilClientRecovers() {
        val messages=mutableListOf<String>()
        opened(cars=3,log=messages::add) {repository,access,_->
            showOtherSignal(repository,access)
            access.clientAvailable=false
            repository.voteTripSignal("agree")
            assertTrue(access.api.votes.isEmpty())
            assertEquals("trip.signals: vote skipped reason=client_not_ready",messages.last())
            assertEquals("답을 보내지 못했어요. 다시 눌러 주세요",repository.states.value.signals.result)
            access.clientAvailable=true
            repository.voteTripSignal("agree")
            assertEquals(listOf("agree"),access.api.votes)
        }
    }
    @Test fun losingClientDuringVoteReleasesVotingAndShowsFailure()=opened(cars=3) {repository,access,_->
        showOtherSignal(repository,access)
        repository.voteTripSignal("agree")
        access.clientAvailable=false
        access.authority.onConnectionLost()
        assertFalse(repository.states.value.signals.voting)
        assertEquals("답을 보내지 못했어요. 다시 눌러 주세요",repository.states.value.signals.result)
        assertNotNull(repository.states.value.signals.overlay)
        assertEquals(2,access.clients)
    }
    private fun showOtherSignal(repository: TripsRepository,access: FakeAccess) {
        repository.refreshSignals()
        access.api.replySignals(TripSignalsDevFixture.signals(createdAt=java.time.Instant.now().toString()))
        assertNotNull(repository.states.value.signals.overlay)
    }
    @Test fun devThreeSignalsKeepDetailAvailableAndShowRecentRequest()=opened(cars=3) {repository,access,_->
        val selected=repository.states.value.detail
        val timestamp=java.time.OffsetDateTime.now(java.time.ZoneOffset.ofHours(9)).toString().replace('T',' ')
        val signals=TripSignalsDevFixture.signals(createdAt=timestamp)
        repository.refreshSignals();access.api.replySignals(signals)
        assertSame(selected,repository.states.value.detail)
        assertTrue(repository.states.value.isCurrent)
        assertNull(repository.states.value.notice)
        assertEquals(signals.first(),repository.states.value.signals.overlay)
    }
    @Test fun invalidSignalResponseClearsOnlySignalsAndCanRecover()=opened(cars=3) {repository,access,_->
        val selected=repository.states.value.detail
        val timestamp=java.time.Instant.now().toString()
        val signals=TripSignalsDevFixture.signals(createdAt=timestamp)
        repository.refreshSignals();access.api.replySignals(signals)
        val broken=StrictNativeJson.parseBusiness(TripSignalsDevFixture.response(createdAt=timestamp).toByteArray(Charsets.UTF_8))
        broken.getJSONArray("signals").getJSONObject(1).remove("votes")
        val parsed=runCatching {TripSignalsCodec.signals(broken)}
        assertTrue(parsed.isFailure)
        repository.refreshSignals();access.api.signals.removeFirst()(parsed.map {TripSignalPage(it)}.recoverCatching {throw socialRequestFailure(it,false)})
        assertSame(selected,repository.states.value.detail)
        assertTrue(repository.states.value.isCurrent)
        assertFalse(repository.states.value.busy)
        assertNull(repository.states.value.notice)
        assertNull(repository.states.value.signals.overlay)
        repository.refreshSignals()
        assertEquals(1,access.api.signals.size)
        access.api.replySignals(signals)
        assertTrue(repository.states.value.isCurrent)
    }
    @Test fun signalReadFailureLogsOnlyClassKindAndTruncatedTrip() {
        val messages=mutableListOf<String>()
        opened(log=messages::add) {repository,access,_->
            repository.refreshSignals()
            access.api.signals.removeFirst()(Result.failure(org.json.JSONException("coordinate token account private data")))
            assertEquals(listOf("trip.signals: load failed reason=JSONException trip=aaaaaaaa"),messages)
        }
    }
    @Test fun detailReadFailureIsLoggedAndRefreshRestoresDetail() {
        val messages=mutableListOf<String>()
        opened(log=messages::add) {repository,access,_->
            access.invalidate()
            access.api.details.removeFirst()(Result.failure(IllegalStateException("private data")))
            assertEquals(listOf("trip.detail: load failed reason=IllegalStateException trip=aaaaaaaa"),messages)
            assertEquals("다시 불러와 주세요",repository.states.value.notice)
            repository.request(true)
            access.api.lists.removeFirst()(Result.success(list))
            access.api.details.removeFirst()(Result.success(detail))
            assertTrue(repository.states.value.isCurrent)
            assertNull(repository.states.value.notice)
        }
    }
    @Test fun signalAuthorizationLossStillClearsPrivateDetail()=opened {repository,access,_->
        repository.refreshSignals()
        access.api.signals.removeFirst()(Result.failure(NativeSocialFailure(NativeSocialFailure.Kind.FORBIDDEN)))
        assertNull(repository.states.value.detail)
        assertFalse(repository.states.value.isCurrent)
    }
    @Test fun hiddenOngoingRequestBlocksNewSendWithoutDisclosingItsContents()=opened {repository,access,_->
        repository.refreshSignals();access.api.replySignals(emptyList(),hasActive=true)
        assertTrue(repository.states.value.signals.hasActiveSignal)
        assertNull(repository.states.value.signals.ongoing)
        repository.sendTripSignal(null)
        assertTrue(access.api.sends.isEmpty())
    }
    @Test fun closingThePopupDoesNotUnlockAnotherRequest()=opened(cars=3) {repository,access,_->
        showOtherSignal(repository,access)
        repository.dismissTripSignal()
        assertNull(repository.states.value.signals.overlay)
        assertTrue(repository.states.value.signals.hasActiveSignal)
        repository.sendTripSignal(null)
        assertTrue(access.api.sends.isEmpty())
    }
    @Test fun aRequestMissingFromTheLatestVisiblePageRemovesItsOverlay()=opened(cars=3) {repository,access,_->
        showOtherSignal(repository,access)
        repository.refreshSignals();access.api.replySignals(emptyList(),hasActive=true)
        assertNull(repository.states.value.signals.overlay)
        assertNull(repository.states.value.signals.ongoing)
        assertTrue(repository.states.value.signals.hasActiveSignal)
    }
    @Test fun conflictReconcilesWithCurrentRequestWithoutReportingSuccessfulSend()=opened(cars=3) {repository,access,_->
        repository.refreshSignals();access.api.replySignals(emptyList())
        repository.sendTripSignal(null)
        access.api.sends.removeFirst()(Result.failure(NativeSocialFailure(NativeSocialFailure.Kind.CONFLICT,httpStatus=409,
            serverErrorCode="TRIP_SIGNAL_IN_PROGRESS")))
        assertFalse(repository.states.value.signals.sending)
        assertNull(repository.states.value.signals.sentId)
        assertEquals("손들기가 진행 중이에요",repository.states.value.signals.hint)
        access.api.replySignals(TripSignalsDevFixture.signals(createdAt=java.time.Instant.now().toString()))
        assertTrue(repository.states.value.signals.hasActiveSignal)
        assertNotNull(repository.states.value.signals.ongoing)
    }
    @Test fun requesterCanFinishOnceAndThenStartAnotherRequest()=opened {repository,access,_->
        val signal=TripSignal("signal",owner.id,TripSignalKind.REST,null,java.time.Instant.now().toString(),"valid",0,0,null)
        repository.refreshSignals();access.api.replySignals(emptyList())
        repository.sendTripSignal(null)
        access.api.sends.removeFirst()(Result.success(signal.id))
        access.api.replySignals(listOf(signal))
        val actions=TripsViewModel(repository).actions
        actions.finishSignal("completed");actions.finishSignal("completed")
        assertEquals(listOf("signal" to "completed"),access.api.finished)
        access.api.finishReplies.removeFirst()(Result.success(Unit))
        access.api.replySignals(listOf(signal.copy(inProgress=false,resolution="completed")))
        assertFalse(repository.states.value.signals.hasActiveSignal)
        assertEquals("손들기를 완료했어요",repository.states.value.signals.result)
        assertEquals(owner,repository.states.value.detail?.me)
        actions.sendSignal(null)
        assertEquals(1,access.api.sends.size)
    }
    @Test fun completedHistoricalRequestDoesNotBlockNewSend()=opened(cars=3) {repository,access,_->
        val signal=TripSignalsDevFixture.signals().first().copy(inProgress=false,resolution="agreed",driverAgrees=2,driverTotal=3)
        repository.refreshSignals();access.api.replySignals(listOf(signal))
        assertFalse(repository.states.value.signals.hasActiveSignal)
        assertNull(repository.states.value.signals.ongoing)
        repository.sendTripSignal(null)
        assertEquals(1,access.api.sends.size)
    }
    @Test fun driverSendsSignalInParkOrDriveOnlyWithKnownCarUx()=opened {repository,access,_->
        repository.refreshSignals();access.api.replySignals(emptyList())
        repository.setSetupAllowed(false)
        repository.sendTripSignal(null)
        repository.perform(TripAction.CreateLink) {}
        assertTrue(access.api.actions.isEmpty())
        assertTrue(access.api.sends.isEmpty())
        repository.setGear(TripGear.OTHER);repository.setSetupAllowed(true)
        repository.sendTripSignal(null)
        assertTrue(access.api.sends.isEmpty())
        repository.setGear(TripGear.DRIVE);repository.setSetupAllowed(false);repository.setCarUxKnown(false)
        repository.sendTripSignal(null)
        assertTrue(access.api.sends.isEmpty())
        repository.setCarUxKnown(true)
        repository.perform(TripAction.CreateLink) {}
        assertTrue(access.api.actions.isEmpty())
        repository.sendTripSignal(null)
        assertEquals(1,access.api.sends.size)
        access.api.sends.removeFirst()(Result.success("signal"))
        access.api.replySignals(emptyList())
        assertTrue(repository.states.value.signals.sentWithoutDestination)
    }
    @Test fun majorityResolutionNeverChangesOemRouteForAnUnansweredOrDeclinedCar() {
        for(vote in listOf(null,"pass")) {
            var added=0
            opened(cars=3,navigationRequested={added++}) {repository,access,_->
                added=0
                val pending=TripSignal("signal","other",TripSignalKind.REST,SignalDestination("휴게소",37.1,127.1),
                    java.time.Instant.now().toString(),"valid",1,if(vote=="pass")1 else 0,vote,
                    resolution="pending",driverAgrees=1,driverPasses=if(vote=="pass")1 else 0,driverTotal=3)
                repository.refreshSignals();access.api.replySignals(listOf(pending))
                repository.refreshSignals();access.api.replySignals(listOf(pending.copy(resolution="agreed",driverAgrees=2)))
                assertEquals("A remote vote result is not this driver's navigation command",0,added)
                assertEquals("과반이 동의했어요",repository.states.value.signals.result)
                assertTrue(access.api.votes.isEmpty())
            }
        }
    }
    @Test fun noPlaceNotificationAndDismissNeverSendVotes()=opened {repository,access,_->
        val signal=TripSignal("signal","other",TripSignalKind.RESTROOM,null,java.time.Instant.now().toString(),"valid",0,0,null)
        repository.refreshSignals();access.api.replySignals(listOf(signal))
        assertEquals(signal,repository.states.value.signals.overlay)
        repository.voteTripSignal("agree")
        repository.dismissTripSignal()
        assertTrue(access.api.votes.isEmpty())
        assertNull(repository.states.value.signals.overlay)
    }

    private fun groupSignal()=TripSignal("group-signal","other-driver",TripSignalKind.REST,
        SignalDestination("다 같이 쉬는 곳",37.1,127.1),java.time.Instant.now().minusSeconds(3600).toString(),
        "valid",0,0,null,inProgress=true,resolution="pending",decisionRule="other-car-groups-v1",
        requesterCarId="e".repeat(32),requiredCarIds=listOf(car.id),canRespond=true,
        groupVotes=TripGroupVotes(0,0,1),groupResponses=listOf(TripGroupResponse(car.id,car.name,null)))
    private fun passengerTrip(): TripDetail {
        val passenger=owner.copy(isOwner=false,carId=car.id)
        val drivingCar=car.copy(driverId="other-own-driver",driverName="운전자",isMine=false,iRide=true,
            passengers=listOf(TripPassenger(passenger.id,passenger.name,true)))
        return detail.copy(members=listOf(passenger),cars=listOf(drivingCar))
    }
    private fun showGroupSignal(repository: TripsRepository,access: FakeAccess,signal: TripSignal=groupSignal()) {
        repository.refreshSignals();access.api.replySignals(listOf(signal))
        assertEquals(signal.id,repository.states.value.signals.overlay?.id)
    }
    @Test fun drivingReplyRequiresCarUxThatWasActuallyRead()=opened(trip=passengerTrip(),startNavigation=false) {repository,access,_->
        repository.setGear(TripGear.DRIVE);repository.setSetupAllowed(false);repository.setCarUxKnown(false)
        showGroupSignal(repository,access)
        repository.voteTripSignal("agree");assertTrue(access.api.votes.isEmpty())
        repository.setCarUxKnown(true)
        repository.voteTripSignal("agree");assertEquals(listOf("agree"),access.api.votes)
    }
    @Test fun anotherPassengerWinningTheVoteIsAcknowledgedWithoutClaimingMyChoice()=opened(trip=passengerTrip(),startNavigation=false) {repository,access,_->
        showGroupSignal(repository,access)
        access.api.nextVoteResult=TripSignalVoteResult("pass",true,"first")
        repository.voteTripSignal("agree")
        assertNull(repository.states.value.signals.overlay)
        assertEquals("우리 차에서 이미 응답했어요",repository.states.value.signals.result)
        assertNull(repository.states.value.signals.voted)
    }
    @Test fun vehicleKeepsAnOngoingGroupRequestUntilItsControlsAreAllowed()=
        opened(trip=passengerTrip(),startNavigation=false) {repository,access,_->
            repository.setSetupAllowed(false);repository.setCarUxKnown(false);repository.setGear(TripGear.DRIVE)
            showGroupSignal(repository,access)
            assertEquals(id,repository.states.value.signals.overlayTrip?.id)
            assertFalse(checkNotNull(repository.states.value.detail?.myCar).isMine)
            repository.voteTripSignal("agree")
            assertTrue(access.api.votes.isEmpty())
            repository.setGear(TripGear.PARK);repository.setCarUxKnown(true)
            repository.voteTripSignal("agree")
            assertTrue(access.api.votes.isEmpty())
            repository.setSetupAllowed(true)
            repository.voteTripSignal("agree")
            assertEquals(listOf("agree"),access.api.votes)
            assertEquals(listOf(id to "group-signal"),access.api.voteRequests)
        }
    @Test fun theRequestingCarGroupHasNoResponsePopupOrResponsePost()=opened {repository,access,_->
        val signal=groupSignal().copy(accountId=owner.id,requesterCarId=car.id,canRespond=false,myGroupChoice="agree")
        repository.refreshSignals();access.api.replySignals(listOf(signal))
        assertNull(repository.states.value.signals.overlay)
        assertEquals(signal,repository.states.value.signals.ongoing)
        repository.voteOngoingTripSignal("pass")
        assertTrue(access.api.votes.isEmpty())
    }
    @Test fun aReplyFromAnotherMemberOfTheCarImmediatelyRemovesTheResponsePopup()=
        opened(trip=passengerTrip(),startNavigation=false) {repository,access,_->
            val signal=groupSignal()
            showGroupSignal(repository,access,signal)
            repository.refreshSignals();access.api.replySignals(listOf(signal.copy(canRespond=false,myGroupChoice="pass",
                groupVotes=TripGroupVotes(0,1,1),groupResponses=listOf(TripGroupResponse(car.id,car.name,"pass")))))
            assertNull(repository.states.value.signals.overlay)
            assertEquals("pass",repository.states.value.signals.latestGroupSignal?.myGroupChoice)
            repository.voteOngoingTripSignal("agree")
            assertTrue(access.api.votes.isEmpty())
        }
    @Test fun failedGroupResponseRemainsVisibleAndRetryPostsOncePerAttempt()=
        opened(trip=passengerTrip(),startNavigation=false) {repository,access,_->
            val signal=groupSignal()
            showGroupSignal(repository,access,signal)
            repository.voteTripSignal("agree")
            access.api.voteReplies.removeFirst()(Result.failure(NativeSocialFailure(NativeSocialFailure.Kind.UNAVAILABLE)))
            assertFalse(repository.states.value.signals.voting)
            assertEquals(signal,repository.states.value.signals.overlay)
            assertEquals("답을 보내지 못했어요. 다시 눌러 주세요",repository.states.value.signals.result)
            access.api.replySignals(listOf(signal))
            repository.voteTripSignal("agree");repository.voteTripSignal("agree")
            assertEquals(listOf("agree","agree"),access.api.votes)
        }
    @Test fun successfulGroupResponseClosesThePopupAndStalePollCannotPostAgain()=
        opened(trip=passengerTrip(),startNavigation=false) {repository,access,_->
            val signal=groupSignal()
            showGroupSignal(repository,access,signal)
            repository.voteTripSignal("agree");repository.voteTripSignal("agree")
            assertEquals(1,access.api.votes.size)
            access.api.voteReplies.removeFirst()(Result.success(Unit))
            assertNull(repository.states.value.signals.overlay)
            assertFalse(repository.states.value.signals.voting)
            access.api.replySignals(listOf(signal))
            assertNull(repository.states.value.signals.overlay)
            repository.voteTripSignal("agree");repository.voteOngoingTripSignal("agree")
            assertEquals(1,access.api.votes.size)
        }
    @Test fun aNewGroupRequestCanBeAnsweredWhenThePreviousVotesLateReplyArrivesAfterItsResolution()=
        opened(trip=passengerTrip(),startNavigation=false) {repository,access,_->
            val first=groupSignal()
            showGroupSignal(repository,access,first)
            repository.voteTripSignal("agree")
            val lateReply=access.api.voteReplies.removeFirst()
            access.invalidate()
            val next=groupSignal().copy(id="next-group-signal")
            access.api.replySignals(listOf(next,first.copy(inProgress=false,resolution="agreed",canRespond=false,myGroupChoice="agree")))
            assertEquals(next,repository.states.value.signals.overlay)
            assertFalse(repository.states.value.signals.voting)
            access.api.details.removeFirst()(Result.success(passengerTrip().copy(revision=2)))
            lateReply(Result.success(Unit))
            assertEquals(next,repository.states.value.signals.overlay)
            assertFalse(repository.states.value.signals.voting)
            repository.voteTripSignal("pass")
            assertEquals(listOf(id to first.id,id to next.id),access.api.voteRequests)
            assertEquals(listOf("agree","pass"),access.api.votes)
            assertTrue(repository.states.value.signals.voting)
        }
    @Test fun devicesInvalidationReadsTheSelectedTripsSignalsImmediatelyBeforeDetailReturns()=
        opened(trip=passengerTrip(),startNavigation=false) {repository,access,_->
            access.invalidate()
            assertEquals(1,access.api.details.size)
            assertEquals(1,access.api.signals.size)
            access.api.replySignals(listOf(groupSignal()))
            assertNotNull(repository.states.value.signals.overlay)
            assertTrue(repository.states.value.busy)
            access.api.details.removeFirst()(Result.success(passengerTrip()))
            assertFalse(repository.states.value.busy)
        }
    @Test fun closingTripDetailStillFindsAndAnswersAGroupRequestFromAnotherTab()=
        opened(trip=passengerTrip(),startNavigation=false) {repository,access,_->
            repository.closeDetail()
            assertNull(repository.states.value.detail)
            assertNull(repository.states.value.selectedId)
            repository.refreshSignals()
            assertEquals(id,access.api.signalTripIds.last())
            access.api.replySignals(listOf(groupSignal()))
            assertEquals(id,access.api.detailTripIds.last())
            access.api.details.removeFirst()(Result.success(passengerTrip()))
            assertNull(repository.states.value.detail)
            assertNull(repository.states.value.selectedId)
            assertEquals(id,repository.states.value.signals.overlayTrip?.id)
            repository.voteTripSignal("pass")
            assertEquals(listOf(id to "group-signal"),access.api.voteRequests)
        }
    @Test fun allGroupAgreementRefreshesThePersistedRouteWithoutCallingTheOemWaypointApi() {
        var added=0
        opened(navigationRequested={added++}) {repository,access,_->
            added=0
            val signal=groupSignal().copy(createdAt=java.time.Instant.now().toString())
            showGroupSignal(repository,access,signal)
            repository.refreshSignals();access.api.replySignals(listOf(signal.copy(inProgress=false,resolution="agreed",
                canRespond=false,myGroupChoice="agree",groupVotes=TripGroupVotes(1,0,1))))
            assertEquals(0,added)
            assertNull(repository.states.value.signals.overlay)
            assertEquals("모든 차가 동의해 여행 경로에 추가했어요",repository.states.value.signals.result)
            assertEquals(1,access.api.details.size)
            access.api.details.removeFirst()(Result.success(detail.copy(revision=2)))
            repository.refreshSignals();access.api.replySignals(listOf(signal.copy(inProgress=false,resolution="agreed",canRespond=false)))
            assertEquals(0,added)
            assertTrue(access.api.details.isEmpty())
        }
    }
    @Test fun routeProgressPublishesTheFirstStopAndDeduplicatesNavigationArrivalAndReopening() {
        val second=place.copy(id="d".repeat(32),name="다음 목적지",lat=37.55,lng=127.1)
        val firstItem=TripRouteItem("pickup",checkNotNull(place.id))
        val secondItem=TripRouteItem("pickup",checkNotNull(second.id))
        val routeCar=car.copy(places=listOf(place,second),routeOrder=listOf(firstItem,secondItem),
            routeRevision=7,routeNext=firstItem,routeNextKnown=true)
        val trip=detail.copy(cars=listOf(routeCar))
        opened(trip=trip,startNavigation=false) {repository,access,_->
            assertEquals(listOf(7L to firstItem),access.api.progress)
            val stop=TripRouteOrder.resolve(TripRouteOrder.initial(trip,routeCar),trip,routeCar).last()
            repository.navigate(stop);repository.navigate(stop)
            repository.distance(200.0);repository.distance(200.0)
            assertEquals(listOf(7L to firstItem,7L to secondItem),access.api.progress)
            repository.arrive();repository.arrive()
            assertEquals(listOf(7L to firstItem,7L to secondItem,7L to null),access.api.progress)
            val driving=repository.states.value.driving
            repository.closeDetail();repository.select(id)
            access.api.details.removeFirst()(Result.success(trip))
            assertEquals(driving,repository.states.value.driving)
            assertEquals(3,access.api.progress.size)
        }
    }
    @Test fun staleRouteProgressRefreshesTheRouteRevisionAndRetriesTheCurrentNextStop() {
        val second=place.copy(id="d".repeat(32),name="다음 목적지",lat=37.55,lng=127.1)
        val firstItem=TripRouteItem("pickup",checkNotNull(place.id))
        val secondItem=TripRouteItem("pickup",checkNotNull(second.id))
        val routeCar=car.copy(places=listOf(place,second),routeOrder=listOf(firstItem,secondItem),routeRevision=7)
        val trip=detail.copy(cars=listOf(routeCar))
        opened(trip=trip,startNavigation=false) {repository,access,_->
            access.api.autoProgress=false
            val stop=TripRouteOrder.resolve(TripRouteOrder.initial(trip,routeCar),trip,routeCar).last()
            repository.navigate(stop)
            assertEquals(7L to secondItem,access.api.progress.last())
            access.api.progressReplies.removeFirst()(Result.failure(NativeSocialFailure(NativeSocialFailure.Kind.CONFLICT,httpStatus=409)))
            assertEquals(1,access.api.details.size)
            access.api.details.removeFirst()(Result.success(trip.copy(cars=listOf(routeCar.copy(routeRevision=8)))))
            assertEquals(8L to secondItem,access.api.progress.last())
            access.api.progressReplies.removeFirst()(Result.success(Unit))
            repository.distance(200.0)
            assertEquals(3,access.api.progress.size)
        }
    }

    @Test fun anInsertedGroupStopWaitsForExplicitNavigationAndIgnoresTheOldOemTarget()=opened {repository,access,_->
        val signalPlace=TripPlace("합의한 휴게소","f".repeat(32),"signal",37.6,127.2)
        val signalItem=TripRouteItem("signal",checkNotNull(signalPlace.id))
        val pickupItem=TripRouteItem("pickup",checkNotNull(place.id))
        val updatedCar=car.copy(places=listOf(place,signalPlace),routeOrder=listOf(signalItem,pickupItem),
            routeNext=signalItem,routeNextKnown=true,routeRevision=1)
        val updated=detail.copy(cars=listOf(updatedCar))
        repository.request(true);access.api.details.removeFirst()(Result.success(updated))
        assertEquals(TripDrivingPhase.LATER,repository.states.value.driving.phase)
        assertNull(repository.states.value.driving.targetKey)
        val oldStop=TripRouteOrder.resolve(listOf(pickupItem),updated,updatedCar).single()
        FakeNavi(repository::navigationUpdate).target(oldStop,30.0,5)
        assertNull(repository.states.value.driving.targetKey)
        assertTrue(repository.states.value.driving.arrived.isEmpty())
        val newStop=TripRouteOrder.resolve(listOf(signalItem),updated,updatedCar).single()
        repository.navigate(newStop)
        assertEquals(newStop.key,repository.states.value.driving.targetKey)
        assertEquals(TripDrivingPhase.FAR,repository.states.value.driving.phase)
        FakeNavi(repository::navigationUpdate).target(newStop,250.0,60)
        assertEquals(TripDrivingPhase.NEAR,repository.states.value.driving.phase)
    }
    @Test fun savingAReorderedRouteUsesItsRevisionAndConflictNeverReportsSuccess() {
        val second=place.copy(id="d".repeat(32),name="다음 목적지",lat=37.55,lng=127.1)
        val firstItem=TripRouteItem("pickup",checkNotNull(place.id))
        val secondItem=TripRouteItem("pickup",checkNotNull(second.id))
        val routeCar=car.copy(places=listOf(place,second),routeOrder=listOf(firstItem,secondItem),routeRevision=7)
        val trip=detail.copy(cars=listOf(routeCar))
        opened(trip=trip,startNavigation=false) {repository,access,_->
            repository.setGear(TripGear.PARK)
            var succeeded=false
            repository.saveOrder(listOf(secondItem,firstItem),7) {succeeded=true}
            assertEquals(listOf(7L to listOf(secondItem,firstItem)),access.api.savedRoutes)
            access.api.routeSaveReplies.removeFirst()(Result.failure(NativeSocialFailure(NativeSocialFailure.Kind.CONFLICT,httpStatus=409)))
            assertFalse(succeeded)
            assertFalse(repository.states.value.isCurrent)
            repository.saveOrder(listOf(secondItem,firstItem),7) {succeeded=true}
            assertEquals(1,access.api.savedRoutes.size)
            repository.request(true)
            access.api.details.removeFirst()(Result.success(trip.copy(cars=listOf(routeCar.copy(routeRevision=8)))))
            assertFalse(succeeded)
            assertEquals(1,access.api.savedRoutes.size)
            repository.saveOrder(listOf(secondItem,firstItem),8) {succeeded=true}
            assertEquals(8L,access.api.savedRoutes.last().first)
        }
    }

    @Test fun anOldRouteDraftCannotUseTheNewlyRefreshedRevisionToOverwriteANewStop() {
        val inserted=TripPlace("합의한 휴게소","f".repeat(32),"signal",37.6,127.2)
        val original=TripRouteItem("pickup",checkNotNull(place.id))
        val insertedItem=TripRouteItem("signal",checkNotNull(inserted.id))
        val latestCar=car.copy(places=listOf(place,inserted),routeOrder=listOf(insertedItem,original),routeRevision=5)
        val latest=detail.copy(cars=listOf(latestCar))
        opened(trip=latest,startNavigation=false) {repository,access,_->
            repository.setGear(TripGear.PARK)
            var succeeded=false
            repository.saveOrder(listOf(original),4) {succeeded=true}
            assertTrue(access.api.savedRoutes.isEmpty())
            assertFalse(succeeded)
            assertNotNull(repository.states.value.notice)
            assertEquals(listOf(insertedItem,original),repository.states.value.detail?.myCar?.routeOrder)
            assertEquals(5L,repository.states.value.detail?.myCar?.routeRevision)
        }
    }

    @Test fun tripLocationIsEnabledOnceWithoutReloadingTheDetail() {
        val fixes=mutableListOf<(TripLocationFix)->Unit>()
        opened(startNavigation=false,canShareLocation={true},observeLocation={callback,_->fixes+=callback;Closeable {}}) {repository,access,_->
            assertEquals(listOf(TripAction.SetLocationSharing(true)),access.api.performedActions)
            assertFalse(repository.states.value.busy)
            assertTrue(access.api.locationReads.isEmpty())
            repository.refreshLocationPermissions();repository.refreshLocationPermissions()
            assertEquals(1,access.api.actions.size)
            access.api.actions.removeFirst()(Result.success(TripActionResult(revision=9)))
            assertTrue(repository.states.value.detail!!.locationSharing)
            assertEquals(9L,repository.states.value.detail!!.revision)
            assertTrue(access.api.details.isEmpty());assertTrue(access.api.lists.isEmpty())
            access.api.locationReads.removeFirst()(Result.success(TripLocationShare(id,"c".repeat(32))))
            assertEquals(1,fixes.size)
            fixes.single()(TripLocationFix(37.5,127.0,System.currentTimeMillis(),8.0))
            assertEquals(1,access.api.locationReports.size)
        }
    }

    @Test fun localConsentAndPermissionGateSharingChangesAndGps() {
        var permission=false
        var stopped=0
        val fixes=mutableListOf<(TripLocationFix)->Unit>()
        opened(startNavigation=false,canShareLocation={permission},observeLocation={callback,_->
            fixes+=callback;Closeable {stopped++}
        }) {repository,access,_->
            assertTrue(access.api.performedActions.isEmpty())
            assertFalse(repository.states.value.detail!!.locationSharing)
            assertTrue(access.api.locationReads.isEmpty());assertTrue(fixes.isEmpty())
            permission=true;repository.refreshLocationPermissions()
            assertEquals(listOf(TripAction.SetLocationSharing(true)),access.api.performedActions)
            access.api.actions.removeFirst()(Result.success(TripActionResult(revision=2)))
            assertTrue(repository.states.value.detail!!.locationSharing)
            access.api.locationReads.removeFirst()(Result.success(TripLocationShare(id,"c".repeat(32))))
            assertEquals(1,fixes.size)
            permission=false;repository.refreshLocationPermissions()
            assertEquals(1,stopped)
            fixes.single()(TripLocationFix(37.5,127.0,System.currentTimeMillis(),8.0))
            assertTrue(access.api.locationReports.isEmpty())
            permission=true;repository.refreshLocationPermissions()
            assertEquals(1,access.api.locationReads.size)
            assertEquals(1,access.api.performedActions.size)
        }
    }

    @Test fun readingOtherCarsDoesNotOptThisCarIntoLocationSharingAndClearsAtTheBoundary() {
        val other=TripCarPosition("d".repeat(32),37.5,127.0,"vehicle",1_000)
        for(loseForeground in listOf(true,false)) {
            var observations=0
            opened(startNavigation=false,canShareLocation={false},observeLocation={_,_->
                observations++;Closeable {}
            }) {repository,access,_->
                val reply=access.api.carLocationReads.removeFirst()
                reply(Result.success(TripLocationShare(id,null,listOf(other))))
                assertEquals(listOf(other),repository.states.value.otherCars)
                assertTrue(access.api.performedActions.isEmpty())
                assertTrue(access.api.locationReads.isEmpty())
                assertEquals(0,observations)
                if(loseForeground)repository.setForeground(false) else access.onExpired()
                assertTrue(repository.states.value.otherCars.isEmpty())
                reply(Result.success(TripLocationShare(id,null,listOf(other))))
                assertTrue(repository.states.value.otherCars.isEmpty())
                assertTrue(access.api.locationReports.isEmpty())
            }
        }
        opened(startNavigation=false,trip=detail.copy(state="planned"),canShareLocation={false}) {_,access,_->
            assertTrue(access.api.carLocationReads.isEmpty())
        }
    }

    @Test fun revokedLocalConsentCancelsPendingSharingAndIgnoresLateSuccess() {
        var permission=true
        opened(startNavigation=false,canShareLocation={permission}) {repository,access,_->
            val late=access.api.actions.removeFirst()
            permission=false;repository.refreshLocationPermissions()
            assertEquals(1,access.api.actionCloses)
            late(Result.success(TripActionResult(revision=9)))
            assertFalse(repository.states.value.detail!!.locationSharing)
            assertTrue(access.api.locationReads.isEmpty())
            repository.refreshLocationPermissions()
            assertEquals(1,access.api.performedActions.size)
            permission=true;repository.refreshLocationPermissions()
            assertEquals(2,access.api.performedActions.size)
        }
    }

    @Test fun sharingReplyRechecksLocalConsentBeforeGpsStarts() {
        var permission=true
        opened(startNavigation=false,canShareLocation={permission}) {repository,access,_->
            permission=false
            access.api.actions.removeFirst()(Result.success(TripActionResult(revision=9)))
            assertFalse(repository.states.value.detail!!.locationSharing)
            assertTrue(access.api.locationReads.isEmpty())
            assertEquals(1,access.api.actionCloses)
        }
    }

    @Test fun revocationWhileReadingLocationSharePreventsGpsSubscription() {
        var permission=true
        var observations=0
        opened(startNavigation=false,trip=detail.copy(locationSharing=true),canShareLocation={permission},
            observeLocation={_,_->observations++;Closeable {}}) {repository,access,_->
            val late=access.api.locationReads.removeFirst()
            permission=false;repository.refreshLocationPermissions()
            late(Result.success(TripLocationShare(id,"c".repeat(32))))
            assertEquals(0,observations)
            assertTrue(access.api.locationReports.isEmpty())
            assertTrue(access.api.performedActions.isEmpty())
        }
    }

    @Test fun automaticLocationFailureDoesNotRetryInALoopOrMarkSharingEnabled()=opened(
        startNavigation=false,canShareLocation={true}) {repository,access,_->
        access.api.actions.removeFirst()(Result.failure(java.io.IOException()))
        repeat(3) {repository.refreshLocationPermissions()}
        assertEquals(1,access.api.performedActions.size)
        assertFalse(repository.states.value.detail!!.locationSharing)
        assertFalse(repository.states.value.busy)
        assertTrue(access.api.locationReads.isEmpty())
        repository.request(true)
        access.api.details.removeFirst()(Result.success(detail))
        assertEquals(2,access.api.performedActions.size)
    }

    @Test fun lateLocationEnableCannotRestoreClosedTripState()=opened(
        startNavigation=false,canShareLocation={true}) {repository,access,_->
        val late=access.api.actions.removeFirst()
        repository.closeDetail()
        late(Result.success(TripActionResult(revision=9)))
        assertNull(repository.states.value.detail)
        assertNull(repository.states.value.selectedId)
        assertTrue(access.api.locationReads.isEmpty())
    }

    @Test fun automaticLocationAppliesToPreparationButNotEndedOrUnacceptedTrips() {
        opened(startNavigation=false,canShareLocation={false},trip=detail.copy(state="planned")) {_,access,_->
            assertTrue(access.api.performedActions.isEmpty())
            assertTrue(access.api.locationReads.isEmpty())
        }
        opened(startNavigation=false,canShareLocation={true},trip=detail.copy(state="planned")) {_,access,_->
            assertEquals(listOf(TripAction.SetLocationSharing(true)),access.api.performedActions)
            assertTrue(access.api.locationReads.isEmpty())
        }
        for(trip in listOf(detail.copy(state="completed"),detail.copy(state="cancelled"),detail.copy(members=listOf(owner.copy(accepted=false))))) {
            opened(startNavigation=false,canShareLocation={true},trip=trip) {_,access,_->assertTrue(access.api.performedActions.isEmpty())}
        }
    }

    @Test fun automaticLocationPreferenceCanSyncInDriveWithoutEnablingInteractiveMutations() {
        val access=FakeAccess()
        val repository=TripsRepository(access,canShareLocation={true})
        try {
            repository.setForeground(true);repository.setGear(TripGear.DRIVE)
            access.api.lists.removeFirst()(Result.success(list))
            access.api.details.removeFirst()(Result.success(detail))
            assertEquals(listOf(TripAction.SetLocationSharing(true)),access.api.performedActions)
            repository.perform(TripAction.Finish(1)) {}
            assertEquals(1,access.api.performedActions.size)
        } finally {repository.close()}
    }

    @Test fun staleLocationEnableCannotRollBackNewerTripMetadata()=opened(
        startNavigation=false,canShareLocation={true}) {repository,access,_->
        val late=access.api.actions.removeFirst()
        val resource="trip.$id.location"
        access.listener.onEvent(VehicleEvent("invalidate",listOf(resource),mapOf(resource to "1".repeat(32))))
        access.api.sectionReplies.removeFirst()(Result.success(detail.copy(revision=10)))
        late(Result.success(TripActionResult(revision=2)))
        assertEquals(10L,repository.states.value.detail!!.revision)
        assertFalse(repository.states.value.detail!!.locationSharing)
        access.api.sectionReplies.removeFirst()(Result.success(detail.copy(revision=10,locationSharing=true)))
        assertEquals(10L,repository.states.value.detail!!.revision)
        assertTrue(repository.states.value.detail!!.locationSharing)
        assertEquals(1,access.api.performedActions.size)
    }

    @Test fun locationRecoveryClearsThePreviousSynchronizationFailure()=opened(
        startNavigation=false,canShareLocation={true}) {repository,access,_->
        access.api.actions.removeFirst()(Result.failure(java.io.IOException()))
        assertNotNull(repository.states.value.notice)
        val resource="trip.$id.location"
        access.listener.onEvent(VehicleEvent("invalidate",listOf(resource),mapOf(resource to "1".repeat(32))))
        access.api.sectionReplies.removeFirst()(Result.success(detail.copy(revision=2,locationSharing=true)))
        assertTrue(repository.states.value.detail!!.locationSharing)
        assertNull(repository.states.value.notice)
        assertEquals(1,access.api.locationReads.size)
    }

    @Test fun acceptingAlwaysEnablesLocationAndRejectingOmitsThePreference() {
        for(accept in listOf(true,false)) {
            val access=FakeAccess()
            val repository=TripsRepository(access)
            try {
                repository.setForeground(true);repository.setSetupAllowed(true);repository.request()
                access.api.lists.removeFirst()(Result.success(TripList(emptyList(),listOf(TripInvitation(id,"여행","친구")))))
                repository.respond(id,accept,false)
                assertEquals(listOf(Triple(id,accept,if(accept)true else null)),access.api.responses)
            } finally {repository.close()}
        }
    }

    @Test fun courseScoreIsFinalizedOnlyAfterSuccessfulCompletionAndDoesNotReloadOnSamples() {
        val course=TripCourse("course-a","해안 코스",version=1,stops=listOf(TripCourseStop("stop-a","바다",37.5,127.0)),completedCarIds=emptyList())
        val trip=detail.copy(cars=listOf(car.copy(places=emptyList())),courses=listOf(course))
        val saved=mutableMapOf<String,CourseDrivingResult>()
        lateinit var speed: (Long,Double?)->Unit
        var closes=0
        val scores=LocalCourseScores({saved[it]},{key,result->saved[key]=result},{callback->speed=callback;Closeable {closes++}})
        opened(trip=trip,scores=scores) {repository,access,_->
            speed(1000,20.0);speed(2000,30.0);speed(3000,20.0)
            assertTrue(access.api.details.isEmpty());assertTrue(access.api.sections.isEmpty())
            repository.distance(10.0);repository.arrive()
            assertEquals(TripDrivingPhase.ROUTE_END,repository.states.value.driving.phase)
            repository.completeCourse()
            access.api.courseReplies.removeFirst()(Result.failure(NativeSocialFailure(NativeSocialFailure.Kind.UNAVAILABLE)))
            assertTrue(repository.states.value.courseResults.isEmpty())
            repository.request(true)
            if(access.api.details.isNotEmpty())access.api.details.removeFirst()(Result.success(trip))
            repository.completeCourse()
            access.api.courseReplies.removeFirst()(Result.success(Unit))
            assertEquals(90,repository.states.value.courseResults[course.packId]?.score)
            access.api.details.removeFirst()(Result.success(trip.copy(courses=listOf(course.copy(completedCarIds=listOf(car.id))))))
            assertEquals(90,repository.states.value.courseResults[course.packId]?.score)
            speed(4000,70.0)
            assertEquals(90,repository.states.value.courseResults[course.packId]?.score)
            assertTrue(closes>0)
        }
    }
    private fun segmentedTrip(phase: String="pickup",progress: Long=0): TripDetail {
        val course=TripCourse("coast","서해안 해안도로",version=1,stops=listOf(
            TripCourseStop("join","간월암",36.6,126.4),TripCourseStop("finish","대천",36.3,126.5)),completedCarIds=emptyList())
        val pickup=TripRouteItem("pickup",checkNotNull(place.id))
        val shared=course.stops!!.map {TripRouteItem("course",it.id,course.packId)}
        val next=when(phase) {"pickup"->pickup;"waiting","shared"->shared.last();else->null}
        val plan=TripRoutePlan(2,phase,listOf(TripRouteSegment("pickup",listOf(pickup)),
            TripRouteSegment("shared",shared),TripRouteSegment("drop",emptyList())),
            TripJoinPoint(course.packId,"join","간월암",36.6,126.4),null,progress,next,
            TripJoinBarrier(if(phase=="pickup")emptyList() else listOf(car.id),1,phase !in setOf("pickup","waiting")))
        return detail.copy(routeContractVersion=2,courses=listOf(course),cars=listOf(car.copy(routePlan=plan,routeRevision=8)))
    }
    @Test fun activeSegmentedTripRereadsRouteProgressWhenLocationsChange() {
        val trip=segmentedTrip()
        opened(trip=trip,startNavigation=false) {repository,access,_->
            val key="trip.$id.location"
            access.listener.onEvent(VehicleEvent("invalidate",listOf(key),mapOf(key to "1".repeat(32))))
            access.api.sectionReplies.removeFirst()(Result.success(trip))
            val moved=TripPlanProgress(1200,0.4)
            val own=trip.myCar!!
            access.api.sectionReplies.removeFirst()(Result.success(trip.copy(cars=listOf(own.copy(routePlan=own.routePlan!!.copy(progress=moved))))))
            assertEquals(listOf("location","route"),access.api.sections)
            assertEquals(moved,repository.states.value.detail?.myCar?.routePlan?.progress)
            assertTrue(access.api.details.isEmpty())
        }
    }
    @Test fun singleJoinArrivalOptsInAtTheJoinAndPreservesTheLegacyPickupRequest() {
        val base=segmentedTrip()
        val join=TripRouteItem("course","join","coast")
        val own=base.myCar!!
        val trip=base.copy(courses=base.courses!!.map {it.copy(stops=it.stops!!.take(1))},cars=listOf(own.copy(
            routePlan=own.routePlan!!.copy(segments=own.routePlan!!.segments.map {
                if(it.segment=="shared")it.copy(items=listOf(join)) else it
            }))))
        opened(trip=trip,startNavigation=false) {repository,access,_->
            repository.arrive()
            assertEquals(listOf(false),access.api.arrivalOptins)
            val afterPickup=trip.myCar!!.routePlan!!.copy(next=join,progressRevision=1)
            access.api.arrivalReplies.removeFirst()(Result.success(afterPickup))
            access.api.details.removeFirst()(Result.success(trip.copy(cars=trip.cars.map {it.copy(routePlan=afterPickup)})))
            repository.arrive()
            assertEquals(listOf(false,true),access.api.arrivalOptins)
            assertEquals(join,access.api.arrivalItems.last().third)
        }
    }
    @Test fun singleJoinOptinStartsLiveScoringAfterReleaseWithoutPrematurelyFinalizingTheCourse() {
        val base=segmentedTrip()
        val join=TripRouteItem("course","join","coast")
        val course=base.courses!!.single().copy(stops=base.courses!!.single().stops!!.take(1))
        val plan=base.myCar!!.routePlan!!.copy(next=join,segments=listOf(TripRouteSegment("pickup",emptyList()),
            TripRouteSegment("shared",listOf(join)),TripRouteSegment("drop",emptyList())))
        val trip=base.copy(courses=listOf(course),cars=listOf(base.myCar!!.copy(routePlan=plan)))
        val stored=mutableMapOf<String,CourseDrivingResult>()
        var speed: ((Long,Double?)->Unit)?=null
        var current: TripsRepository?=null
        val scores=LocalCourseScores({stored[it]},{key,result->stored[key]=result},{callback->speed=callback;Closeable {}},
            changed={key,result->current?.scoreChanged(key,result)})
        opened(trip=trip,startNavigation=false,scores=scores) {repository,access,_->
            current=repository
            assertNotNull(speed)
            repository.arrive()
            assertEquals(listOf(true),access.api.arrivalOptins)
            val released=plan.copy(phase="shared",progressRevision=1,joinBarrier=TripJoinBarrier(listOf(car.id),1,true))
            access.api.arrivalReplies.removeFirst()(Result.success(released))
            access.api.details.removeFirst()(Result.success(trip.copy(cars=trip.cars.map {it.copy(routePlan=released)})))
            repository.setGear(TripGear.DRIVE)
            assertNotNull(speed)
            speed!!(1000,20.0);speed!!(1200,20.0)
            assertEquals(100,repository.states.value.liveCourseScore?.score)
            assertEquals(false,repository.states.value.liveCourseScore?.completed)
            assertTrue(access.api.finalReports.isEmpty())
        }
    }
    @Test fun singleJoinSharedCourseRequiresParkedExplicitCompletionWithBothRevisions() {
        val base=segmentedTrip("shared",1)
        val join=TripRouteItem("course","join","coast")
        val own=base.myCar!!
        val trip=base.copy(courses=base.courses!!.map {it.copy(stops=it.stops!!.take(1))},cars=listOf(own.copy(
            routePlan=own.routePlan!!.copy(next=join,segments=own.routePlan!!.segments.map {
                if(it.segment=="shared")it.copy(items=listOf(join)) else it
            }))))
        opened(trip=trip,startNavigation=false) {repository,access,_->
            repository.setGear(TripGear.DRIVE);repository.completeCourse()
            assertTrue(access.api.joinedCompletions.isEmpty())
            repository.setGear(TripGear.PARK);repository.completeCourse();repository.completeCourse()
            assertEquals(listOf(Triple("coast",8L,1L)),access.api.joinedCompletions)
            assertEquals("shared",repository.states.value.detail?.myCar?.routePlan?.phase)
            access.api.joinedCompletionReplies.removeFirst()(Result.failure(java.io.IOException("offline")))
            assertFalse(repository.states.value.busy)
            assertEquals("shared",repository.states.value.detail?.myCar?.routePlan?.phase)
            assertFalse(repository.states.value.isCurrent)
            repository.request(true)
            access.api.details.removeFirst()(Result.success(trip))
            repository.completeCourse()
            assertEquals(2,access.api.joinedCompletions.size)
            access.api.joinedCompletionReplies.removeFirst()(Result.success(Unit))
            assertEquals(1,access.api.details.size)
            val done=trip.copy(state="completed",cars=trip.cars.map {it.copy(routePlan=it.routePlan!!.copy(phase="done",next=null,progressRevision=2))})
            access.api.details.removeFirst()(Result.success(done))
            assertEquals("done",repository.states.value.detail?.myCar?.routePlan?.phase)
            repository.completeCourse()
            assertEquals(2,access.api.joinedCompletions.size)
        }
    }
    @Test fun segmentedNavigationNeverReportsArrivalUntilTheParkedDriverConfirms() {
        val trip=segmentedTrip()
        opened(trip=trip) {repository,access,_->
            repository.navigationUpdate(TripNavigationUpdate(targets=listOf(TripNavigationTarget(37.5,127.0,10.0,1))))
            assertEquals(TripDrivingPhase.NEAR,repository.states.value.driving.phase)
            assertTrue(repository.states.value.driving.arrived.isEmpty())
            val pickup=trip.myCar!!.routePlan!!.next!!
            assertEquals("Guidance is shared without confirming arrival",listOf(8L to pickup),access.api.progress)
            assertTrue(access.api.arrivalItems.isEmpty())
            repository.arrive();repository.arrive()
            assertEquals(1,access.api.arrivalItems.size)
            assertEquals(Triple(8L,0L,trip.myCar!!.routePlan!!.next!!),access.api.arrivalItems.single())
            val after=trip.myCar!!.routePlan!!.copy(progressRevision=1,next=TripRouteItem("course","join","coast"))
            access.api.arrivalReplies.removeFirst()(Result.success(after))
            assertEquals(1L,repository.states.value.detail?.myCar?.routePlan?.progressRevision)
            assertTrue(place.id!!.let {"pickup::$it"} in repository.states.value.driving.arrived)
            assertEquals(listOf(8L to pickup,8L to TripRouteItem("course","join","coast")),access.api.progress)
        }
    }
    @Test fun segmentedArrivalUsesServerNextWithoutLocationOrNavigationTarget() {
        for(phase in listOf("pickup","shared")) {
            val trip=segmentedTrip(phase)
            opened(trip=trip,startNavigation=false) {repository,access,_->
                assertNull(repository.states.value.driving.targetKey)
                assertEquals(TripDrivingPhase.LATER,repository.states.value.driving.phase)
                val arrivedBefore=repository.states.value.driving.arrived
                repository.arrive();repository.arrive()
                assertEquals(listOf(Triple(8L,0L,trip.myCar!!.routePlan!!.next!!)),access.api.arrivalItems)
                assertEquals("Arrival is pending until the server accepts",arrivedBefore,repository.states.value.driving.arrived)
                assertTrue(repository.states.value.busy)
                assertEquals(listOf(8L to trip.myCar!!.routePlan!!.next!!),access.api.progress)
            }
        }
        val trip=segmentedTrip()
        opened(trip=trip) {repository,access,_->
            val other=TripRouteOrder.resolve(TripRouteOrder.initial(trip,trip.myCar!!),trip,trip.myCar!!).last()
            repository.navigate(other)
            assertEquals(TripDrivingPhase.FAR,repository.states.value.driving.phase)
            assertEquals(8L to other.item,access.api.progress.last())
            repository.arrive()
            assertEquals(trip.myCar!!.routePlan!!.next,access.api.arrivalItems.single().third)
        }
    }
    @Test fun segmentedArrivalFailureKeepsCurrentNextAndAllowsExplicitRetryWithoutLocation() {
        for(error in listOf(java.io.IOException("offline"),NativeSocialFailure(NativeSocialFailure.Kind.UNAVAILABLE))) {
            val trip=segmentedTrip()
            opened(trip=trip,startNavigation=false) {repository,access,_->
                val before=repository.states.value.detail?.myCar?.routePlan
                repository.arrive()
                access.api.arrivalReplies.removeFirst()(Result.failure(error))
                assertFalse(repository.states.value.busy)
                assertEquals(before,repository.states.value.detail?.myCar?.routePlan)
                assertTrue(repository.states.value.driving.arrived.isEmpty())
                assertEquals("도착을 저장하지 못했어요. 정차 후 다시 눌러 주세요",repository.states.value.notice)
                assertEquals("Failure never silently retries a write",1,access.api.arrivalItems.size)
                repository.arrive()
                assertEquals(2,access.api.arrivalItems.size)
                assertEquals(access.api.arrivalItems.first(),access.api.arrivalItems.last())
            }
        }
    }
    @Test fun segmentedGuidanceConflictRereadsTheRouteWithoutConfirmingArrival() {
        val trip=segmentedTrip()
        opened(trip=trip,startNavigation=false) {repository,access,_->
            access.api.autoProgress=false
            val other=TripRouteOrder.resolve(TripRouteOrder.initial(trip,trip.myCar!!),trip,trip.myCar!!).last()
            repository.navigate(other)
            assertEquals(8L to other.item,access.api.progress.last())
            access.api.progressReplies.removeFirst()(Result.failure(NativeSocialFailure(NativeSocialFailure.Kind.CONFLICT,409)))
            assertEquals(1,access.api.details.size)
            assertTrue(access.api.arrivalItems.isEmpty())
            assertEquals(0L,repository.states.value.detail?.myCar?.routePlan?.progressRevision)
        }
    }
    @Test fun segmentedArrivalConflictRefreshesServerNextWithoutAdvancingLocally() {
        val trip=segmentedTrip()
        opened(trip=trip,startNavigation=false) {repository,access,_->
            repository.arrive()
            access.api.arrivalReplies.removeFirst()(Result.failure(NativeSocialFailure(NativeSocialFailure.Kind.CONFLICT,409)))
            assertEquals("경로가 바뀌었어요. 다음 장소를 확인하고 다시 눌러 주세요",repository.states.value.notice)
            assertEquals(1,access.api.details.size)
            assertEquals(0L,repository.states.value.detail?.myCar?.routePlan?.progressRevision)
            val revised=trip.copy(cars=trip.cars.map {it.copy(routeRevision=9,routePlan=it.routePlan!!.copy(progressRevision=2))})
            access.api.details.removeFirst()(Result.success(revised))
            repository.arrive()
            assertEquals(Triple(9L,2L,revised.myCar!!.routePlan!!.next!!),access.api.arrivalItems.last())
        }
    }
    @Test fun pickupAndDropArrivalsRequireParkAndCurrentDriverAcrossGearChanges() {
        for(phase in listOf("pickup","drop")) {
            val original=segmentedTrip()
            val drop=TripRouteItem("drop","d".repeat(32))
            val own=original.myCar!!
            val trip=if(phase=="pickup")original else original.copy(cars=listOf(own.copy(
                places=own.places.orEmpty()+TripPlace("내릴 곳",drop.ref,"drop",37.5,127.0),
                routePlan=own.routePlan!!.copy(phase="drop",next=drop,segments=own.routePlan!!.segments.map {
                    if(it.segment=="drop")it.copy(items=listOf(drop)) else it
                }))))
            opened(trip=trip,startNavigation=false) {repository,access,_->
                repository.setGear(TripGear.DRIVE);repository.arrive()
                assertTrue(access.api.arrivalItems.isEmpty())
                repository.setGear(TripGear.PARK);repository.arrive()
                assertEquals(1,access.api.arrivalItems.size)
                access.api.arrivalReplies.removeFirst()(Result.failure(java.io.IOException("offline")))
                repository.setGear(TripGear.DRIVE);repository.arrive()
                assertEquals(1,access.api.arrivalItems.size)
                repository.setGear(TripGear.PARK);repository.arrive()
                assertEquals(2,access.api.arrivalItems.size)
            }
            val passengerTrip=trip.copy(cars=trip.cars.map {it.copy(isMine=false,iRide=true)})
            opened(trip=passengerTrip,startNavigation=false) {repository,access,_->
                repository.arrive()
                assertTrue(access.api.arrivalItems.isEmpty())
            }
        }
        for(phase in listOf("waiting","done"))opened(trip=segmentedTrip(phase),startNavigation=false) {repository,access,_->
            repository.arrive();assertTrue(access.api.arrivalItems.isEmpty())
        }
    }
    @Test fun routeEventReleasesTheJoinBarrierWithoutChangingRouteRevision() {
        val waiting=segmentedTrip("waiting",1)
        opened(trip=waiting,startNavigation=false) {repository,access,_->
            repository.setGear(TripGear.DRIVE)
            val key="trip.$id.route"
            access.listener.onEvent(VehicleEvent("invalidate",listOf(key),mapOf(key to "1".repeat(32))))
            val released=waiting.copy(cars=waiting.cars.map {it.copy(routePlan=it.routePlan!!.copy(phase="shared",
                joinBarrier=it.routePlan!!.joinBarrier.copy(released=true)))})
            access.api.sectionReplies.removeFirst()(Result.success(released))
            assertEquals(8L,repository.states.value.detail?.myCar?.routeRevision)
            assertEquals("shared",repository.states.value.detail?.myCar?.routePlan?.phase)
            assertEquals("trip-total-v1",repository.states.value.liveCourseId)
            assertEquals(listOf(8L to waiting.myCar!!.routePlan!!.next!!),access.api.progress)
        }
    }
    @Test fun totalScoreKeepsTheSameAccumulatorAcrossPickupWaitingSharedAndDrop() {
        val stored=mutableMapOf<String,CourseDrivingResult>()
        var speed: ((Long,Double?)->Unit)?=null
        var current: TripsRepository?=null
        val scores=LocalCourseScores({stored[it]},{key,result->stored[key]=result},{callback->speed=callback;Closeable {}},
            changed={key,result->current?.scoreChanged(key,result)})
        opened(trip=segmentedTrip(),startNavigation=false,scores=scores) {repository,access,_->
            current=repository
            access.scoreReportAuthority=ScoreReportAuthority("device","grant")
            speed!!(1000,0.0);speed!!(1200,12.0)
            assertEquals(95,repository.states.value.liveCourseScore?.score)
            for(phase in listOf("waiting","shared","drop")) {
                repository.request(true);access.api.details.removeFirst()(Result.success(segmentedTrip(phase)))
                assertEquals("trip-total-v1",repository.states.value.liveCourseId)
                assertEquals(95,repository.states.value.liveCourseScore?.score)
                assertEquals(false,repository.states.value.liveCourseScore?.completed)
            }
            speed!!(1400,0.0)
            assertEquals(90,repository.states.value.liveCourseScore?.score)
            repository.request(true);access.api.details.removeFirst()(Result.success(segmentedTrip("done").copy(state="completed")))
            assertEquals(90,access.api.finalReports.single().second.score)
            assertTrue(access.api.finalReports.single().second.final)
            assertEquals("trip-total-v1",repository.states.value.liveCourseId)
            assertEquals(90,repository.states.value.liveCourseScore?.score)
            assertEquals(true,repository.states.value.liveCourseScore?.completed)
        }
    }
    @Test fun allActiveSegmentsStartTripScoringButDoneDoesNot() {
        for(phase in listOf("pickup","waiting","drop","done")) {
            var starts=0
            val scores=object: CourseScores {
                override fun start(key: String) {starts++}
                override fun pause() {}
                override fun finish(key: String): CourseDrivingResult?=null
                override fun read(key: String): CourseDrivingResult?=null
                override fun reset(key: String) {}
                override fun forget() {}
            }
            opened(trip=segmentedTrip(phase),startNavigation=false,scores=scores) {repository,access,_->
                repository.setGear(TripGear.DRIVE)
                if(phase=="done")assertEquals(0,starts) else assertTrue("Scoring in $phase",starts>0)
                if(phase=="done")assertTrue(access.api.scoreReports.isEmpty()) else assertTrue(access.api.scoreReports.all {it.first=="trip-total-v1" && !it.second.final})
                repository.loadSignalCandidates(TripSignalKind.FUEL)
                assertTrue(access.api.candidateRequests.isEmpty())
            }
        }
    }
    @Test fun completedTripTotalUsesCurrentDeviceWithoutSeparateConsent() {
        val base=segmentedTrip("done",4)
        val finished=base.copy(state="completed",courses=base.courses!!.map {it.copy(completedCarIds=listOf(car.id))})
        val result=CourseDrivingResult(1,1,1000,completed=true)
        val scores=LocalCourseScores({result},{_,_->},{Closeable {}})
        opened(trip=finished,startNavigation=false,scores=scores) {repository,access,_->
            access.scoreReportAuthority=ScoreReportAuthority("device","grant")
            repository.request(true);access.api.details.removeFirst()(Result.success(finished))
            assertEquals(1,access.api.finalReports.size)
            assertEquals(result.report(final=true),access.api.finalReports.single().second)
            assertEquals("trip-total-v1",repository.states.value.liveCourseId)
            assertEquals(result,repository.states.value.liveCourseScore)
            repository.request(true);access.api.details.removeFirst()(Result.success(finished))
            assertEquals(1,access.api.finalReports.size)
            assertTrue(access.api.scoreReports.isEmpty());assertTrue(access.api.progress.isEmpty())
        }
    }
    @Test fun oneStopJoinDoesNotUploadItsUnmeasurableFinalUntilExplicitCompletionSucceeds() {
        val base=segmentedTrip()
        val course=base.courses!!.single().copy(stops=base.courses!!.single().stops!!.take(1))
        val item=TripRouteItem("course","join","coast")
        val plan=base.myCar!!.routePlan!!.copy(segments=listOf(TripRouteSegment("pickup",emptyList()),
            TripRouteSegment("shared",listOf(item)),TripRouteSegment("drop",emptyList())),next=item)
        val trip=base.copy(courses=listOf(course),cars=listOf(base.myCar!!.copy(routePlan=plan)))
        val stored=mutableMapOf<String,CourseDrivingResult>()
        val scores=LocalCourseScores({stored[it]},{key,result->stored[key]=result},{Closeable {}})
        opened(trip=trip,startNavigation=false,scores=scores) {repository,access,_->
            access.scoreReportAuthority=ScoreReportAuthority("device","grant")
            val stop=TripRouteOrder.resolve(listOf(item),trip,trip.myCar!!).single()
            repository.navigate(stop);repository.distance(100.0);repository.arrive()
            val waiting=plan.copy(phase="waiting",progressRevision=1,next=item,
                joinBarrier=TripJoinBarrier(listOf(car.id),2,false))
            access.api.arrivalReplies.removeFirst()(Result.success(waiting))
            val pending=trip.copy(cars=listOf(trip.myCar!!.copy(routePlan=waiting)))
            access.api.details.removeFirst()(Result.success(pending))
            assertTrue(access.api.finalReports.isEmpty())
            val released=waiting.copy(phase="shared",joinBarrier=waiting.joinBarrier.copy(released=true))
            repository.request(true);access.api.details.removeFirst()(Result.success(pending.copy(cars=listOf(pending.myCar!!.copy(routePlan=released)))))
            assertTrue(access.api.finalReports.isEmpty())
            repository.completeCourse()
            assertEquals(1,access.api.joinedCompletions.size)
            access.api.joinedCompletionReplies.removeFirst()(Result.success(Unit))
            val finished=pending.copy(state="completed",courses=listOf(course.copy(completedCarIds=listOf(car.id))),
                cars=listOf(pending.myCar!!.copy(routePlan=released.copy(phase="done",next=null,progressRevision=2))))
            access.api.details.removeFirst()(Result.success(finished))
            assertEquals(1,access.api.finalReports.size)
            val report=access.api.finalReports.single().second
            assertTrue(report.final);assertFalse(report.measurable);assertNull(report.score)
        }
    }
    @Test fun explicitComparisonRefreshRetriesTheSameFailedFinalBeforeReadingTheComparison() {
        val base=segmentedTrip("done",4)
        val trip=base.copy(state="completed",courses=base.courses!!.map {it.copy(completedCarIds=listOf(car.id))})
        val result=CourseDrivingResult(1,0,1000,completed=true)
        val scores=LocalCourseScores({result},{_,_->},{Closeable {}})
        opened(trip=trip,startNavigation=false,scores=scores) {repository,access,_->
            access.scoreReportAuthority=ScoreReportAuthority("device","grant")
            access.api.finalFailure=true
            repository.request(true);access.api.details.removeFirst()(Result.success(trip))
            assertEquals(1,access.api.finalReports.size)
            access.api.finalFailure=false
            repository.refreshDrivingVersus()
            assertEquals(2,access.api.finalReports.size)
            assertEquals(access.api.finalReports.first(),access.api.finalReports.last())
            repository.refreshDrivingVersus()
            assertEquals(2,access.api.finalReports.size)
        }
    }
    @Test fun carPolicyLookupUsesItsOwnReadsWithoutSelectingOrChangingTheTrip()=opened(startNavigation=false) {repository,access,_->
        repository.closeDetail()
        val policy=TripRemotePolicy(true,setOf("light.cabin"),"device")
        repository.refreshRemotePolicy()
        assertNull(repository.states.value.selectedId)
        access.api.lists.removeFirst()(Result.success(list))
        access.api.details.removeFirst()(Result.success(detail.copy(cars=listOf(car.copy(remotePolicy=policy)))))
        assertNull(repository.states.value.selectedId)
        assertNull(repository.states.value.detail)
        assertEquals(policy,repository.states.value.remotePolicySnapshot.policy)
        assertEquals(id,repository.states.value.remotePolicySnapshot.tripId)
    }
    @Test fun carPolicyLookupDistinguishesNoActiveTripFromReadFailure()=opened(startNavigation=false) {repository,access,_->
        repository.closeDetail();repository.refreshRemotePolicy()
        access.api.lists.removeFirst()(Result.success(TripList(emptyList(),emptyList())))
        assertEquals(AccountReadStatus.READY,repository.states.value.remotePolicySnapshot.status)
        assertNull(repository.states.value.remotePolicySnapshot.tripId)
        repository.refreshRemotePolicy()
        access.api.lists.removeFirst()(Result.failure(java.io.IOException()))
        assertEquals(AccountReadStatus.UNAVAILABLE,repository.states.value.remotePolicySnapshot.status)
        assertNull(repository.states.value.remotePolicySnapshot.policy)
    }
    @Test fun carPolicyLateReplyAfterForegroundLossCannotRestorePrivatePolicy()=opened(startNavigation=false) {repository,access,_->
        repository.closeDetail();repository.refreshRemotePolicy()
        access.api.lists.removeFirst()(Result.success(list))
        val late=access.api.details.removeFirst()
        repository.setForeground(false)
        late(Result.success(detail.copy(cars=listOf(car.copy(remotePolicy=TripRemotePolicy(true,setOf("light.cabin"),"device"))))))
        assertNull(repository.states.value.remotePolicySnapshot.policy)
        assertEquals(AccountReadStatus.CONNECTION_REQUIRED,repository.states.value.remotePolicySnapshot.status)
    }
    @Test fun carPolicyScopeLossDiscardsPendingLookup()=opened(startNavigation=false) {repository,access,_->
        repository.closeDetail();repository.refreshRemotePolicy()
        val late=access.api.lists.removeFirst()
        access.onExpired()
        late(Result.success(list))
        assertNull(repository.states.value.remotePolicySnapshot.policy)
        assertEquals(AccountReadStatus.CONNECTION_REQUIRED,repository.states.value.status)
        assertTrue(access.api.details.isEmpty())
    }
    @Test fun carPolicyLookupDroppedWhileDetailRetriesRunsTheNextLookup()=opened(startNavigation=false) {repository,access,_->
        val policy=TripRemotePolicy(true,setOf("light.cabin"),"device")
        repository.refreshRemotePolicy()
        val dropped=access.api.lists.removeFirst()
        access.invalidate()
        access.api.details.removeFirst()(Result.failure(NativeSocialFailure(NativeSocialFailure.Kind.UNAVAILABLE)))
        assertFalse(repository.states.value.isCurrent)
        dropped(Result.success(list))
        access.api.details.removeFirst()(Result.success(detail))
        access.api.lists.removeFirst()(Result.success(list))
        access.api.details.removeFirst()(Result.success(detail.copy(cars=listOf(car.copy(remotePolicy=policy)))))
        assertEquals(AccountReadStatus.READY,repository.states.value.remotePolicySnapshot.status)
        assertEquals(policy,repository.states.value.remotePolicySnapshot.policy)
    }
    @Test fun carPolicyLookupDroppedWhenClientIsNotReadyCanBeRefreshedAgain()=opened(startNavigation=false) {repository,access,_->
        repository.closeDetail();repository.refreshRemotePolicy()
        val dropped=access.api.lists.removeFirst()
        access.clientAvailable=false
        dropped(Result.success(list))
        assertNotEquals(AccountReadStatus.LOADING,repository.states.value.remotePolicySnapshot.status)
        access.clientAvailable=true
        repository.refreshRemotePolicy()
        access.api.lists.removeFirst()(Result.success(TripList(emptyList(),emptyList())))
        assertEquals(AccountReadStatus.READY,repository.states.value.remotePolicySnapshot.status)
    }
    @Test fun carPolicyLookupCancelledByReconnectDoesNotStayLoading()=opened(startNavigation=false) {repository,access,_->
        repository.closeDetail();repository.refreshRemotePolicy()
        assertEquals(AccountReadStatus.LOADING,repository.states.value.remotePolicySnapshot.status)
        access.invalidate()
        access.api.lists.removeLast()(Result.failure(java.io.IOException("offline")))
        assertFalse(repository.states.value.isCurrent)
        assertNotEquals(AccountReadStatus.LOADING,repository.states.value.remotePolicySnapshot.status)
    }
    private class FakeAccess: TripsRepositoryAccess {
        override val scoreNamespace="account-a"
        override var scoreReportAuthority: ScoreReportAuthority?=null
        val api=FakeApi()
        lateinit var authority: NativeSocialObserver
        lateinit var listener: VehicleEventsListener
        var clients=0
        var clientAvailable=true
        private var retained=false
        override val connected=true
        override var onExpired: ()->Unit = {}
        override fun observe(changed: ()->Unit)=Closeable {}
        override fun client(): TripsRepositoryClient {
            clients++
            return object: TripsRepositoryClient {
                override val tripsApi=api
                private var active=false
                override val ready get()=active && clientAvailable
                override fun open(observer: NativeSocialObserver,callback: (Result<Unit>)->Unit) {
                    authority=observer;active=true;callback(Result.success(Unit))
                }
                override fun close() {active=false}
            }
        }
        override fun subscribe(listener: VehicleEventsListener): Closeable {this.listener=listener;listener.onOpen();return Closeable {}}
        fun invalidate() {listener.onEvent(VehicleEvent("invalidate",listOf("devices")))}
        var remembers=true
        override fun remember(): Boolean {retained=remembers;return remembers}
        override fun canRetain()=retained
        override fun invalidated()=false
        override fun forget() {retained=false}
        /** 계정·연결 경계가 바뀌어 기억한 읽기를 더는 보여 줄 수 없다. */
        fun changeAccount() {retained=false}
        override fun post(action: ()->Unit)=action()
        val scheduled=mutableListOf<Pair<Long,()->Unit>>()
        override fun schedule(delayMillis: Long,action: ()->Unit): Closeable {
            val entry=delayMillis to action;scheduled.add(entry);return Closeable {scheduled.remove(entry)}
        }
    }
    private class FakeApi: TripsApi {
        val sections=mutableListOf<String>()
        val sectionReplies=ArrayDeque<(Result<TripDetail>)->Unit>()
        override fun readSection(detail: TripDetail,section: String,callback: (Result<TripDetail>)->Unit): Closeable {
            sections.add(section);sectionReplies.add(callback);return Closeable {}
        }
        val joinedCompletions=mutableListOf<Triple<String,Long,Long>>()
        val joinedCompletionReplies=ArrayDeque<(Result<Unit>)->Unit>()
        override fun completeJoinedCourse(id: String,carId: String,packId: String,routeRevision: Long,progressRevision: Long,
            report: DrivingScoreReport,callback: (Result<Unit>)->Unit): Closeable {
            joinedCompletions.add(Triple(packId,routeRevision,progressRevision));joinedCompletionReplies.add(callback);return Closeable {}
        }
        val arrivalOptins=mutableListOf<Boolean>()
        override fun routeArrival(id: String,carId: String,routeRevision: Long,progressRevision: Long,item: TripRouteItem,
            singleJoinCompletion: Boolean,callback: (Result<TripRoutePlan>)->Unit): Closeable {
            arrivalOptins.add(singleJoinCompletion)
            return routeArrival(id,carId,routeRevision,progressRevision,item,callback)
        }
        val arrivalItems=mutableListOf<Triple<Long,Long,TripRouteItem>>()
        val arrivalReplies=ArrayDeque<(Result<TripRoutePlan>)->Unit>()
        override fun routeArrival(id: String,carId: String,routeRevision: Long,progressRevision: Long,item: TripRouteItem,
            callback: (Result<TripRoutePlan>)->Unit): Closeable {
            arrivalItems.add(Triple(routeRevision,progressRevision,item));arrivalReplies.add(callback);return Closeable {}
        }
        val progress=mutableListOf<Pair<Long,TripRouteItem?>>()
        var autoProgress=true
        val progressReplies=ArrayDeque<(Result<Unit>)->Unit>()
        override fun routeProgress(id: String,carId: String,routeRevision: Long,next: TripRouteItem?,callback: (Result<Unit>)->Unit): Closeable {
            progress.add(routeRevision to next)
            if(autoProgress)callback(Result.success(Unit)) else progressReplies.add(callback)
            return Closeable {}
        }
        val lists=ArrayDeque<(Result<TripList>)->Unit>()
        val details=ArrayDeque<(Result<TripDetail>)->Unit>()
        val actions=ArrayDeque<(Result<TripActionResult>)->Unit>()
        var actionCloses=0
        val performedActions=mutableListOf<TripAction>()
        val responses=mutableListOf<Triple<String,Boolean,Boolean?>>()
        val signals=ArrayDeque<(Result<TripSignalPage>)->Unit>()
        val sends=ArrayDeque<(Result<String>)->Unit>()
        val votes=mutableListOf<String>()
        val voteRequests=mutableListOf<Pair<String,String>>()
        val savedRoutes=mutableListOf<Pair<Long,List<TripRouteItem>>>()
        val routeSaveReplies=ArrayDeque<(Result<Unit>)->Unit>()
        val signalTripIds=mutableListOf<String>()
        val detailTripIds=mutableListOf<String>()
        val voteReplies=ArrayDeque<(Result<Unit>)->Unit>()
        val locationReads=ArrayDeque<(Result<TripLocationShare>)->Unit>()
        val carLocationReads=ArrayDeque<(Result<TripLocationShare>)->Unit>()
        val locationReports=mutableListOf<Triple<String,String,TripLocationFix>>()
        override fun readLocationShare(id: String,callback: (Result<TripLocationShare>)->Unit)=Closeable {}.also {locationReads.add(callback)}
        override fun readCarLocations(id: String,callback: (Result<TripLocationShare>)->Unit)=Closeable {}.also {carLocationReads.add(callback)}
        override fun reportLocation(id: String,shareId: String,fix: TripLocationFix,callback: (Result<Unit>)->Unit): Closeable {
            locationReports+=Triple(id,shareId,fix);callback(Result.success(Unit));return Closeable {}
        }
        fun replySignals(values: List<TripSignal>,hasActive: Boolean=values.any {it.inProgress}) {
            signals.removeFirst()(Result.success(TripSignalPage(values,hasActive)))
        }
        val finished=mutableListOf<Pair<String,String>>()
        val finishReplies=ArrayDeque<(Result<Unit>)->Unit>()
        override fun finishSignal(id: String,signal: String,result: String,callback: (Result<Unit>)->Unit)=Closeable {}.also {finished.add(signal to result);finishReplies.add(callback)}
        override fun readSignals(id: String,callback: (Result<TripSignalPage>)->Unit)=Closeable {}.also {signalTripIds.add(id);signals.add(callback)}
        override fun sendSignal(id: String,kind: TripSignalKind,destination: SignalDestination?,callback: (Result<String>)->Unit)=Closeable {}.also {sends.add(callback)}
        val candidateRequests=mutableListOf<Triple<String,TripSignalKind,SignalLocation>>()
        val candidateReplies=ArrayDeque<(Result<List<SignalCandidate>>)->Unit>()
        var candidateReadCloses=0
        override fun signalCandidates(id: String,kind: TripSignalKind,location: SignalLocation,callback: (Result<List<SignalCandidate>>)->Unit): Closeable {
            candidateRequests.add(Triple(id,kind,location));candidateReplies.add(callback);return Closeable {candidateReadCloses++}
        }
        var nextVoteResult: TripSignalVoteResult?=null
        override fun voteSignalResult(id: String,signal: String,choice: String,callback: (Result<TripSignalVoteResult>)->Unit): Closeable {
            nextVoteResult?.let {nextVoteResult=null;callback(Result.success(it));return Closeable {}}
            return voteSignal(id,signal,choice) {reply->callback(reply.map {TripSignalVoteResult(choice)})}
        }
        override fun voteSignal(id: String,signal: String,choice: String,callback: (Result<Unit>)->Unit)=Closeable {}.also {voteRequests.add(id to signal);votes.add(choice);voteReplies.add(callback)}
        val finalReports=mutableListOf<Pair<String,DrivingScoreReport>>()
        var finalFailure=false
        override fun reportFinalDrivingScore(id: String,carId: String,packId: String,report: DrivingScoreReport,
            callback: (Result<Unit>)->Unit): Closeable {
            finalReports.add(packId to report)
            callback(if(finalFailure)Result.failure(java.io.IOException()) else Result.success(Unit));return Closeable {}
        }
        override fun reportTripDrivingScore(id: String,carId: String,report: DrivingScoreReport,callback: (Result<Unit>)->Unit): Closeable {
            if(report.final)finalReports.add("trip-total-v1" to report) else scoreReports.add("trip-total-v1" to report)
            callback(if(report.final && finalFailure)Result.failure(java.io.IOException()) else Result.success(Unit));return Closeable {}
        }
        val scoreReports=mutableListOf<Pair<String,DrivingScoreReport>>()
        override fun reportDrivingScore(id: String,carId: String,packId: String,report: DrivingScoreReport,callback: (Result<Unit>)->Unit): Closeable {
            scoreReports+=packId to report;callback(Result.success(Unit));return Closeable {}
        }
        var completions=0
        val courseReplies=ArrayDeque<(Result<Unit>)->Unit>()
        override fun readList(callback: (Result<TripList>)->Unit)=Closeable {}.also {lists.add(callback)}
        override fun readDetail(id: String,callback: (Result<TripDetail>)->Unit)=Closeable {}.also {detailTripIds.add(id);details.add(callback)}
        override fun perform(id: String,action: TripAction,callback: (Result<TripActionResult>)->Unit)=Closeable {actionCloses++}.also {performedActions+=action;actions.add(callback)}
        override fun respond(id: String,accept: Boolean,locationConsent: Boolean?,callback: (Result<Unit>)->Unit)=Closeable {}.also {responses+=Triple(id,accept,locationConsent)}
        override fun readPlaces(id: String,carId: String,callback: (Result<List<TripPlace>>)->Unit)=error("unexpected places")
        override fun saveRouteOrder(id: String,carId: String,routeRevision: Long,items: List<TripRouteItem>,callback: (Result<Unit>)->Unit)=Closeable {}.also {savedRoutes.add(routeRevision to items);routeSaveReplies.add(callback)}
        override fun completeCourse(id: String,carId: String,packId: String,callback: (Result<Unit>)->Unit): Closeable {completions++;courseReplies.add(callback);return Closeable {}}
        override fun readInviteFriends(id: String,callback: (Result<List<TripInviteFriend>>)->Unit)=error("unexpected friends")
    }
}
