import XCTest

@MainActor
final class TripInvitationTests: XCTestCase {
    func testAcceptanceReturnsToTheListWithoutASeparateSharingChoice() {
        let app = launchInvitation()
        capture("TripInvitation")
        app.buttons["tripInvitationAccept"].tap()
        let done = app.buttons["tripInvitationDone"]
        XCTAssertTrue(done.waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["tripInvitationAccept"].exists)
        capture("TripInvitationAccepted")
        done.tap()
        XCTAssertTrue(app.buttons["tripAccepted-jeju"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["tripInvite-jeju"].exists)
        app.buttons["tripAccepted-jeju"].tap()
        XCTAssertTrue(app.buttons["tripInvitationDone"].waitForExistence(timeout: 5))
    }

    func testDeclineRequiresConfirmationAndReturnsToTheList() {
        let app = launchInvitation()
        app.buttons["tripInvitationDecline"].tap()
        XCTAssertTrue(app.buttons["tripInvitationDeclineConfirm"].waitForExistence(timeout: 5))
        app.buttons["tripInvitationDeclineCancel"].tap()
        XCTAssertTrue(app.buttons["tripInvitationAccept"].exists)
        app.buttons["tripInvitationDecline"].tap()
        app.buttons["tripInvitationDeclineConfirm"].tap()
        XCTAssertTrue(app.staticTexts["샘플 여행"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["tripInvite-jeju"].exists)
        XCTAssertFalse(app.buttons["tripAccepted-jeju"].exists)
    }

    private func launchInvitation() -> XCUIApplication {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["-walkthrough.step", "finished", "-trips-ui-preview"]
        app.launch()
        let invitation = app.buttons["tripInvite-jeju"]
        XCTAssertTrue(invitation.waitForExistence(timeout: 5))
        invitation.tap()
        XCTAssertTrue(app.staticTexts["inviteDetailTitle"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.staticTexts["tripDetailTitle"].exists)
        return app
    }

    private func capture(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
