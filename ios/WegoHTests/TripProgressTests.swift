import XCTest
@testable import WegoH

@MainActor
final class TripProgressTests: XCTestCase {
    func testRemoteSummaryChoosesSubjectParticleFromOwnersFinalHangul() {
        let tail = " 허용한 조작 2개 · 차 버튼 대신 여기서 조절해요"
        XCTAssertEqual(tripRemoteSummary(ownerName: "사용자A", actionCount: 2), "사용자A이" + tail)
        XCTAssertEqual(tripRemoteSummary(ownerName: "나무", actionCount: 2), "나무가" + tail)
        XCTAssertEqual(tripRemoteSummary(ownerName: "바다", actionCount: 2), "바다가" + tail)
        XCTAssertEqual(tripRemoteSummary(ownerName: " 나무 ", actionCount: 2), "나무가" + tail)
        XCTAssertEqual(tripRemoteSummary(ownerName: "사용자A".decomposedStringWithCanonicalMapping, actionCount: 2), "사용자A이" + tail)
        XCTAssertEqual(tripRemoteSummary(ownerName: "Car", actionCount: 2), "Car님이" + tail)
    }

    func testRemotePermissionStartsOffAndRequiresAtLeastOneGroupWhenEnabled() {
        var preferences = TripRemotePreferences()
        XCTAssertFalse(preferences.enabled)
        XCTAssertTrue(preferences.allowedGroups.isEmpty)
        XCTAssertTrue(preferences.isValid)
        preferences.enabled = true
        XCTAssertEqual(preferences.actionCount, 10)
        XCTAssertFalse(preferences.allowedGroups.contains(.windows))
        preferences.groups = Set(TripRemoteGroup.allCases)
        XCTAssertEqual(preferences.actionCount, 11)
        preferences.groups.removeAll()
        XCTAssertFalse(preferences.isValid)
        preferences.enabled = false
        XCTAssertTrue(preferences.isValid)
        XCTAssertEqual(preferences.actionCount, 0)
    }

    func testDisabledServerPolicyKeepsDefaultGroupsForTheNextEnable() {
        var preferences = TripRemotePreferences(policy: .off)
        XCTAssertFalse(preferences.enabled)
        XCTAssertEqual(preferences.groups, [.climate, .lights, .seats])
        preferences.enabled = true
        XCTAssertTrue(preferences.isValid)
        XCTAssertEqual(preferences.actionCount, 10)
        XCTAssertEqual(TripRemotePreferences(policy: nil), TripRemotePreferences())
        let saved = TripRemotePreferences(policy: .init(enabled: true, actions: TripRemoteGroup.windows.actionIDs, deviceId: nil))
        XCTAssertEqual(saved.groups, [.windows])
    }

    func testVehicleChangeResetKeepsLastChoiceAndExplainsWhy() {
        let reset = TripRemotePreferences(policy: .init(enabled: false, actions: TripRemoteGroup.climate.actionIDs, deviceId: nil))
        XCTAssertFalse(reset.enabled)
        XCTAssertTrue(reset.disabledByVehicleChange)
        XCTAssertEqual(reset.groups, [.climate])
        XCTAssertEqual(reset.summary, tripRemoteVehicleChangeNotice)
        XCTAssertFalse(TripRemotePreferences(policy: .off).disabledByVehicleChange)
        var reenabled = reset
        reenabled.enabled = true
        XCTAssertEqual(reenabled.summary, "공조 · 조작 5개 허용")
    }

    func testRemotePolicySummaryListsAllowedGroupsInDisplayOrder() {
        XCTAssertEqual(TripRemotePreferences().summary, "아직 허용한 조작이 없어요")
        XCTAssertEqual(TripRemotePreferences(enabled: true, groups: []).summary, "아직 허용한 조작이 없어요")
        XCTAssertEqual(TripRemotePreferences(enabled: false, groups: Set(TripRemoteGroup.allCases)).summary, "아직 허용한 조작이 없어요")
        XCTAssertEqual(TripRemotePreferences(enabled: true, groups: [.seats, .climate]).summary, "공조·시트 · 조작 7개 허용")
        XCTAssertEqual(TripRemotePreferences(enabled: true, groups: Set(TripRemoteGroup.allCases)).summary, "공조·조명·창문·시트 · 조작 11개 허용")
    }

    func testPreviewCarRetainsExplicitRemoteChoicesWithoutChangingSourceSample() async throws {
        let trip = try XCTUnwrap(TripPreviewData.myTrips.first { $0.id == "new-trip" })
        let store = TripPreparationStore(preview: trip)
        await store.load()
        XCTAssertEqual(store.previewDateLabel, trip.dateLabel)
        let choice = TripRemotePreferences(enabled: true, groups: [.climate, .lights])
        try await store.createCar(name: "샘플 차", seats: 3, remote: choice)
        XCTAssertEqual(store.previewRemotePreferences, choice)
        XCTAssertEqual(store.detail?.myCar?.name, "샘플 차")
        let reopened = TripPreparationStore(preview: trip)
        await reopened.load()
        XCTAssertFalse(reopened.previewRemotePreferences.enabled)
        XCTAssertTrue(reopened.detail?.cars.isEmpty == true)
    }

