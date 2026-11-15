import XCTest

@MainActor
final class WalkthroughTests: XCTestCase {
    func testFirstRunPermissionsAndVehiclePreview() {
        continueAfterFailure = false
        let app = XCUIApplication()
        let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")

        app.launchArguments = ["-wegoh-first-run-testing", "-wegoh-first-run-reset"]
        app.launch()
        let skip = app.buttons["introSkip"]
        XCTAssertTrue(skip.waitForExistence(timeout: 10), "Run on a simulator with a fresh WegoH installation.")
        XCTAssertTrue(app.buttons["introNext"].exists)
        capture("Intro")

        skip.tap()
        let proceed = app.buttons["permissionsContinue"]
        let done = app.buttons["walkthroughDone"]
        let permissionScreen = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            proceed.exists || done.exists
        }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [permissionScreen], timeout: 5), .completed)
        let elements = app.descendants(matching: .any)
        for identifier in ["locationRow", "microphoneRow", "cameraRow"] {
            XCTAssertTrue(elements[identifier].firstMatch.exists)
        }
        XCTAssertFalse(springboard.alerts.firstMatch.exists)
        if proceed.exists {
            capture("Permissions")
            proceed.tap()
            denyRequestedPermissions(in: springboard, until: done)
        }
        XCTAssertTrue(done.waitForExistence(timeout: 10))
        XCTAssertEqual(app.staticTexts["permissionResultTitle"].label, "권한 확인 결과")
        for identifier in ["locationRow", "microphoneRow"] {
            let row = app.descendants(matching: .any)[identifier].firstMatch
            XCTAssertTrue(row.label.contains("허용 안 함"), "Expected the denied result for \(identifier)")
        }
        let cameraRow = elements["cameraRow"].firstMatch
        let cameraResult = ["허용 안 함", "사용 제한", "확인할 수 없음"].first(where: cameraRow.label.contains)
        XCTAssertNotNil(cameraResult, cameraRow.label)
        capture("Result")
        done.tap()
        let loginTitle = app.staticTexts["loginTitle"]
        let signIn = app.buttons["loginWebContinue"]
        let later = app.buttons["loginLater"]
        XCTAssertTrue(loginTitle.waitForExistence(timeout: 5))
        XCTAssertTrue(signIn.isEnabled)
        XCTAssertEqual(signIn.label, "이메일로 로그인")
        XCTAssertEqual(later.label, "나중에 하기")
        capture("Login")
        app.terminate()
        app.launchArguments = ["-wegoh-first-run-testing"]
        app.launch()
        XCTAssertTrue(loginTitle.waitForExistence(timeout: 5))
        later.tap()
        let tripsTab = app.tabBars.buttons["여행"]
        XCTAssertTrue(tripsTab.waitForExistence(timeout: 5))
        XCTAssertTrue(tripsTab.isSelected)
        let settingsTab = app.tabBars.buttons["설정"]
        settingsTab.tap()
        let profile = elements["settingsProfile"].firstMatch
        let permissions = elements["settingsPermissions"].firstMatch
        let vehicles = elements["settingsVehicles"].firstMatch
        for (row, title) in [(profile, "프로필"), (permissions, "권한 설정"), (vehicles, "연결 차량 설정")] {
            XCTAssertTrue(row.waitForExistence(timeout: 5))
            XCTAssertTrue(row.label.contains(title))
        }
        XCTAssertLessThan(profile.frame.midY, permissions.frame.midY)
        XCTAssertLessThan(permissions.frame.midY, vehicles.frame.midY)
        capture("Settings")

        profile.tap()
        let profileLogin = app.buttons["profileLogin"]
        XCTAssertTrue(profileLogin.waitForExistence(timeout: 5))
        XCTAssertTrue(app.navigationBars["프로필"].exists)
        XCTAssertTrue(profileLogin.isHittable)
        profileLogin.tap()
        XCTAssertTrue(loginTitle.waitForExistence(timeout: 5))
        XCTAssertTrue(signIn.isHittable)
        XCTAssertEqual(later.label, "닫기")
        later.tap()
        XCTAssertTrue(profileLogin.waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["profileLogout"].exists)
        app.navigationBars.buttons.firstMatch.tap()

        permissions.tap()
        for identifier in ["locationStatus", "microphoneStatus"] {
            let status = elements[identifier].firstMatch
            XCTAssertTrue(status.waitForExistence(timeout: 5))
            XCTAssertTrue(status.label.contains("허용 안 함") || (status.value as? String)?.contains("허용 안 함") == true)
        }
        let cameraStatus = elements["cameraStatus"].firstMatch
        XCTAssertTrue(cameraStatus.exists)
        if let cameraResult {
            XCTAssertTrue(cameraStatus.label.contains(cameraResult) || (cameraStatus.value as? String)?.contains(cameraResult) == true)
        }
        XCTAssertTrue(elements["systemSettingsLink"].firstMatch.exists)
        capture("DevicePermissions")
        app.navigationBars.buttons.firstMatch.tap()

        vehicles.tap()
        let vehicleLogin = app.buttons["vehicleLogin"]
        XCTAssertTrue(vehicleLogin.waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["vehicleSampleQR"].exists)
        XCTAssertFalse(app.buttons["vehicleConfirmLink"].exists)
        capture("VehicleLoginRequired")

    }

    private func denyRequestedPermissions(in springboard: XCUIApplication, until done: XCUIElement) {
        let purposes = [("여행 상세 화면", "LocationPrompt"), ("내 목소리", "MicrophonePrompt"),
                        ("차량 화면의 QR 코드", "CameraPrompt")]
        for _ in 0..<purposes.count {
            let ready = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
                done.exists || springboard.alerts.firstMatch.exists
            }, object: nil)
            XCTAssertEqual(XCTWaiter.wait(for: [ready], timeout: 15), .completed)
            if done.exists { return }
            let alert = springboard.alerts.firstMatch
            let requested = purposes.first { purpose, _ in
                alert.staticTexts.matching(NSPredicate(format: "label CONTAINS %@", purpose)).firstMatch.exists
            }
            XCTAssertNotNil(requested, "Unexpected permission prompt: " + alert.label)
            guard let requested else { return }
            capture(requested.1)
            let deny = alert.buttons.matching(NSPredicate(
                format: "label IN %@", ["허용 안 함", "허용 안함", "Don’t Allow", "Don't Allow"]
            )).firstMatch
            XCTAssertTrue(deny.exists)
            deny.tap()
        }
    }

    private func capture(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
