import Foundation

enum IPhoneTripCourseDraftError: Error, LocalizedError {
    case permissionRequired, selectionChanged
    var errorDescription: String? {
        switch self {
        case .permissionRequired: "공유 경로를 가져올 수 없어요. 원저자의 재사용 허용과 내 경로 만들기 권한을 확인해 주세요."
        case .selectionChanged: "공유 경로나 재사용 허용이 바뀌었어요. 장소 목록을 다시 불러온 뒤 선택해 주세요."
        }
    }
}

struct IPhoneTripHistoryReceipt: Decodable {
    var id: String
    var revision: Int
    var permissionRevision: Int
    var isValid: Bool { validTripID(id) && validTripRevision(revision) && validTripRevision(permissionRevision) }
}

struct IPhoneTripResults: Decodable {
    struct Period: Decodable { var startedAt: String; var endedAt: String? }
    struct Summary: Decodable {
        struct Course: Decodable { var id: String; var version: Int; var title: String }
        var title: String
        var courses: [Course]
        var isValid: Bool {
            validTripText(title, max: 40) && courses.count <= 10
                && courses.allSatisfy { validCourseID($0.id) && validTripRevision($0.version) && validTripText($0.title, max: 120) }
                && Set(courses.map(\.id)).count == courses.count
        }
    }
    var tripId: String
    var state: String
    var readOnly: Bool
    var ownPeriod: Period
    var history: IPhoneTripHistoryReceipt?
    var sourceKind: String
    var startTimeEstimated: Bool
    var summary: Summary?
    var isValid: Bool {
        validTripID(tripId) && ["completed", "cancelled", "left"].contains(state) && readOnly
            && validTripTimestamp(ownPeriod.startedAt) && (ownPeriod.endedAt.map(validTripTimestamp) ?? true)
            && (history?.isValid ?? true) && validTripText(sourceKind, max: 64) && (summary?.isValid ?? true)
    }
}

struct IPhoneTripSavedHistory: Decodable {
    struct Source: Decodable { var tripId: String? }
    struct Visit: Decodable, Identifiable {
        struct Place: Decodable { var name: String; var latitude: Double; var longitude: Double }
        var id: String
        var place: Place
        var visitedAt: String
        var review: String
        var rating: Int?
        var isValid: Bool {
            validTripID(id) && validTripText(place.name, max: 80)
                && validTripCoordinates(lat: place.latitude, lng: place.longitude) && validTripTimestamp(visitedAt)
                && validTripText(review, max: 1000, multiline: true) && (rating.map { (1...5).contains($0) } ?? true)
        }
    }
    var id: String
    var title: String
    var ownerId: String
    var own: Bool
    var revision: Int
    var startedAt: String
    var endedAt: String?
    var source: Source
    var visits: [Visit]
    var isValid: Bool {
        validTripID(id) && validTripText(title, max: 100) && validTripAccountID(ownerId) && own && validTripRevision(revision)
            && validTripTimestamp(startedAt) && (endedAt.map(validTripTimestamp) ?? true)
            && visits.count <= 500 && visits.allSatisfy(\.isValid) && Set(visits.map(\.id)).count == visits.count
    }
}

