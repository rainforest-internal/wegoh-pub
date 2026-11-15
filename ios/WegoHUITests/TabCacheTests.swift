import XCTest

@MainActor
final class TabCacheTests: XCTestCase {
    func testCreateActionsFloatAboveTabsAndStayFixedWhileScrolling() {
        let app = launch()
        assertFloatingAction(app, identifier: "tripCreate")
        app.tabBars.buttons["경로"].tap()
        assertFloatingAction(app, identifier: "coursesCreate")
        app.tabBars.buttons["음악"].tap()
        assertFloatingAction(app, identifier: "musicAddPlaylist")
        app.terminate()

        app.launchArguments = ["-walkthrough.step", "finished", "-friends-ui-testing"]
        app.launch()
        XCTAssertTrue(app.tabBars.buttons["친구"].waitForExistence(timeout: 8))
        app.tabBars.buttons["친구"].tap()
        assertFloatingAction(app, identifier: "friendsAdd")
    }

    private func assertFloatingAction(_ app: XCUIApplication, identifier: String) {
        let button = app.buttons[identifier]
        XCTAssertTrue(button.waitForExistence(timeout: 8))
        XCTAssertEqual(app.buttons.matching(identifier: identifier).count, 1)
        XCTAssertTrue(button.isHittable)
        let original = button.frame
        XCTAssertGreaterThan(original.width, app.frame.width * 0.8)
        XCTAssertGreaterThan(original.minY, app.frame.midY)
        XCTAssertLessThanOrEqual(original.maxY, app.tabBars.firstMatch.frame.minY)
        app.swipeUp()
        XCTAssertTrue(button.isHittable)
        XCTAssertEqual(button.frame.minY, original.minY, accuracy: 2)
        capture(identifier + "-floating-above-tabs")
    }

    func testDetailsHideTabBarAndBackRestoresItAcrossAllFiveTabs() {
        let app = launch(mode: "-trips-ui-preview")
        let trip = app.buttons["trip-gangneung"]
        XCTAssertTrue(trip.waitForExistence(timeout: 8))
        for _ in 0..<5 where !trip.isHittable { app.swipeUp() }
        trip.tap()
        assertDetailAndReturn(app, name: "TripDetail-no-tabs")

        app.tabBars.buttons["경로"].tap()
        let course = app.buttons["courseDiscovery-test-coast"]
        XCTAssertTrue(course.waitForExistence(timeout: 8))
        for _ in 0..<8 {
            let bottom = app.buttons["coursesCreate"].frame.minY
            if course.isHittable && course.frame.maxY < bottom { break }
            app.swipeUp()
        }
        course.tap()
        capture("Course-after-navigation")
        XCTAssertTrue(app.staticTexts["coursePublicTitle"].waitForExistence(timeout: 5), app.debugDescription)
        assertDetailAndReturn(app, name: "CourseDetail-no-tabs")

        app.tabBars.buttons["음악"].tap()
        let playlist = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH %@", "musicItem-")).firstMatch
        XCTAssertTrue(playlist.waitForExistence(timeout: 5))
        for _ in 0..<4 where !playlist.isHittable { app.swipeUp() }
        playlist.tap()
        assertDetailAndReturn(app, name: "MusicDetail-no-tabs")

        app.tabBars.buttons["설정"].tap()
        app.buttons["settingsPermissions"].tap()
        assertDetailAndReturn(app, name: "SettingsDetail-no-tabs")
        app.terminate()

        app.launchArguments = ["-walkthrough.step", "finished", "-friends-ui-testing"]
        app.launch()
        XCTAssertTrue(app.tabBars.buttons["친구"].waitForExistence(timeout: 8))
        app.tabBars.buttons["친구"].tap()
        let friend = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH %@", "friendProfile-")).firstMatch
        XCTAssertTrue(friend.waitForExistence(timeout: 8))
        friend.tap()
        assertDetailAndReturn(app, name: "FriendDetail-no-tabs")
    }

