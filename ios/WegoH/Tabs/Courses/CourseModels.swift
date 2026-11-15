import Foundation

struct CourseCoordinate: Codable, Hashable {
    let lat: Double
    let lng: Double
    var isValid: Bool { lat.isFinite && lng.isFinite && (32...39).contains(lat) && (124...132).contains(lng) }
}

struct CourseRoute {
    let distanceMeters: Double
    let durationSeconds: Double
    let path: [CourseCoordinate]
}

/// 목록 응답에 함께 오는 카드 지도용 장소. 카드마다 상세를 다시 읽지 않는다.
struct CourseCardStop: Codable, Hashable, Identifiable {
    let id: String
    let name: String
    let lat: Double
    let lng: Double

    var isValid: Bool {
        validCourseID(id) && validCourseText(name, maximum: 80) && lat.isFinite && lng.isFinite &&
        (-90...90).contains(lat) && (-180...180).contains(lng)
    }
}

extension CourseCardStop {
    init(_ stop: CourseStop) {
        self.init(id: stop.id, name: stop.name, lat: stop.latitude, lng: stop.longitude)
    }
}

func validCourseCardStops(_ stops: [CourseCardStop], count: Int) -> Bool {
    stops.count == count && Set(stops.map(\.id)).count == stops.count && stops.allSatisfy(\.isValid)
}

struct CourseSummary: Codable, Hashable, Identifiable {
    let id: String
    let version: Int
    let title: String
    let author: String
    let description: String
    let stopCount: Int
    let stopNames: [String]
    let checksum: String
    let state: String
    let stops: [CourseCardStop]

    var isValid: Bool {
        validCourseID(id) && (1...2_147_483_647).contains(version) &&
        validCourseText(title, maximum: 100) && validCourseText(author, maximum: 80) &&
        validCourseText(description, maximum: 500) && (1...3).contains(stopCount) &&
        validCourseStopNames(stopNames, count: stopCount) &&
        checksum.range(of: #"\A[a-f0-9]{64}\z"#, options: .regularExpression) != nil &&
        ["approved", "rejected", "quarantined"].contains(state) && validCourseCardStops(stops, count: stopCount)
    }

    var stateLabel: String { state == "approved" ? "공개 중" : "공개 중지" }
}

struct CoursePlace: Codable, Equatable, Identifiable {
    let id: String
    let name: String
    let address: String
    let roadAddress: String
    let lat: Double
    let lng: Double
    let source: String

    var displayAddress: String { roadAddress.isEmpty ? address : roadAddress }
    var isValid: Bool {
        !id.isEmpty && id.count <= 240 && validCourseText(name, maximum: 80) &&
        address.count <= 200 && roadAddress.count <= 200 && source == "kakao" &&
        lat.isFinite && lng.isFinite && (-90...90).contains(lat) && (-180...180).contains(lng)
    }
}

struct CourseStop: Codable, Hashable, Identifiable {
    struct Arrival: Codable, Hashable { var type: String; var message: String }
    struct Place: Codable, Hashable { let id: String; let provider: String; let name: String; let address: String }
    var id: String
    var name: String
    var latitude: Double
    var longitude: Double
    var radiusMeters: Double
    var action: Arrival
    var poiId: String?
    var address: String?
    var place: Place?

    init(place result: CoursePlace) {
        id = "stop-" + UUID().uuidString.lowercased()
        name = result.name
        latitude = result.lat
        longitude = result.lng
        radiusMeters = 100
        action = Arrival(type: "chime", message: "\(result.name)에 도착했어요.")
        address = result.displayAddress
        place = Place(id: result.id, provider: result.source, name: result.name, address: result.displayAddress)
    }

    var isValid: Bool {
        validCourseID(id) && validCourseText(name, maximum: 80) && latitude.isFinite && longitude.isFinite &&
        (-90...90).contains(latitude) && (-180...180).contains(longitude) &&
        radiusMeters.isFinite && (25...500).contains(radiusMeters) && action.type == "chime" &&
        validCourseText(action.message, maximum: 240)
    }
}

struct OwnedCourse: Codable, Equatable, Identifiable {
    var schemaVersion = 1
    var id: String
    var version: Int
    var title: String
    var author: String
    var description: String
    var stops: [CourseStop]

