import XCTest

@MainActor
final class LoadingTests: XCTestCase {
    func testFastRequestDoesNotFlashLoading() {
        let app = launch("fast")
        XCTAssertTrue(app.staticTexts["loadingFixtureComplete"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.otherElements["wegoLoading"].exists)
    }

    func testSlowRequestOffersWaitingAndRetryWithoutLosingThePage() {
        let app = launch("slow")
        XCTAssertTrue(app.staticTexts["wegoLoadingSlow"].waitForExistence(timeout: 12))
        app.buttons["wegoLoadingWait"].tap()
        XCTAssertFalse(app.staticTexts["wegoLoadingSlow"].exists)
        XCTAssertTrue(app.navigationBars["공통 로딩"].exists)
        let retryApp = launch("slow")
        XCTAssertTrue(retryApp.buttons["wegoLoadingRetry"].waitForExistence(timeout: 12))
        retryApp.buttons["wegoLoadingRetry"].tap()
        XCTAssertEqual(retryApp.staticTexts["loadingFixtureRetryCount"].label, "재시도 1")
        XCTAssertTrue(retryApp.staticTexts["wegoLoadingSlow"].waitForExistence(timeout: 12))
    }

    func testFailureRetryAndBusyButton() {
        let app = launch("failure")
        XCTAssertTrue(app.buttons["wegoLoadingFailureRetry"].waitForExistence(timeout: 5))
        app.buttons["wegoLoadingFailureRetry"].tap()
        XCTAssertTrue(app.staticTexts["loadingFixtureComplete"].exists)
        let busy = launch("button")
        XCTAssertTrue(busy.buttons["loadingFixtureSave"].waitForExistence(timeout: 5))
        XCTAssertFalse(busy.buttons["loadingFixtureSave"].isEnabled)
        XCTAssertTrue(busy.staticTexts["이미 입력한 내용은 그대로 보여요."].exists)
    }

    private func launch(_ mode: String) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["-loading-ui-fixture", mode]
        app.launch()
        return app
    }
}
