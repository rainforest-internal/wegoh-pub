import Foundation
import XCTest
@testable import WegoH

@MainActor
final class TripLiveActivityStoreTests: XCTestCase {
    func testIncomingSignalDoesNotPresentUnusableActionsForReadOnlySession() async throws {
        let (preparation, api, activity, _) = try await context()
        let session = SessionManager(api: FeatureAuth(accountID: try XCTUnwrap(api.value.me).id,
                                                     scopes: ["account:read", "trips:read"]), credentials: FeatureCredential())
        await session.restore()
        activity.signalValues = [signal(preparation)]
        let inbox = TripSignalInbox(session: session, api: api, activity: activity)
        await inbox.refresh(tripID: api.value.id)
        XCTAssertNil(inbox.prompt)
        XCTAssertFalse(inbox.canRespond)
        XCTAssertEqual(activity.signalReads, 0)
    }

    func testIncomingSignalLateReadCannotReopenAfterAConfirmedResponse() async throws {
        let (preparation, api, activity, session) = try await context()
        let pending = signal(preparation)
        activity.signalValues = [pending]
        let inbox = TripSignalInbox(session: session, api: api, activity: activity)
        await inbox.refresh(tripID: api.value.id)
        activity.pauseSignals = true
        let read = Task { await inbox.refresh() }
        for _ in 0..<1000 where activity.signalContinuation == nil { await Task.yield() }
        let continuation = try XCTUnwrap(activity.signalContinuation)
        activity.pauseSignals = false
        activity.pauseVote = true
        let vote = Task { await inbox.respond(agree: false) }
        for _ in 0..<1000 where activity.voteContinuation == nil { await Task.yield() }
        activity.signalValues[0].canRespond = false
        activity.signalValues[0].myGroupChoice = "pass"
        try XCTUnwrap(activity.voteContinuation).resume(returning: false)
        await vote.value
        XCTAssertNil(inbox.prompt)
        continuation.resume(returning: [pending])
        await read.value
        XCTAssertNil(inbox.prompt)
        XCTAssertEqual(activity.votes, 1)
    }

    func testIncomingSignalRechecksAfterForegroundReturnWithoutAnotherVote() async throws {
        let (preparation, api, activity, session) = try await context()
        activity.signalValues = [signal(preparation)]
        let inbox = TripSignalInbox(session: session, api: api, activity: activity)
        await inbox.refresh(tripID: api.value.id)
        inbox.suspend()
        XCTAssertFalse(inbox.canRespond)
        await inbox.refresh()
        XCTAssertTrue(inbox.canRespond)
        XCTAssertEqual(activity.votes, 0)
    }

    func testIncomingSignalRejectedVoteKeepsPromptAndShowsErrorWithoutAutomaticResend() async throws {
        let (preparation, api, activity, session) = try await context()
        activity.signalValues = [signal(preparation)]
        activity.voteFailure = URLError(.notConnectedToInternet)
        let inbox = TripSignalInbox(session: session, api: api, activity: activity)
        await inbox.refresh(tripID: api.value.id)
        await inbox.respond(agree: true)
        XCTAssertNotNil(inbox.prompt)
        XCTAssertNotNil(inbox.message)
        XCTAssertTrue(inbox.canRespond)
        XCTAssertEqual(activity.votes, 1)
    }

    func testIncomingSignalAppearsWithoutOpeningPushAndClosesWhenAnotherCarMemberAnswers() async throws {
        let (preparation, api, activity, session) = try await context()
        activity.signalValues = [signal(preparation)]
        let inbox = TripSignalInbox(session: session, api: api, activity: activity)
        await inbox.refresh(tripID: api.value.id)
        XCTAssertEqual(inbox.prompt?.signal.id, activity.signalValues.first?.id)
        XCTAssertTrue(inbox.canRespond)
        activity.signalValues[0].canRespond = false
        activity.signalValues[0].myGroupChoice = "agree"
        await inbox.refresh()
        XCTAssertNil(inbox.prompt)
        XCTAssertEqual(activity.votes, 0)
    }

    func testIncomingSignalSkipsOwnCarAlreadyAnsweredAndTerminalRequests() async throws {
        let (preparation, api, activity, session) = try await context()
        let inbox = TripSignalInbox(session: session, api: api, activity: activity)
        var value = signal(preparation)
        value.requesterCarId = try XCTUnwrap(api.value.myCar).id
        activity.signalValues = [value]
        await inbox.refresh(tripID: api.value.id)
        XCTAssertNil(inbox.prompt)
        value.requesterCarId = nil
        for resolution in ["agreed", "passed", "cancelled", "completed", "reconfirm"] {
            value.resolution = resolution
            activity.signalValues = [value]
            await inbox.refresh(tripID: api.value.id)
            XCTAssertNil(inbox.prompt, resolution)
        }
        value.resolution = "pending"; value.canRespond = false
        activity.signalValues = [value]
        await inbox.refresh(tripID: api.value.id)
        XCTAssertNil(inbox.prompt)
    }

    func testIncomingSignalSerializesResponseAndClosesOnlyAfterServerConfirms() async throws {
        let (preparation, api, activity, session) = try await context()
        activity.signalValues = [signal(preparation)]
        activity.pauseVote = true
        let inbox = TripSignalInbox(session: session, api: api, activity: activity)
        await inbox.refresh(tripID: api.value.id)
        let vote = Task { await inbox.respond(agree: true) }
        for _ in 0..<1000 where activity.voteContinuation == nil { await Task.yield() }
        XCTAssertNotNil(inbox.prompt)
        XCTAssertTrue(inbox.responding)
        await inbox.respond(agree: false)
        XCTAssertEqual(activity.votes, 1)
        activity.signalValues[0].canRespond = false
        activity.signalValues[0].myGroupChoice = "agree"
        try XCTUnwrap(activity.voteContinuation).resume(returning: false)
        await vote.value
        XCTAssertNil(inbox.prompt)
        XCTAssertFalse(inbox.responding)
    }

