import Foundation
import XCTest
@testable import WegoH

final class PreviewSessionTests: XCTestCase {
    @MainActor
    func testCoursePreviewLogoutClearsSessionAndStaysSignedOut() async throws {
        try await checkLogout(configuration: CourseUIFixture.configuration(),
                              credentials: CourseUIFixture.Credential())
    }

    @MainActor
    func testFriendsPreviewLogoutClearsSessionAndStaysSignedOut() async throws {
        try await checkLogout(configuration: FriendsUIFixture.configuration(),
                              credentials: FriendsUIFixture.Credential())
    }

    @MainActor
    private func checkLogout(configuration: URLSessionConfiguration,
                             credentials: any IPhoneCredentialStoring) async throws {
        let manager = SessionManager(api: IPhoneSessionAPI(configuration: configuration),
                                     credentials: credentials)
        await manager.restore()
        XCTAssertEqual(manager.phase, .signedIn)
        XCTAssertNotNil(manager.current)

        await manager.signOut()
        XCTAssertEqual(manager.phase, .signedOut)
        XCTAssertNil(manager.current)
        XCTAssertNil(try credentials.load())

        await manager.restore()
        XCTAssertEqual(manager.phase, .signedOut)
        XCTAssertNil(manager.current)
    }
}
