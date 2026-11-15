import XCTest

@MainActor final class NotificationSettingsTests: XCTestCase {
    func testNotificationsExplainEventsAndOfferSystemSettingsBeforePermissionRequest() {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["-walkthrough.step", "finished", "-friends-ui-testing"]
        app.launch()
        XCTAssertTrue(app.tabBars.buttons["설정"].waitForExistence(timeout: 10))
        app.tabBars.buttons["설정"].tap()
        let row = app.buttons["settingsNotifications"]
        XCTAssertTrue(row.waitForExistence(timeout: 5))
        row.tap()
        XCTAssertTrue(app.staticTexts["친구와 여행 소식을 바로 받아요"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["notificationsOpenSettings"].exists)
        XCTAssertTrue(app.staticTexts["notificationPermissionStatus"].exists || app.otherElements["notificationPermissionStatus"].exists)
        let screenshot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        screenshot.name = "NotificationSettingsDefaultText"
        screenshot.lifetime = .keepAlways
        add(screenshot)
    }
}