    func testIncomingSignalKeepsUncertainResponseAndRetriesReadWithoutResendingVote() async throws {
        let (preparation, api, activity, session) = try await context()
        activity.signalValues = [signal(preparation)]
        activity.pauseVote = true
        let inbox = TripSignalInbox(session: session, api: api, activity: activity)
        await inbox.refresh(tripID: api.value.id)
        let vote = Task { await inbox.respond(agree: true) }
        for _ in 0..<1000 where activity.voteContinuation == nil { await Task.yield() }
        activity.failure = URLError(.networkConnectionLost)
        try XCTUnwrap(activity.voteContinuation).resume(returning: false)
        await vote.value
        XCTAssertNotNil(inbox.prompt)
        XCTAssertTrue(inbox.needsVerification)
        await inbox.respond(agree: true)
        XCTAssertEqual(activity.votes, 1)
        activity.failure = nil
        activity.signalValues[0].canRespond = false
        await inbox.refresh(tripID: api.value.id)
        XCTAssertNil(inbox.prompt)
        XCTAssertEqual(activity.votes, 1)
    }

    func testIncomingSignalClearsAfterLogoutAndCannotSendCachedResponse() async throws {
        let (preparation, api, activity, session) = try await context()
        activity.signalValues = [signal(preparation)]
        let inbox = TripSignalInbox(session: session, api: api, activity: activity)
        await inbox.refresh(tripID: api.value.id)
        await session.signOut()
        XCTAssertFalse(inbox.canRespond)
        await inbox.respond(agree: true)
        await inbox.refresh()
        XCTAssertNil(inbox.prompt)
        XCTAssertEqual(activity.votes, 0)
    }

    func testIncomingSignalIsDiscoveredFromActiveTripsWithoutAPushPermission() async throws {
        let (preparation, api, activity, session) = try await context()
        api.page.trips = [.init(id: api.value.id, title: api.value.title, state: .active, isOwner: false,
                                ownerName: "일행", memberCount: 2, carCount: 2)]
        activity.signalValues = [signal(preparation)]
        let inbox = TripSignalInbox(session: session, api: api, activity: activity)
        await inbox.refresh(discover: true)
        XCTAssertNotNil(inbox.prompt)
        XCTAssertEqual(api.listReads, 1)
        await inbox.refresh()
        XCTAssertEqual(api.listReads, 1)
    }

    func testIncomingSignalKeepsPromptOnNetworkFailureButClearsOnRevokedAccess() async throws {
        let (preparation, api, activity, session) = try await context()
        activity.signalValues = [signal(preparation)]
        let inbox = TripSignalInbox(session: session, api: api, activity: activity)
        await inbox.refresh(tripID: api.value.id)
        activity.failure = URLError(.notConnectedToInternet)
        await inbox.refresh()
        XCTAssertNotNil(inbox.prompt)
        XCTAssertFalse(inbox.canRespond)
        activity.failure = IPhoneSessionError.forbidden
        await inbox.refresh()
        XCTAssertNil(inbox.prompt)
    }

    func testSignalCandidateFiltersRequireAheadAndAllFacilitiesAndUseLeadCar() async throws {
        let (preparation, _, activity, _) = try await context()
        let store = TripLiveSignalStore(preparation: preparation, api: activity,
            locationProvider: { .init(lat: 37.5, lng: 127, heading: 90) })
        let good = IPhoneTripSignalCandidate(name: "조건에 맞는 휴게소", lat: 37.6, lng: 127, verdict: "ahead",
            fromLeadMeters: 1000, detourSeconds: 60, facilities: ["toilet": true, "nursing": true])
        var missing = good; missing.name = "시설 없는 곳"; missing.facilities = [:]
        var behind = good; behind.name = "경로 밖"; behind.verdict = "off_route"
        activity.page = .init(cars: [
            .init(carId: String(repeating: "a", count: 32), state: "same_road", alongMeters: 20),
            .init(carId: String(repeating: "b", count: 32), state: "same_road", alongMeters: 40),
            .init(carId: String(repeating: "c", count: 32), state: "off_route", alongMeters: 100)
        ], basis: "route", partial: false, candidates: [good, missing, behind])
        store.next()
        await store.search()
        XCTAssertEqual(store.candidates.map(\.name), [good.name])
        XCTAssertEqual(store.leadCarID, String(repeating: "b", count: 32))
        store.selectedID = good.id
        store.toggle(.nursing)
        XCTAssertNil(store.selected)
        XCTAssertNil(store.leadCarID)
        XCTAssertTrue(store.candidates.isEmpty)
        await store.search()
        XCTAssertEqual(activity.requestedFacilities, [.restroom, .nursing])
        XCTAssertEqual(store.candidates.map(\.name), [good.name])
    }

    func testSignalDuplicateVoteIsSerializedAndExistingCarVoteWins() async throws {
        let (preparation, _, activity, _) = try await context()
        activity.signalValues = [signal(preparation)]
        activity.pauseVote = true
        let store = TripLiveSignalStore(preparation: preparation, api: activity)
        await store.refresh()
        XCTAssertTrue(store.canRespond)
        let pending = Task { await store.vote(agree: true) }
        for _ in 0..<1000 where activity.voteContinuation == nil { await Task.yield() }
        let continuation = try XCTUnwrap(activity.voteContinuation)
        await store.vote(agree: false)
        XCTAssertEqual(activity.votes, 1)
        activity.signalValues[0].canRespond = false
        activity.signalValues[0].myGroupChoice = "agree"
        continuation.resume(returning: true)
        await pending.value
        XCTAssertFalse(store.canRespond)
        XCTAssertEqual(store.signal?.myGroupChoice, "agree")
        XCTAssertEqual(store.message, "우리 차에서 이미 응답했어요.")
    }

    func testSignalAccessLossClearsValuesAndLogoutHidesCachedResponseImmediately() async throws {
        let (preparation, _, activity, session) = try await context()
        activity.signalValues = [signal(preparation)]
        let store = TripLiveSignalStore(preparation: preparation, api: activity)
        await store.refresh()
        XCTAssertNotNil(store.signal)
        activity.failure = IPhoneSessionError.forbidden
        await store.refresh()
        XCTAssertNil(store.signal)
        XCTAssertTrue(store.candidates.isEmpty)
        XCTAssertEqual(session.phase, .signedIn)
        activity.failure = nil
        await store.refresh()
        XCTAssertNotNil(store.signal)
        await session.signOut()
        XCTAssertNil(store.signal)
        XCTAssertFalse(store.canRespond)
        XCTAssertFalse(store.canSend)
    }

    func testImmediatelyAgreedSignalIsFoundBySentID() async throws {
        let (preparation, _, activity, _) = try await context()
        var agreed = signal(preparation)
        agreed.id = String(repeating: "a", count: 32); agreed.inProgress = false; agreed.resolution = "agreed"; agreed.canRespond = false
        activity.sentID = agreed.id
        activity.signalValues = [agreed]
        let store = TripLiveSignalStore(preparation: preparation, api: activity)
        store.next()
        await store.send()
        XCTAssertEqual(store.signal?.id, agreed.id)
        XCTAssertEqual(store.signal?.resolution, "agreed")
        await store.refresh()
        XCTAssertEqual(store.signal?.id, agreed.id)
    }