struct IPhoneTripCourseDraftOptions: Decodable {
    struct Place: Decodable, Identifiable {
        var id: String
        var courseId: String
        var version: Int
        var name: String
        var latitude: Double
        var longitude: Double
        var canReuse: Bool
        var isValid: Bool {
            validTripID(id) && validCourseID(courseId) && validTripRevision(version) && validTripText(name, max: 80)
                && validTripCoordinates(lat: latitude, lng: longitude)
        }
    }
    var title: String
    var selectionFingerprint: String
    var places: [Place]
    var isValid: Bool {
        validTripText(title, max: 40) && selectionFingerprint.range(of: #"\A[a-f0-9]{64}\z"#, options: .regularExpression) != nil
            && places.count <= 30 && places.allSatisfy(\.isValid) && Set(places.map(\.id)).count == places.count
    }
}

struct IPhoneTripHistoryAPI {
    private let transport: IPhoneSessionAPI
    init(configuration: URLSessionConfiguration? = nil) { transport = IPhoneSessionAPI(configuration: configuration) }
    private func path(_ tripID: String, _ suffix: String) throws -> String {
        guard validTripID(tripID) else { throw IPhoneTripRequestError.invalidInput }
        return "trips/" + tripID + "/" + suffix
    }
    private func decode<T: Decodable>(_ data: Data, as type: T.Type) throws -> T {
        do { return try JSONDecoder().decode(type, from: data) }
        catch { throw IPhoneSessionError.invalidResponse }
    }
    func results(_ tripID: String, token: String) async throws -> IPhoneTripResults {
        let value = try decode(await transport.resource(path(tripID, "results"), token: token), as: IPhoneTripResults.self)
        guard value.isValid, value.tripId == tripID else { throw IPhoneSessionError.invalidResponse }
        return value
    }
    func history(_ tripID: String, token: String) async throws -> IPhoneTripSavedHistory {
        let value = try decode(await transport.resource(path(tripID, "history"), token: token), as: IPhoneTripSavedHistory.self)
        guard value.isValid, value.source.tripId == tripID else { throw IPhoneSessionError.invalidResponse }
        return value
    }
    func saveHistory(_ tripID: String, title: String, token: String) async throws -> IPhoneTripHistoryReceipt {
        guard validTripText(title, max: 100) else { throw IPhoneTripRequestError.invalidInput }
        let data = try await transport.resource(path(tripID, "history"), method: "POST",
            payload: JSONEncoder().encode(["title": title.trimmingCharacters(in: .whitespacesAndNewlines)]), token: token, status: 201, alternateStatus: 200)
        let value = try decode(data, as: IPhoneTripHistoryReceipt.self)
        guard value.isValid else { throw IPhoneSessionError.invalidResponse }
        return value
    }
    func draftOptions(_ tripID: String, token: String) async throws -> IPhoneTripCourseDraftOptions {
        let value = try decode(await transport.resource(path(tripID, "course-draft-options"), token: token), as: IPhoneTripCourseDraftOptions.self)
        guard value.isValid else { throw IPhoneSessionError.invalidResponse }
        return value
    }
    func createDraft(_ tripID: String, options: IPhoneTripCourseDraftOptions, selection: Set<String>, token: String) async throws -> CourseDetail {
        let places = options.places.filter { selection.contains($0.id) }
        guard options.isValid, (1...3).contains(selection.count), places.count == selection.count, places.allSatisfy(\.canReuse)
        else { throw IPhoneTripRequestError.invalidInput }
        struct Body: Encodable { var selectionIds: [String]; var selectionFingerprint: String }
        let data: Data
        do {
            data = try await transport.resource(path(tripID, "course-drafts"), method: "POST",
                payload: JSONEncoder().encode(Body(selectionIds: places.map(\.id), selectionFingerprint: options.selectionFingerprint)), token: token, status: 201)
        } catch IPhoneSessionError.forbidden { throw IPhoneTripCourseDraftError.permissionRequired }
        catch IPhoneResourceError.conflict { throw IPhoneTripCourseDraftError.selectionChanged }
        let value = try decode(data, as: CourseDetail.self)
        guard value.pack.isValid, value.pack.version == 1, value.remixDraftId.map(validTripID) == true,
              value.tags == [], value.hasCover == false, value.pack.stops.count == places.count,
              zip(value.pack.stops, places).allSatisfy({ stop, place in stop.name == place.name && stop.latitude == place.latitude && stop.longitude == place.longitude })
        else { throw IPhoneSessionError.invalidResponse }
        return value
    }
}

private func validTripTimestamp(_ value: String) -> Bool {
    guard !value.isEmpty, value.utf8.count <= 64 else { return false }
    let formatter = ISO8601DateFormatter()
    formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    if formatter.date(from: value) != nil { return true }
    formatter.formatOptions = [.withInternetDateTime]
    return formatter.date(from: value) != nil
}
