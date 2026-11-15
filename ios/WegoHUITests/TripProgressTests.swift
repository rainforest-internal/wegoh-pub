import XCTest

@MainActor
final class TripProgressTests: XCTestCase {
    func testCurrentRouteRemoteAndHandRaiseAgreementPreview() {
        let app = launch()
        open("trip-gangneung", in: app)
        XCTAssertTrue(app.staticTexts["지금 경로"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["11월 12일–13일 · 만든 사람 사용자A"].exists)
        capture("TripProgressCurrentRoute")
        open("tripProgressRemote", in: app)
        XCTAssertTrue(app.buttons["remoteApplyClimate"].waitForExistence(timeout: 5))
        capture("TripProgressRemote")
        app.buttons["remoteApplyClimate"].tap()
        let message = app.staticTexts["remotePreviewMessage"]
        for _ in 0..<5 where !message.isHittable { app.swipeUp() }
        XCTAssertTrue(message.exists)
        XCTAssertTrue(message.label.contains("실제 차량에는 명령을 보내지 않았어요"))
        app.buttons["닫기"].tap()
        open("tripProgressSignal", in: app)
        XCTAssertTrue(app.buttons["signalReason-restroom"].waitForExistence(timeout: 5))
        capture("TripSignalReason")
        app.buttons["signalReason-restroom"].tap()
        app.buttons["signalNext"].tap()
        XCTAssertTrue(app.buttons["signalPlace-gujeong"].waitForExistence(timeout: 5))
        app.buttons["signalPlace-gujeong"].tap()
        capture("TripSignalPlace")
        app.buttons["signalSend"].tap()
        XCTAssertEqual(app.staticTexts["signalStatusHeadline"].label, "일행의 답을 기다리고 있어요")
        capture("TripSignalWaiting")
        app.buttons["signalPreviewScenario"].tap()
        app.buttons["모두 동의한 상태 보기"].tap()
        XCTAssertEqual(app.staticTexts["signalStatusHeadline"].label, "다음 목적지 앞에 추가됐어요")
        capture("TripSignalAgreed")
        app.buttons["signalFinish"].tap()
        XCTAssertEqual(app.staticTexts["signalStatusHeadline"].label, "들르기를 마쳤어요")
        app.buttons["여행으로"].tap()
        XCTAssertTrue(app.staticTexts["서산휴게소"].waitForExistence(timeout: 5))
    }

    func testReceivedSignalPassClosesRequestAndAllowsNewSignal() {
        let app = launch()
        open("trip-gangneung", in: app)
        open("tripProgressScenarios", in: app)
        app.buttons["받은 손들기 요청 보기"].tap()
        XCTAssertEqual(app.staticTexts["signalStatusHeadline"].label, "사용자E님이 손을 들었어요")
        capture("TripSignalReceived")
        app.buttons["signalPass"].tap()
        XCTAssertEqual(app.staticTexts["signalStatusHeadline"].label, "요청을 마쳤어요")
        capture("TripSignalDeclined")
        app.buttons["여행으로"].tap()
        open("tripProgressSignal", in: app)
        XCTAssertTrue(app.buttons["signalReason-restroom"].waitForExistence(timeout: 5))
    }

    func testCarRemotePermissionIsOptionalAndCannotSaveAnEmptyAllowedSet() {
        let app = launch()
        open("trip-new-trip", in: app)
        app.buttons["내 차로 운전할게요"].tap()
        let save = app.buttons["tripCarCreateSave"]
        XCTAssertTrue(save.waitForExistence(timeout: 5))
        XCTAssertTrue(save.isEnabled)
        let permission = app.switches["tripRemotePermissionToggle"]
        XCTAssertTrue(permission.waitForExistence(timeout: 5))
        let forms = app.scrollViews.containing(.switch, identifier: "tripRemotePermissionToggle")
        XCTAssertEqual(forms.count, 1)
        let form = forms.element
        let header = app.navigationBars["차 만들기"]
        let footer = app.staticTexts["차를 만들면 내가 운전자가 되고, 일행이 이 차를 고를 수 있어요."]
        XCTAssertTrue(header.exists)
        XCTAssertTrue(footer.exists)
        func permissionIsFullyVisible() -> Bool {
            permission.isHittable && permission.frame.minY >= header.frame.maxY
                && permission.frame.maxY < min(footer.frame.minY, save.frame.minY)
        }
        for _ in 0..<6 where !permissionIsFullyVisible() {
            if permission.frame.minY < header.frame.maxY { form.swipeDown() }
            else { form.swipeUp() }
        }
        XCTAssertTrue(permissionIsFullyVisible(), "The whole permission toggle must be above the sticky footer")
        XCTAssertEqual(permission.value as? String, "0")
        permission.tap()
        let enabled = XCTNSPredicateExpectation(predicate: NSPredicate(format: "value == %@", "1"), object: permission)
        XCTAssertEqual(XCTWaiter.wait(for: [enabled], timeout: 5), .completed)
        for group in ["climate", "lights", "seats"] {
            open("tripRemoteGroup-\(group)", in: app)
            XCTAssertEqual(app.buttons["tripRemoteGroup-\(group)"].value as? String, "허용 안 함")
        }
        capture("TripCarRemoteEmptySelection")
        XCTAssertFalse(save.isEnabled)
        open("tripRemoteGroup-windows", in: app)
        XCTAssertTrue(save.isEnabled)
        capture("TripCarRemotePermission")
    }

    private func launch() -> XCUIApplication {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["-walkthrough.step", "finished", "-trips-ui-preview"]
        app.launch()
        return app
    }
    private func open(_ id: String, in app: XCUIApplication) {
        let button = app.buttons[id]
        XCTAssertTrue(button.waitForExistence(timeout: 5), id)
        let save = app.buttons["tripCarCreateSave"]
        for _ in 0..<6 where !button.isHittable || (save.exists && button.frame.maxY > save.frame.minY) { app.swipeUp() }
        XCTAssertTrue(button.isHittable, id)
        button.tap()
    }
    private func capture(_ name: String) {
        let image = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        image.name = name
        image.lifetime = .keepAlways
        add(image)
    }
}
