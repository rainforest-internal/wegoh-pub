import Foundation
import XCTest
@testable import WegoH

@MainActor
final class TripPreparationStoreTests: XCTestCase {
    func testOwnerCanStartWithTheirCarAndCourseWhileAnotherMemberIsUnassigned() async throws {
        let preview = TripPreview(id: "owner-ready", title: "출발 준비", state: .planned, dateLabel: "날짜 미정",
            ownerName: "사용자E", members: ["사용자E", "사용자A"], cars: [], summary: "샘플", stops: [])
        let store = TripPreparationStore(preview: preview)
        await store.load()
        XCTAssertEqual(store.detail?.members.map(\.readiness), [.needsCar, .needsCar])
        try await store.createCar(name: "사용자E의 차", seats: 2)
        try await store.addCourse(packID: try XCTUnwrap(store.previewAvailableCourses.first).id)
        XCTAssertEqual(store.detail?.unassigned.map(\.name), ["사용자A"])
        XCTAssertEqual(store.detail?.members.map { "\($0.name):\($0.readiness.rawValue)" }, ["사용자E:ready", "사용자A:needsCar"])
        try await store.start()
        XCTAssertEqual(store.detail?.state, .active)
    }

    func testInitialPreviewCreatesOnlyOneDriverGroupAndStartsLocally() async throws {
        let preview = initialPreview()
        let store = TripPreparationStore(preview: preview)
        await store.load()
        XCTAssertTrue(store.isPreview)
        XCTAssertEqual(store.previewActorName, "사용자E")
        XCTAssertEqual(store.detail?.members.count, 1)
        XCTAssertEqual(store.detail?.unassigned.count, 1)
        await store.loadVehicles()
        XCTAssertEqual(store.vehicles, [ProfileVehicle(profile:
            .init(deviceId: "preview-vehicle", plateNumber: "123가4567", name: "샘플 차량", defaultName: "샘플 차량", revision: 0))])
        try await store.createCar(name: "사용자E의 차", seats: 3)
        XCTAssertEqual(store.detail?.cars.count, 1)
        XCTAssertEqual(store.detail?.myCar?.seats, 3)
        XCTAssertTrue(store.detail?.myCar?.isMine == true)
        XCTAssertEqual(store.detail?.unassigned.count, 0)
        let created = try XCTUnwrap(store.detail)
        do { try await store.createCar(name: "두 번째 차", seats: 1); XCTFail("Second driver group accepted") }
        catch { XCTAssertEqual(error as? TripPreparationError, .alreadyDriving) }
        XCTAssertEqual(store.detail, created)
        let course = try XCTUnwrap(store.previewAvailableCourses.first)
        try await store.addCourse(packID: course.packId)
        try await store.start()
        XCTAssertEqual(store.detail?.state, .active)
        XCTAssertTrue(preview.state == .planned)
        XCTAssertTrue(preview.cars.isEmpty)
        let fresh = TripPreparationStore(preview: preview)
        await fresh.load()
        XCTAssertEqual(fresh.detail?.state, .planned)
        XCTAssertTrue(fresh.detail?.cars.isEmpty == true)
    }

    func testSwitchAndLeaveMoveOnlyTheActorAndKeepOriginalPreviewUntouched() async throws {
        let preview = try XCTUnwrap(TripPreviewData.myTrips.first { $0.id == "gapyeong" })
        let store = TripPreparationStore(preview: preview)
        await store.load()
        let original = try XCTUnwrap(store.detail)
        let actor = try XCTUnwrap(original.me)
        XCTAssertEqual(actor.name, "사용자D")
        let target = try XCTUnwrap(original.cars.first { $0.driverName == "사용자B" })
        try await store.ride(carID: target.id)
        let moved = try XCTUnwrap(store.detail)
        XCTAssertEqual(moved.me?.carId, target.id)
        XCTAssertEqual(moved.cars.flatMap(\.passengers).filter { $0.id == actor.id }.count, 1)
        XCTAssertEqual(moved.members.count, original.members.count)
        try await store.leaveCar()
        XCTAssertNil(store.detail?.me?.carId)
        XCTAssertEqual(store.detail?.unassigned.filter { $0.id == actor.id }.count, 1)
        XCTAssertEqual(store.detail?.members.count, preview.members.count)
        let fresh = TripPreparationStore(preview: preview)
        await fresh.load()
        XCTAssertEqual(fresh.detail, original)
        XCTAssertEqual(TripPreviewData.myTrips.first { $0.id == "gapyeong" }?.preparation?.cars[1].members,
                       ["사용자A", "사용자D", "사용자E"])
    }

