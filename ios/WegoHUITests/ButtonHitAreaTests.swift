import XCTest

@MainActor
final class ButtonHitAreaTests: XCTestCase {
    func testDateCardPaddingOpensTheChosenDatePicker() {
        let app = launch(["-trips-ui-create"])
        let start = app.buttons["tripCreateStartDate"]
        reveal(start, in: app)
        tapInset(start, dx: 0.85, dy: 0.85)
        XCTAssertTrue(app.navigationBars["시작일 선택"].waitForExistence(timeout: 5))
        XCTAssertEqual(app.navigationBars.matching(identifier: "시작일 선택").count, 1)
        app.navigationBars["시작일 선택"].buttons["취소"].tap()
        let end = app.buttons["tripCreateEndDate"]
        reveal(end, in: app)
        tapInset(end, dx: 0.85, dy: 0.85)
        XCTAssertTrue(app.navigationBars["종료일 선택"].waitForExistence(timeout: 5))
        capture("DateCardPadding")
    }

    func testStepperPaddingChangesTheCountExactlyOnce() {
        let app = launch(["-profile-ui-testing", "-trip-car-ui-missing-plate"])
        let plus = app.buttons["인원 늘리기"]
        reveal(plus, in: app)
        XCTAssertEqual(app.staticTexts["tripCarSeats"].label, "3명")
        tapInset(plus, dx: 0.15, dy: 0.15)
        XCTAssertEqual(app.staticTexts["tripCarSeats"].label, "4명")
        tapInset(app.buttons["인원 줄이기"], dx: 0.85, dy: 0.85)
        XCTAssertEqual(app.staticTexts["tripCarSeats"].label, "3명")
        capture("StepperPadding")
    }

    func testDisabledStepperPaddingDoesNotChangeTheMinimum() {
        let app = launch(["-profile-ui-testing", "-trip-car-ui-missing-plate"])
        let minus = app.buttons["인원 줄이기"]
        reveal(minus, in: app)
        tapInset(minus, dx: 0.15, dy: 0.15)
        tapInset(minus, dx: 0.85, dy: 0.85)
        XCTAssertEqual(app.staticTexts["tripCarSeats"].label, "1명")
        XCTAssertFalse(minus.isEnabled)
        minus.coordinate(withNormalizedOffset: CGVector(dx: 0.15, dy: 0.15)).tap()
        XCTAssertEqual(app.staticTexts["tripCarSeats"].label, "1명")
        XCTAssertFalse(app.buttons["tripCarCreateSave"].isEnabled)
        capture("DisabledStepperPadding")
    }

    func testInvitationCancelAndJoinUseTheWholeButton() {
        let app = launch(["-trips-ui-preview"])
        let invitation = app.buttons["tripInvite-jeju"]
        reveal(invitation, in: app)
        invitation.tap()
        let decline = app.buttons["tripInvitationDecline"]
        reveal(decline, in: app)
        tapInset(decline, dx: 0.15, dy: 0.5)
        let cancel = app.buttons["tripInvitationDeclineCancel"]
        XCTAssertTrue(cancel.waitForExistence(timeout: 5))
        tapInset(cancel, dx: 0.85, dy: 0.5)
        XCTAssertFalse(app.buttons["tripInvitationDeclineConfirm"].exists)
        let accept = app.buttons["tripInvitationAccept"]
        XCTAssertTrue(accept.waitForExistence(timeout: 5))
        XCTAssertGreaterThanOrEqual(accept.frame.width, 44)
        XCTAssertGreaterThanOrEqual(accept.frame.height, 44)
        accept.coordinate(withNormalizedOffset: CGVector(dx: 0.15, dy: 0.5)).tap()
        XCTAssertTrue(app.buttons["tripInvitationDone"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["tripInvitationAccept"].exists)
        capture("InvitationButtonPadding")
    }

    private func launch(_ options: [String]) -> XCUIApplication {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["-walkthrough.step", "finished"] + options
        app.launch()
        return app
    }

    private func reveal(_ element: XCUIElement, in app: XCUIApplication) {
        XCTAssertTrue(element.waitForExistence(timeout: 5))
        for _ in 0..<4 where !element.isHittable { app.swipeUp() }
        XCTAssertTrue(element.isHittable)
    }

    private func tapInset(_ element: XCUIElement, dx: CGFloat, dy: CGFloat) {
        XCTAssertTrue(element.isHittable)
        XCTAssertGreaterThanOrEqual(element.frame.width, 44)
        XCTAssertGreaterThanOrEqual(element.frame.height, 44)
        element.coordinate(withNormalizedOffset: CGVector(dx: dx, dy: dy)).tap()
    }

    private func capture(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
