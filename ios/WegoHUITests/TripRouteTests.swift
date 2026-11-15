import XCTest

@MainActor
final class TripRouteTests: XCTestCase {
    func testLiveTripActionsStayAboveTabBarWhileContentScrolls() {
        let app = launch("full-pickup")
        XCTAssertTrue(app.staticTexts["tripDetailTitle"].waitForExistence(timeout: 8))
        let remote = app.buttons["tripLiveRemote"]
        let signal = app.buttons["tripLiveSignal"]
        XCTAssertTrue(remote.isHittable)
        XCTAssertTrue(signal.exists)
        XCTAssertFalse(signal.isEnabled)
        let original = remote.frame
        let heading = app.staticTexts["tripDetailTitle"].frame
        app.swipeUp()
        app.swipeUp()
        XCTAssertTrue(remote.isHittable)
        XCTAssertEqual(remote.frame.minY, original.minY, accuracy: 2)
        XCTAssertEqual(signal.frame.minY, original.minY, accuracy: 2)
        XCTAssertLessThan(remote.frame.maxY, app.frame.maxY)
        XCTAssertLessThan(app.staticTexts["tripDetailTitle"].frame.minY, heading.minY)
        capture("TripProgress-fixed-actions-after-scroll")
        app.swipeDown()
        XCTAssertTrue(remote.isHittable)
        XCTAssertEqual(remote.frame.minY, original.minY, accuracy: 2)
    }