    func testSentSignalIsFoundByRefreshAfterFailedRead() async throws {
        let (preparation, _, activity, _) = try await context()
        var agreed = signal(preparation)
        agreed.id = String(repeating: "a", count: 32); agreed.inProgress = false; agreed.resolution = "agreed"; agreed.canRespond = false
        var other = signal(preparation)
        other.id = String(repeating: "b", count: 32)
        activity.sentID = agreed.id
        activity.signalValues = [other, agreed]
        activity.afterSendFailure = IPhoneResourceError.unavailable
        let store = TripLiveSignalStore(preparation: preparation, api: activity)
        store.next()
        await store.send()
        XCTAssertTrue(store.needsRefresh)
        XCTAssertNil(store.signal)
        XCTAssertEqual(store.sentSignalID, agreed.id)
        activity.failure = nil
        await store.refresh()
        XCTAssertFalse(store.needsRefresh)
        XCTAssertEqual(store.signal?.id, agreed.id)
        XCTAssertEqual(store.signal?.resolution, "agreed")
    }

    func testSavedSignalWithFailedReadCannotBeSentAgain() async throws {
        let (preparation, _, activity, _) = try await context()
        activity.afterSendFailure = IPhoneResourceError.unavailable
        let store = TripLiveSignalStore(preparation: preparation, api: activity)
        store.next()
        XCTAssertTrue(store.canSend)
        await store.send()
        XCTAssertTrue(store.needsRefresh)
        XCTAssertFalse(store.canSend)
        await store.send()
        XCTAssertEqual(activity.sends, 1)
        activity.failure = nil
        await store.refresh()
        XCTAssertFalse(store.needsRefresh)
    }

    func testVisibleProgressRefreshFetchesCurrentDetailAndReceivedSignals() async throws {
        let (preparation, api, activity, _) = try await context()
        activity.signalValues = [signal(preparation)]
        api.value.revision += 1
        await preparation.refreshVisibleState()
        XCTAssertEqual(preparation.detail?.revision, api.value.revision)
        XCTAssertEqual(preparation.activeSignals.map(\.id), activity.signalValues.map(\.id))
        api.value.state = .completed
        await preparation.refreshVisibleState()
        XCTAssertTrue(preparation.activeSignals.isEmpty)
        XCTAssertEqual(activity.signalReads, 1)
    }

    func testRemoteUsesCurrentGrantAndNeverSendsRemovedAction() async throws {
        let (preparation, _, activity, _) = try await context()
        let action = IPhoneTripRemote.Action(id: "light.cabin", revision: 1, label: "실내등", argumentKind: "switch")
        let remote = IPhoneTripRemote(deviceId: String(repeating: "d", count: 32), ownerName: "운전자", deviceName: "연결 차량", grantRevision: 3, actions: [action])
        activity.remoteValues = [remote]
        let store = TripLiveRemoteStore(preparation: preparation, api: activity)
        await store.load()
        var old = remote; old.grantRevision = 2
        await store.send(remote: old, action: action, seat: "ROW_2_LEFT", value: true)
        XCTAssertEqual(activity.commands, 0)
        let removed = IPhoneTripRemote.Action(id: "hvac.fan", revision: 1, label: "풍량", argumentKind: "hvac-fan")
        await store.send(remote: remote, action: removed, seat: "ROW_2_LEFT", value: 20)
        XCTAssertEqual(activity.commands, 0)
        await store.send(remote: remote, action: action, seat: "ROW_2_LEFT", value: true)
        XCTAssertEqual(activity.commands, 1)
        XCTAssertTrue(store.message?.contains("전달 대기") == true)
        XCTAssertTrue(store.message?.contains("실제 작동 여부") == true)
    }

    func testRemoteAccessLossAndMovingOutOfCarHidePermissionCache() async throws {
        let (preparation, api, activity, session) = try await context()
        activity.remoteValues = [.init(deviceId: String(repeating: "d", count: 32), ownerName: "운전자", deviceName: "차", grantRevision: 3,
            actions: [.init(id: "light.cabin", revision: 1, label: "실내등", argumentKind: "switch")])]
        let store = TripLiveRemoteStore(preparation: preparation, api: activity)
        await store.load()
        XCTAssertEqual(store.remotes.count, 1)
        activity.failure = IPhoneSessionError.forbidden
        await store.load()
        XCTAssertTrue(store.remotes.isEmpty)
        XCTAssertEqual(session.phase, .signedIn)
        activity.failure = nil
        await store.load()
        let actor = try XCTUnwrap(api.value.me?.id)
        for index in api.value.cars.indices { api.value.cars[index].passengers.removeAll { $0.id == actor }; api.value.cars[index].iRide = false }
        await preparation.load()
        XCTAssertTrue(store.remotes.isEmpty)
    }

    func testClimateBundleSendsTemperatureThenFanUsingTheSelectedSeat() async throws {
        let (preparation, _, activity, _) = try await context()
        let temperature = IPhoneTripRemote.Action(id: "hvac.temperature", revision: 1, label: "온도", argumentKind: "hvac-celsius")
        let fan = IPhoneTripRemote.Action(id: "hvac.fan", revision: 1, label: "풍량", argumentKind: "hvac-fan")
        let remote = IPhoneTripRemote(deviceId: String(repeating: "d", count: 32), ownerName: "운전자", deviceName: "차", grantRevision: 3, actions: [temperature, fan])
        activity.remoteValues = [remote]
        let store = TripLiveRemoteStore(preparation: preparation, api: activity)
        await store.load()
        await store.sendBundle(remote: remote, seat: "ROW_2_RIGHT", commands: [(temperature, 22.5), (fan, 3)])
        XCTAssertEqual(activity.commandIDs, ["hvac.temperature", "hvac.fan"])
        XCTAssertEqual(activity.commandSeats, ["ROW_2_RIGHT", "ROW_2_RIGHT"])
        XCTAssertTrue(store.message?.contains("온도 · 전달 대기") == true)
        XCTAssertTrue(store.message?.contains("풍량 · 전달 대기") == true)
        XCTAssertTrue(store.message?.contains("실제 작동 여부") == true)
    }