    func testPassengerCreatesCarAtomicallyAndDriverCannotRideOrLeaveAnotherGroup() async throws {
        let preview = try XCTUnwrap(TripPreviewData.myTrips.first { $0.id == "yangpyeong" })
        let store = TripPreparationStore(preview: preview)
        await store.load()
        let original = try XCTUnwrap(store.detail)
        let previousCar = try XCTUnwrap(original.myCar)
        let actor = try XCTUnwrap(original.me)
        try await store.createCar(name: "사용자A의 차", seats: 2)
        let created = try XCTUnwrap(store.detail)
        XCTAssertTrue(created.myCar?.isMine == true)
        XCTAssertFalse(created.cars.first { $0.id == previousCar.id }?.passengers.contains { $0.id == actor.id } ?? true)
        XCTAssertEqual(created.members.count, original.members.count)
        do { try await store.ride(carID: previousCar.id); XCTFail("Driver joined a different car") }
        catch { XCTAssertEqual(error as? TripPreparationError, .driverCannotRide) }
        do { try await store.leaveCar(); XCTFail("Driver silently left their group") }
        catch { XCTAssertEqual(error as? TripPreparationError, .driverCannotRide) }
        XCTAssertEqual(store.detail, created)
        XCTAssertEqual(preview.preparation?.cars.count, 1)
    }

    func testFullCarRejectsRideWithoutRemovingThePreviousAssignment() async throws {
        let preview = TripPreview(id: "full-test", title: "만차 시험", state: .planned, dateLabel: "날짜 미정",
            ownerName: "사용자E", members: ["사용자E", "사용자A", "사용자D", "사용자B"], cars: ["사용자A의 차", "사용자D의 차"],
            summary: "샘플", stops: [], preparation: .init(invitationCount: 3, acceptedInvitationCount: 3,
                selectedCarID: "user-f", allMembersAssigned: true, pickupName: nil, dropoffName: nil,
                cars: [.init(id: "user-f", title: "사용자A의 차", driverName: "사용자A", members: ["사용자A", "사용자E"], passengerCapacity: 2),
                       .init(id: "user-i", title: "사용자D의 차", driverName: "사용자D", members: ["사용자D", "사용자B"], passengerCapacity: 1)], courses: []))
        let store = TripPreparationStore(preview: preview)
        await store.load()
        let original = try XCTUnwrap(store.detail)
        let full = try XCTUnwrap(original.cars.first { $0.driverName == "사용자D" })
        do { try await store.ride(carID: full.id); XCTFail("Full car accepted passenger") }
        catch { XCTAssertEqual(error as? TripPreparationError, .full) }
        XCTAssertEqual(store.detail, original)
        XCTAssertTrue(store.errorMessage?.contains("만석") == true)
    }

    func testAbsentPreviewActorDoesNotInventAMemberAndUnsupportedInviteDoesNotSucceed() async throws {
        let preview = TripPreview(id: "no-actor", title: "명시 사용자 시험", state: .planned, dateLabel: "날짜 미정",
            ownerName: "사용자D", members: ["사용자D"], cars: [], summary: "샘플", stops: [])
        let missing = TripPreparationStore(preview: preview)
        await missing.load()
        XCTAssertNil(missing.detail)
        XCTAssertTrue(missing.errorMessage?.contains("미리보기 사용자") == true)
        let explicit = TripPreparationStore(preview: preview, actorName: "사용자D")
        await explicit.load()
        let original = try XCTUnwrap(explicit.detail)
        XCTAssertEqual(original.members.count, 1)
        do { try await explicit.invite(accountID: "team-" + String(repeating: "b", count: 40)); XCTFail("Unsupported invite accepted") }
        catch { XCTAssertEqual(error as? TripPreparationError, .previewUnsupported) }
        XCTAssertEqual(explicit.detail, original)
    }

