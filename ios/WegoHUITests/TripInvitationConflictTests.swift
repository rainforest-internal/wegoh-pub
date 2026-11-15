import XCTest

@MainActor
final class TripInvitationConflictTests: XCTestCase {
    func testClosedInvitationReturnsToTheAuthoritativeListWithoutPretendingItJoined() {
        let app = launch()
        answerInvitation(in: app)
        returnToListIfNeeded(in: app)
        XCTAssertTrue(app.staticTexts["tripsRefreshError"].waitForExistence(timeout: 5))
        XCTAssertFalse(invitation(in: app).exists)
        XCTAssertFalse(app.buttons["tripInvitationAccept"].exists)
        capture("ClosedInvitationRemovedAfterConflict")
    }

    func testOfflineConflictRecoveryKeepsTheCacheUntilExplicitReload() {
        let app = launch(offline: true)
        answerInvitation(in: app)
        let done = app.buttons["tripInvitationDone"]
        XCTAssertTrue(done.waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["만료된 여행 초대"].exists)
        XCTAssertFalse(app.buttons["tripInvitationAccept"].exists)
        capture("ClosedInvitationExplainsTheFailure")
        done.tap()
        XCTAssertTrue(app.staticTexts["tripsRefreshError"].waitForExistence(timeout: 5))
        XCTAssertTrue(invitation(in: app).exists)
        app.buttons["tripsRefresh"].tap()
        XCTAssertTrue(app.staticTexts["받은 초대가 없어요."].waitForExistence(timeout: 5))
        XCTAssertFalse(invitation(in: app).exists)
        XCTAssertFalse(app.staticTexts["tripsRefreshError"].exists)
        capture("ClosedInvitationExplicitReload")
    }

    private func launch(offline: Bool = false) -> XCUIApplication {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["-walkthrough.step", "finished", "-course-discovery-live-ui", "-trip-invitation-closed-ui"]
        if offline { app.launchArguments.append("-trip-invitation-reload-offline") }
        app.launch()
        XCTAssertTrue(invitation(in: app).waitForExistence(timeout: 8))
        return app
    }

    private func invitation(in app: XCUIApplication) -> XCUIElement {
        app.buttons["accountTripInvite-" + String(repeating: "c", count: 32)]
    }

    private func answerInvitation(in app: XCUIApplication) {
        invitation(in: app).tap()
        app.buttons["tripInvitationAccept"].tap()
    }

    private func returnToListIfNeeded(in app: XCUIApplication) {
        let done = app.buttons["tripInvitationDone"]
        if done.waitForExistence(timeout: 3) { done.tap() }
    }

    private func capture(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
