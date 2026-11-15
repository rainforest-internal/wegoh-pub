import XCTest

@MainActor
final class TripCompletedTests: XCTestCase {
    func testCompletedTripShowsFinalSummaryParticipantsAndReadOnlySampleRecord() {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["-walkthrough.step", "finished", "-trips-ui-preview"]
        app.launch()
        let trip = app.buttons["trip-suwon"]
        for _ in 0..<8 where !trip.isHittable { app.swipeUp() }
        XCTAssertTrue(trip.isHittable)
        trip.tap()
        XCTAssertTrue(app.staticTexts["tripDetailTitle"].waitForExistence(timeout: 5))
        XCTAssertEqual(app.staticTexts["tripDetailTitle"].label, "수원 화성 산책")
        XCTAssertTrue(app.staticTexts["10월 24일 (토) · 만든 사람 사용자D"].exists)
        XCTAssertTrue(app.staticTexts["모든 경로 완료"].exists)
        XCTAssertEqual(app.staticTexts["tripCompletedSummary"].label, "일행 5명 · 차량 2대 · 완료한 차 2/2")
        XCTAssertFalse(app.staticTexts["tripCompletedScore-suwon-fortress"].exists)
        XCTAssertFalse(app.buttons["tripPreparingStart"].exists)
        capture("TripCompleted")
        let records = app.buttons["tripCompletedRecords"]
        for _ in 0..<6 where !records.isHittable || records.frame.maxY > app.tabBars.firstMatch.frame.minY { app.swipeUp() }
        XCTAssertTrue(records.isHittable)
        capture("TripCompletedParticipants")
        records.tap()
        XCTAssertTrue(app.staticTexts["tripCompletedSampleRecord"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.textFields.allElementsBoundByIndex.isEmpty)
        capture("TripCompletedSampleRecord")
        app.buttons["닫기"].tap()
        XCTAssertTrue(app.staticTexts["tripDetailTitle"].waitForExistence(timeout: 5))
        app.navigationBars.buttons.firstMatch.tap()
        XCTAssertTrue(trip.waitForExistence(timeout: 5))
        XCTAssertTrue(app.tabBars.buttons["경로"].exists)
    }

    private func capture(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
