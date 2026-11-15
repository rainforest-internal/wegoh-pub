import Foundation

protocol IPhoneCourseServing {
    func list(token: String) async throws -> [CourseSummary]
    func detail(_ summary: CourseSummary, token: String) async throws -> CourseDetail
    func save(_ draft: CourseDraft, token: String) async throws -> CourseSaveReceipt
    func search(_ query: String, token: String) async throws -> [CoursePlace]
    func route(_ points: [CourseCoordinate], token: String) async throws -> CourseRoute
}

enum CourseRequestError: Error, LocalizedError {
    case invalidInput, conflict, missing, unavailable
    var errorDescription: String? {
        switch self {
        case .invalidInput: "경로 이름과 설명, 선택한 장소를 확인해 주세요."
        case .conflict: "이미 새 버전이 저장됐어요. 내 경로에서 최신 버전을 확인한 뒤 다시 수정해 주세요."
        case .missing: "이 경로를 찾을 수 없어요. 목록을 새로고침해 주세요."
        case .unavailable: "서버에 연결할 수 없어요. 입력한 내용은 그대로 두고 다시 시도해 주세요."
        }
    }
}

final class IPhoneCourseAPI: IPhoneCourseServing {
    private let http: IPhoneSessionAPI
    init(configuration: URLSessionConfiguration? = nil) { http = IPhoneSessionAPI(configuration: configuration) }

    func list(token: String) async throws -> [CourseSummary] {
        struct Catalogue: Decodable { let packs: [CourseSummary] }
        let value: Catalogue = try await read("courses", token: token)
        guard value.packs.count <= 1000, value.packs.allSatisfy(\.isValid),
              Set(value.packs.map(\.id)).count == value.packs.count else { throw IPhoneSessionError.invalidResponse }
        return value.packs
    }

    func detail(_ summary: CourseSummary, token: String) async throws -> CourseDetail {
        guard summary.isValid else { throw IPhoneSessionError.invalidResponse }
        let value: CourseDetail = try await read("courses/\(summary.id)/versions/\(summary.version)", token: token)
        guard value.pack.isValid, value.pack.id == summary.id, value.pack.version == summary.version,
              value.remixDraftId.map({ $0.range(of: #"\A[a-f0-9]{32}\z"#, options: .regularExpression) != nil }) ?? true else {
            throw IPhoneSessionError.invalidResponse
        }
        return value
    }

    func save(_ draft: CourseDraft, token: String) async throws -> CourseSaveReceipt {
        guard draft.canSave else { throw CourseRequestError.invalidInput }
        struct Publication: Encodable { let pack: OwnedCourse; let rightsConfirmed: Bool; let remixDraftId: String?; let tags: [String]; let copyCoverFromVersion: Int? }
        let payload = try JSONEncoder().encode(Publication(pack: draft.pack, rightsConfirmed: true, remixDraftId: draft.remixDraftId, tags: draft.tags, copyCoverFromVersion: draft.copyCoverFromVersion))
        let data = try await http.resource("courses", method: "POST", payload: payload, token: token, status: 201, alternateStatus: 200)
        let value: CourseSaveReceipt = try decode(data)
        guard value.id == draft.id, value.version == draft.pack.version,
              value.pack.isValid, value.pack.id == value.id, value.pack.version == value.version,
              ["approved", "rejected", "quarantined"].contains(value.state),
              value.checksum.range(of: #"\A[a-f0-9]{64}\z"#, options: .regularExpression) != nil else {
            throw IPhoneSessionError.invalidResponse
        }
        return value
    }

    func search(_ query: String, token: String) async throws -> [CoursePlace] {
        struct Results: Decodable { let places: [CoursePlace] }
        var components = URLComponents()
        components.queryItems = [URLQueryItem(name: "q", value: query.trimmingCharacters(in: .whitespacesAndNewlines))]
        let value: Results = try await read("places/search?" + (components.percentEncodedQuery ?? ""), token: token)
        guard value.places.count <= 15, value.places.allSatisfy(\.isValid) else { throw IPhoneSessionError.invalidResponse }
        return value.places
    }

    func route(_ points: [CourseCoordinate], token: String) async throws -> CourseRoute {
        guard (2...3).contains(points.count), points.allSatisfy(\.isValid) else { throw CourseRequestError.invalidInput }
        struct Request: Encodable { let points: [CourseCoordinate] }
        struct Result: Decodable { let distanceMeters: Double; let durationSeconds: Double; let path: [[Double]] }
        let data = try await http.resource("routes/preview", method: "POST", payload: JSONEncoder().encode(Request(points: points)), token: token)
        let value: Result = try decode(data)
        guard value.distanceMeters.isFinite, value.distanceMeters >= 0,
              value.durationSeconds.isFinite, value.durationSeconds >= 0,
              (2...2000).contains(value.path.count), value.path.allSatisfy({ $0.count == 2 }) else {
            throw IPhoneSessionError.invalidResponse
        }
        let path = value.path.map { CourseCoordinate(lat: $0[0], lng: $0[1]) }
        guard path.allSatisfy(\.isValid) else { throw IPhoneSessionError.invalidResponse }
        return CourseRoute(distanceMeters: value.distanceMeters, durationSeconds: value.durationSeconds, path: path)
    }

    private func read<T: Decodable>(_ path: String, token: String) async throws -> T {
        try decode(await http.resource(path, token: token))
    }

    private func decode<T: Decodable>(_ data: Data) throws -> T {
        do { return try JSONDecoder().decode(T.self, from: data) }
        catch { throw IPhoneSessionError.invalidResponse }
    }
}
