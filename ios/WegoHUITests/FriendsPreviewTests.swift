import XCTest

@MainActor
final class FriendsPreviewTests: XCTestCase {
    func testAcceptAndBlockFriendKeepListsInSync() {
        let app = launchFriends()
        let accept = app.buttons["friendAccept-team-4444444444444444444444444444444444444444"]
        reveal(accept, in: app)
        accept.tap()
        XCTAssertTrue(accept.waitForNonExistence(timeout: 5))

        let profile = app.buttons["friendProfile-team-4444444444444444444444444444444444444444"]
        reveal(profile, in: app)
        profile.tap()
        XCTAssertTrue(app.staticTexts["사용자E"].firstMatch.waitForExistence(timeout: 5))
        XCTAssertFalse(app.staticTexts["차량 번호"].exists)

        reveal(app.buttons["friendBlock"], in: app)
        app.buttons["friendBlock"].tap()
        XCTAssertTrue(app.alerts.buttons["취소"].waitForExistence(timeout: 3))
        app.alerts.buttons["취소"].tap()
        XCTAssertTrue(app.staticTexts["사용자E"].firstMatch.exists)
        app.buttons["friendBlock"].tap()
        app.alerts.buttons["친구 차단"].tap()
        XCTAssertTrue(app.buttons["friendsAdd"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["friendProfile-team-4444444444444444444444444444444444444444"].exists)

        let blocked = app.descendants(matching: .any)["friendsBlocked"].firstMatch
        reveal(blocked, in: app)
        blocked.tap()
        let unblock = app.buttons["friendUnblock-team-4444444444444444444444444444444444444444"]
        reveal(unblock, in: app)
        unblock.tap()
        XCTAssertFalse(unblock.exists)
        XCTAssertFalse(app.buttons["friendProfile-team-4444444444444444444444444444444444444444"].exists)
    }

    func testSearchAndSendRequestWithoutDuplicatingIt() {
        let app = launchFriends()
        capture("FriendsHome")
        app.buttons["friendsAdd"].tap()
        let input = app.textFields["friendCodeInput"]
        XCTAssertTrue(input.waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["friendSearch"].isEnabled)
        input.tap()
        input.typeText("UNKNOWN")
        app.buttons["friendSearch"].tap()
        XCTAssertTrue(app.staticTexts["friendSearchEmpty"].waitForExistence(timeout: 5))

        input.tap()
        input.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: 7) + "nara2048")
        app.buttons["friendSearch"].tap()
        let send = app.buttons["friendSendRequest"]
        XCTAssertTrue(send.waitForExistence(timeout: 5))
        send.tap()
        XCTAssertTrue(app.staticTexts["friendRequestSent"].waitForExistence(timeout: 5))
        XCTAssertFalse(send.exists)
        capture("FriendSearchRequestSent")
        app.buttons["friendAddDone"].tap()

        let outgoing = app.descendants(matching: .any)["friendsOutgoing"].firstMatch
        reveal(outgoing, in: app)
        outgoing.tap()
        let cancel = app.buttons["friendCancel-team-8888888888888888888888888888888888888888"]
        reveal(cancel, in: app)
        cancel.tap()
        XCTAssertTrue(cancel.waitForNonExistence(timeout: 5))
        app.tabBars.buttons["여행"].tap()
        XCTAssertTrue(app.buttons["tripsLogin"].waitForExistence(timeout: 5))
        XCTAssertEqual(app.buttons["tripsLogin"].label, "다시 로그인")
        app.tabBars.buttons["설정"].tap()
        XCTAssertTrue(app.buttons["settingsProfile"].waitForExistence(timeout: 5))
    }

    private func launchFriends() -> XCUIApplication {
        continueAfterFailure = false
        XCUIDevice.shared.orientation = .portrait
        let app = XCUIApplication()
        app.launchArguments = ["-walkthrough.step", "finished", "-friends-ui-testing"]
        app.launch()
        let friends = app.tabBars.buttons["친구"]
        XCTAssertTrue(friends.waitForExistence(timeout: 5))
        friends.tap()
        XCTAssertTrue(app.buttons["friendsAdd"].waitForExistence(timeout: 5))
        return app
    }

    private func reveal(_ element: XCUIElement, in app: XCUIApplication) {
        for _ in 0..<8 where !element.isHittable { app.swipeUp() }
        XCTAssertTrue(element.isHittable, element.identifier)
    }

    private func capture(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