    func testClimateBundleStopsAfterPartialFailureAndDoesNotRetrySavedCommand() async throws {
        let (preparation, _, activity, _) = try await context()
        let temperature = IPhoneTripRemote.Action(id: "hvac.temperature", revision: 1, label: "온도", argumentKind: "hvac-celsius")
        let fan = IPhoneTripRemote.Action(id: "hvac.fan", revision: 1, label: "풍량", argumentKind: "hvac-fan")
        let remote = IPhoneTripRemote(deviceId: String(repeating: "d", count: 32), ownerName: "운전자", deviceName: "차", grantRevision: 3, actions: [temperature, fan])
        activity.remoteValues = [remote]
        activity.failedCommandNumber = 2
        let store = TripLiveRemoteStore(preparation: preparation, api: activity)
        await store.load()
        await store.sendBundle(remote: remote, seat: "ROW_2_LEFT", commands: [(temperature, 22.5), (fan, 3)])
        XCTAssertEqual(activity.commands, 2)
        XCTAssertTrue(store.message?.contains("1개 명령을 전달했고 나머지는 보내지 못했어요") == true)
        XCTAssertTrue(store.remotes.isEmpty)
        await store.sendBundle(remote: remote, seat: "ROW_2_LEFT", commands: [(temperature, 22.5), (fan, 3)])
        XCTAssertEqual(activity.commands, 2)
    }

    func testClimateBundleStopsOnNegativeOrUnknownReceipt() async throws {
        for stage in ["rejected", "cancelled", "expired", "unknown"] {
            let (preparation, _, activity, _) = try await context()
            let temperature = IPhoneTripRemote.Action(id: "hvac.temperature", revision: 1, label: "온도", argumentKind: "hvac-celsius")
            let fan = IPhoneTripRemote.Action(id: "hvac.fan", revision: 1, label: "풍량", argumentKind: "hvac-fan")
            let remote = IPhoneTripRemote(deviceId: String(repeating: "d", count: 32), ownerName: "운전자", deviceName: "차", grantRevision: 3, actions: [temperature, fan])
            activity.remoteValues = [remote]
            activity.commandStage = stage
            let store = TripLiveRemoteStore(preparation: preparation, api: activity)
            await store.load()
            await store.sendBundle(remote: remote, seat: "ROW_2_LEFT", commands: [(temperature, 22.5), (fan, 3)])
            XCTAssertEqual(activity.commands, 1, stage)
            XCTAssertEqual(activity.commandIDs, ["hvac.temperature"], stage)
            XCTAssertTrue(store.message?.contains("나머지 명령은 보내지 않았어요") == true, stage)
        }
    }

    func testClimateBundleRechecksCarMembershipBetweenCommands() async throws {
        let (preparation, api, activity, _) = try await context()
        let temperature = IPhoneTripRemote.Action(id: "hvac.temperature", revision: 1, label: "온도", argumentKind: "hvac-celsius")
        let fan = IPhoneTripRemote.Action(id: "hvac.fan", revision: 1, label: "풍량", argumentKind: "hvac-fan")
        let remote = IPhoneTripRemote(deviceId: String(repeating: "d", count: 32), ownerName: "운전자", deviceName: "차", grantRevision: 3, actions: [temperature, fan])
        activity.remoteValues = [remote]
        let actor = try XCTUnwrap(api.value.me?.id)
        activity.afterCommand = {
            for index in api.value.cars.indices {
                api.value.cars[index].passengers.removeAll { $0.id == actor }
                api.value.cars[index].iRide = false
            }
            await preparation.load()
        }
        let store = TripLiveRemoteStore(preparation: preparation, api: activity)
        await store.load()
        await store.sendBundle(remote: remote, seat: "ROW_2_LEFT", commands: [(temperature, 22.5), (fan, 3)])
        XCTAssertEqual(activity.commands, 1)
        XCTAssertEqual(activity.commandIDs, ["hvac.temperature"])
        XCTAssertTrue(store.remotes.isEmpty)
    }

    func testFriendTripInvitePreservesDetailOnOfflineAndRefetchesOnceOnSuccess() async throws {
        let (preparation, api, _, _) = try await context(state: .planned)
        let before = try XCTUnwrap(preparation.detail)
        api.failure = IPhoneTripRequestError.unavailable
        do { try await preparation.invite(accountID: "team-" + String(repeating: "f", count: 40)); XCTFail("Offline invitation succeeded") }
        catch IPhoneTripRequestError.unavailable { }
        XCTAssertEqual(preparation.detail, before)
        XCTAssertEqual(api.reads, 1)
        api.failure = nil
        try await preparation.invite(accountID: "team-" + String(repeating: "f", count: 40))
        XCTAssertEqual(api.reads, 2)
        XCTAssertEqual(api.inviteWrites, 2)
    }

    func testStableOrdinalDoesNotChangeAfterAnotherCarDisappears() async throws {
        let (preparation, api, _, _) = try await context()
        let mine = try XCTUnwrap(api.value.myCar)
        let index = try XCTUnwrap(api.value.cars.firstIndex(where: { $0.id == mine.id }))
        api.value.cars[index].ordinal = 7
        await preparation.load()
        let detail = try XCTUnwrap(preparation.detail)
        XCTAssertTrue(detail.numberedName(try XCTUnwrap(detail.myCar)).hasPrefix("7호차 · "))
        XCTAssertFalse(IPhoneTripCar(id: mine.id, name: mine.name, seats: mine.seats, driverId: mine.driverId,
            driverName: mine.driverName, isMine: mine.isMine, iRide: mine.iRide, driverVehicleReady: mine.driverVehicleReady,
            passengers: mine.passengers, ordinal: 0).isValid)
    }

    private func context(state: IPhoneTripState = .active) async throws -> (TripPreparationStore, FeatureTripAPI, FeatureActivityAPI, SessionManager) {
        let preview = try XCTUnwrap(TripPreviewData.myTrips.first { $0.id == "yangpyeong" })
        let sample = TripPreparationPreviewAPI(preview: preview)
        var detail = try await sample.detail(sample.tripID, token: "")
        detail.state = state
        let session = SessionManager(api: FeatureAuth(accountID: try XCTUnwrap(detail.me).id), credentials: FeatureCredential())
        await session.restore()
        let api = FeatureTripAPI(value: detail), activity = FeatureActivityAPI()
        let preparation = TripPreparationStore(tripID: detail.id, session: session, api: api, activityAPI: activity)
        await preparation.load()
        return (preparation, api, activity, session)
    }

