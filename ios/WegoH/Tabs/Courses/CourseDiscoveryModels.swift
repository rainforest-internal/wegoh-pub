import Foundation

struct CourseDiscoveryItem: Decodable, Hashable, Identifiable {
    let id: String
    let version: Int
    let title: String
    let author: String
    let description: String
    let stopCount: Int
    let stopNames: [String]
    let starred: Bool
    let starCount: Int
    let tags: [String]
    let canFollow: Bool
    let followId: String?
    let creatorRank: Int?
    let creatorId: String?
    let hasCover: Bool
    let checksum: String
    let stops: [CourseCardStop]
    var key: String { "\(id):\(version)" }

    var isValid: Bool {
        validCourseID(id) && (1...Int(Int32.max)).contains(version)
            && validCourseText(title, maximum: 100) && validCourseText(author, maximum: 80)
            && validCourseText(description, maximum: 500) && (1...3).contains(stopCount)
            && validCourseStopNames(stopNames, count: stopCount)
            && validDiscoveryCount(starCount) && validDiscoveryTags(tags)
            && (followId.map(validCourseFollowID) ?? true)
            && (creatorId.map(validDiscoveryAccountID) ?? true)
            && (creatorRank.map { (1...3).contains($0) } ?? true)
            && (canFollow || followId == nil)
            && checksum.range(of: #"\A[a-f0-9]{64}\z"#, options: .regularExpression) != nil
            && validCourseCardStops(stops, count: stopCount)
    }
}

struct CourseDiscoveryNewsItem: Decodable, Equatable, Identifiable {
    let item: CourseDiscoveryItem
    let eventId: String
    let approvedAt: String
    let read: Bool
    var id: String { eventId }
    var title: String { item.title }
    var author: String { item.author }
    var isValid: Bool { item.isValid && validCourseEventID(eventId) && validDiscoveryTimestamp(approvedAt) }

    private enum CodingKeys: String, CodingKey { case eventId, approvedAt, read }
    init(from decoder: Decoder) throws {
        item = try CourseDiscoveryItem(from: decoder)
        let box = try decoder.container(keyedBy: CodingKeys.self)
        eventId = try box.decode(String.self, forKey: .eventId)
        approvedAt = try box.decode(String.self, forKey: .approvedAt)
        read = try box.decode(Bool.self, forKey: .read)
    }
}

struct CourseLibraryCreator: Decodable, Equatable, Identifiable {
    let id: String
    let name: String?
    let creatorId: String?
    var isValid: Bool {
        validCourseFollowID(id) && (name.map { validCourseText($0, maximum: 80) } ?? true)
            && (creatorId.map(validDiscoveryAccountID) ?? true)
    }
}

struct CourseDiscoveryLibrary: Decodable, Equatable {
    let `public`: [CourseDiscoveryItem]
    let saved: [CourseDiscoveryItem]
    let news: [CourseDiscoveryNewsItem]
    let following: [CourseLibraryCreator]
    let popularTags: [String]
    let followedTags: [String]
    let unreadCount: Int
    var recommended: [CourseDiscoveryItem] { self.public }

    var isValid: Bool {
        self.public.count <= 1000 && saved.count <= 1000 && news.count <= 30 && following.count <= 1000
            && self.public.allSatisfy(\.isValid) && saved.allSatisfy { $0.isValid && $0.starred }
            && news.allSatisfy(\.isValid) && following.allSatisfy(\.isValid)
            && Set(self.public.map(\.id)).count == self.public.count
            && Set(saved.map(\.key)).count == saved.count && Set(news.map(\.id)).count == news.count
            && Set(following.map(\.id)).count == following.count
            && validDiscoveryTags(popularTags, maximum: 1000) && validDiscoveryTags(followedTags, maximum: 1000)
            && validDiscoveryCount(unreadCount)
    }
}

struct CourseDiscoveryDetail: Decodable, Equatable {
    let pack: OwnedCourse
    let checksum: String
    let tags: [String]
    let hasCover: Bool
    let creatorId: String?
    let starred: Bool
    let starCount: Int
    let canFollow: Bool
    let followId: String?

