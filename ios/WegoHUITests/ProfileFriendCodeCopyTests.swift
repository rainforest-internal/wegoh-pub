import XCTest

@MainActor
final class ProfileFriendCodeCopyTests: XCTestCase {
    func testCopyConfirmationKeepsFriendCodeEditingAvailable() {
        let app = launch()
        let copy = app.buttons["profileCopyFriendCode"]
        XCTAssertTrue(copy.waitForExistence(timeout: 8))
        XCTAssertEqual(copy.label, "친구 코드 복사")
        XCTAssertEqual(copy.value as? String, "user-d.drive")
        XCTAssertGreaterThanOrEqual(copy.frame.height, 44)
        copy.tap()
        XCTAssertTrue(app.staticTexts["profileFriendCodeCopied"].waitForExistence(timeout: 3))
        capture("ProfileFriendCodeCopied")
        let edit = app.buttons["profileEditHandle"]
        for _ in 0..<4 where !edit.isHittable { app.swipeUp() }
        edit.tap()
        let input = app.textFields["profileEditInput"]
        XCTAssertTrue(input.waitForExistence(timeout: 5))
        XCTAssertEqual(input.value as? String, "user-d.drive")
        XCTAssertFalse(app.buttons["profileSave"].isEnabled)
    }

    private func launch() -> XCUIApplication {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["-walkthrough.step", "finished", "-profile-ui-testing"]
        app.launch()
        app.tabBars.buttons["설정"].tap()
        let profile = app.buttons["settingsProfile"]
        XCTAssertTrue(profile.waitForExistence(timeout: 5))
        profile.tap()
        return app
    }

    private func capture(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