    func testPlacelessRequestWaitsForRequesterInsteadOfConsent() {
        var value = IPhoneTripSignal(id: String(repeating: "e", count: 32), accountId: "team-" + String(repeating: "e", count: 40),
            kind: "cafe", destination: nil, contextState: "valid", inProgress: true, resolution: "pending", agreed: false,
            canRespond: false, myGroupChoice: nil, requesterCarId: nil, groupVotes: nil, groupResponses: nil)
        XCTAssertTrue(value.waitsForRequester)
        value.resolution = "completed"; value.inProgress = false
        XCTAssertFalse(value.waitsForRequester)
        value.resolution = "pending"; value.inProgress = true
        value.destination = IPhoneTripSignalDestination(name: "카페", latitude: 37.5, longitude: 127.0)
        XCTAssertFalse(value.waitsForRequester)
    }

    func testPlacelessRequestDoesNotTellDriverItCannotBeAnswered() {
        var value = IPhoneTripSignal(id: String(repeating: "e", count: 32), accountId: "team-" + String(repeating: "e", count: 40),
            kind: "restroom", destination: nil, contextState: "valid", inProgress: true, resolution: "pending", agreed: false,
            canRespond: false, myGroupChoice: nil, requesterCarId: nil, groupVotes: nil, groupResponses: nil)
        XCTAssertNil(value.responseUnavailableCaption(isSender: false, canRespond: false))
        value.destination = IPhoneTripSignalDestination(name: "서산휴게소", latitude: 36.7, longitude: 126.5)
        XCTAssertEqual(value.responseUnavailableCaption(isSender: false, canRespond: false), "이 차에서 응답할 수 없는 요청이에요.")
        value.myGroupChoice = "agree"
        XCTAssertEqual(value.responseUnavailableCaption(isSender: false, canRespond: false), "우리 차에서 이미 응답했어요.")
        XCTAssertNil(value.responseUnavailableCaption(isSender: true, canRespond: false))
        XCTAssertNil(value.responseUnavailableCaption(isSender: false, canRespond: true))
        value.inProgress = false
        XCTAssertNil(value.responseUnavailableCaption(isSender: false, canRespond: false))
    }

    private func signal(_ preparation: TripPreparationStore) -> IPhoneTripSignal {
        .init(id: String(repeating: "e", count: 32), accountId: "team-" + String(repeating: "e", count: 40), kind: "restroom",
              destination: nil, contextState: "valid", inProgress: true, resolution: "pending", agreed: false,
              canRespond: true, myGroupChoice: nil, requesterCarId: nil, groupVotes: nil, groupResponses: nil)
    }
}

@MainActor
final class FeatureTripAPI: IPhoneTripServing {
    var value: IPhoneTripDetail
    var page = IPhoneTripList(trips: [], invitations: [])
    var reads = 0, listReads = 0, inviteWrites = 0, responses = 0
    var failure: Error?, listFailure: Error?
    var pauseResponse = false, pauseList = false
    var responseContinuation: CheckedContinuation<Void, Never>?
    var listContinuation: CheckedContinuation<IPhoneTripList, Never>?
    var receivedConsent: Bool?
    init(value: IPhoneTripDetail) { self.value = value }
    func list(token: String) async throws -> IPhoneTripList {
        listReads += 1
        if let listFailure { throw listFailure }
        if pauseList { return await withCheckedContinuation { listContinuation = $0 } }
        return page
    }
    func detail(_ tripID: String, token: String) async throws -> IPhoneTripDetail { reads += 1; return value }
    func create(_ draft: IPhoneTripDraft, token: String) async throws -> String { throw TripPreparationError.previewUnsupported }
    func respond(_ tripID: String, accept: Bool, locationConsent: Bool, token: String) async throws {
        responses += 1; receivedConsent = locationConsent
        if let failure { throw failure }
        if pauseResponse { await withCheckedContinuation { responseContinuation = $0 } }
        page.invitations.removeAll { $0.id == tripID }
    }
    func addMember(_ tripID: String, accountID: String, token: String) async throws { inviteWrites += 1; if let failure { throw failure } }
    func createCar(_ tripID: String, name: String, seats: Int, token: String) async throws -> String { throw TripPreparationError.previewUnsupported }
    func ride(_ tripID: String, carID: String, token: String) async throws { throw TripPreparationError.previewUnsupported }
    func leaveCar(_ tripID: String, token: String) async throws { throw TripPreparationError.previewUnsupported }
    func addCourse(_ tripID: String, packID: String, token: String) async throws { throw TripPreparationError.previewUnsupported }
    func addCarPlace(_ tripID: String, carID: String, kind: IPhoneTripPlaceKind, name: String, lat: Double, lng: Double, token: String) async throws -> String { throw TripPreparationError.previewUnsupported }
    func removeCarPlace(_ tripID: String, carID: String, placeID: String, token: String) async throws { throw TripPreparationError.previewUnsupported }
    func start(_ tripID: String, revision: Int, endActiveTrip: Bool, token: String) async throws { throw TripPreparationError.previewUnsupported }
    func setLocationSharing(_ tripID: String, enabled: Bool, token: String) async throws { throw TripPreparationError.previewUnsupported }
}

@MainActor
final class TripsAccountStoreTests: XCTestCase {
    func testCacheBindingRejectsRenewedExpiryAndScopesButKeepsDisplayNameChanges() async throws {
        let (store, _, session, _) = try await context()
        await store.load()
        let account = try XCTUnwrap(session.current)
        XCTAssertNotNil(store.value)
        XCTAssertTrue(store.belongsToAccount(account))
        XCTAssertTrue(store.belongsToAccount(.init(accountID: account.accountID, displayName: "새 이름",
                                                   expiresAt: account.expiresAt, scopes: account.scopes)))
        XCTAssertFalse(store.belongsToAccount(.init(accountID: account.accountID, displayName: account.displayName,
                                                    expiresAt: account.expiresAt.addingTimeInterval(60), scopes: account.scopes)))
        XCTAssertFalse(store.belongsToAccount(.init(accountID: account.accountID, displayName: account.displayName,
                                                    expiresAt: account.expiresAt, scopes: ["account:read"])))
        let otherID = "team-" + String(repeating: account.accountID.hasSuffix("0") ? "1" : "0", count: 40)
        XCTAssertFalse(store.belongsToAccount(.init(accountID: otherID, displayName: account.displayName,
                                                    expiresAt: account.expiresAt, scopes: account.scopes)))
        await session.signOut()
        XCTAssertNil(store.value)
    }