    func testLateParticipantCanChooseExistingCarDuringAnActiveTrip() {
        let app = launch("full-unassigned")
        XCTAssertTrue(app.staticTexts["tripDetailTitle"].waitForExistence(timeout: 8))
        let entry = app.buttons["tripProgressCars"]
        XCTAssertTrue(entry.waitForExistence(timeout: 3))
        guard entry.exists else { return }
        reveal(entry, app: app)
        entry.tap()
        XCTAssertTrue(app.navigationBars["탈 차 고르기"].waitForExistence(timeout: 5))
        let ride = app.buttons.matching(NSPredicate(format: "label ENDSWITH %@", ", 이 차 타기")).firstMatch
        reveal(ride, app: app)
        ride.tap()
        XCTAssertTrue(app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@", "내가 탄 차")).firstMatch.waitForExistence(timeout: 5))
        app.buttons["완료"].tap()
        XCTAssertTrue(app.staticTexts["샘플 저장 완료"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["내가 탄 차 · 운전자 사용자A"].waitForExistence(timeout: 5))
        let remote = app.buttons["tripLiveRemote"]
        reveal(remote, app: app)
        XCTAssertTrue(remote.isEnabled)
        capture("TripProgress-late-participant-car-selected")
    }

    func testFiveServerPhasesGateSignalsWithoutInventingETAOrOtherCarPlaces() {
        for (mode, title) in [("pickup", "타는 곳으로 이동 중"), ("waiting", "합류 대기"), ("shared", "경로 주행 중"), ("drop", "내리는 곳으로 이동 중"), ("done", "주행 완료")] {
            let app = launch(mode)
            let phase = app.staticTexts["tripRoutePhase"]
            XCTAssertTrue(phase.waitForExistence(timeout: 8), mode)
            XCTAssertTrue(phase.label.contains(title))
            XCTAssertTrue(app.staticTexts["도착 예상 시간 미제공"].exists)
            if mode == "waiting" { XCTAssertTrue(app.staticTexts["타는 곳으로 이동 중"].exists) }
            XCTAssertFalse(app.staticTexts["사당역"].exists)
            capture("TripRoute-" + mode)
            let signal = app.buttons["tripLiveSignal"]
            reveal(signal, app: app)
            XCTAssertTrue(signal.exists)
            XCTAssertEqual(signal.isEnabled, mode == "shared")
            XCTAssertTrue(app.buttons["tripLiveRemote"].isEnabled)
            app.terminate()
        }
    }

    func testOwnPlaceRecommendationAndSameDropSaveAtomically() {
        let app = launch("places")
        let toggle = app.switches["tripDropAtPickup"]
        XCTAssertTrue(toggle.waitForExistence(timeout: 8))
        XCTAssertEqual(toggle.value as? String, "1")
        let choice = app.buttons["tripMyPlace-pickup-" + String(repeating: "1", count: 32)]
        reveal(choice, app: app); choice.tap()
        XCTAssertEqual(choice.value as? String, "선택됨")
        capture("TripMyPlaces-recommendation")
        let save = app.buttons["tripMyPlacesSave"]
        XCTAssertTrue(save.isEnabled); save.tap()
        XCTAssertTrue(app.staticTexts["tripRouteFixtureSaved"].waitForExistence(timeout: 5))
    }

    func testPlaceSearchUsesExistingNativeSearchSheetWithoutCreatingBeforeSave() {
        let app = launch("places")
        let search = app.buttons["tripMyPlacesSearch-pickup"]
        XCTAssertTrue(search.waitForExistence(timeout: 8)); search.tap()
        let query = app.textFields["coursePlaceQuery"]
        XCTAssertTrue(query.waitForExistence(timeout: 5)); query.tap(); query.typeText("합정")
        app.buttons["coursePlaceSearch"].tap()
        XCTAssertTrue(app.staticTexts["합정역 샘플 출구"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.staticTexts["tripRouteFixtureSaved"].exists)
        capture("TripMyPlaces-search")
    }

    func testAutomaticVersusPendingFinalTieAndUnavailableHaveNoParticipationConsent() {
        for (mode, headline) in [("versus-pending", "최종 점수 집계 중"), ("versus-final", "1호차 · 사용자A의 차 · 승리"), ("versus-tie", "1호차 · 사용자A의 차, 2호차 · 사용자B의 차 · 공동 1등"), ("versus-unavailable", "지금은 점수를 비교할 수 없어요"), ("versus-sharing", "지금은 점수를 비교할 수 없어요")] {
            let app = launch(mode)
            let title = app.staticTexts["tripVersusHeadline"]
            XCTAssertTrue(title.waitForExistence(timeout: 8), mode)
            XCTAssertEqual(title.label, headline)
            XCTAssertFalse(app.buttons["참가하기"].exists)
            XCTAssertFalse(app.buttons["동의"].exists)
            if mode == "versus-unavailable" { XCTAssertTrue(app.staticTexts["측정 불가"].firstMatch.exists); XCTAssertFalse(app.staticTexts["100점"].exists) }
            capture("TripVersus-" + mode)
            app.terminate()
        }
    }

    func testOwnerChangesSharedOrderWithCapturedRevision() {
        let app = launch("priority")
        let down = app.buttons["tripCourseOrder-0-1"]
        XCTAssertTrue(down.waitForExistence(timeout: 8)); reveal(down, app: app); down.tap()
        XCTAssertTrue(app.staticTexts["샘플 저장 완료"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["1. 보령 해안도로"].exists)
        capture("TripRoute-owner-order")
    }

    func testV4SharingUsesExistingSettingsSaveWithoutMissionConsent() {
        let app = launch("functional-v4")
        let purpose = app.switches["vehiclePurpose-driving-score:report"]
        XCTAssertTrue(app.navigationBars["차량 기능 허용"].waitForExistence(timeout: 8))
        reveal(purpose, app: app)
        XCTAssertEqual(purpose.value as? String, "1")
        XCTAssertFalse(app.buttons["대결 참가 동의"].exists)
        let save = app.buttons["vehiclePurposesSave"]
        reveal(save, app: app); save.tap()
        XCTAssertTrue(app.staticTexts["선택한 기능을 저장했어요."].waitForExistence(timeout: 5))
        capture("TripFunctional-v4-explicit-save")
    }

    func testPreparationOpensOwnPlaceSheetFromChecklist() {
        let app = launch("full-preparation")
        let entry = app.buttons["tripPreparingPickup"]
        XCTAssertTrue(entry.waitForExistence(timeout: 8)); reveal(entry, app: app); entry.tap()
        XCTAssertTrue(app.navigationBars["타는 곳·내리는 곳"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.switches["tripDropAtPickup"].exists)
        capture("TripMyPlaces-normal-entry")
    }

    func testDriverChecklistDoesNotRequireOwnPickupAndDrop() {
        let app = launch("full-preparation-owner")
        let row = app.descendants(matching: .any)["tripPreparingPickup"].firstMatch
        XCTAssertTrue(row.waitForExistence(timeout: 8))
        reveal(row, app: app)
        capture("TripPreparation-driver-checklist")
        XCTAssertTrue(row.label.contains("선택 불필요"))
        XCTAssertTrue(row.label.contains("운전자는 정하지 않아도 돼요"))
        XCTAssertEqual(row.value as? String, "준비 완료")
        XCTAssertFalse(app.buttons["tripPreparingPickup"].exists)
        XCTAssertFalse(app.staticTexts["3/4 · 준비 필요"].exists)
        XCTAssertTrue(app.buttons["tripPreparingStart"].isEnabled)
    }

    func testNonOwnerDriverDoesNotNeedOwnPlaces() {
        let app = launch("full-preparation-driver")
        let row = app.descendants(matching: .any)["tripPreparingPickup"].firstMatch
        XCTAssertTrue(row.waitForExistence(timeout: 8))
        reveal(row, app: app)
        XCTAssertTrue(row.label.contains("선택 불필요"))
        XCTAssertEqual(row.value as? String, "준비 완료")
        XCTAssertFalse(app.buttons["tripPreparingPickup"].exists)
        XCTAssertFalse(app.buttons["tripPreparingStart"].exists)
        capture("TripPreparation-nonowner-driver")
    }

    func testRoleBadgesRemainGroupedWithNamesAcrossPreparationAndCarPicker() {
        let app = launch("full-preparation-roles")
        let roles = app.buttons["tripRoles"]
        XCTAssertTrue(roles.waitForExistence(timeout: 8)); reveal(roles, app: app)
        XCTAssertTrue(roles.label.contains("DJ, 사용자A"))
        XCTAssertTrue(roles.label.contains("맛집, 사용자C"))
        XCTAssertTrue(roles.label.contains("쉼터, 사용자D"))
        XCTAssertLessThanOrEqual(roles.frame.maxX, app.frame.maxX)
        capture("TripRoles-preparation")
        roles.tap()
        XCTAssertTrue(app.navigationBars["역할 정하기"].waitForExistence(timeout: 5))
        let food = app.descendants(matching: .any)["tripMemberRole-team-" + String(repeating: "2", count: 40)].firstMatch
        XCTAssertTrue(food.exists)
        XCTAssertEqual(food.label, "맛집, 사용자C")
        capture("TripRoles-readonly")
        app.buttons["완료"].tap()
        let cars = app.buttons["tripPreparingCars"]; reveal(cars, app: app); cars.tap()
        XCTAssertTrue(app.navigationBars["탈 차 고르기"].waitForExistence(timeout: 5))
        XCTAssertTrue(food.exists)
        XCTAssertTrue(app.frame.intersects(food.frame))
        XCTAssertGreaterThan(food.frame.width, 0)
        XCTAssertLessThanOrEqual(food.frame.maxX, app.frame.maxX)
        capture("TripRoles-car-picker")
    }

    func testProgressShowsRolesForTheCorrectCar() {
        let app = launch("full-shared-roles")
        let otherDriver = app.descendants(matching: .any)["tripMemberRole-team-" + String(repeating: "4", count: 40)].firstMatch
        XCTAssertTrue(otherDriver.waitForExistence(timeout: 8)); reveal(otherDriver, app: app)
        XCTAssertEqual(otherDriver.label, "DJ, 사용자B")
        capture("TripRoles-other-car")
    }

    func testCompletedTripReadsComparisonThroughDedicatedEndpoint() {
        let app = launch("full-result")
        XCTAssertTrue(app.staticTexts["tripDetailTitle"].waitForExistence(timeout: 8))
        let result = app.staticTexts["tripVersusHeadline"]
        XCTAssertTrue(result.waitForExistence(timeout: 5))
        XCTAssertEqual(result.label, "1호차 · 사용자A의 차 · 승리")
        XCTAssertFalse(app.buttons["참가하기"].exists)
        capture("TripRoute-completed-comparison")
    }

    func testStaleSelectionRequiresExplicitReloadAndAnotherSave() {
        let app = launch("places-stale")
        let choice = app.buttons["tripMyPlace-pickup-" + String(repeating: "1", count: 32)]
        XCTAssertTrue(choice.waitForExistence(timeout: 8)); choice.tap()
        app.buttons["tripMyPlacesSave"].tap()
        XCTAssertTrue(app.staticTexts["tripMyPlacesError"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.staticTexts["tripRouteFixtureSaved"].exists)
        let reload = app.buttons["tripMyPlacesReload"]; reveal(reload, app: app); reload.tap()
        XCTAssertTrue(choice.waitForExistence(timeout: 5)); reveal(choice, app: app); choice.tap()
        app.buttons["tripMyPlacesSave"].tap()
        XCTAssertTrue(app.staticTexts["tripRouteFixtureSaved"].waitForExistence(timeout: 5))
        capture("TripMyPlaces-stale-recovered")
    }

    private func launch(_ mode: String) -> XCUIApplication {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["-trip-route-ui-testing", mode]
        app.launch(); return app
    }
    private func reveal(_ element: XCUIElement, app: XCUIApplication) {
        for _ in 0..<12 where !element.isHittable { app.swipeUp() }
        XCTAssertTrue(element.isHittable)
    }
    private func capture(_ name: String) {
        let shot = XCTAttachment(screenshot: XCUIScreen.main.screenshot()); shot.name = name; shot.lifetime = .keepAlways; add(shot)
    }
}