    func testPreviewPickupUsesOnlyCurrentCarAndValidatesPlaceLimits() async throws {
        let store = TripPreparationStore(preview: initialPreview())
        await store.load()
        try await store.createCar(name: "사용자E의 차", seats: 2)
        let carID = try XCTUnwrap(store.detail?.myCar?.id)
        try await store.addCarPlace(carID: carID, kind: .pickup, name: "만나는 곳", lat: 37.5, lng: 127)
        let place = try XCTUnwrap(store.detail?.myCar?.places.first)
        XCTAssertEqual(place.name, "만나는 곳")
        XCTAssertTrue(place.isValid)
        let original = try XCTUnwrap(store.detail)
        do {
            try await store.addCarPlace(carID: carID, kind: .pickup, name: String(repeating: "가", count: 41), lat: 37.5, lng: 127)
            XCTFail("Overlong place accepted")
        } catch IPhoneResourceError.invalidInput { }
        XCTAssertEqual(store.detail, original)
        try await store.removeCarPlace(carID: carID, placeID: try XCTUnwrap(place.id))
        XCTAssertTrue(store.detail?.myCar?.places.isEmpty == true)
    }

    func testWriteRetainsDetailRefetchesOnceAndRejectsDuplicateWrites() async throws {
        let (store, api, auth, _) = try await realStore()
        await store.load()
        let original = try XCTUnwrap(store.detail)
        api.holdWrite = true
        let write = Task { try await store.ride(carID: String(repeating: "a", count: 32)) }
        while api.pendingWrite == nil { await Task.yield() }
        XCTAssertTrue(store.busy)
        XCTAssertFalse(store.loading)
        XCTAssertEqual(store.detail, original)
        do { try await store.leaveCar(); XCTFail("Duplicate write accepted") }
        catch { XCTAssertEqual(error as? TripPreparationError, .busy) }
        api.pendingWrite?.resume()
        api.pendingWrite = nil
        try await write.value
        XCTAssertEqual(api.readCount, 2)
        XCTAssertEqual(api.writeCount, 1)
        XCTAssertEqual(auth.restoreCount, 1)
        XCTAssertFalse(store.busy)
    }

    func testListSynchronizationOnlyFollowsSuccessfulMutationsEvenWhenDetailRefreshFails() async throws {
        var synchronizations = 0
        weak var observedStore: TripPreparationStore?
        let (store, api, _, _) = try await realStore(onMutation: {
            synchronizations += 1
            XCTAssertEqual(observedStore?.busy, true)
            XCTAssertEqual(observedStore?.needsRefresh, false, "A saved change is being reconciled; retry is premature")
        })
        observedStore = store
        await store.load()
        await store.refreshVisibleState()
        XCTAssertEqual(synchronizations, 0, "Reading a detail must not refresh the cached list")
        api.failure = IPhoneTripRequestError.unavailable
        do { try await store.start(); XCTFail("Failed mutation was accepted") }
        catch IPhoneTripRequestError.unavailable { }
        XCTAssertEqual(synchronizations, 0)
        api.failure = nil
        try await store.start()
        XCTAssertEqual(synchronizations, 1)
        api.readFailure = IPhoneTripRequestError.unavailable
        try await store.leaveCar()
        XCTAssertTrue(store.needsRefresh)
        XCTAssertEqual(synchronizations, 2, "A saved change must synchronize the list even if its detail refresh fails")
        api.readFailure = nil
        await store.load()
        XCTAssertEqual(synchronizations, 2, "Retrying a detail read must not repeat list synchronization")
    }