    var item: CourseDiscoveryItem {
        .init(id: pack.id, version: pack.version, title: pack.title, author: pack.author,
              description: pack.description, stopCount: pack.stops.count, stopNames: pack.stops.map(\.name),
              starred: starred, starCount: starCount,
              tags: tags, canFollow: canFollow, followId: followId, creatorRank: nil, creatorId: creatorId,
              hasCover: hasCover, checksum: checksum, stops: pack.stops.map(CourseCardStop.init))
    }

    var isValid: Bool {
        pack.isValid && checksum.range(of: #"\A[a-f0-9]{64}\z"#, options: .regularExpression) != nil
            && validDiscoveryTags(tags) && validDiscoveryCount(starCount)
            && (creatorId.map(validDiscoveryAccountID) ?? true) && (followId.map(validCourseFollowID) ?? true)
            && (canFollow || followId == nil)
    }
}

struct CourseDiscoveryPublicCreator: Decodable, Equatable {
    struct Profile: Decodable, Equatable {
        let id: String
        let name: String
        let courseCount: Int
        let starCount: Int
        let followerCount: Int
        let following: Bool
        let followId: String?
        var isValid: Bool {
            validDiscoveryAccountID(id) && validCourseText(name, maximum: 80)
                && validDiscoveryCount(courseCount) && validDiscoveryCount(starCount) && validDiscoveryCount(followerCount)
                && (followId.map(validCourseFollowID) ?? true) && following == (followId != nil)
        }
    }
    let creator: Profile
    let courses: [CourseDiscoveryItem]
    var isValid: Bool {
        creator.isValid && courses.count <= 1000 && courses.allSatisfy { $0.isValid && $0.creatorId == creator.id }
            && Set(courses.map(\.id)).count == courses.count
    }
}

struct CourseTagInsights {
    struct TagCount: Equatable, Identifiable {
        let tag: String
        let count: Int
        var id: String { courseTagKey(tag) }
    }
    struct CreatorCount: Identifiable {
        let id: String
        let item: CourseDiscoveryItem
        let count: Int
    }
    let courses: [CourseDiscoveryItem]
    let selectedTags: Set<String>

    var relatedTags: [TagCount] {
        let selected = Set(selectedTags.map(courseTagKey))
        let tags = courses.flatMap(\.tags).filter { !selected.contains(courseTagKey($0)) }
        return Dictionary(grouping: tags, by: courseTagKey).values.compactMap { values in
            values.first.map { TagCount(tag: $0, count: values.count) }
        }.sorted { $0.count == $1.count ? $0.tag < $1.tag : $0.count > $1.count }
    }

    var creators: [CreatorCount] {
        Dictionary(grouping: courses, by: \.creatorId).compactMap { id, values -> CreatorCount? in
            guard let id, let item = values.first else { return nil }
            return CreatorCount(id: id, item: item, count: values.count)
        }.sorted { $0.count == $1.count ? $0.id < $1.id : $0.count > $1.count }
    }
}

func normalizedDiscoveryTag(_ raw: String) -> String? { normalizedCourseTag(raw) }

func courseVisibleFilterTags(popular: [String], selected: Set<String>) -> [String] {
    var seen = Set<String>()
    return (Array(popular.prefix(8)) + selected.sorted()).filter { seen.insert(courseTagKey($0)).inserted }
}

func validDiscoveryTags(_ tags: [String], maximum: Int = 8) -> Bool {
    tags.count <= maximum && tags.allSatisfy { normalizedDiscoveryTag($0) == $0 }
        && Set(tags.map(courseTagKey)).count == tags.count
}

func validCourseFollowID(_ value: String) -> Bool {
    value.range(of: #"\A[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\z"#, options: .regularExpression) != nil
}
func validDiscoveryAccountID(_ value: String) -> Bool {
    value.range(of: #"\Ateam-[0-9a-f]{40}\z"#, options: .regularExpression) != nil
}
func validCourseEventID(_ value: String) -> Bool {
    value.range(of: #"\A[1-9][0-9]{0,18}\z"#, options: .regularExpression) != nil && (Int64(value).map { $0 > 0 } ?? false)
}
private func validDiscoveryCount(_ value: Int) -> Bool { (0...Int(Int32.max)).contains(value) }
private func validDiscoveryTimestamp(_ value: String) -> Bool {
    guard value.utf8.count <= 64 else { return false }
    let formatter = ISO8601DateFormatter()
    if formatter.date(from: value) != nil { return true }
    formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    return formatter.date(from: value) != nil
}
