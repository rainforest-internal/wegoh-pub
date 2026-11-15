import XCTest

@MainActor
final class CourseDiscoveryLiveUITests: XCTestCase {
    func testEmptySubscriptionNewsCentersItsTitleAndMessageWithinTheCard() {
        let app = launch()
        tap(app.buttons["coursesSection-subscriptions"], in: app)
        let title = app.staticTexts["새 구독 소식이 없어요"]
        reveal(title, in: app)
        let message = app.staticTexts["구독한 창작자의 새 경로가 여기에 표시돼요."]
        XCTAssertTrue(title.isHittable)
        XCTAssertTrue(message.isHittable)
        XCTAssertEqual(title.frame.midX, app.frame.midX, accuracy: 2)
        XCTAssertEqual(message.frame.midX, title.frame.midX, accuracy: 2)
        XCTAssertLessThanOrEqual(title.frame.maxY, message.frame.minY)
        let screenshot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        screenshot.name = "CenteredEmptySubscriptionNews"
        screenshot.lifetime = .keepAlways
        add(screenshot)
    }

    func testInitialLibraryLoadShowsStatusBeforeAnyAccountOrEmptyContent() {
        let app = launch(["-course-discovery-delayed-library"])
        let loading = app.descendants(matching: .any)["wegoLoading"].firstMatch
        XCTAssertTrue(loading.waitForExistence(timeout: 2))
        XCTAssertFalse(app.buttons["coursesLogin"].exists)
        XCTAssertFalse(app.staticTexts["courseDiscoverySearchEmpty"].exists)
        XCTAssertFalse(app.buttons["courseDiscovery-test-coast"].exists)
        let screenshot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        screenshot.name = "InitialCourseListLoading"
        screenshot.lifetime = .keepAlways
        add(screenshot)
        XCTAssertTrue(app.buttons["courseDiscovery-test-coast"].waitForExistence(timeout: 6))
        XCTAssertFalse(loading.exists)
    }