    var isValid: Bool {
        schemaVersion == 1 && validCourseID(id) && (1...2_147_483_647).contains(version) &&
        validCourseText(title, maximum: 100) && validCourseText(author, maximum: 80) &&
        validCourseText(description, maximum: 500) && (1...3).contains(stops.count) &&
        Set(stops.map(\.id)).count == stops.count && stops.allSatisfy(\.isValid)
    }
}

struct CourseDetail: Codable, Equatable {
    var pack: OwnedCourse
    let remixDraftId: String?
    var tags: [String]? = nil
    var hasCover: Bool? = nil
}

struct CourseDraft: Equatable, Identifiable {
    var pack: OwnedCourse
    let remixDraftId: String?
    let original: OwnedCourse?
    var tags: [String]
    let originalTags: [String]
    let copyCoverFromVersion: Int?
    var rightsConfirmed = false
    var id: String { pack.id }
    var isEditing: Bool { original != nil }
    var hasChanges: Bool {
        guard var previous = original else {
            return !pack.title.isEmpty || !pack.description.isEmpty || !pack.stops.isEmpty || !tags.isEmpty
        }
        previous.version = pack.version
        return previous != pack || tags != originalTags
    }
    var tagsAreValid: Bool {
        tags.count <= 8 && tags.allSatisfy { normalizedCourseTag($0) == $0 }
            && Set(tags.map(courseTagKey)).count == tags.count
    }
    var canSave: Bool { pack.isValid && tagsAreValid && rightsConfirmed && hasChanges }
    var saveRequirement: String? {
        if !validCourseText(pack.title, maximum: 100) { return "경로 이름을 1~100자로 입력해 주세요." }
        if !validCourseText(pack.description, maximum: 500) { return "경로 설명을 1~500자로 입력해 주세요." }
        if pack.stops.isEmpty { return "장소를 1곳 이상 추가해 주세요." }
        if !pack.isValid { return "선택한 장소와 경로 정보를 확인해 주세요." }
        if !tagsAreValid { return "태그는 최대 8개, 각각 24자까지 입력할 수 있어요." }
        if !hasChanges { return "수정한 내용이 없어요." }
        if !rightsConfirmed { return "경로와 장소 정보의 제3자 제공에 동의해 주세요." }
        return nil
    }


    init(author: String) {
        pack = OwnedCourse(id: "course-" + UUID().uuidString.lowercased(), version: 1,
                           title: "", author: author, description: "", stops: [])
        remixDraftId = nil
        original = nil
        tags = []
        originalTags = []
        copyCoverFromVersion = nil
    }

    init(copy detail: CourseDetail, author: String) {
        pack = detail.pack
        pack.author = author
        remixDraftId = detail.remixDraftId
        original = nil
        tags = detail.tags ?? []
        originalTags = []
        copyCoverFromVersion = nil
    }

    init(detail: CourseDetail) {
        original = detail.pack
        tags = detail.tags ?? []
        originalTags = tags
        copyCoverFromVersion = detail.hasCover == true ? detail.pack.version : nil
        pack = detail.pack
        pack.version += 1
        remixDraftId = detail.remixDraftId
    }
}

struct CourseSaveReceipt: Decodable {
    let pack: OwnedCourse
    let id: String
    let version: Int
    let checksum: String
    let state: String
}

func validCourseID(_ value: String) -> Bool {
    value.range(of: #"\A[a-z0-9][a-z0-9_-]{0,79}\z"#, options: .regularExpression) != nil
}

func validCourseText(_ value: String, maximum: Int) -> Bool {
    !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && value.utf16.count <= maximum
}

func validCourseStopNames(_ names: [String], count: Int) -> Bool {
    names.count == count && names.allSatisfy { validCourseText($0, maximum: 80) }
}

func normalizedCourseTag(_ value: String) -> String? {
    var tag = value.trimmingCharacters(in: .whitespacesAndNewlines)
    if tag.hasPrefix("#") { tag.removeFirst() }
    tag = tag.precomposedStringWithCanonicalMapping
    guard (1...24).contains(tag.unicodeScalars.count),
          tag.range(of: #"\A[\p{L}\p{N}][\p{L}\p{M}\p{N}_-]*\z"#, options: .regularExpression) != nil else { return nil }
    return tag
}

func courseTagKey(_ tag: String) -> String {
    tag.folding(options: [.caseInsensitive], locale: Locale(identifier: "en_US_POSIX"))
}
