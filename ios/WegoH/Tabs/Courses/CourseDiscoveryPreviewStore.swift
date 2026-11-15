import Foundation
import Observation

enum CourseHomeSection: String, CaseIterable, Identifiable {
    case recommended = "추천", subscriptions = "구독", owned = "내 경로"
    var id: Self { self }
    var accessibilityID: String {
        switch self { case .recommended: "recommended"; case .subscriptions: "subscriptions"; case .owned: "owned" }
    }
}

struct CourseDiscoveryCreator: Identifiable {
    let id: String
    let name: String
    let courseCount: Int?
    let subscriberCount: Int?
    let tags: [String]
}

struct CourseDiscoveryCourse: Identifiable {
    let id: String
    let title: String
    let creatorID: String
    let stopCount: Int?
    let stops: [String]
    let tags: [String]
    let starCount: Int?
    let description: String
    let published: String?
}

struct CourseDiscoveryNews: Identifiable {
    let courseID: String
    let age: String
    var id: String { courseID }
}

@MainActor @Observable
final class CourseDiscoveryPreviewStore {
    private(set) var followedCreators: Set<String> = ["user-f", "user-h"]
    private(set) var starredCourses: Set<String> = ["coffee-coast", "jeonju-food"]
    private(set) var readNews: Set<String> = ["coffee-coast"]
    private(set) var followedTags: Set<String> = []
    static let popularTags = ["먹방", "드라이브", "바다", "카페", "야경"]
    static let creators: [CourseDiscoveryCreator] = [
        .init(id: "user-f", name: "사용자A", courseCount: 12, subscriberCount: nil, tags: ["드라이브", "바다"]),
        .init(id: "user-g", name: "사용자C", courseCount: 14, subscriberCount: 86, tags: ["먹방", "시장", "당일치기"]),
        .init(id: "user-h", name: "사용자E", courseCount: nil, subscriberCount: nil, tags: ["먹방", "당일치기"]),
        .init(id: "user-k", name: "사용자A", courseCount: nil, subscriberCount: nil, tags: ["먹방"])
    ]
    static let courses: [CourseDiscoveryCourse] = [
        .init(id: "coffee-coast", title: "강릉 커피 해안길", creatorID: "user-f", stopCount: 3,
              stops: ["안목해변", "경포호", "주문진항"], tags: ["드라이브", "바다", "카페"], starCount: 128,
              description: "안목해변에서 커피 한 잔을 마시고, 바다를 따라 주문진까지 함께 달려요.", published: "2주 전"),
        .init(id: "sokcho-food", title: "속초 먹방 한 바퀴", creatorID: "user-g", stopCount: 3,
              stops: ["중앙시장", "아바이마을", "영랑호"], tags: ["먹방", "시장"], starCount: 64, description: "", published: "3일 전"),
        .init(id: "sunrise", title: "동해 일출 드라이브", creatorID: "user-f", stopCount: nil,
              stops: [], tags: ["드라이브", "바다", "야경"], starCount: nil, description: "", published: "5일 전"),
        .init(id: "jeonju-food", title: "전주 한옥마을 먹거리 코스", creatorID: "user-h", stopCount: 3,
              stops: [], tags: ["먹방", "당일치기"], starCount: 51, description: "", published: nil),
        .init(id: "jumunjin-food", title: "주문진 수산시장 한 끼", creatorID: "user-g", stopCount: 2,
              stops: [], tags: [], starCount: 39, description: "", published: "2주 전"),
        .init(id: "yangyang-food", title: "양양 서핑 뒤 국밥 코스", creatorID: "user-g", stopCount: 3,
              stops: [], tags: ["먹방", "바다"], starCount: 27, description: "", published: "한 달 전")
    ]
    static let news = [CourseDiscoveryNews(courseID: "sokcho-food", age: "3일 전"),
                       CourseDiscoveryNews(courseID: "sunrise", age: "5일 전"),
                       CourseDiscoveryNews(courseID: "coffee-coast", age: "2주 전")]
    private static let initialStars: Set<String> = ["coffee-coast", "jeonju-food"]
    var following: [CourseDiscoveryCreator] { Self.creators.filter { followedCreators.contains($0.id) } }
    var saved: [CourseDiscoveryCourse] { Self.courses.filter { starredCourses.contains($0.id) } }
    var visibleNews: [CourseDiscoveryNews] {
        Self.news.filter { item in
            course(item.courseID).map {
                followedCreators.contains($0.creatorID) || !followedTags.isDisjoint(with: $0.tags)
            } ?? false
        }
    }
    var unreadCount: Int { visibleNews.filter { !readNews.contains($0.id) }.count }
    func creator(_ id: String) -> CourseDiscoveryCreator? { Self.creators.first { $0.id == id } }
    func course(_ id: String) -> CourseDiscoveryCourse? { Self.courses.first { $0.id == id } }
    func recommendations(query: String, selectedTags: Set<String> = []) -> [CourseDiscoveryCourse] {
        let normalized = query.trimmingCharacters(in: .whitespacesAndNewlines).replacingOccurrences(of: "#", with: "")
        guard !normalized.isEmpty || !selectedTags.isEmpty else { return Array(Self.courses.prefix(2)) }
        return Self.courses.filter { course in
            selectedTags.isSubset(of: Set(course.tags)) && (normalized.isEmpty
                || course.title.localizedCaseInsensitiveContains(normalized)
                || course.tags.contains { $0.localizedCaseInsensitiveContains(normalized) })
        }
    }
    func courses(tag: String, query: String = "") -> [CourseDiscoveryCourse] {
        let normalized = query.trimmingCharacters(in: .whitespacesAndNewlines).replacingOccurrences(of: "#", with: "")
        return Self.courses.filter { course in
            course.tags.contains(tag) && (normalized.isEmpty || course.title.localizedCaseInsensitiveContains(normalized)
                || course.tags.contains { $0.localizedCaseInsensitiveContains(normalized) })
        }
    }
    func courses(creator: String, tag: String?) -> [CourseDiscoveryCourse] {
        Self.courses.filter { course in
            guard course.creatorID == creator else { return false }
            return tag.map { course.tags.contains($0) } ?? true
        }
    }
    func starCount(_ course: CourseDiscoveryCourse) -> Int? {
        course.starCount.map { $0 + (starredCourses.contains(course.id) ? 1 : 0) - (Self.initialStars.contains(course.id) ? 1 : 0) }
    }
    func toggleStar(_ id: String) {
        guard course(id) != nil else { return }
        if starredCourses.contains(id) { starredCourses.remove(id) } else { starredCourses.insert(id) }
    }
    func toggleFollow(_ id: String) {
        guard creator(id) != nil else { return }
        if followedCreators.contains(id) { followedCreators.remove(id) } else { followedCreators.insert(id) }
    }
    func toggleTag(_ tag: String) {
        if followedTags.contains(tag) { followedTags.remove(tag) } else { followedTags.insert(tag) }
    }
    func markRead(_ id: String) { if Self.news.contains(where: { $0.id == id }) { readNews.insert(id) } }
}
