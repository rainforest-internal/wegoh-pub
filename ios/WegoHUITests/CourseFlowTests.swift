import XCTest

@MainActor
final class CourseFlowTests: XCTestCase {
    func testCreateSearchSelectSaveAndEditARealCourseScreen() {
        continueAfterFailure = false
        let app = launchCourses()
        XCTAssertTrue(app.buttons["course-fixture-coast"].waitForExistence(timeout: 10))
        capture("CourseList")
        app.buttons["course-fixture-coast"].tap()
        XCTAssertTrue(app.staticTexts["courseDetailTitle"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["courseRouteLoaded"].waitForExistence(timeout: 5))
        capture("CourseDetail")
        app.buttons["courseEdit"].tap()
        let title = app.textFields["courseTitle"]
        XCTAssertTrue(title.waitForExistence(timeout: 5))
        XCTAssertEqual(title.value as? String, "태안 노을 드라이브")
        XCTAssertFalse(app.buttons["courseSave"].isEnabled)
        title.tap()
        title.tap()
        XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 3))
        title.typeText(" Evening")
        confirmRights(in: app)
        capture("CourseEdit")
        app.buttons["courseSave"].tap()
        XCTAssertTrue(app.staticTexts["courseDetailTitle"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@", "v2")).firstMatch.waitForExistence(timeout: 5))
        app.navigationBars.buttons.firstMatch.tap()
        app.buttons["coursesCreate"].tap()
        let newTitle = app.textFields["courseTitle"]
        XCTAssertTrue(newTitle.waitForExistence(timeout: 5))
        newTitle.tap(); newTitle.tap(); newTitle.typeText("Weekend Coast")
        let description = app.textViews["courseDescription"].firstMatch
        let multiline = description.exists ? description : app.textFields["courseDescription"].firstMatch
        dismissKeyboard(in: app)
        revealEditorField(multiline, in: app)
        multiline.tap()
        XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 5))
        revealEditorField(multiline, in: app)
        multiline.typeText("A coastal route")
        XCTAssertTrue((multiline.value as? String)?.contains("A coastal route") == true)
        let keyboardDone = app.buttons["courseKeyboardDismiss"]
        XCTAssertTrue(keyboardDone.waitForExistence(timeout: 5))
        keyboardDone.tap()
        XCTAssertTrue(app.keyboards.firstMatch.waitForNonExistence(timeout: 5))