    func testNotificationRequiresFreshListAndNeverRespondsOnOpen() async throws {
        let (store, api, _, invitation) = try await context()

        let pending = await store.invitationDestination(for: invitation.id)
        XCTAssertEqual(pending, .review(invitation))
        XCTAssertEqual(api.listReads, 1)

        api.listFailure = IPhoneTripRequestError.unavailable
        let failed = await store.invitationDestination(for: invitation.id)
        XCTAssertNil(failed, "Do not route using the cached invitation if the new read failed")
        XCTAssertEqual(store.value?.invitations, [invitation])
        api.listFailure = nil

        api.page = .init(trips: [], invitations: [])
        let removed = await store.invitationDestination(for: invitation.id)
        XCTAssertEqual(removed, .unavailable)
        api.page.trips = [.init(id: invitation.id, title: "참여한 여행", state: .planned, isOwner: false,
                                ownerName: "방장", memberCount: 2, carCount: 0)]
        let joined = await store.invitationDestination(for: invitation.id)
        XCTAssertEqual(joined, .member(invitation.id))
        XCTAssertEqual(api.listReads, 4)
        XCTAssertEqual(api.reads, 0)
        XCTAssertEqual(api.responses, 0)
    }

    func testCancelledNotificationReadDoesNotRouteOrPopulateList() async throws {
        let (store, api, _, invitation) = try await context()
        api.pauseList = true
        let routing = Task { await store.invitationDestination(for: invitation.id) }
        for _ in 0..<1000 where api.listContinuation == nil { await Task.yield() }
        let continuation = try XCTUnwrap(api.listContinuation)
        routing.cancel()
        continuation.resume(returning: api.page)
        let destination = await routing.value
        XCTAssertNil(destination)
        XCTAssertNil(store.value)
        XCTAssertEqual(api.responses, 0)
    }

    func testLoggedOutAccountCannotNavigateWhenAnInvitationNotificationReadReturnsLate() async throws {
        let (store, api, session, invitation) = try await context()
        api.pauseList = true
        let routing = Task { await store.invitationDestination(for: invitation.id) }
        for _ in 0..<1000 where api.listContinuation == nil { await Task.yield() }
        let pending = try XCTUnwrap(api.listContinuation)
        await session.signOut()
        pending.resume(returning: api.page)
        let destination = await routing.value
        XCTAssertNil(destination)
        XCTAssertNil(store.value)
        XCTAssertEqual(api.responses, 0)
    }

    func testForegroundInvitationDuringFirstReadCoalescesAndReadsLatestWithoutResponding() async throws {
        let (store, api, session, invitation) = try await context()
        let account = try XCTUnwrap(session.current)
        func notification(_ digit: String, accountID: String, kind: String = "trip_invitation") throws -> IPhonePushNotification {
            try XCTUnwrap(IPhonePushNotification(userInfo: ["wegoh": ["eventId": String(repeating: digit, count: 32),
                "accountId": accountID, "kind": kind, "tripId": invitation.id]]))
        }

        api.pauseList = true
        let initial = Task { await store.load() }
        for _ in 0..<1000 where api.listContinuation == nil { await Task.yield() }
        let pending = try XCTUnwrap(api.listContinuation)
        let event = try notification("1", accountID: account.accountID)
        XCTAssertFalse(store.noteInvalidation(invitation: try notification("2", accountID: "team-" + String(repeating: "f", count: 40)), foregroundReturn: nil))
        XCTAssertFalse(store.noteInvalidation(invitation: try notification("3", accountID: account.accountID, kind: "hand_raise"), foregroundReturn: nil))
        XCTAssertTrue(store.noteInvalidation(invitation: event, foregroundReturn: nil))
        XCTAssertFalse(store.noteInvalidation(invitation: event, foregroundReturn: nil))
        await store.refreshAfterInvalidation()
        XCTAssertTrue(store.noteInvalidation(invitation: try notification("4", accountID: account.accountID), foregroundReturn: nil))
        await store.refreshAfterInvalidation()
        XCTAssertEqual(api.listReads, 1)

        api.pauseList = false
        pending.resume(returning: .init(trips: [], invitations: []))
        let fresh = await initial.value
        XCTAssertEqual(fresh?.invitations, [invitation])
        XCTAssertEqual(store.value, fresh)
        XCTAssertEqual(api.listReads, 2)
        XCTAssertEqual(api.reads, 0)
        XCTAssertEqual(api.responses, 0)

        let returnFromBackground = UUID()
        XCTAssertTrue(store.noteInvalidation(invitation: nil, foregroundReturn: returnFromBackground))
        await store.refreshAfterInvalidation()
        XCTAssertFalse(store.noteInvalidation(invitation: nil, foregroundReturn: returnFromBackground))
        XCTAssertEqual(api.listReads, 3)
    }

    func testInvalidationFailureKeepsSnapshotAndARefreshOnlyReads() async throws {
        let (store, api, session, invitation) = try await context()
        await store.load()
        api.listFailure = IPhoneTripRequestError.unavailable
        await store.refreshAfterInvalidation()
        XCTAssertEqual(store.value?.invitations, [invitation])
        XCTAssertNotNil(store.errorMessage)
        api.listFailure = nil
        api.page = .init(trips: [], invitations: [])
        await store.load()
        XCTAssertEqual(store.value?.invitations, [])
        XCTAssertNil(store.errorMessage)
        await session.signOut()
        await store.refreshAfterInvalidation()
        XCTAssertNil(store.value)
        XCTAssertEqual(api.listReads, 3)
        XCTAssertEqual(api.responses, 0)
    }

    func testActualAccountListAndAcceptAlwaysShareAndRefreshOnce() async throws {
        let (store, api, _, invitation) = try await context()
        await store.load()
        XCTAssertEqual(store.value?.invitations.map(\.id), [invitation.id])
        try await store.respond(invitation, accept: true, locationConsent: false)
        XCTAssertEqual(api.receivedConsent, true)
        XCTAssertEqual(api.responses, 1)
        XCTAssertEqual(api.listReads, 2)
        XCTAssertTrue(store.value?.invitations.isEmpty == true)
        XCTAssertFalse(store.needsRefresh)
    }