    func testSignalRequiresPlaceStepAndAgreementBeforeInsertingARoute() {
        let signal = TripSignalPreviewStore()
        signal.send()
        XCTAssertEqual(signal.phase, .reason)
        signal.chooseReason(.restroom)
        signal.next()
        XCTAssertTrue(signal.canSend)
        signal.send()
        XCTAssertEqual(signal.phase, .waiting)
        XCTAssertNil(signal.insertedPlaceName)
        signal.begin()
        XCTAssertEqual(signal.phase, .waiting)
        signal.resolveSample(agreed: true)
        XCTAssertEqual(signal.phase, .agreed)
        XCTAssertEqual(signal.insertedPlaceName, "서산휴게소")
        signal.resolveSample(agreed: false)
        XCTAssertEqual(signal.phase, .agreed)
        signal.finish()
        XCTAssertEqual(signal.phase, .completed)
        XCTAssertEqual(signal.insertedPlaceName, "서산휴게소")
        signal.begin()
        XCTAssertEqual(signal.phase, .reason)
    }

    func testDeclinedOrCancelledSignalCannotBeChangedByALateResponse() {
        let signal = TripSignalPreviewStore()
        signal.showReceived()
        XCTAssertEqual(signal.phase, .received)
        signal.vote(agree: false)
        XCTAssertEqual(signal.phase, .declined)
        signal.vote(agree: true)
        signal.resolveSample(agreed: true)
        XCTAssertEqual(signal.phase, .declined)
        XCTAssertNil(signal.insertedPlaceName)
        signal.begin()
        signal.next()
        signal.send()
        signal.cancel()
        signal.resolveSample(agreed: true)
        XCTAssertEqual(signal.phase, .cancelled)
        XCTAssertNil(signal.insertedPlaceName)
    }

    func testReceivedSignalCannotBeFinishedOrCancelledByTheVoter() {
        let signal = TripSignalPreviewStore()
        signal.showReceived()
        signal.vote(agree: true)
        signal.cancel()
        XCTAssertEqual(signal.phase, .waiting)
        signal.resolveSample(agreed: true)
        signal.finish()
        XCTAssertEqual(signal.phase, .agreed)
    }

    func testNoDestinationRequestDoesNotInsertAFabricatedPlace() {
        let signal = TripSignalPreviewStore()
        signal.next()
        signal.placeID = nil
        signal.send()
        signal.resolveSample(agreed: true)
        XCTAssertEqual(signal.phase, .agreed)
        XCTAssertNil(signal.insertedPlaceName)
    }
    func testDrivingScoresValidateFormulaAndKeepOnlyMyCarInDetail() async throws {
        let preview = try XCTUnwrap(TripPreviewData.myTrips.first { $0.id == "gangneung" })
        let store = TripPreparationStore(preview: preview)
        await store.load()
        var detail = try XCTUnwrap(store.detail)
        let mine = try XCTUnwrap(detail.myCar)
        let other = try XCTUnwrap(detail.cars.first { $0.id != mine.id })
        let score = IPhoneTripDrivingScore(carId: mine.id, score: 90, accelerations: 1, brakings: 1, measurable: true, final: true)
        XCTAssertTrue(score.isValid)
        detail.courses[0].drivingScores = [score]
        XCTAssertTrue(detail.isValid)
        var invalid = score; invalid.score = 95
        XCTAssertFalse(invalid.isValid)
        invalid = score; invalid.measurable = false
        XCTAssertFalse(invalid.isValid)
        invalid.score = nil
        XCTAssertTrue(invalid.isValid)
        detail.courses[0].drivingScores = [IPhoneTripDrivingScore(carId: other.id, score: 90, accelerations: 1, brakings: 1, measurable: true, final: true)]
        XCTAssertFalse(detail.isValid)
    }

    func testRoleChangesRequireOwnerAndNeverExpandPermissions() async throws {
        let preview = try XCTUnwrap(TripPreviewData.myTrips.first { $0.id == "yangpyeong" })
        let nonowner = TripPreparationStore(preview: preview)
        await nonowner.load()
        let actor = try XCTUnwrap(nonowner.detail?.me)
        do { try await nonowner.setRole(accountID: actor.id, role: .food); XCTFail("Nonowner changed role") }
        catch IPhoneSessionError.forbidden { }
        let owner = TripPreparationStore(preview: preview, actorName: preview.ownerName)
        await owner.load()
        let before = try XCTUnwrap(owner.detail)
        try await owner.setRole(accountID: actor.id, role: .rest)
        XCTAssertEqual(owner.detail?.members.first { $0.id == actor.id }?.role, .rest)
        XCTAssertEqual(owner.detail?.myPermissions, before.myPermissions)
        XCTAssertEqual(owner.detail?.isOwner, before.isOwner)
    }

}