    func testTagResultsShowActualRelatedTagsAndCreatorProfile() {
        let app = launch()
        tap(app.buttons["courseFilter-바다"], in: app)
        XCTAssertTrue(app.staticTexts["courseTagTitle"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["courseRelatedTag-커피"].exists)
        tap(app.buttons["courseTagCreator-team-" + String(repeating: "b", count: 40)], in: app)
        XCTAssertTrue(app.staticTexts["courseCreatorName"].waitForExistence(timeout: 5))
        XCTAssertEqual(app.staticTexts["courseCreatorName"].label, "사용자G")
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = "LiveCreatorProfile"
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    func testPublicTagOpensSearchWithoutChangingSubscription() {
        let app = launch()
        tap(app.buttons["courseDiscovery-test-coast"], in: app)
        XCTAssertTrue(app.staticTexts["coursePublicTitle"].waitForExistence(timeout: 5))
        tap(app.buttons["coursePublicTag-바다"], in: app)
        XCTAssertTrue(app.staticTexts["courseTagTitle"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["courseTagFollow-바다"].label.contains("태그 구독"))
        XCTAssertFalse(app.buttons["courseTagFollow-바다"].label.contains("해제"))
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = "LiveTagResults"
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    func testSearchAndTagsFilterRealLibraryInlineAndReset() {
        let app = launch()
        let coast = app.buttons["courseDiscovery-test-coast"]
        let beach = app.buttons["courseDiscovery-test-beach"]
        XCTAssertTrue(coast.waitForExistence(timeout: 8))
        XCTAssertTrue(beach.exists)

        tap(app.buttons["courseFilter-바다"], in: app)
        tap(app.buttons["courseFilter-커피"], in: app)
        XCTAssertTrue(beach.waitForNonExistence(timeout: 5))
        XCTAssertTrue(coast.exists)
        XCTAssertFalse(app.staticTexts["coursePublicTitle"].exists)
        XCTAssertTrue(app.buttons["courseFilter-바다"].isSelected)
        XCTAssertTrue(app.buttons["courseFilter-커피"].isSelected)
        let input = app.textFields["courseDiscoverySearch"]
        tap(input, in: app)
        input.typeText("ocean\n")
        XCTAssertTrue(app.staticTexts["courseDiscoverySearchEmpty"].waitForExistence(timeout: 5))
        tap(app.buttons["courseFilter-all"], in: app)
        XCTAssertTrue(beach.waitForExistence(timeout: 5))
        XCTAssertTrue(coast.exists)
    }

    func testFollowsSavedAndReadStatesComeFromAccountLibrary() {
        let app = launch()
        tap(app.buttons["courseFilter-커피"], in: app)
        tap(app.buttons["courseTagFollow-커피"], in: app)
        let star = app.buttons["courseStar-test-coast"]
        tap(star, in: app)
        expect(star, "value == %@", "저장됨")
        let creator = app.buttons["courseFollow-test-coast"]
        tap(creator, in: app)
        expect(creator, "label CONTAINS %@", "해제")
        tap(app.buttons["coursesSection-subscriptions"], in: app)
        XCTAssertTrue(app.buttons["courseFollowingTag-커피"].waitForExistence(timeout: 5))
        expect(app.staticTexts["courseFollowingCount"], "label CONTAINS %@", "1")
        reveal(app.buttons["courseSaved-test-coast"], in: app)
        XCTAssertTrue(app.buttons["courseSaved-test-coast"].exists)
        let unread = app.staticTexts["courseNewsUnreadCount"]
        reveal(unread, in: app)
        expect(unread, "label CONTAINS %@", "1")
        tap(app.buttons["courseNews-12"], in: app)
        XCTAssertTrue(app.staticTexts["coursePublicTitle"].waitForExistence(timeout: 5))
        app.navigationBars.buttons.firstMatch.tap()
        reveal(unread, in: app)
        expect(unread, "label CONTAINS %@", "0")
        tap(app.buttons["courseFollowingTag-커피"], in: app)
        XCTAssertTrue(app.buttons["courseFollowingTag-커피"].waitForNonExistence(timeout: 5))
        reveal(app.buttons["courseSaved-test-coast"], in: app)
        XCTAssertTrue(app.buttons["courseSaved-test-coast"].exists)
    }

    func testPublicCourseAddsToTripAndCopiesWithoutRightsConsent() {
        let app = launch()
        tap(app.buttons["courseDiscovery-test-coast"], in: app)
        XCTAssertTrue(app.staticTexts["coursePublicTitle"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["courseEdit"].exists)
        tap(app.buttons["coursePublicAddToTrip"], in: app)
        tap(app.buttons["courseTripAdd-" + String(repeating: "c", count: 32)], in: app)
        XCTAssertTrue(app.staticTexts["coursePublicNotice"].waitForExistence(timeout: 5))
        tap(app.buttons["coursePublicImport"], in: app)
        let title = app.textFields["courseTitle"]
        XCTAssertTrue(title.waitForExistence(timeout: 5))
        XCTAssertEqual(title.value as? String, "해안 커피길")
        let rights = app.switches["courseRights"]
        XCTAssertTrue(rights.exists)
        XCTAssertEqual(rights.value as? String, "0")
        XCTAssertFalse(app.buttons["courseSave"].isEnabled)
    }

    func testTemporaryFailureCanBeRetriedAndSignedOutHasNoPublicAccountFeed() {
        let app = launch(["-course-discovery-fail-once"])
        XCTAssertTrue(app.staticTexts["courseDiscoveryError"].waitForExistence(timeout: 5))
        tap(app.buttons["다시 시도"], in: app)
        XCTAssertTrue(app.buttons["courseDiscovery-test-coast"].waitForExistence(timeout: 5))
        app.terminate()
        let signedOut = launch(["-courses-ui-signed-out"])
        XCTAssertTrue(signedOut.buttons["coursesLogin"].waitForExistence(timeout: 5))
        XCTAssertFalse(signedOut.buttons["courseDiscovery-test-coast"].exists)
    }

    func testRevokedSessionDuringStarClosesPreviousAccountFeed() {
        let app = launch(["-course-discovery-expired"])
        tap(app.buttons["courseStar-test-coast"], in: app)
        XCTAssertTrue(app.buttons["courseDiscovery-test-coast"].waitForNonExistence(timeout: 6))
        XCTAssertTrue(app.buttons["coursesLogin"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["courseSaved-test-coast"].exists)
    }

    private func launch(_ extra: [String] = []) -> XCUIApplication {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["-walkthrough.step", "finished", "-course-discovery-live-ui", "-trips-ui-preview"] + extra
        app.launch()
        let courseTab = app.tabBars.buttons["경로"]
        XCTAssertTrue(courseTab.waitForExistence(timeout: 8))
        courseTab.tap()
        return app
    }

    private func tap(_ element: XCUIElement, in app: XCUIApplication,
                     file: StaticString = #filePath, line: UInt = #line) {
        reveal(element, in: app, file: file, line: line)
        element.tap()
    }

    private func reveal(_ element: XCUIElement, in app: XCUIApplication,
                        file: StaticString = #filePath, line: UInt = #line) {
        for _ in 0..<12 {
            if !element.exists { app.swipeUp(); continue }
            let tabs = app.tabBars.firstMatch
            let navigation = app.navigationBars.firstMatch
            let bottom = tabs.exists && tabs.isHittable ? tabs.frame.minY : app.frame.maxY
            let top = navigation.exists && navigation.isHittable ? navigation.frame.maxY : app.frame.minY
            if element.frame.minY < top { app.swipeDown() }
            else if element.frame.maxY > bottom || !element.isHittable { app.swipeUp() }
            else { break }
        }
        XCTAssertTrue(element.exists, element.identifier, file: file, line: line)
        XCTAssertTrue(element.isHittable, element.identifier, file: file, line: line)
    }

    private func expect(_ element: XCUIElement, _ format: String, _ value: String,
                        file: StaticString = #filePath, line: UInt = #line) {
        let ready = XCTNSPredicateExpectation(predicate: NSPredicate(format: format, value), object: element)
        XCTAssertEqual(XCTWaiter.wait(for: [ready], timeout: 5), .completed, file: file, line: line)
    }
}