    func testSavedMutationWithFailedRefreshReturnsSuccessAndRetryOnlyReads() async throws {
        let (store, api, _, _) = try await realStore()
        await store.load()
        let original = try XCTUnwrap(store.detail)
        api.readFailure = IPhoneTripRequestError.unavailable
        try await store.addCarPlace(carID: String(repeating: "a", count: 32), kind: .pickup,
                                    name: "저장된 픽업", lat: 37.5, lng: 127)
        XCTAssertEqual(api.writeCount, 1)
        XCTAssertEqual(api.readCount, 2)
        XCTAssertEqual(store.detail, original)
        XCTAssertTrue(store.needsRefresh)
        XCTAssertFalse(store.busy)
        XCTAssertFalse(store.loading)
        XCTAssertEqual(store.errorMessage, "변경은 저장했지만 최신 정보를 불러오지 못했어요. 다시 불러와 주세요.")
        do {
            try await store.addCarPlace(carID: String(repeating: "a", count: 32), kind: .pickup,
                                        name: "중복 픽업", lat: 37.5, lng: 127)
            XCTFail("A new mutation was accepted before refreshing saved state")
        } catch { XCTAssertEqual(error as? TripPreparationError, .refreshRequired) }
        XCTAssertEqual(api.writeCount, 1)
        api.readFailure = nil
        await store.load()
        XCTAssertEqual(api.readCount, 3)
        XCTAssertEqual(api.writeCount, 1)
        XCTAssertFalse(store.needsRefresh)
        XCTAssertNil(store.errorMessage)
    }

    func testPreviewProjectsOldCarPlacesAfterMovingLeavingAndCreatingACar() async throws {
        let preview = try XCTUnwrap(TripPreviewData.myTrips.first { $0.id == "gapyeong" })
        let store = TripPreparationStore(preview: preview)
        await store.load()
        let oldCar = try XCTUnwrap(store.detail?.myCar)
        let nextCar = try XCTUnwrap(store.detail?.cars.first { $0.driverName == "사용자B" })
        try await store.addCarPlace(carID: oldCar.id, kind: .pickup, name: "사용자A 차 픽업", lat: 37.5, lng: 127)
        let privatePlace = try XCTUnwrap(store.detail?.myCar?.places.first)
        XCTAssertNotNil(privatePlace.id)
        try await store.ride(carID: nextCar.id)
        var detail = try XCTUnwrap(store.detail)
        XCTAssertTrue(detail.isValid)
        XCTAssertEqual(detail.myCar?.id, nextCar.id)
        try checkHiddenPlace(detail, carID: oldCar.id)
        try await store.leaveCar()
        detail = try XCTUnwrap(store.detail)
        XCTAssertTrue(detail.isValid)
        XCTAssertNil(detail.myCar)
        try checkHiddenPlace(detail, carID: oldCar.id)
        try await store.ride(carID: oldCar.id)
        XCTAssertEqual(store.detail?.myCar?.places.first, privatePlace)
        try await store.createCar(name: "사용자D의 차", seats: 3)
        detail = try XCTUnwrap(store.detail)
        XCTAssertTrue(detail.isValid)
        XCTAssertTrue(detail.myCar?.isMine == true)
        XCTAssertEqual(detail.members.count, preview.memberCount)
        try checkHiddenPlace(detail, carID: oldCar.id)
    }

    func testLogoutDiscardsLateWriteAndPermissionFailureKeepsSessionButClearsProtectedData() async throws {
        let (store, api, _, session) = try await realStore()
        await store.load()
        let original = try XCTUnwrap(store.detail)
        api.failure = IPhoneSessionError.forbidden
        do { try await store.leaveCar(); XCTFail("Forbidden write accepted") }
        catch IPhoneSessionError.forbidden { }
        XCTAssertNil(store.detail)
        XCTAssertTrue(store.vehicles.isEmpty)
        XCTAssertTrue(store.needsRefresh)
        XCTAssertEqual(session.phase, .signedIn)
        XCTAssertTrue(store.errorMessage?.contains("권한") == true)
        api.failure = nil
        await store.load()
        XCTAssertEqual(store.detail, original)
        XCTAssertFalse(store.needsRefresh)
        api.holdWrite = true
        let write = Task { try await store.leaveCar() }
        while api.pendingWrite == nil { await Task.yield() }
        await session.signOut()
        api.pendingWrite?.resume()
        api.pendingWrite = nil
        do { try await write.value; XCTFail("Late write result survived logout") }
        catch is CancellationError { }
        XCTAssertEqual(api.readCount, 2)
        XCTAssertNil(store.detail)
        XCTAssertTrue(store.vehicles.isEmpty)
        XCTAssertTrue(store.needsRefresh)
        XCTAssertNotNil(store.errorMessage)
    }

