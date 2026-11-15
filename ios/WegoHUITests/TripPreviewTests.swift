import XCTest

@MainActor
final class TripPreviewTests: XCTestCase {
    func testTravelHomeShowsInvitationsAndMemberTrips() {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["-walkthrough.step", "finished", "-trips-ui-preview"]
        app.launch()

        let travel = app.tabBars.buttons["여행"]
        XCTAssertTrue(travel.waitForExistence(timeout: 5))
        XCTAssertTrue(travel.isSelected)
        XCTAssertTrue(app.staticTexts["샘플 여행"].exists)
        capture("TravelHome")

        revealAndOpen("tripInvite-jeju", in: app)
        let invite = app.staticTexts["inviteDetailTitle"]
        XCTAssertTrue(invite.waitForExistence(timeout: 5))
        XCTAssertEqual(invite.label, "제주 동쪽 한 바퀴")
        XCTAssertFalse(app.staticTexts["tripDetailTitle"].exists)
        app.navigationBars.buttons.firstMatch.tap()

        for (id, title) in [("gangneung", "서해안 드라이브"), ("yangpyeong", "양평 두물머리 나들이"), ("suwon", "수원 화성 산책")] {
            revealAndOpen("trip-\(id)", in: app)
            let detail = app.staticTexts["tripDetailTitle"]
            XCTAssertTrue(detail.waitForExistence(timeout: 5))
            XCTAssertEqual(detail.label, title)
            if id == "gangneung" { capture("TravelDetail") }
            app.navigationBars.buttons.firstMatch.tap()
        }

        app.tabBars.buttons["설정"].tap()
        let profile = app.descendants(matching: .any)["settingsProfile"].firstMatch
        XCTAssertTrue(profile.waitForExistence(timeout: 5))
        profile.tap()
        XCTAssertTrue(app.navigationBars["프로필"].waitForExistence(timeout: 5))
    }

    private func revealAndOpen(_ id: String, in app: XCUIApplication) {
        let button = app.buttons[id]
        for _ in 0..<5 where !button.isHittable { app.swipeUp() }
        XCTAssertTrue(button.isHittable, id)
        button.tap()
    }

    private func capture(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