    func testDeclineNeverSendsLocationConsentAndConcurrentReplyIsRejected() async throws {
        let (store, api, _, invitation) = try await context()
        await store.load()
        api.pauseResponse = true
        let reply = Task { try await store.respond(invitation, accept: false, locationConsent: true) }
        for _ in 0..<1000 where api.responseContinuation == nil { await Task.yield() }
        let continuation = try XCTUnwrap(api.responseContinuation)
        do { try await store.respond(invitation, accept: true, locationConsent: true); XCTFail("Concurrent response accepted") }
        catch { XCTAssertEqual(error as? TripPreparationError, .busy) }
        continuation.resume()
        try await reply.value
        XCTAssertEqual(api.responses, 1)
        XCTAssertEqual(api.receivedConsent, false)
    }

    func testConfirmedReplyWithOfflineReloadIsNotResubmitted() async throws {
        let (store, api, _, invitation) = try await context()
        await store.load()
        api.listFailure = IPhoneTripRequestError.unavailable
        try await store.respond(invitation, accept: true, locationConsent: false)
        XCTAssertTrue(store.needsRefresh)
        XCTAssertTrue(store.value?.invitations.isEmpty == true)
        XCTAssertEqual(api.responses, 1)
        do { try await store.respond(invitation, accept: true, locationConsent: false); XCTFail("Saved response resubmitted") }
        catch { XCTAssertEqual(error as? TripPreparationError, .refreshRequired) }
        api.listFailure = nil
        await store.load()
        XCTAssertFalse(store.needsRefresh)
        XCTAssertEqual(api.responses, 1)
        XCTAssertEqual(api.listReads, 3)
    }

    func testClosedInvitationConflictReloadsOnlyListAndPreservesOriginalFailure() async throws {
        let (store, api, _, invitation) = try await context()
        await store.load()
        XCTAssertEqual(store.value?.invitations.map(\.id), [invitation.id])
        let conflict = IPhoneTripRequestError.routeConflict("TRIP_STATE_CONFLICT")
        api.failure = conflict
        api.page.invitations = []
        do {
            try await store.respond(invitation, accept: true, locationConsent: false)
            XCTFail("Closed invitation was accepted")
        } catch IPhoneTripRequestError.routeConflict(let code) {
            XCTAssertEqual(code, "TRIP_STATE_CONFLICT")
        } catch { XCTFail("Unexpected invitation response error: \(error)") }
        XCTAssertEqual(api.responses, 1, "Never retry a failed acceptance POST")
        XCTAssertEqual(api.listReads, 2, "Read the authoritative list exactly once after the conflict")
        XCTAssertTrue(store.value?.invitations.isEmpty == true)
        XCTAssertFalse(store.needsRefresh)
        XCTAssertEqual(store.errorMessage, tripPreparationErrorMessage(conflict))
        do {
            try await store.respond(invitation, accept: true, locationConsent: false)
            XCTFail("Removed invitation was accepted again")
        } catch IPhoneTripRequestError.missing { }
        catch { XCTFail("Unexpected removed invitation error: \(error)") }
        XCTAssertEqual(api.responses, 1)
        XCTAssertEqual(api.listReads, 2)
    }

    func testClosedInvitationConflictWithOfflineReloadRequiresManualRefreshBeforeAnotherWrite() async throws {
        let (store, api, _, invitation) = try await context()
        await store.load()
        let conflict = IPhoneTripRequestError.routeConflict("TRIP_STATE_CONFLICT")
        api.failure = conflict
        api.listFailure = IPhoneTripRequestError.unavailable
        do {
            try await store.respond(invitation, accept: true, locationConsent: false)
            XCTFail("Closed invitation was accepted")
        } catch IPhoneTripRequestError.routeConflict(let code) {
            XCTAssertEqual(code, "TRIP_STATE_CONFLICT")
        } catch { XCTFail("Unexpected invitation response error: \(error)") }
        XCTAssertEqual(api.responses, 1)
        XCTAssertEqual(api.listReads, 2)
        XCTAssertEqual(store.value?.invitations.map(\.id), [invitation.id], "Offline refresh must preserve the last loaded list")
        XCTAssertTrue(store.needsRefresh)
        do {
            try await store.respond(invitation, accept: true, locationConsent: false)
            XCTFail("A stale invitation was resubmitted without manual refresh")
        } catch { XCTAssertEqual(error as? TripPreparationError, .refreshRequired) }
        XCTAssertEqual(api.responses, 1)
        XCTAssertEqual(api.listReads, 2)
        api.listFailure = nil
        api.page.invitations = []
        await store.load()
        XCTAssertEqual(api.listReads, 3)
        XCTAssertTrue(store.value?.invitations.isEmpty == true)
        XCTAssertFalse(store.needsRefresh)
        XCTAssertEqual(api.responses, 1)
    }

    func testDeclineWithGenericConflictReloadsOnlyListAndDoesNotSendLocationConsent() async throws {
        let (store, api, _, invitation) = try await context()
        await store.load()
        api.failure = IPhoneTripRequestError.conflict
        api.page.invitations = []
        do {
            try await store.respond(invitation, accept: false, locationConsent: true)
            XCTFail("Conflicting decline was accepted")
        } catch IPhoneTripRequestError.conflict { }
        catch { XCTFail("Unexpected decline error: \(error)") }
        XCTAssertEqual(api.receivedConsent, false)
        XCTAssertEqual(api.responses, 1)
        XCTAssertEqual(api.listReads, 2)
        XCTAssertTrue(store.value?.invitations.isEmpty == true)
        XCTAssertFalse(store.needsRefresh)
        XCTAssertEqual(store.errorMessage, tripPreparationErrorMessage(IPhoneTripRequestError.conflict))
    }

    func testConflictReloadWithLostReadAccessClearsProtectedCacheAndKeepsOriginalFailure() async throws {
        let (store, api, session, invitation) = try await context()
        await store.load()
        api.failure = IPhoneTripRequestError.routeConflict("TRIP_STATE_CONFLICT")
        api.listFailure = IPhoneSessionError.forbidden
        do {
            try await store.respond(invitation, accept: true, locationConsent: false)
            XCTFail("Closed invitation was accepted")
        } catch IPhoneTripRequestError.routeConflict(let code) {
            XCTAssertEqual(code, "TRIP_STATE_CONFLICT")
        } catch { XCTFail("Unexpected invitation response error: \(error)") }
        XCTAssertEqual(api.responses, 1)
        XCTAssertEqual(api.listReads, 2)
        XCTAssertNil(store.value)
        XCTAssertTrue(store.needsRefresh)
        XCTAssertEqual(session.phase, .signedIn)
    }