    func testPostMutationMissingClearsCacheAndMissingReadAlsoHidesOldDetail() async throws {
        let (store, api, _, session) = try await realStore()
        await store.load()
        XCTAssertNotNil(store.detail)
        api.readFailure = IPhoneTripRequestError.missing
        try await store.leaveCar()
        XCTAssertEqual(api.writeCount, 1)
        XCTAssertNil(store.detail)
        XCTAssertTrue(store.vehicles.isEmpty)
        XCTAssertTrue(store.needsRefresh)
        XCTAssertEqual(session.phase, .signedIn)
        api.readFailure = nil
        await store.load()
        XCTAssertNotNil(store.detail)
        api.readFailure = IPhoneResourceError.missing
        await store.load()
        XCTAssertNil(store.detail)
        XCTAssertTrue(store.needsRefresh)
        XCTAssertEqual(api.writeCount, 1)
    }

    func testDisplayNameRefreshUsesCurrentSessionForReadsAndWritesWithoutRestoring() async throws {
        let (store, api, auth, session) = try await realStore()
        await store.load()
        let account = try XCTUnwrap(session.current)
        session.updateDisplayName("바꾼 이름", for: account)
        await store.load()
        try await store.leaveCar()
        XCTAssertEqual(api.readCount, 3)
        XCTAssertEqual(api.writeCount, 1)
        XCTAssertEqual(auth.restoreCount, 1)
        XCTAssertEqual(session.current?.displayName, "바꾼 이름")
        XCTAssertTrue(store.accountIsCurrent)
        XCTAssertNotNil(store.detail)
    }

    func testPreviewAtomicMyPlacesSelectsBothOrKeepsPreviousSelectionOnFailure() async throws {
        let preview = try XCTUnwrap(TripPreviewData.myTrips.first { $0.id == "yangpyeong" })
        let store = TripPreparationStore(preview: preview)
        await store.load()
        var detail = try XCTUnwrap(store.detail)
        XCTAssertTrue(detail.myCar?.iRide == true)
        let draft = IPhoneTripMyPlacesDraft(revision: detail.revision,
            pickup: .new(name: "서울역", lat: 37.55, lng: 126.97), drop: nil, dropAtPickup: true)
        try await store.saveMyPlaces(draft)
        detail = try XCTUnwrap(store.detail)
        let car = try XCTUnwrap(detail.myCar), me = try XCTUnwrap(detail.me)
        let selected = car.places.filter { $0.selectedBy?.contains(me.id) == true }
        XCTAssertEqual(Set(selected.compactMap { $0.kind?.rawValue }), ["pickup", "drop"])
        XCTAssertEqual(Set(selected.compactMap(\.lat)), [37.55])
        XCTAssertEqual(Set(selected.compactMap(\.lng)), [126.97])
        let original = detail
        do {
            try await store.saveMyPlaces(.init(revision: detail.revision,
                pickup: .new(name: "새 픽업", lat: 37.6, lng: 127),
                drop: .existing(String(repeating: "f", count: 32)), dropAtPickup: false))
            XCTFail("Missing drop accepted")
        } catch IPhoneTripRequestError.missing { }
        XCTAssertNil(store.detail)
        XCTAssertTrue(store.needsRefresh)
        await store.load()
        XCTAssertFalse(store.needsRefresh)
        XCTAssertEqual(store.detail, original)
        try await store.saveMyPlaces(draft)
        XCTAssertEqual(store.detail, original)
        var stale = draft
        stale.pickup = .new(name: "다른 픽업", lat: 37.6, lng: 127)
        do { try await store.saveMyPlaces(stale); XCTFail("Stale selection overwritten") }
        catch IPhoneTripRequestError.routeConflict(let code) { XCTAssertEqual(code, "TRIP_PLACE_SELECTION_CHANGED") }
        XCTAssertEqual(store.detail, original)
    }

