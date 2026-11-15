import XCTest

@MainActor
final class CourseDiscoveryTests: XCTestCase {
    func testSectionsKeepMyCoursesLiveAndDiscoveryExplicitlySeparate() {
        let app = launch()
        XCTAssertTrue(app.buttons["coursesDiscoveryPreview"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["courseDiscovery-coffee-coast"].exists)
        open("coursesSection-owned", in: app)
        XCTAssertTrue(app.buttons["course-fixture-coast"].waitForExistence(timeout: 5))
        app.buttons["course-fixture-coast"].tap()
        XCTAssertTrue(app.buttons["courseEdit"].waitForExistence(timeout: 5))
        app.navigationBars.buttons.firstMatch.tap()
        open("coursesSection-recommended", in: app)
        open("coursesDiscoveryPreview", in: app)
        XCTAssertTrue(app.buttons["courseDiscovery-coffee-coast"].waitForExistence(timeout: 5))
        capture("CourseRecommendations")
    }

    func testPreviewFollowStarAndNewsStayInSyncAcrossSections() {
        let app = launch()
        open("coursesDiscoveryPreview", in: app)
        open("courseFollow-user-g-sokcho-food", in: app)
        app.buttons["courseStar-sokcho-food"].tap()
        open("coursesPreviewSection-subscriptions", in: app)
        XCTAssertTrue(app.buttons["courseFollowing-user-g"].waitForExistence(timeout: 5))
        XCTAssertEqual(app.staticTexts["courseFollowingCount"].label, "구독한 창작자 3")
        XCTAssertEqual(app.staticTexts["courseSavedCount"].label, "저장한 경로 3")
        capture("CourseSubscriptions")
        open("courseNews-sokcho-food", in: app)
        XCTAssertTrue(app.staticTexts["coursePublicPreviewTitle"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["courseEdit"].exists)
        capture("CoursePublicPreview")
        app.navigationBars.buttons.firstMatch.tap()
        XCTAssertEqual(app.staticTexts["courseNewsUnreadCount"].label, "읽지 않은 소식 1")
    }

    func testTagAndCreatorSubscriptionsAndSearchArePreviewOnly() {
        let app = launch()
        open("coursesDiscoveryPreview", in: app)
        let preview = previewContent(in: app)
        open("courseDiscovery-sokcho-food", in: app)
        app.buttons.matching(identifier: "courseTag-먹방").firstMatch.tap()
        XCTAssertTrue(app.staticTexts["courseTagPreviewTitle"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.textFields["courseTagSearch"].exists)
        app.buttons["courseTagFollow"].tap()
        capture("CourseTagPreview")
        open("courseTagCreator-user-g", in: app)
        XCTAssertEqual(app.staticTexts["courseCreatorPreviewName"].label, "사용자C")
        app.buttons["courseCreatorFollow"].tap()
        capture("CourseCreatorPreview")
        app.navigationBars.buttons.firstMatch.tap()
        app.navigationBars.buttons.firstMatch.tap()
        app.navigationBars.buttons.firstMatch.tap()
        app.buttons["coursesPreviewSection-subscriptions"].tap()
        XCTAssertTrue(app.buttons["courseFollowingTag-먹방"].waitForExistence(timeout: 5))
        app.buttons["courseFollowingTag-먹방"].tap()
        XCTAssertFalse(app.buttons["courseFollowingTag-먹방"].exists)
        app.buttons["coursesPreviewSection-recommended"].tap()
        let search = preview.textFields["courseDiscoverySearch"]
        reveal(search, in: app, scrollView: preview)
        search.tap(); search.tap(); search.typeText("no-sample-match")
        XCTAssertTrue(preview.staticTexts["courseDiscoverySearchEmpty"].waitForExistence(timeout: 5))
    }

    func testRecommendationTagsFilterInPlaceAndSupportMultipleSelection() {
        let app = launch()
        open("coursesDiscoveryPreview", in: app)
        let preview = previewContent(in: app)
        preview.buttons["courseFilter-바다"].tap()
        XCTAssertTrue(preview.buttons["courseFilter-바다"].isSelected)
        XCTAssertFalse(app.staticTexts["courseTagPreviewTitle"].exists)
        XCTAssertTrue(app.buttons["courseDiscovery-coffee-coast"].exists)
        XCTAssertTrue(app.buttons["courseDiscovery-sunrise"].exists)
        XCTAssertFalse(app.buttons["courseDiscovery-sokcho-food"].exists)
        preview.buttons["courseFilter-드라이브"].tap()
        XCTAssertTrue(preview.buttons["courseFilter-바다"].isSelected)
        XCTAssertTrue(preview.buttons["courseFilter-드라이브"].isSelected)
        XCTAssertFalse(app.buttons["courseDiscovery-yangyang-food"].exists)
        capture("CourseTagFilters")
        preview.buttons["courseFilter-드라이브"].tap()
        XCTAssertFalse(preview.buttons["courseFilter-드라이브"].isSelected)
        XCTAssertTrue(app.buttons["courseDiscovery-yangyang-food"].exists)
        preview.buttons["courseFilter-all"].tap()
        XCTAssertTrue(preview.buttons["courseFilter-all"].isSelected)
        XCTAssertFalse(preview.buttons["courseFilter-바다"].isSelected)
        XCTAssertTrue(app.buttons["courseDiscovery-sokcho-food"].exists)
        let cardTag = preview.buttons["courseFilter-coffee-coast-카페"]
        reveal(cardTag, in: app, scrollView: preview)
        cardTag.tap()
        XCTAssertFalse(app.staticTexts["courseTagPreviewTitle"].exists)
        XCTAssertTrue(app.buttons["courseDiscovery-coffee-coast"].exists)
        XCTAssertFalse(app.buttons["courseDiscovery-sokcho-food"].exists)
    }

    private func previewContent(in app: XCUIApplication) -> XCUIElement {
        let containers = app.scrollViews.matching(identifier: "courseDiscoveryPreviewContent")
        let preview = app.scrollViews["courseDiscoveryPreviewContent"]
        XCTAssertTrue(preview.waitForExistence(timeout: 5))
        XCTAssertEqual(containers.count, 1, "The scenario must target exactly one preview container")
        return preview
    }

    private func launch() -> XCUIApplication {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["-walkthrough.step", "finished", "-courses-ui-testing", "-course-discovery-live-ui", "-trips-ui-preview"]
        app.launch()
        let tab = app.tabBars.buttons["경로"]
        XCTAssertTrue(tab.waitForExistence(timeout: 5)); tab.tap()
        reveal(app.buttons["coursesDiscoveryPreview"], in: app)
        return app
    }
    private func open(_ id: String, in app: XCUIApplication) {
        let element = app.buttons[id]
        reveal(element, in: app)
        element.tap()
    }
    private func reveal(_ element: XCUIElement, in app: XCUIApplication, scrollView: XCUIElement? = nil) {
        let scroll = scrollView ?? app
        for _ in 0..<12 {
            if !element.exists { scroll.swipeUp(); continue }
            let top = scrollView?.frame.minY ?? (app.navigationBars.firstMatch.exists ? app.navigationBars.firstMatch.frame.maxY : app.frame.minY)
            let tabBar = app.tabBars.firstMatch
            let bottom = scrollView?.frame.maxY ?? (tabBar.exists && tabBar.isHittable ? tabBar.frame.minY : app.frame.maxY)
            if element.frame.minY < top { scroll.swipeDown() }
            else if element.frame.maxY > bottom || !element.isHittable { scroll.swipeUp() }
            else { break }
        }
        XCTAssertTrue(element.exists, element.identifier)
        XCTAssertTrue(element.isHittable, element.identifier)
    }
    private func capture(_ name: String) {
        let screenshot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        screenshot.name = name; screenshot.lifetime = .keepAlways; add(screenshot)
    }
}