        let addPlace = app.buttons["courseAddPlace"]
        let editor = app.scrollViews.containing(.button, identifier: "courseAddPlace").firstMatch
        XCTAssertTrue(editor.waitForExistence(timeout: 5))
        XCTAssertTrue(addPlace.waitForExistence(timeout: 5))
        let save = app.buttons["courseSave"]
        for _ in 0..<6 where !addPlace.isHittable || addPlace.frame.midY >= save.frame.minY {
            editor.swipeUp()
        }
        XCTAssertTrue(addPlace.isHittable)
        XCTAssertLessThan(addPlace.frame.midY, save.frame.minY)
        addPlace.tap()
        let query = app.textFields["coursePlaceQuery"]
        XCTAssertTrue(query.waitForExistence(timeout: 5))
        query.tap(); query.typeText("Gyeongpo")
        app.buttons["coursePlaceSearch"].tap()
        let result = app.buttons["coursePlace-kakao-1"]
        XCTAssertTrue(result.waitForExistence(timeout: 5))
        result.tap()
        capture("CoursePlaceSelection")
        app.buttons["coursePlaceAdd"].tap()
        XCTAssertTrue(app.buttons["courseSave"].waitForExistence(timeout: 5))
        confirmRights(in: app)
        app.buttons["courseSave"].tap()
        XCTAssertTrue(app.staticTexts["Weekend Coast"].waitForExistence(timeout: 5))
        capture("CourseCreated")
    }

    func testEditingOnlyTagsReloadsSavedVersionBeforeNextEdit() {
        let app = launchCourses(extra: ["-trips-ui-preview"])
        app.buttons["course-fixture-coast"].tap()
        let edit = app.buttons["courseEdit"]
        XCTAssertTrue(edit.waitForExistence(timeout: 5))
        edit.tap()
        let input = app.textFields["courseTagInput"]
        XCTAssertTrue(input.waitForExistence(timeout: 5))
        if !input.isHittable { app.swipeUp() }
        input.tap()
        input.typeText("sunset\n")
        let tag = app.buttons["courseEditorTag-sunset"]
        XCTAssertTrue(tag.waitForExistence(timeout: 5))

        let save = app.buttons["courseSave"]
        XCTAssertFalse(save.isEnabled)
        confirmRights(in: app)
        save.tap()
        let version = app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@", "v2")).firstMatch
        XCTAssertTrue(version.waitForExistence(timeout: 5))
        edit.tap()
        XCTAssertTrue(tag.waitForExistence(timeout: 5))
        XCTAssertFalse(save.isEnabled)
    }

    func testEmptyAndSignedOutDoNotShowSampleCourses() {
        let app = launchCourses(extra: ["-courses-ui-empty"])
        XCTAssertTrue(app.staticTexts["아직 만든 경로가 없어요"].waitForExistence(timeout: 5))
        capture("CourseEmpty")
        app.terminate()
        app.launchArguments = ["-walkthrough.step", "finished", "-courses-ui-testing", "-courses-ui-signed-out"]
        app.launch()
        app.tabBars.buttons["경로"].tap()
        XCTAssertTrue(app.buttons["coursesSection-owned"].waitForExistence(timeout: 5))
        app.buttons["coursesSection-owned"].tap()
        XCTAssertTrue(app.buttons["coursesLogin"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["coursesCreate"].exists)
        capture("CourseSignedOut")
    }

    func testRouteFailureKeepsTheCourseAndAllowsRetry() {
        let app = launchCourses(extra: ["-courses-ui-route-failure"])
        app.buttons["course-fixture-coast"].tap()
        XCTAssertTrue(app.staticTexts["도로 경로를 불러오지 못했어요."].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["courseDetailTitle"].exists)
        XCTAssertFalse(app.staticTexts["courseRouteLoaded"].exists)
        app.buttons["경로 다시 시도"].tap()
        XCTAssertTrue(app.staticTexts["도로 경로를 불러오지 못했어요."].waitForExistence(timeout: 5))
    }

    private func confirmRights(in app: XCUIApplication, file: StaticString = #filePath, line: UInt = #line) {
        let row = app.switches["courseRights"]
        let control = row.switches.firstMatch
        let save = app.buttons["courseSave"]
        let scroll = app.scrollViews.containing(.switch, identifier: "courseRights").firstMatch
        let keyboard = app.keyboards.firstMatch
        if keyboard.exists {
            let dismiss = app.buttons["courseKeyboardDismiss"]
            if dismiss.waitForExistence(timeout: 3) {
                dismiss.tap()
                XCTAssertTrue(keyboard.waitForNonExistence(timeout: 5), file: file, line: line)
            }
        }
        XCTAssertTrue(scroll.waitForExistence(timeout: 5), file: file, line: line)
        XCTAssertTrue(control.waitForExistence(timeout: 5), file: file, line: line)
        func isVisible() -> Bool {
            let bottom = min(save.frame.minY, keyboard.exists ? keyboard.frame.minY : app.frame.maxY)
            return control.isHittable && control.frame.maxY < bottom && control.frame.minY >= scroll.frame.minY
        }
        for _ in 0..<6 where !isVisible() {
            scroll.swipeUp()
        }
        XCTAssertTrue(isVisible(), "Consent switch must be above the sticky save button and keyboard", file: file, line: line)
        for _ in 0..<2 where (row.value as? String) != "1" { control.tap() }
        XCTAssertEqual(row.value as? String, "1", file: file, line: line)
        XCTAssertTrue(save.isEnabled, file: file, line: line)
    }

    private func dismissKeyboard(in app: XCUIApplication) {
        guard app.keyboards.firstMatch.exists else { return }
        let done = app.buttons["courseKeyboardDismiss"]
        XCTAssertTrue(done.waitForExistence(timeout: 5))
        done.tap()
        XCTAssertTrue(app.keyboards.firstMatch.waitForNonExistence(timeout: 5))
    }

    private func revealEditorField(_ field: XCUIElement, in app: XCUIApplication) {
        let editor = app.scrollViews.containing(.button, identifier: "courseAddPlace").firstMatch
        let save = app.buttons["courseSave"]
        XCTAssertTrue(editor.waitForExistence(timeout: 5))
        XCTAssertTrue(field.exists)
        for _ in 0..<6 {
            if field.frame.minY < editor.frame.minY { editor.swipeDown() }
            else if field.frame.maxY >= save.frame.minY || !field.isHittable { editor.swipeUp() }
            else { break }
        }
        XCTAssertTrue(field.isHittable)
        XCTAssertLessThan(field.frame.maxY, save.frame.minY)
    }

    private func launchCourses(extra: [String] = []) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["-walkthrough.step", "finished", "-courses-ui-testing"] + extra
        app.launch()
        let tab = app.tabBars.buttons["경로"]
        XCTAssertTrue(tab.waitForExistence(timeout: 5))
        tab.tap()
        XCTAssertTrue(app.buttons["coursesSection-owned"].waitForExistence(timeout: 5))
        app.buttons["coursesSection-owned"].tap()
        return app
    }
    private func capture(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name; attachment.lifetime = .keepAlways; add(attachment)
    }
}