    func testMyPlacesRefetchesOnceBlocksConcurrentSaveAndDoesNotResubmitAfterRefreshFailure() async throws {
        let preview = try XCTUnwrap(TripPreviewData.myTrips.first { $0.id == "yangpyeong" })
        let (store, api, _, _) = try await realStore(preview: preview)
        await store.load()
        let detail = try XCTUnwrap(store.detail)
        let draft = IPhoneTripMyPlacesDraft(revision: detail.revision, pickup: nil, drop: nil, dropAtPickup: false)
        api.holdWrite = true
        let save = Task { try await store.saveMyPlaces(draft) }
        while api.pendingWrite == nil { await Task.yield() }
        do { try await store.saveMyPlaces(draft); XCTFail("Duplicate save accepted") }
        catch { XCTAssertEqual(error as? TripPreparationError, .busy) }
        api.readFailure = IPhoneTripRequestError.unavailable
        api.pendingWrite?.resume(); api.pendingWrite = nil
        try await save.value
        XCTAssertEqual(api.savedDraft, draft)
        XCTAssertEqual(api.writeCount, 1)
        XCTAssertEqual(api.readCount, 2)
        XCTAssertTrue(store.needsRefresh)
        XCTAssertEqual(store.detail, detail)
        do { try await store.saveMyPlaces(draft); XCTFail("Saved selection resubmitted") }
        catch { XCTAssertEqual(error as? TripPreparationError, .refreshRequired) }
        XCTAssertEqual(api.writeCount, 1)
        api.readFailure = nil
        await store.load()
        XCTAssertEqual(api.writeCount, 1)
        XCTAssertFalse(store.needsRefresh)
    }

    func testMyPlacesPreservesLegacyActiveAllowsPreparationAndRejectsV2ActiveOrDriver() async throws {
        let preview = try XCTUnwrap(TripPreviewData.myTrips.first { $0.id == "yangpyeong" })
        let (store, api, _, _) = try await realStore(preview: preview)
        let draft = IPhoneTripMyPlacesDraft(revision: api.value.revision, pickup: nil, drop: nil, dropAtPickup: false)
        api.value.state = .active
        api.value.routeContractVersion = 1
        await store.load()
        try await store.saveMyPlaces(draft)
        XCTAssertEqual(api.writeCount, 1)
        api.value.routeContractVersion = 2
        await store.load()
        do { try await store.saveMyPlaces(draft); XCTFail("Active v2 modified") }
        catch IPhoneTripRequestError.routeConflict(let code) { XCTAssertEqual(code, "TRIP_ROUTE_PLAN_LOCKED") }
        XCTAssertEqual(api.writeCount, 1)
        api.value.state = .planned
        await store.load()
        try await store.saveMyPlaces(draft)
        XCTAssertEqual(api.writeCount, 2)
        let driver = TripPreparationStore(preview: initialPreview())
        await driver.load()
        try await driver.createCar(name: "운전자 차", seats: 2)
        let driverDetail = try XCTUnwrap(driver.detail)
        do {
            try await driver.saveMyPlaces(.init(revision: driverDetail.revision, pickup: nil, drop: nil, dropAtPickup: false))
            XCTFail("Driver saved rider choices")
        } catch IPhoneSessionError.forbidden { }
        XCTAssertEqual(driver.detail, driverDetail)
    }

    func testSelectionConflictRetainsDetailAndCapturedRevisionWithoutAutomaticRetry() async throws {
        let preview = try XCTUnwrap(TripPreviewData.myTrips.first { $0.id == "yangpyeong" })
        let (store, api, _, _) = try await realStore(preview: preview)
        await store.load()
        let original = try XCTUnwrap(store.detail)
        let draft = IPhoneTripMyPlacesDraft(revision: original.revision, pickup: nil, drop: nil, dropAtPickup: false)
        api.failure = IPhoneTripRequestError.routeConflict("TRIP_PLACE_SELECTION_CHANGED")
        do { try await store.saveMyPlaces(draft); XCTFail("Conflict accepted") }
        catch IPhoneTripRequestError.routeConflict(let code) { XCTAssertEqual(code, "TRIP_PLACE_SELECTION_CHANGED") }
        XCTAssertEqual(store.detail, original)
        XCTAssertEqual(api.savedDraft?.revision, original.revision)
        XCTAssertEqual(api.writeCount, 1)
        XCTAssertEqual(api.readCount, 1)
        XCTAssertTrue(store.errorMessage?.contains("승하차 선택") == true)
        XCTAssertFalse(store.needsRefresh)
    }

