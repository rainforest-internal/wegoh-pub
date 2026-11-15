import XCTest
@testable import WegoH

@MainActor
final class CourseDiscoveryTests: XCTestCase {
    func testFollowChangesTheSubscriptionListAndNewsTogether() {
        let store = CourseDiscoveryPreviewStore()
        XCTAssertEqual(store.following.map(\.id), ["user-f", "user-h"])
        XCTAssertEqual(store.unreadCount, 1)
        XCTAssertFalse(store.visibleNews.contains { $0.courseID == "sokcho-food" })
        store.toggleFollow("user-g")
        XCTAssertEqual(store.following.count, 3)
        XCTAssertEqual(store.unreadCount, 2)
        store.markRead("sokcho-food")
        XCTAssertEqual(store.unreadCount, 1)
        store.toggleFollow("user-g")
        XCTAssertFalse(store.visibleNews.contains { $0.courseID == "sokcho-food" })
        store.toggleFollow("user-g")
        XCTAssertEqual(store.unreadCount, 1)
    }

    func testStarsAffectSavedCoursesAndDoNotChangeThePublishedSamples() throws {
        let store = CourseDiscoveryPreviewStore()
        let course = try XCTUnwrap(store.course("sokcho-food"))
        XCTAssertEqual(store.starCount(course), 64)
        XCTAssertEqual(store.saved.count, 2)
        store.toggleStar(course.id)
        XCTAssertEqual(store.saved.count, 3)
        XCTAssertEqual(store.starCount(course), 65)
        store.toggleStar(course.id)
        XCTAssertEqual(store.saved.count, 2)
        XCTAssertEqual(store.starCount(course), 64)
        let reopened = CourseDiscoveryPreviewStore()
        XCTAssertFalse(reopened.starredCourses.contains(course.id))
        XCTAssertEqual(course.starCount, 64)
    }

    func testSearchAndTagFilteringUseOnlyProvidedSampleFields() {
        let store = CourseDiscoveryPreviewStore()
        XCTAssertEqual(store.recommendations(query: " #바다 ").map(\.id), ["coffee-coast", "sunrise", "yangyang-food"])
        XCTAssertEqual(store.recommendations(query: "속초").map(\.id), ["sokcho-food"])
        XCTAssertTrue(store.recommendations(query: "없는 검색어").isEmpty)
        XCTAssertEqual(store.courses(tag: "먹방", query: "속초").map(\.id), ["sokcho-food"])
        XCTAssertTrue(store.courses(tag: "먹방", query: "강릉").isEmpty)
        XCTAssertNil(store.course("sunrise")?.stopCount)
        XCTAssertNil(store.course("sunrise")?.starCount)
        store.toggleTag("먹방")
        XCTAssertTrue(store.followedTags.contains("먹방"))
        XCTAssertFalse(store.followedCreators.contains("user-g"))
        store.toggleTag("먹방")
        XCTAssertTrue(store.followedTags.isEmpty)
    }

    func testRecommendationsCombineMultipleTagsWithSearchAndAllowClearing() {
        let store = CourseDiscoveryPreviewStore()
        XCTAssertEqual(store.recommendations(query: "", selectedTags: ["바다"]).map(\.id), ["coffee-coast", "sunrise", "yangyang-food"])
        XCTAssertEqual(store.recommendations(query: "", selectedTags: ["바다", "드라이브"]).map(\.id), ["coffee-coast", "sunrise"])
        XCTAssertEqual(store.recommendations(query: "강릉", selectedTags: ["바다", "드라이브"]).map(\.id), ["coffee-coast"])
        XCTAssertTrue(store.recommendations(query: "", selectedTags: ["먹방", "카페"]).isEmpty)
        XCTAssertEqual(store.recommendations(query: "", selectedTags: []).map(\.id), ["coffee-coast", "sokcho-food"])
        XCTAssertTrue(store.followedTags.isEmpty)
    }

    func testTagNewsDoesNotFollowTheCreatorOrDuplicateTheirNews() {
        let store = CourseDiscoveryPreviewStore()
        XCTAssertFalse(store.visibleNews.contains { $0.id == "sokcho-food" })
        store.toggleTag("먹방")
        XCTAssertTrue(store.visibleNews.contains { $0.id == "sokcho-food" })
        XCTAssertFalse(store.followedCreators.contains("user-g"))
        store.toggleFollow("user-g")
        XCTAssertEqual(store.visibleNews.filter { $0.id == "sokcho-food" }.count, 1)
        store.toggleFollow("user-g")
        store.toggleTag("먹방")
        XCTAssertFalse(store.visibleNews.contains { $0.id == "sokcho-food" })
    }
}