    func testReselectingTripsTabRereadsShownListButLeavesFailedEmptyListToRetry() async throws {
        let (store, api, _, invitation) = try await context()
        api.page = .init(trips: [], invitations: [])
        await store.reloadOnSelection(invalidated: false)
        XCTAssertEqual(api.listReads, 1)
        XCTAssertEqual(store.value?.invitations.count, 0)
        api.page = .init(trips: [], invitations: [invitation])
        await store.reloadOnSelection(invalidated: false)
        XCTAssertEqual(api.listReads, 2)
        XCTAssertEqual(store.value?.invitations.map(\.id), [invitation.id])
        api.listFailure = IPhoneSessionError.forbidden
        await store.load()
        XCTAssertNil(store.value)
        await store.reloadOnSelection(invalidated: false)
        XCTAssertEqual(api.listReads, 3)
    }

    func testPermissionLossClearsOldListAndLogoutDiscardsLateRead() async throws {
        let (store, api, session, _) = try await context()
        await store.load()
        XCTAssertNotNil(store.value)
        api.listFailure = IPhoneSessionError.forbidden
        await store.load()
        XCTAssertNil(store.value)
        XCTAssertEqual(session.phase, .signedIn)
        api.listFailure = nil
        api.pauseList = true
        let read = Task { await store.load() }
        for _ in 0..<1000 where api.listContinuation == nil { await Task.yield() }
        let continuation = try XCTUnwrap(api.listContinuation)
        await session.signOut()
        continuation.resume(returning: api.page)
        _ = await read.value
        XCTAssertNil(store.value)
    }

    private func context() async throws -> (TripsAccountStore, FeatureTripAPI, SessionManager, IPhoneTripInvitation) {
        let preview = try XCTUnwrap(TripPreviewData.myTrips.first { $0.id == "yangpyeong" })
        let sample = TripPreparationPreviewAPI(preview: preview)
        let detail = try await sample.detail(sample.tripID, token: "")
        let session = SessionManager(api: FeatureAuth(accountID: try XCTUnwrap(detail.me).id), credentials: FeatureCredential())
        await session.restore()
        let invitation = IPhoneTripInvitation(tripId: String(repeating: "f", count: 32), title: "받은 초대", ownerName: "방장")
        let api = FeatureTripAPI(value: detail)
        api.page = .init(trips: [], invitations: [invitation])
        return (TripsAccountStore(session: session, api: api), api, session, invitation)
    }
}

@MainActor
private final class FeatureActivityAPI: IPhoneTripActivityServing {
    var signalValues: [IPhoneTripSignal] = []
    var remoteValues: [IPhoneTripRemote] = []
    var page = IPhoneTripCandidatePage(basis: "route", partial: false, candidates: [])
    var requestedFacilities: Set<TripSignalFacility> = []
    var signalReads = 0, votes = 0, commands = 0, sends = 0
    var commandIDs: [String] = [], commandSeats: [String] = []
    var failedCommandNumber: Int?
    var commandStage = "queued"
    var afterCommand: (() async -> Void)?
    var failure: Error?, afterSendFailure: Error?
    var pauseVote = false
    var pauseSignals = false
    var signalContinuation: CheckedContinuation<[IPhoneTripSignal], Never>?
    var voteFailure: Error?
    var voteContinuation: CheckedContinuation<Bool, Never>?
    func signals(_ tripID: String, token: String) async throws -> [IPhoneTripSignal] {
        signalReads += 1
        if let failure { throw failure }
        if pauseSignals { return await withCheckedContinuation { signalContinuation = $0 } }
        return signalValues
    }
    func candidates(_ tripID: String, reason: TripSignalReason, facilities: Set<TripSignalFacility>, location: TripSignalLocation.Point,
                    destination: IPhoneTripCourseStop?, token: String) async throws -> IPhoneTripCandidatePage { requestedFacilities = facilities; return page }
    var sentID = String(repeating: "e", count: 32)
    func send(_ tripID: String, reason: TripSignalReason, destination: IPhoneTripSignalDestination?, token: String) async throws -> String {
        sends += 1
        if let failure { throw failure }
        if let afterSendFailure { failure = afterSendFailure }
        return sentID
    }
    func vote(_ tripID: String, signalID: String, agree: Bool, token: String) async throws -> Bool {
        votes += 1
        if let voteFailure { throw voteFailure }
        if pauseVote { return await withCheckedContinuation { voteContinuation = $0 } }
        return false
    }
    func finish(_ tripID: String, signalID: String, cancelled: Bool, token: String) async throws { if let failure { throw failure } }
    func remotes(_ tripID: String, token: String) async throws -> [IPhoneTripRemote] { if let failure { throw failure }; return remoteValues }
    func command(_ tripID: String, remote: IPhoneTripRemote, action: IPhoneTripRemote.Action, seat: String, value: Any, token: String) async throws -> IPhoneTripRemoteReceipt {
        commands += 1
        commandIDs.append(action.id)
        commandSeats.append(seat)
        if let failure { throw failure }
        if failedCommandNumber == commands { throw IPhoneTripRequestError.unavailable }
        await afterCommand?()
        return .init(id: String(repeating: "f", count: 32), stage: commandStage, physicalExecutionVerified: false)
    }
}

private final class FeatureAuth: IPhoneSessionServing {
    let accountID: String
    let scopes: Set<String>
    init(accountID: String, scopes: Set<String> = ["account:read", "trips:read", "trips:manage"]) { self.accountID = accountID; self.scopes = scopes }
    func restore(token: String) async throws -> AccountSession { .init(accountID: accountID, displayName: "시험 계정", expiresAt: .now.addingTimeInterval(3600), scopes: scopes) }
    func beginLogin() async throws -> IPhoneLoginAttempt { throw IPhoneSessionError.unavailable }
    func exchange(_ attempt: IPhoneLoginAttempt, callbackURL: URL) async throws -> IPhoneSessionReceipt { throw IPhoneSessionError.unavailable }
    func cancel(_ attempt: IPhoneLoginAttempt) async throws { }
    func logout(token: String) async throws { }
}

@MainActor
private final class FeatureCredential: IPhoneCredentialStoring {
    private var value: StoredIPhoneCredential? = .init(token: String(repeating: "F", count: 43), logoutPending: false)
    func load() throws -> StoredIPhoneCredential? { value }
    func saveToken(_ token: String) throws { value = .init(token: token, logoutPending: false) }
    func markLogoutPending() throws { value = value.map { .init(token: $0.token, logoutPending: true) } }
    func clearToken() throws { value = nil }
}