    func testOwnerReordersAllCoursesWithCapturedRevisionAndStaleOrderKeepsCurrentDetail() async throws {
        let store = TripPreparationStore(preview: initialPreview())
        await store.load()
        let options = Array(store.previewAvailableCourses.prefix(2))
        XCTAssertEqual(options.count, 2)
        for course in options { try await store.addCourse(packID: course.packId) }
        let original = try XCTUnwrap(store.detail)
        let reversed = Array(original.courses.map(\.packId).reversed())
        try await store.prioritizeCourses(packIDs: reversed, revision: original.revision)
        XCTAssertEqual(store.detail?.courses.map(\.packId), reversed)
        let saved = try XCTUnwrap(store.detail)
        do { try await store.prioritizeCourses(packIDs: options.map(\.packId), revision: original.revision); XCTFail("Stale order accepted") }
        catch IPhoneTripRequestError.routeConflict(let code) { XCTAssertEqual(code, "TRIP_REVISION_CONFLICT") }
        XCTAssertEqual(store.detail, saved)
    }

    func testExistingAcceptedTripEnablesSharingOnceAndKeepsTheServerValue() async throws {
        let (store, api, _, _) = try await realStore()
        api.value.locationConsent = false
        await store.load()
        XCTAssertEqual(api.sharingUpdates, [true])
        XCTAssertEqual(store.detail?.locationConsent, true)
        XCTAssertNil(store.errorMessage)
        await store.load()
        XCTAssertEqual(api.sharingUpdates, [true])
        XCTAssertEqual(api.readCount, 3)
    }

    func testFailedSharingUpdateDoesNotPretendItSucceededAndCanRetry() async throws {
        let (store, api, _, _) = try await realStore()
        api.value.locationConsent = false
        api.failure = IPhoneSessionError.unavailable
        await store.load()
        XCTAssertNil(store.detail)
        XCTAssertFalse(api.value.locationConsent)
        XCTAssertNotNil(store.errorMessage)
        api.failure = nil
        await store.load()
        XCTAssertEqual(store.detail?.locationConsent, true)
        XCTAssertEqual(api.sharingUpdates, [true])
    }

    func testCompletedTripDoesNotChangeHistoricalSharing() async throws {
        let (store, api, _, _) = try await realStore()
        api.value.locationConsent = false
        api.value.state = .completed
        await store.load()
        XCTAssertTrue(api.sharingUpdates.isEmpty)
        XCTAssertEqual(store.detail?.locationConsent, false)
    }

    private func initialPreview() -> TripPreview {
        TripPreview(id: "new-trip", title: "처음 준비하는 여행", state: .planned, dateLabel: "날짜 미정",
                    ownerName: "사용자E", members: ["사용자E"], cars: [], summary: "새 샘플 여행", stops: [])
    }

    private func checkHiddenPlace(_ detail: IPhoneTripDetail, carID: String) throws {
        let place = try XCTUnwrap(detail.cars.first { $0.id == carID }?.places.first)
        XCTAssertEqual(place.name, "사용자A 차 픽업")
        XCTAssertNil(place.id)
        XCTAssertNil(place.kind)
        XCTAssertNil(place.lat)
        XCTAssertNil(place.lng)
        XCTAssertNil(place.addedBy)
        XCTAssertNil(place.selectedBy)
        XCTAssertNil(place.createdAt)
    }

    private func realStore(preview custom: TripPreview? = nil, onMutation: (@MainActor () async -> Void)? = nil) async throws -> (TripPreparationStore, PreparationTestAPI, PreparationTestAuth, SessionManager) {
        let preview = TripPreparationPreviewAPI(preview: custom ?? initialPreview())
        let detail = try await preview.detail(preview.tripID, token: "")
        let auth = PreparationTestAuth(accountID: try XCTUnwrap(detail.me).id)
        let session = SessionManager(api: auth, credentials: PreparationTestCredential())
        await session.restore()
        let api = PreparationTestAPI(value: detail)
        return (TripPreparationStore(tripID: detail.id, session: session, api: api, onMutation: onMutation), api, auth, session)
    }
}