    private func assertDetailAndReturn(_ app: XCUIApplication, name: String) {
        let hidden = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in !app.tabBars.firstMatch.exists }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [hidden], timeout: 5), .completed)
        capture(name)
        let back = app.navigationBars.buttons.element(boundBy: 0)
        XCTAssertTrue(back.waitForExistence(timeout: 5))
        back.tap()
        XCTAssertTrue(app.tabBars.buttons["여행"].waitForExistence(timeout: 5))
    }

    func testTripListOnlyReloadsAfterExplicitRefresh() {
        let app = launch()
        let tripID = "accountTrip-" + String(repeating: "c", count: 32)
        let trip = app.buttons[tripID]
        XCTAssertTrue(trip.waitForExistence(timeout: 8))
        for title in ["경로", "음악", "친구", "설정"] {
            let otherTab = app.tabBars.buttons[title]
            otherTab.tap()
            XCTAssertTrue(otherTab.isSelected)
            app.tabBars.buttons["여행"].tap()
            XCTAssertTrue(trip.waitForExistence(timeout: 5), "The last loaded trip must remain after returning from \(title)")
            XCTAssertFalse(app.staticTexts["tripsRefreshError"].waitForExistence(timeout: 1))
            XCTAssertFalse(app.buttons["tripsLogin"].exists)
            XCTAssertFalse(app.otherElements["tripsEmpty"].exists)
        }
        pullToRefresh(app, containing: tripID)
        XCTAssertTrue(app.staticTexts["tripsRefreshError"].waitForExistence(timeout: 5))
        XCTAssertTrue(trip.exists)
        XCTAssertFalse(app.buttons["tripsLogin"].exists)
        XCTAssertFalse(app.otherElements["tripsEmpty"].exists)
        capture("CachedTripAfterExplicitRefreshFailure")
    }

    func testOwnedAndDiscoveryKeepTheirDataAndFiltersUntilExplicitRefresh() {
        let app = launch()
        app.tabBars.buttons["경로"].tap()
        let discovered = app.buttons["courseDiscovery-test-coast"]
        XCTAssertTrue(discovered.waitForExistence(timeout: 8))
        app.buttons["coursesSection-owned"].tap()
        let owned = app.buttons["course-fixture-coast"]
        XCTAssertTrue(owned.waitForExistence(timeout: 5))
        app.buttons["coursesSection-recommended"].tap()
        XCTAssertTrue(discovered.waitForExistence(timeout: 5))
        XCTAssertFalse(app.staticTexts["courseDiscoveryError"].waitForExistence(timeout: 1))
        app.buttons["courseFilter-바다"].tap()
        XCTAssertTrue(app.staticTexts["courseDiscoveryError"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["courseFilter-바다"].isSelected)
        app.buttons["coursesSection-owned"].tap()
        XCTAssertTrue(owned.waitForExistence(timeout: 5))
        XCTAssertFalse(app.staticTexts["coursesError"].waitForExistence(timeout: 1))
        app.buttons["coursesSection-recommended"].tap()
        XCTAssertTrue(app.staticTexts["courseDiscoveryError"].waitForExistence(timeout: 5))
        XCTAssertTrue(discovered.exists)
        XCTAssertTrue(app.buttons["courseFilter-바다"].isSelected)
        XCTAssertFalse(app.buttons["coursesLogin"].exists)
        app.buttons["coursesSection-owned"].tap()
        XCTAssertTrue(owned.waitForExistence(timeout: 5))
        XCTAssertFalse(app.staticTexts["coursesError"].waitForExistence(timeout: 1))
        pullToRefresh(app, containing: "course-fixture-coast")
        XCTAssertTrue(app.staticTexts["coursesError"].waitForExistence(timeout: 5))
        XCTAssertTrue(owned.exists)
        XCTAssertFalse(app.buttons["coursesLogin"].exists)
        XCTAssertFalse(app.otherElements["coursesEmpty"].exists)
        capture("CachedOwnedCourseAfterExplicitRefreshFailure")
    }

    func testInitialFailureDoesNotRetryOnRevisitButExplicitRetryLoads() {
        let app = launch(mode: "-tab-cache-fail-first")
        app.tabBars.buttons["경로"].tap()
        XCTAssertTrue(app.buttons["courseDiscovery-test-coast"].waitForExistence(timeout: 8))
        app.buttons["coursesSection-owned"].tap()
        let error = app.staticTexts["coursesError"]
        let owned = app.buttons["course-fixture-coast"]
        XCTAssertTrue(error.waitForExistence(timeout: 5))
        app.tabBars.buttons["여행"].tap()
        app.tabBars.buttons["경로"].tap()
        XCTAssertTrue(error.waitForExistence(timeout: 5))
        XCTAssertFalse(owned.waitForExistence(timeout: 1))
        app.buttons["coursesSection-recommended"].tap()
        app.buttons["coursesSection-owned"].tap()
        XCTAssertTrue(error.waitForExistence(timeout: 5))
        XCTAssertFalse(owned.waitForExistence(timeout: 1))
        XCTAssertFalse(app.buttons["coursesLogin"].exists)
        XCTAssertFalse(app.otherElements["coursesEmpty"].exists)
        let retries = app.buttons.matching(identifier: "wegoLoadingFailureRetry")
        XCTAssertEqual(retries.count, 1)
        retries.element.tap()
        XCTAssertTrue(owned.waitForExistence(timeout: 5))
        XCTAssertFalse(error.exists)
        capture("InitialFailureExplicitRetry")
    }

    func testFriendsKeepTheirDataUntilExplicitRefresh() {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["-walkthrough.step", "finished", "-friends-ui-testing", "-friends-ui-cache-fail-refresh"]
        app.launch()
        let friendsTab = app.tabBars.buttons["친구"]
        XCTAssertTrue(friendsTab.waitForExistence(timeout: 8))
        friendsTab.tap()
        let friendID = "friendProfile-team-" + String(repeating: "1", count: 40)
        let friend = app.buttons[friendID]
        XCTAssertTrue(friend.waitForExistence(timeout: 8))
        for title in ["음악", "설정", "여행"] {
            app.tabBars.buttons[title].tap()
            friendsTab.tap()
            XCTAssertTrue(friend.waitForExistence(timeout: 5), "Cached friends must remain after returning from \(title)")
            XCTAssertFalse(app.staticTexts["friendsError"].waitForExistence(timeout: 1))
            XCTAssertFalse(app.otherElements["friendsEmpty"].exists)
        }
        let error = app.staticTexts["friendsError"]
        for _ in 0..<3 {
            pullToRefresh(app, containing: friendID)
            if error.waitForExistence(timeout: 1) { break }
        }
        XCTAssertTrue(error.waitForExistence(timeout: 5))
        XCTAssertTrue(friend.exists)
        XCTAssertFalse(app.otherElements["friendsEmpty"].exists)
        capture("CachedFriendsAfterExplicitRefreshFailure")
    }

    func testShortFriendsListPullRefreshesOnceAndPreservesCachedFriend() {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["-walkthrough.step", "finished", "-friends-ui-testing",
                               "-friends-ui-short-list", "-friends-ui-cache-fail-refresh"]
        app.launch()
        let friendsTab = app.tabBars.buttons["친구"]
        XCTAssertTrue(friendsTab.waitForExistence(timeout: 8))
        friendsTab.tap()
        let friendID = "friendProfile-team-" + String(repeating: "1", count: 40)
        let friend = app.buttons[friendID]
        XCTAssertTrue(friend.waitForExistence(timeout: 8))
        XCTAssertEqual(app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH %@", "friendProfile-")).count, 1)
        XCTAssertEqual(app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH %@", "friendAccept-")).count, 0)
        XCTAssertFalse(app.staticTexts["friendsOutgoing"].exists)
        XCTAssertFalse(app.staticTexts["friendsBlocked"].exists)
        let scrollViews = app.scrollViews.containing(.button, identifier: friendID)
        XCTAssertEqual(scrollViews.count, 1)
        XCTAssertLessThan(friend.frame.maxY, scrollViews.element.frame.maxY, "The short list must fit without scrolling")
        let error = app.staticTexts["friendsError"]
        XCTAssertFalse(error.waitForExistence(timeout: 1))
        capture("ShortFriendsBeforePullRefresh")
        pullToRefresh(app, containing: friendID)
        XCTAssertTrue(error.waitForExistence(timeout: 5), "One explicit pull must perform the second GET even when content fits")
        XCTAssertTrue(friend.exists)
        XCTAssertFalse(app.otherElements["friendsEmpty"].exists)
        capture("ShortFriendsAfterExplicitRefreshFailure")
    }

    private func pullToRefresh(_ app: XCUIApplication, containing identifier: String) {
        let scrollViews = app.scrollViews.containing(.button, identifier: identifier)
        XCTAssertEqual(scrollViews.count, 1)
        let scroll = scrollViews.element
        scroll.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.25))
            .press(forDuration: 0.1, thenDragTo: scroll.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.85)))
    }

    private func launch(mode: String = "-tab-cache-fail-refresh") -> XCUIApplication {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = ["-walkthrough.step", "finished", "-course-discovery-live-ui",
                               "-courses-ui-testing", mode]
        app.launch()
        XCTAssertTrue(app.tabBars.buttons["여행"].waitForExistence(timeout: 10))
        return app
    }

    private func capture(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
