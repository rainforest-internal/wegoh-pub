import XCTest

@MainActor
final class TripSharedStartTests: XCTestCase {
    func testSingleJoinRemainsSharedAndOffersSignals() {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["-trip-route-ui-testing", "full-single-shared"]
        app.launch()
        let headline = app.staticTexts["공유 경로 진행 중"]
        XCTAssertTrue(headline.waitForExistence(timeout: 8))
        for _ in 0..<10 where !headline.isHittable { app.swipeUp() }
        XCTAssertTrue(headline.isHittable)
        let signal = app.buttons["tripLiveSignal"]
        for _ in 0..<10 where !signal.isHittable { app.swipeUp() }
        XCTAssertTrue(signal.isEnabled)
        XCTAssertFalse(app.staticTexts["공유 경로가 끝나 새 손들기를 보낼 수 없어요."].exists)
        let screenshot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        screenshot.name = "SingleJoin-SharedStarted"
        screenshot.lifetime = .keepAlways
        add(screenshot)
    }
}
