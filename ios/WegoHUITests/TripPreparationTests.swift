import XCTest

@MainActor
final class TripPreparationTests: XCTestCase {
    func testMissingPlateExplainsBlockAndRegistrationEnablesCreateWithoutLosingDraft() {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["-walkthrough.step", "finished", "-profile-ui-testing", "-trip-car-ui-missing-plate"]
        app.launch()
        let save = app.buttons["tripCarCreateSave"]
        XCTAssertTrue(save.waitForExistence(timeout: 5))
        XCTAssertFalse(save.isEnabled)
        let register = app.buttons["tripCarRegisterPlate"]
        XCTAssertTrue(register.waitForExistence(timeout: 3))
        let increase = app.buttons["인원 늘리기"]
        for _ in 0..<3 where !increase.isHittable { app.swipeUp() }
        increase.tap()
        XCTAssertEqual(app.staticTexts["tripCarSeats"].label, "4명")
        let name = app.textFields["tripCarName"]
        name.tap()
        name.typeText(" QA")
        capture("CarPlateRequired")
        register.tap()
        let vehicle = app.buttons["profileEditPlate-" + String(repeating: "b", count: 32)]
        for _ in 0..<3 where !vehicle.isHittable { app.swipeUp() }
        XCTAssertTrue(vehicle.waitForExistence(timeout: 5))
        vehicle.tap()
        let plate = app.textFields["profileEditInput"]
        XCTAssertTrue(plate.waitForExistence(timeout: 5))
        plate.tap()
        plate.typeText("1234567")
        app.buttons["profileSave"].tap()
        XCTAssertTrue(vehicle.waitForExistence(timeout: 5))
        app.navigationBars.buttons.element(boundBy: 0).tap()
        XCTAssertTrue(save.waitForExistence(timeout: 5))
        XCTAssertTrue(save.isEnabled)
        XCTAssertEqual(name.value as? String, "사용자D의 차 QA")
        XCTAssertEqual(app.staticTexts["tripCarSeats"].label, "4명")
        capture("CarPlateRegistered")
    }

    func testNewPreparationCreatesCarAddsCourseAndStartsOnlyAfterReady() {
        let app = launch("-trips-ui-preview")
        open("trip-new-trip", in: app)
        let start = app.buttons["tripPreparingStart"]
        XCTAssertTrue(start.waitForExistence(timeout: 5))
        XCTAssertFalse(start.isEnabled)
        XCTAssertTrue(app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "탈 차 고르기,")).firstMatch.exists)
        capture("PreparationInitial")
        app.buttons["내 차로 운전할게요"].tap()
        let save = app.buttons["tripCarCreateSave"]
        XCTAssertTrue(save.waitForExistence(timeout: 5))
        XCTAssertEqual(app.textFields["tripCarName"].value as? String, "사용자E의 차")
        capture("PreparationCreateCar")
        save.tap()
        XCTAssertTrue(app.buttons["tripPreparingCars"].waitForExistence(timeout: 5))
        XCTAssertFalse(start.isEnabled)
        let addCourse = app.buttons["tripPreparingAddCourse"]
        for _ in 0..<4 where !addCourse.isHittable || addCourse.frame.maxY >= start.frame.minY { app.swipeUp() }
        addCourse.tap()
        let course = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "서해안 해안도로 코스")).firstMatch
        for _ in 0..<4 where !course.isHittable { app.swipeUp() }
        XCTAssertTrue(course.waitForExistence(timeout: 5))
        course.tap()
        let addSelected = app.buttons["tripCourseAddSelected"]
        XCTAssertTrue(addSelected.waitForExistence(timeout: 5))
        XCTAssertTrue(addSelected.isEnabled)
        addSelected.tap()
        XCTAssertTrue(start.waitForExistence(timeout: 5))
        XCTAssertTrue(start.isEnabled)
        start.tap()
        XCTAssertTrue(app.staticTexts["진행 중"].waitForExistence(timeout: 5))
        XCTAssertFalse(start.exists)
    }

    func testChoosingAndLeavingCarKeepsTripAndOtherMembers() {
        let app = launch("-trips-ui-preview")
        open("trip-gapyeong", in: app)
        app.buttons["tripPreparingCars"].tap()
        let change = app.buttons["1호차 · 사용자B의 차, 이 차로 바꾸기"]
        XCTAssertTrue(change.waitForExistence(timeout: 5))
        capture("PreparationCarChoices")
        change.tap()
        let leave = app.buttons["1호차 · 사용자B의 차, 내리기"]
        XCTAssertTrue(leave.waitForExistence(timeout: 5))
        leave.tap()
        let confirmation = app.alerts["이 차에서 내릴까요?"]
        XCTAssertTrue(confirmation.waitForExistence(timeout: 5))
        capture("PreparationLeaveCarConfirmation")
        confirmation.buttons["취소"].tap()
        XCTAssertTrue(leave.waitForExistence(timeout: 5))
        leave.tap()
        XCTAssertTrue(confirmation.waitForExistence(timeout: 5))
        confirmation.buttons["내리기"].tap()
        XCTAssertTrue(app.buttons["1호차 · 사용자B의 차, 이 차 타기"].waitForExistence(timeout: 5))
        app.buttons["완료"].tap()
        XCTAssertTrue(app.staticTexts["차 2대 · 일행 5명"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["탈 차를 골라 주세요"].exists)
    }

    func testCreateErrorPreservesDraft() {
        let app = launch("-trips-ui-create")
        let title = app.textFields["tripCreateTitle"]
        XCTAssertTrue(title.waitForExistence(timeout: 5))
        let save = app.buttons["tripCreateSave"]
        XCTAssertFalse(save.isEnabled)
        title.tap()
        title.typeText("Travel QA")
        XCTAssertTrue(save.isEnabled)
        save.tap()
        XCTAssertTrue(app.staticTexts["tripCreateError"].waitForExistence(timeout: 5))
        XCTAssertEqual(title.value as? String, "Travel QA")
    }

    private func launch(_ option: String) -> XCUIApplication {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["-walkthrough.step", "finished", option]
        app.launch()
        return app
    }

    private func open(_ id: String, in app: XCUIApplication) {
        let button = app.buttons[id]
        for _ in 0..<6 where !button.isHittable { app.swipeUp() }
        XCTAssertTrue(button.isHittable, id)
        button.tap()
    }

    private func capture(_ title: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = title
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
