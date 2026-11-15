import XCTest

@MainActor
final class TripActivityTests: XCTestCase {
    func testNumberedMapPinsRemainVisibleAfterRouteArrives() {
        let app = launch("map-layering")
        XCTAssertTrue(app.descendants(matching: .any)["mapLayeringPreview"].firstMatch.waitForExistence(timeout: 8))
        let ready = Date().addingTimeInterval(5)
        let rendered = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in Date() >= ready }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [rendered], timeout: 7), .completed)
        capture("Map-numbered-pins-above-route")
    }

    func testReturningAfterSupportExpiryAutomaticallyRefreshesAndKeepsSeatAndDrafts() {
        assertSupportResume("remote-resume")
    }

    func testPresentedRemoteSheetRefreshesAfterSupportExpiry() {
        assertSupportResume("remote-resume-sheet")
    }

    func testForegroundSupportRecoversFromTransientReadFailureWithoutManualRetry() {
        assertSupportResume("remote-resume-retry")
    }

    private func assertSupportResume(_ mode: String) {
        let app = launch(mode)
        if mode == "remote-resume-sheet" {
            XCTAssertTrue(app.buttons["리모컨 열기"].waitForExistence(timeout: 8))
            app.buttons["리모컨 열기"].tap()
        }
        XCTAssertTrue(app.buttons["조수석"].waitForExistence(timeout: 8))
        app.buttons["조수석"].tap()
        app.buttons["온도 올리기"].tap()
        app.buttons["풍량 늘리기"].tap()
        let apply = app.buttons["tripRemoteApplyClimate"]
        let draftLabel = apply.label
        XCTAssertTrue(draftLabel.contains("23"))
        XCTAssertTrue(draftLabel.contains("풍량 4"))
        XCUIDevice.shared.press(.home)
        XCTAssertTrue(app.wait(for: .runningBackground, timeout: 5))
        let waitUntil = Date().addingTimeInterval(9)
        let expired = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in Date() >= waitUntil }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [expired], timeout: 11), .completed)
        app.activate()
        XCTAssertTrue(app.wait(for: .runningForeground, timeout: 5))
        let enabled = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in apply.exists && apply.isEnabled }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [enabled], timeout: 8), .completed)
        XCTAssertTrue(app.buttons["조수석"].isSelected)
        XCTAssertEqual(apply.label, draftLabel)
        XCTAssertEqual(app.staticTexts["remoteFixtureCommandCount"].label, "명령 전송 0")
        XCTAssertNotEqual(app.staticTexts["remoteFixtureReadCount"].label, "리모컨 조회 1")
        capture("LiveRemote-resumed-" + mode)
    }

    func testClimateApplyShowsScreenLoadingThenSuccessToastWithoutMovingControls() {
        let app = launch("remote")
        XCTAssertTrue(app.buttons["조수석"].waitForExistence(timeout: 8))
        app.buttons["조수석"].tap()
        let apply = app.buttons["tripRemoteApplyClimate"]
        reveal(apply, in: app)
        let originalY = apply.frame.minY
        apply.tap()
        let loading = app.descendants(matching: .any)["tripRemoteScreenLoading"].firstMatch
        XCTAssertTrue(loading.waitForExistence(timeout: 3))
        XCTAssertFalse(apply.isEnabled)
        capture("LiveRemote-climate-screen-loading")
        let feedback = app.staticTexts["tripRemoteToast"]
        let confirmed = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label CONTAINS %@", "적용했어요"), object: feedback)
        XCTAssertEqual(XCTWaiter.wait(for: [confirmed], timeout: 12), .completed)
        XCTAssertFalse(loading.exists)
        XCTAssertEqual(apply.frame.minY, originalY, accuracy: 2)
        XCTAssertTrue(apply.label.contains("22.5"))
        XCTAssertTrue(apply.label.contains("풍량 3"))
        XCTAssertEqual(app.staticTexts["remoteFixtureCommandCount"].label, "명령 전송 2")
        XCTAssertFalse(app.staticTexts["tripRemoteCommandStatus"].exists)
        capture("LiveRemote-climate-one-feedback-slot")
    }

    func testToggleShowsScreenLoadingThenCommitsWithToast() {
        let app = launch("remote-feedback")
        XCTAssertTrue(app.buttons["조수석"].waitForExistence(timeout: 8))
        XCTAssertFalse(app.staticTexts["사용자A 허용한 조작 3개 · 차 버튼 대신 여기서 조절해요"].exists)
        app.buttons["조수석"].tap()
        let toggle = app.switches["tripRemoteToggle-hvac.power"]
        reveal(toggle, in: app)
        let originalY = toggle.frame.minY
        toggle.tap()
        let loading = app.descendants(matching: .any)["tripRemoteScreenLoading"].firstMatch
        XCTAssertTrue(loading.waitForExistence(timeout: 3))
        XCTAssertFalse(toggle.isEnabled)
        XCTAssertEqual(toggle.value as? String, "0")
        XCTAssertGreaterThan(loading.frame.height, app.frame.height * 0.75)
        XCTAssertTrue(app.navigationBars.firstMatch.exists)
        XCTAssertLessThanOrEqual(loading.frame.minY, app.navigationBars.firstMatch.frame.minY)
        XCTAssertGreaterThan(loading.frame.width, app.frame.width * 0.95)
        XCTAssertFalse(app.buttons["허용 범위 확인"].isEnabled)
        capture("LiveRemote-toggle-screen-loading")
        XCTAssertTrue(waitForValue("1", element: toggle))
        XCTAssertFalse(loading.exists)
        XCTAssertTrue(toggle.isEnabled)
        XCTAssertEqual(toggle.frame.minY, originalY, accuracy: 2)
        XCTAssertFalse(app.buttons["tripRemoteHistory"].exists)
        XCTAssertFalse(app.buttons["tripRemoteRefreshStatus"].exists)
        XCTAssertFalse(app.staticTexts["tripRemoteToggleNotice-hvac.power"].exists)
        XCTAssertEqual(app.staticTexts["remoteFixtureCommandCount"].label, "명령 전송 1")
        XCTAssertEqual(app.staticTexts["tripRemoteToast"].label, "적용했어요.")
        capture("LiveRemote-toggle-final-result")
        let dismissed = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: app.staticTexts["tripRemoteToast"])
        XCTAssertEqual(XCTWaiter.wait(for: [dismissed], timeout: 6), .completed)
    }

    func testClimateFailureRestoresInputsAndShowsFailureToast() {
        let app = launch("remote-rejected")
        XCTAssertTrue(app.buttons["조수석"].waitForExistence(timeout: 8))
        app.buttons["조수석"].tap()
        app.buttons["온도 올리기"].tap(); app.buttons["풍량 늘리기"].tap()
        let apply = app.buttons["tripRemoteApplyClimate"]
        XCTAssertTrue(apply.label.contains("23°C"))
        apply.tap()
        let feedback = app.staticTexts["tripRemoteToast"]
        let restored = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label CONTAINS %@", "적용하지 못했어요"), object: feedback)
        XCTAssertEqual(XCTWaiter.wait(for: [restored], timeout: 12), .completed)
        XCTAssertTrue(apply.isEnabled)
        XCTAssertTrue(apply.label.contains("22.5°C"))
        XCTAssertTrue(apply.label.contains("풍량 3"))
        XCTAssertFalse(app.buttons["tripRemoteRefreshStatus"].exists)
        XCTAssertEqual(app.staticTexts["remoteFixtureCommandCount"].label, "명령 전송 2")
        capture("LiveRemote-climate-failure-restored")
    }

    func testLiveSignalReasonPlaceReceivedAndTerminalLayoutsUseIsolatedHTTPFixture() {
        for (mode, expected) in [("reason", "무엇이 필요하세요?"), ("waiting", "동의 기다리는 중"),
                                  ("received", "사용자E님이 손을 들었어요"), ("agreed", "다음 목적지 앞에 추가했어요")] {
            let app = launch(mode)
            XCTAssertTrue(app.staticTexts[expected].waitForExistence(timeout: 8), mode)
            capture("LiveSignal-" + mode)
            if mode == "reason" {
                app.buttons["liveSignalReason-ev_charge"].tap()
                app.buttons["다음"].tap()
                XCTAssertTrue(app.staticTexts["어디에 들를까요?"].waitForExistence(timeout: 3))
                XCTAssertTrue(app.buttons["현재 위치로 후보 찾기"].exists)
                capture("LiveSignal-places")
            }
            if mode == "received" {
                XCTAssertEqual(app.buttons["동의"].frame.width, app.buttons["다음에"].frame.width, accuracy: 1)
                XCTAssertEqual(app.buttons["동의"].frame.height, app.buttons["다음에"].frame.height, accuracy: 1)
                app.buttons["동의"].tap()
                XCTAssertTrue(app.staticTexts["다음 목적지 앞에 추가했어요"].waitForExistence(timeout: 5))
                XCTAssertFalse(app.buttons["동의"].exists)
            }
            app.terminate()
        }
        let declined = launch("received")
        XCTAssertTrue(declined.buttons["다음에"].waitForExistence(timeout: 8))
        declined.buttons["다음에"].tap()
        XCTAssertTrue(declined.staticTexts["다음에 들르기로 했어요"].waitForExistence(timeout: 5))
        capture("LiveSignal-passed")
    }
    func testAllowedRemoteActionsAndCommandQueueStatus() {
        let app = launch("remote")
        let apply = app.buttons["tripRemoteApplyClimate"]
        XCTAssertTrue(apply.waitForExistence(timeout: 8))
        XCTAssertFalse(app.staticTexts["사용자A 허용한 조작 3개 · 차 버튼 대신 여기서 조절해요"].exists)
        XCTAssertTrue(app.staticTexts["tripRemoteChooseSupportedSeat"].exists)
        XCTAssertFalse(apply.isEnabled, "A seat must be explicitly chosen before sending")
        XCTAssertEqual(app.staticTexts["remoteFixtureCommandCount"].label, "명령 전송 0")
        XCTAssertFalse(app.buttons["운전석"].exists)
        XCTAssertFalse(app.buttons["tripRemoteSend-window.position"].exists)
        let passenger = app.buttons["조수석"]
        reveal(passenger, in: app)
        XCTAssertFalse(passenger.isSelected)
        XCTAssertFalse(app.buttons["뒷좌석 왼쪽"].isSelected)
        passenger.tap()
        XCTAssertTrue(passenger.isSelected)
        reveal(apply, in: app)
        XCTAssertTrue(apply.isEnabled)
        XCTAssertTrue(apply.label.contains("22.5"))
        XCTAssertTrue(apply.label.contains("풍량 3"))
        XCTAssertTrue(app.staticTexts["지원 범위 15–30 · 0.5씩"].exists)
        XCTAssertFalse(app.staticTexts["tripRemoteToast"].exists)
        capture("LiveRemote-supported-seat-explicit")
        XCTAssertFalse(app.buttons["tripRemoteSend-hvac.power"].exists)
        let toggle = app.switches["tripRemoteToggle-hvac.power"]
        reveal(toggle, in: app)
        XCTAssertEqual(toggle.value as? String, "0")
        toggle.tap()
        XCTAssertTrue(waitForValue("1", element: toggle))
        XCTAssertTrue(toggle.isEnabled)
        XCTAssertFalse(app.staticTexts["tripRemoteToggleNotice-hvac.power"].exists)
        XCTAssertFalse(app.buttons["tripRemoteRefreshStatus"].exists)
        XCTAssertEqual(app.staticTexts["remoteFixtureCommandCount"].label, "명령 전송 1")
        XCTAssertEqual(app.staticTexts["remoteFixtureLastTarget"].label, "요청 좌석 ROW_1_RIGHT")
        capture("LiveRemote-one-command-terminal-feedback")
    }
    func testUnknownRemoteSupportShowsFallbackSeatsButCannotSendCommands() {
        let app = launch("remote-unknown")
        let apply = app.buttons["tripRemoteApplyClimate"]
        XCTAssertTrue(apply.waitForExistence(timeout: 8))
        XCTAssertFalse(apply.isEnabled)
        XCTAssertTrue(app.staticTexts["tripRemoteFallbackSeats"].exists)
        for title in ["조수석", "뒷좌석 왼쪽", "뒷좌석 오른쪽"] { XCTAssertTrue(app.buttons[title].exists, title) }
        XCTAssertFalse(app.buttons["운전석"].exists)
        let passenger = app.buttons["조수석"]
        reveal(passenger, in: app)
        passenger.tap()
        XCTAssertTrue(passenger.isSelected)
        XCTAssertFalse(apply.isEnabled, "Fallback seats never grant sending without current support")
        let toggle = app.switches["tripRemoteToggle-hvac.power"]
        reveal(toggle, in: app)
        XCTAssertFalse(toggle.isEnabled)
        XCTAssertFalse(app.buttons["tripRemoteSend-hvac.power"].exists)
        XCTAssertEqual(app.staticTexts["remoteFixtureCommandCount"].label, "명령 전송 0")
        XCTAssertEqual(app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@", "SDK")).count, 0)
        capture("LiveRemote-unknown-support-disabled")
    }
    func testBooleanRejectionRestoresPreviousLocalDraftWithoutResending() {
        let app = launch("remote-rejected")
        XCTAssertTrue(app.buttons["tripRemoteApplyClimate"].waitForExistence(timeout: 8))
        let passenger = app.buttons["조수석"]
        passenger.tap()
        XCTAssertTrue(passenger.isSelected)
        let toggle = app.switches["tripRemoteToggle-hvac.power"]
        reveal(toggle, in: app)
        XCTAssertEqual(toggle.value as? String, "0")
        XCTAssertTrue(toggle.isEnabled)
        let counter = app.staticTexts["remoteFixtureCommandCount"]
        XCTAssertEqual(counter.label, "명령 전송 0")
        toggle.tap()
        let sent = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label == %@", "명령 전송 1"), object: counter)
        XCTAssertEqual(XCTWaiter.wait(for: [sent], timeout: 5), .completed)
        let rejected = app.staticTexts["tripRemoteToast"]
        let restored = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label CONTAINS %@", "적용하지 못했어요"), object: rejected)
        XCTAssertEqual(XCTWaiter.wait(for: [restored], timeout: 12), .completed)
        reveal(toggle, in: app)
        XCTAssertTrue(waitForValue("0", element: toggle))
        XCTAssertTrue(toggle.isEnabled)
        XCTAssertEqual(counter.label, "명령 전송 1")
        XCTAssertEqual(app.staticTexts["remoteFixtureLastTarget"].label, "요청 좌석 ROW_1_RIGHT")
        capture("LiveRemote-rejected-draft-restored")
    }

    func testUnknownToggleRestoresDisplayWithoutStatusLookupOrAutomaticResend() {
        for mode in ["remote-uncertain", "remote-timeout"] {
            let app = launch(mode)
            XCTAssertTrue(app.buttons["tripRemoteApplyClimate"].waitForExistence(timeout: 8))
            app.buttons["조수석"].tap()
            let toggle = app.switches["tripRemoteToggle-hvac.power"]
            reveal(toggle, in: app)
            toggle.tap()
            let failure = app.staticTexts["tripRemoteToast"]
            XCTAssertTrue(failure.waitForExistence(timeout: 12))
            XCTAssertTrue(failure.label.contains("응답을 확인하지 못했어요"))
            XCTAssertTrue(waitForValue("0", element: toggle))
            XCTAssertTrue(toggle.isEnabled)
            XCTAssertFalse(app.buttons["tripRemoteAcknowledge-hvac.power"].exists)
            XCTAssertFalse(app.buttons["tripRemoteRefreshStatus"].exists)
            XCTAssertEqual(app.staticTexts["remoteFixtureCommandCount"].label, "명령 전송 1")
            capture("LiveRemote-" + mode + "-restored-without-resend")
            app.terminate()
        }
    }

    func testClimateDraftValuesStayWithExplicitSeatAndDoNotSendUntilApplied() {
        let app = launch("remote")
        let apply = app.buttons["tripRemoteApplyClimate"]
        XCTAssertTrue(apply.waitForExistence(timeout: 8))
        app.buttons["조수석"].tap()
        let increase = app.buttons["온도 올리기"]
        reveal(increase, in: app)
        increase.tap()
        reveal(apply, in: app)
        XCTAssertTrue(apply.label.contains("23°C"))
        let rear = app.buttons["뒷좌석 왼쪽"]
        reveal(rear, in: app); rear.tap()
        reveal(apply, in: app)
        XCTAssertTrue(apply.label.contains("22.5°C"))
        let passenger = app.buttons["조수석"]
        reveal(passenger, in: app); passenger.tap()
        reveal(apply, in: app)
        XCTAssertTrue(apply.label.contains("23°C"))
        XCTAssertEqual(app.staticTexts["remoteFixtureCommandCount"].label, "명령 전송 0")
        capture("LiveRemote-per-seat-local-drafts")
    }

    func testNewScorePurposeStartsOffAndRequiresExplicitSave() {
        let app = launch("functional")
        let purpose = app.switches["vehiclePurpose-driving-score:report"]
        XCTAssertTrue(purpose.waitForExistence(timeout: 8))
        XCTAssertEqual(purpose.value as? String, "0")
        capture("ScorePermission-off")
        purpose.coordinate(withNormalizedOffset: CGVector(dx: 0.9, dy: 0.5)).tap()
        XCTAssertTrue(waitForValue("1", element: purpose))
        capture("ScorePermission-selected")
        let save = app.buttons["vehiclePurposesSave"]
        for _ in 0..<4 where !save.isHittable { app.swipeUp() }
        save.tap()
        XCTAssertTrue(app.staticTexts["선택한 기능을 저장했어요."].waitForExistence(timeout: 5))
        XCTAssertTrue(waitForValue("1", element: purpose))
        capture("ScorePermission-saved")
    }
    func testRolesAreGroupedByNumberedCarsAndOwnerCanChangeOne() {
        let app = launch("roles")
        XCTAssertTrue(app.staticTexts["1호차 · 사용자A의 차"].waitForExistence(timeout: 8))
        let role = app.buttons["tripRole-team-3333333333333333333333333333333333333333-rest"]
        for _ in 0..<5 where !role.isHittable { app.swipeUp() }
        XCTAssertTrue(role.isHittable)
        role.tap()
        XCTAssertTrue(role.waitForExistence(timeout: 3))
        XCTAssertFalse(role.isEnabled)
        capture("TripRoles-owner")
    }
    private func launch(_ mode: String) -> XCUIApplication {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["-trip-activity-ui-testing", mode]
        app.launch()
        return app
    }
    private func waitForValue(_ value: String, element: XCUIElement) -> Bool {
        let expected = XCTNSPredicateExpectation(predicate: NSPredicate(format: "value == %@", value), object: element)
        return XCTWaiter.wait(for: [expected], timeout: 12) == .completed
    }
    private func reveal(_ element: XCUIElement, in app: XCUIApplication) {
        for _ in 0..<12 {
            if !element.exists { app.swipeUp(); continue }
            let navigation = app.navigationBars.firstMatch
            let top = navigation.exists ? navigation.frame.maxY : app.frame.minY
            if element.frame.minY < top { app.swipeDown() }
            else if element.frame.maxY > app.frame.maxY || !element.isHittable { app.swipeUp() }
            else { break }
        }
        XCTAssertTrue(element.exists)
        XCTAssertTrue(element.isHittable)
    }
    private func capture(_ name: String) {
        let item = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        item.name = name; item.lifetime = .keepAlways; add(item)
    }
}
