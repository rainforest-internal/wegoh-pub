import XCTest

@MainActor
final class TripMultiInvitationTests: XCTestCase {
    func testSelectsSeveralFriendsAndKeepsPartialFailureVisible() {
        let app = launch()
        let first = friend(4, app), failed = friend(5, app)
        XCTAssertFalse(friend(2, app).isEnabled)
        XCTAssertFalse(friend(3, app).isEnabled)
        reveal(first, in: app); first.tap()
        reveal(failed, in: app); failed.tap()
        let send = app.buttons["tripInviteSendSelected"]
        XCTAssertEqual(send.label, "2명 초대")
        capture("TripMultiInvite-Selected")
        send.tap()
        XCTAssertTrue(app.staticTexts["tripInviteSummary"].waitForExistence(timeout: 8))
        XCTAssertFalse(first.isEnabled)
        XCTAssertEqual(first.value as? String, "초대 보냄")
        XCTAssertTrue(app.staticTexts["tripInviteFailure-" + account(5)].waitForExistence(timeout: 5))
        XCTAssertEqual(send.label, "1명 초대")
        capture("TripMultiInvite-PartialFailure")
    }

    func testSavedInviteSurvivesRefreshFailureAndKeepsRemainingSelection() {
        let app = launch(extra: ["-trip-multi-invite-refresh-fails"])
        let first = friend(4, app), next = friend(6, app)
        reveal(first, in: app); first.tap()
        reveal(next, in: app); next.tap()
        let send = app.buttons["tripInviteSendSelected"]
        send.tap()
        let reload = app.buttons["tripInviteReload"]
        XCTAssertTrue(reload.waitForExistence(timeout: 8))
        XCTAssertFalse(send.isEnabled)
        XCTAssertFalse(first.isEnabled)
        capture("TripMultiInvite-RefreshFailure")
        reveal(reload, in: app); reload.tap()
        XCTAssertTrue(send.waitForExistence(timeout: 5))
        XCTAssertTrue(send.isEnabled)
        XCTAssertEqual(send.label, "1명 초대")
        send.tap()
        XCTAssertTrue(app.staticTexts.matching(NSPredicate(format: "identifier == %@ AND label == %@", "tripInviteSummary", "2명에게 초대를 보냈어요.")).firstMatch.waitForExistence(timeout: 5))
        XCTAssertEqual(app.staticTexts["tripInviteSummary"].label, "2명에게 초대를 보냈어요.")
        capture("TripMultiInvite-Recovered")
    }

    private func launch(extra: [String] = []) -> XCUIApplication {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["-trip-multi-invite-ui-testing"] + extra
        app.launch()
        let invite = app.buttons["tripPreparingInvite"]
        XCTAssertTrue(invite.waitForExistence(timeout: 8)); invite.tap()
        XCTAssertTrue(app.buttons["tripInviteSendSelected"].waitForExistence(timeout: 5))
        return app
    }
    private func account(_ number: Int) -> String { "team-" + String(repeating: String(number), count: 40) }
    private func friend(_ number: Int, _ app: XCUIApplication) -> XCUIElement { app.buttons["tripInviteFriend-" + account(number)] }
    private func reveal(_ element: XCUIElement, in app: XCUIApplication) {
        XCTAssertTrue(element.waitForExistence(timeout: 5))
        for _ in 0..<12 where !element.isHittable {
            if element.frame.minY < app.frame.midY { app.swipeDown() } else { app.swipeUp() }
        }
        XCTAssertTrue(element.isHittable)
    }
    private func capture(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name; attachment.lifetime = .keepAlways; add(attachment)
    }
}
