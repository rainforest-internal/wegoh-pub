import notify
import XCTest

@MainActor
final class TripInvitationPushTests: XCTestCase {
    private let tripID = String(repeating: "c", count: 32)

    func testOpeningPushShowsPendingInvitationAndCanJoinDirectly() {
        let app = launch()
        assertReview(in: app)
        let screenshot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        screenshot.name = "PushPendingTripInvitation"
        screenshot.lifetime = .keepAlways
        add(screenshot)

        app.buttons["tripInvitationAccept"].tap()
        let done = app.buttons["tripInvitationDone"]
        XCTAssertTrue(done.waitForExistence(timeout: 5))
        done.tap()
        XCTAssertTrue(app.buttons["accountTrip-" + tripID].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["accountTripInvite-" + tripID].exists)
    }

    func testForegroundInvitationRefreshesVisibleListWithoutOpeningReview() {
        let app = launch(["-trip-push-foreground-ui"])
        let currentTrip = app.buttons["accountTrip-" + String(repeating: "a", count: 32)]
        let incoming = app.buttons["accountTripInvite-" + tripID]
        let empty = app.staticTexts["받은 초대가 없어요."]
        XCTAssertTrue(currentTrip.waitForExistence(timeout: 8))
        XCTAssertTrue(empty.exists)
        XCTAssertFalse(incoming.exists)

        XCTAssertEqual(notify_post("io.wegoh.iphone.tests.tripInvitationArrived"), UInt32(NOTIFY_STATUS_OK))
        XCTAssertTrue(incoming.waitForExistence(timeout: 8))
        XCTAssertTrue(currentTrip.exists)
        XCTAssertFalse(empty.exists)
        XCTAssertFalse(app.buttons["tripInvitationAccept"].exists)
        let screenshot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        screenshot.name = "ForegroundInvitationInExistingTripList"
        screenshot.lifetime = .keepAlways
        add(screenshot)

        incoming.tap()
        assertReview(in: app)
    }

    func testReturningFromBackgroundShowsAnInvitationWithoutAPushAndKeepsNormalTabSwitchCached() {
        let app = launch(["-trip-push-foreground-ui", "-trip-push-muted-ui"])
        let existing = app.buttons["accountTrip-" + String(repeating: "a", count: 32)]
        let incoming = app.buttons["accountTripInvite-" + tripID]
        let travelTab = app.tabBars.buttons["여행"]
        let settingsTab = app.tabBars.buttons["설정"]
        XCTAssertTrue(existing.waitForExistence(timeout: 8))
        XCTAssertFalse(incoming.exists)
        settingsTab.tap()
        XCTAssertEqual(notify_post("io.wegoh.iphone.tests.tripInvitationArrived"), 0)
        travelTab.tap()
        XCTAssertTrue(existing.waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["받은 초대가 없어요."].exists)
        XCTAssertFalse(incoming.exists)

        settingsTab.tap()
        XCUIDevice.shared.press(.home)
        XCTAssertTrue(app.wait(for: .runningBackground, timeout: 5))
        app.activate()
        XCTAssertTrue(app.wait(for: .runningForeground, timeout: 5))
        XCTAssertTrue(settingsTab.isSelected)
        for _ in 0..<2 where !travelTab.isSelected {
            travelTab.tap()
            let selected = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in travelTab.isSelected }, object: nil)
            _ = XCTWaiter.wait(for: [selected], timeout: 2)
        }
        XCTAssertTrue(travelTab.isSelected)
        XCTAssertTrue(incoming.waitForExistence(timeout: 8))
        XCTAssertTrue(existing.exists)
        XCTAssertFalse(app.buttons["tripInvitationAccept"].exists)
    }

    func testClosingPushLeavesInvitationPendingAndDeclineRequiresConfirmation() {
        let app = launch()
        assertReview(in: app)
        app.navigationBars.buttons.firstMatch.tap()
        let invitation = app.buttons["accountTripInvite-" + tripID]
        XCTAssertTrue(invitation.waitForExistence(timeout: 5))
        invitation.tap()
        app.buttons["tripInvitationDecline"].tap()
        let cancel = app.buttons["tripInvitationDeclineCancel"]
        XCTAssertTrue(cancel.waitForExistence(timeout: 5))
        cancel.tap()
        XCTAssertTrue(app.buttons["tripInvitationAccept"].exists)
        app.buttons["tripInvitationDecline"].tap()
        app.buttons["tripInvitationDeclineConfirm"].tap()
        XCTAssertTrue(app.staticTexts["받은 초대가 없어요."].waitForExistence(timeout: 5))
        XCTAssertFalse(invitation.exists)
        XCTAssertFalse(app.buttons["accountTrip-" + tripID].exists)
    }

    func testObsoleteInvitationPushStaysOnListWithNotice() {
        let app = launch(["-trip-push-expired"])
        let notice = app.descendants(matching: .any).matching(identifier: "tripPushNotice").firstMatch
        XCTAssertTrue(notice.waitForExistence(timeout: 8))
        XCTAssertTrue(app.staticTexts["받은 초대가 없어요."].exists)
        XCTAssertFalse(app.buttons["tripInvitationAccept"].exists)
        XCTAssertFalse(app.buttons["accountTrip-" + tripID].exists)
    }

    private func launch(_ extra: [String] = []) -> XCUIApplication {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["-walkthrough.step", "finished", "-course-discovery-live-ui", "-trip-push-invitation-ui"] + extra
        app.launch()
        return app
    }

    private func assertReview(in app: XCUIApplication, file: StaticString = #filePath, line: UInt = #line) {
        let title = app.staticTexts["inviteDetailTitle"]
        XCTAssertTrue(title.waitForExistence(timeout: 8), file: file, line: line)
        XCTAssertEqual(title.label, "강릉 바다 여행", file: file, line: line)
        XCTAssertTrue(app.buttons["tripInvitationAccept"].isHittable, file: file, line: line)
        XCTAssertTrue(app.buttons["tripInvitationDecline"].exists, file: file, line: line)
    }
}