@MainActor
private final class PreparationTestAPI: IPhoneTripServing {
    var value: IPhoneTripDetail
    var savedDraft: IPhoneTripMyPlacesDraft?
    var readCount = 0
    var sharingUpdates: [Bool] = []
    var writeCount = 0
    var holdWrite = false
    var failure: Error?
    var readFailure: Error?
    var pendingWrite: CheckedContinuation<Void, Never>?
    init(value: IPhoneTripDetail) { self.value = value; self.value.locationConsent = true }
    func detail(_ tripID: String, token: String) async throws -> IPhoneTripDetail {
        readCount += 1
        if let readFailure { throw readFailure }
        return value
    }
    private func write() async throws {
        writeCount += 1
        if let failure { throw failure }
        if holdWrite { await withCheckedContinuation { pendingWrite = $0 } }
    }
    func list(token: String) async throws -> IPhoneTripList { throw IPhoneSessionError.unavailable }
    func create(_ draft: IPhoneTripDraft, token: String) async throws -> String { throw IPhoneSessionError.unavailable }
    func respond(_ tripID: String, accept: Bool, locationConsent: Bool, token: String) async throws { try await write() }
    func addMember(_ tripID: String, accountID: String, token: String) async throws { try await write() }
    func createCar(_ tripID: String, name: String, seats: Int, token: String) async throws -> String { try await write(); return String(repeating: "c", count: 32) }
    func ride(_ tripID: String, carID: String, token: String) async throws { try await write() }
    func leaveCar(_ tripID: String, token: String) async throws { try await write() }
    func addCourse(_ tripID: String, packID: String, token: String) async throws { try await write() }
    func saveMyPlaces(_ tripID: String, carID: String, draft: IPhoneTripMyPlacesDraft, token: String) async throws {
        savedDraft = draft
        try await write()
    }
    func prioritizeCourses(_ tripID: String, packIDs: [String], revision: Int, token: String) async throws { try await write() }
    func start(_ tripID: String, revision: Int, endActiveTrip: Bool, token: String) async throws { try await write() }
    func setLocationSharing(_ tripID: String, enabled: Bool, token: String) async throws {
        try await write()
        value.locationConsent = enabled
        sharingUpdates.append(enabled)
    }
    func addCarPlace(_ tripID: String, carID: String, kind: IPhoneTripPlaceKind, name: String, lat: Double, lng: Double, token: String) async throws -> String { try await write(); return String(repeating: "d", count: 32) }
    func removeCarPlace(_ tripID: String, carID: String, placeID: String, token: String) async throws { try await write() }
}

@MainActor
private final class PreparationTestCredential: IPhoneCredentialStoring {
    private var value: StoredIPhoneCredential? = .init(token: String(repeating: "F", count: 43), logoutPending: false)
    func load() throws -> StoredIPhoneCredential? { value }
    func saveToken(_ token: String) throws { value = .init(token: token, logoutPending: false) }
    func markLogoutPending() throws { value = value.map { .init(token: $0.token, logoutPending: true) } }
    func clearToken() throws { value = nil }
}

private final class PreparationTestAuth: IPhoneSessionServing {
    let accountID: String
    var restoreCount = 0
    init(accountID: String) { self.accountID = accountID }
    func restore(token: String) async throws -> AccountSession {
        restoreCount += 1
        return AccountSession(accountID: accountID, displayName: "실계정 시험", expiresAt: .now.addingTimeInterval(3600))
    }
    func beginLogin() async throws -> IPhoneLoginAttempt { throw IPhoneSessionError.unavailable }
    func exchange(_ attempt: IPhoneLoginAttempt, callbackURL: URL) async throws -> IPhoneSessionReceipt { throw IPhoneSessionError.unavailable }
    func cancel(_ attempt: IPhoneLoginAttempt) async throws { }
    func logout(token: String) async throws { }
}
