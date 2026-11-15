import XCTest

@MainActor
final class TripMusicTests: XCTestCase {
    func testExplicitSharingAndRightsAddOnePrivateLinkAndCanRevoke() {
        let app = openMusic()
        let sharing = app.switches["tripMusicSharing"]
        XCTAssertEqual(sharing.value as? String, "0")
        sharing.tap()
        fillDraft(in: app)
        let add = app.buttons["tripMusicAdd"]
        XCTAssertFalse(add.isEnabled)
        reveal(app.switches["tripMusicRights"], in: app).tap()
        XCTAssertEqual(app.switches["tripMusicReview"].value as? String, "0")
        XCTAssertTrue(add.isEnabled)
        reveal(add, in: app).tap()
        XCTAssertTrue(app.staticTexts.matching(identifier: "tripMusicMessage").matching(NSPredicate(format: "label CONTAINS %@", "나에게만")).firstMatch.waitForExistence(timeout: 5))
        capture("TripMusic-PrivateAdded")
        for _ in 0..<6 where !sharing.isHittable { app.swipeDown() }
        sharing.tap()
        XCTAssertTrue(app.staticTexts["tripMusicEmpty"].waitForExistence(timeout: 5))
        XCTAssertEqual(sharing.value as? String, "0")
    }

    func testLostPOSTResponseLocksRepeatedAddUntilExplicitListConfirmation() {
        let app = openMusic(lost: true)
        app.switches["tripMusicSharing"].tap()
        fillDraft(in: app)
        reveal(app.switches["tripMusicRights"], in: app).tap()
        let add = reveal(app.buttons["tripMusicAdd"], in: app)
        add.tap()
        XCTAssertTrue(app.staticTexts.matching(identifier: "tripMusicMessage").matching(NSPredicate(format: "label CONTAINS %@", "추가 결과를 확인하지 못했어요")).firstMatch.waitForExistence(timeout: 5))
        XCTAssertFalse(add.isEnabled)
        XCTAssertEqual(app.textFields["tripMusicTitle"].value as? String, "합성 음악")
        capture("TripMusic-UnknownResult")
        reveal(app.buttons["tripMusicReload"], in: app).tap()
        XCTAssertTrue(app.staticTexts.matching(identifier: "tripMusicMessage").matching(NSPredicate(format: "label CONTAINS %@", "현재 공유 설정과 목록")).firstMatch.waitForExistence(timeout: 5))
        XCTAssertTrue(app.descendants(matching: .any)["tripMusicItem-" + String(format: "%032x", 1)].waitForExistence(timeout: 5))
        capture("TripMusic-ConfirmedAfterLostResponse")
    }

    private func openMusic(lost: Bool = false) -> XCUIApplication {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["-trip-music-ui-testing"]
        if lost { app.launchArguments.append("-trip-music-post-lost") }
        app.launch()
        reveal(app.buttons["tripProgressMusic"], in: app).tap()
        XCTAssertTrue(app.switches["tripMusicSharing"].waitForExistence(timeout: 8))
        return app
    }
    private func fillDraft(in app: XCUIApplication) {
        let title = reveal(app.textFields["tripMusicTitle"], in: app); title.tap(); title.typeText("합성 음악")
        let url = reveal(app.textFields["tripMusicURL"], in: app); url.tap(); url.typeText("https://open.spotify.com/playlist/sample")
        app.swipeUp()
    }
    @discardableResult private func reveal(_ element: XCUIElement, in app: XCUIApplication) -> XCUIElement {
        XCTAssertTrue(element.waitForExistence(timeout: 5))
        for _ in 0..<8 where !element.isHittable { app.swipeUp() }
        XCTAssertTrue(element.isHittable)
        return element
    }
    private func capture(_ name: String) {
        let value = XCTAttachment(screenshot: XCUIScreen.main.screenshot()); value.name = name; value.lifetime = .keepAlways; add(value)
    }
}
