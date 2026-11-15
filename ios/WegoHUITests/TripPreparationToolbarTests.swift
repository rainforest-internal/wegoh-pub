import XCTest

@MainActor
final class TripPreparationToolbarTests: XCTestCase {
    func testOwnerToolbarSeparatesManagementAndInvitationTargets() {
        checkToolbar()
    }

    private func checkToolbar() {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["-trip-route-ui-testing", "full-preparation-owner"]
        app.launch()
        let management = app.buttons["tripManagement"]
        let invite = app.buttons["tripPreparingInvite"]
        XCTAssertTrue(management.waitForExistence(timeout: 8))
        XCTAssertTrue(invite.waitForExistence(timeout: 5))
        XCTAssertEqual(management.label, "관리")
        XCTAssertEqual(invite.label, "친구 초대")
        for button in [management, invite] {
            XCTAssertTrue(button.isHittable)
            XCTAssertGreaterThanOrEqual(button.frame.width, 44)
            XCTAssertGreaterThanOrEqual(button.frame.height, 44)
            XCTAssertTrue(app.frame.contains(button.frame))
        }
        XCTAssertGreaterThanOrEqual(invite.frame.minX - management.frame.maxX, 8)
        let screenshot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        screenshot.name = "PreparationToolbar"
        screenshot.lifetime = .keepAlways
        add(screenshot)
        management.coordinate(withNormalizedOffset: CGVector(dx: 0.15, dy: 0.5)).tap()
        XCTAssertTrue(app.navigationBars["여행 관리"].waitForExistence(timeout: 5))
    }
}
