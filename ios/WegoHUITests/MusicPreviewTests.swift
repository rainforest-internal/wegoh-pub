import XCTest

@MainActor
final class MusicPreviewTests: XCTestCase {
    func testAddEditAndDeleteAPlaylistLink() {
        let app = launchMusic()
        app.buttons["musicAddPlaylist"].tap()
        let title = app.textFields["musicPlaylistTitle"]
        XCTAssertTrue(title.waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["musicSavePlaylist"].isEnabled)
        XCTAssertTrue(app.buttons["musicPlatform"].exists)
        title.tap()
        title.typeText("Weekend Drive")
        let url = app.textFields["musicPlaylistURL"]
        url.tap()
        let invalidURL = "http://open.spotify.com/playlist/fixture"
        url.typeText(invalidURL)
        app.buttons["musicSavePlaylist"].tap()
        XCTAssertTrue(app.staticTexts["musicPlaylistError"].waitForExistence(timeout: 5))
        let savedURL = "https://open.spotify.com/playlist/fixture"
        app.buttons["musicClearURL"].tap()
        url.typeText(savedURL)
        app.buttons["musicSavePlaylist"].tap()
        let item = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "Weekend Drive,")).firstMatch
        XCTAssertTrue(item.waitForExistence(timeout: 5))
        XCTAssertTrue(item.label.contains("스포티파이"))
        XCTAssertTrue(app.buttons["musicAddPlaylist"].exists)
        item.tap()
        XCTAssertTrue(title.waitForExistence(timeout: 5))
        XCTAssertEqual(title.value as? String, "Weekend Drive")
        XCTAssertEqual(url.value as? String, savedURL)
        XCTAssertFalse(app.buttons["musicSavePlaylist"].isEnabled)
        app.buttons["musicClearTitle"].tap()
        title.typeText("Evening Drive")
        let editedURL = "https://open.spotify.com/playlist/edited"
        app.buttons["musicClearURL"].tap()
        url.typeText(editedURL)
        capture("MusicEditPlaylist")
        app.buttons["musicSavePlaylist"].tap()
        let editedItem = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "Evening Drive,")).firstMatch
        XCTAssertTrue(editedItem.waitForExistence(timeout: 5))
        XCTAssertFalse(item.exists)
        editedItem.tap()
        XCTAssertTrue(url.waitForExistence(timeout: 5))
        XCTAssertEqual(url.value as? String, editedURL)
        app.buttons["musicDeletePlaylist"].tap()
        app.alerts.buttons["취소"].tap()
        XCTAssertTrue(url.exists)
        app.buttons["musicDeletePlaylist"].tap()
        app.alerts.buttons["삭제"].tap()
        XCTAssertTrue(app.buttons["musicAddPlaylist"].waitForExistence(timeout: 5))
        XCTAssertFalse(editedItem.exists)
    }

    func testSampleLinkStaysOnTheListAndEmptyState() {
        let app = launchMusic()
        capture("MusicList")
        app.buttons["musicItem-coast"].tap()
        XCTAssertTrue(app.textFields["musicPlaylistTitle"].waitForExistence(timeout: 5))
        XCTAssertEqual(app.textFields["musicPlaylistTitle"].value as? String, "바다로 가는 길")
        app.navigationBars.buttons.firstMatch.tap()
        XCTAssertTrue(app.buttons["musicAddPlaylist"].exists)
        XCTAssertTrue(app.buttons["musicItem-coast"].exists)
        for id in ["coast", "afternoon", "weekend"] {
            app.buttons["musicItem-\(id)"].tap()
            XCTAssertTrue(app.buttons["musicDeletePlaylist"].waitForExistence(timeout: 5))
            app.buttons["musicDeletePlaylist"].tap()
            app.alerts.buttons["삭제"].tap()
            XCTAssertTrue(app.buttons["musicAddPlaylist"].waitForExistence(timeout: 5))
        }
        XCTAssertTrue(app.staticTexts["musicEmpty"].waitForExistence(timeout: 5))
        capture("MusicEmptyList")
        app.tabBars.buttons["친구"].tap()
        XCTAssertTrue(app.buttons["friendsAdd"].waitForExistence(timeout: 5))
    }

    private func launchMusic() -> XCUIApplication {
        continueAfterFailure = false
        XCUIDevice.shared.orientation = .portrait
        let app = XCUIApplication()
        app.launchArguments = ["-walkthrough.step", "finished", "-friends-ui-testing"]
        app.launch()
        let music = app.tabBars.buttons["음악"]
        XCTAssertTrue(music.waitForExistence(timeout: 5))
        music.tap()
        XCTAssertTrue(app.buttons["musicAddPlaylist"].waitForExistence(timeout: 5))
        return app
    }

    private func capture(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
