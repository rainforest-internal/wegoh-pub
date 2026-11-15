import Foundation
import Observation

@MainActor
@Observable
final class CoursesStore {
    private(set) var courses: [CourseSummary] = []
    private(set) var isLoading = false
    private(set) var hasLoaded = false
    private(set) var error: String?
    let api: any IPhoneCourseServing
    private let cardPlaces = CourseCardPlaces()
    private var read: UUID?

    init(api: any IPhoneCourseServing = IPhoneCourseAPI()) { self.api = api }

    func load(session: SessionManager, account: AccountSession) async {
        guard session.phase == .signedIn else { return }
        let stamp = UUID()
        read = stamp
        isLoading = true
        error = nil
        defer { if read == stamp { isLoading = false } }
        do {
            let items = try await session.withToken(for: account) { try await api.list(token: $0) }
            guard read == stamp else { return }
            courses = items
            hasLoaded = true
        } catch is CancellationError {
        } catch {
            guard read == stamp, session.current == account else { return }
            self.error = courseErrorMessage(error)
        }
    }

    func previewRoute(for course: CourseSummary, points: [CourseCoordinate], session: SessionManager, account: AccountSession) async throws -> CourseRoute {
        guard session.phase == .signedIn, session.current == account else { throw CancellationError() }
        return try await cardPlaces.route(for: CourseCardRevision(course), points: points) {
            try await session.withToken(for: account) { try await self.api.route(points, token: $0) }
        }
    }

    func apply(_ receipt: CourseSaveReceipt) {
        read = nil
        isLoading = false
        error = nil
        hasLoaded = true
        let pack = receipt.pack
        let summary = CourseSummary(id: pack.id, version: pack.version, title: pack.title, author: pack.author,
            description: pack.description, stopCount: pack.stops.count, stopNames: pack.stops.map(\.name),
            checksum: receipt.checksum, state: receipt.state, stops: pack.stops.map(CourseCardStop.init))
        if let index = courses.firstIndex(where: { $0.id == pack.id }) { courses[index] = summary }
        else { courses.insert(summary, at: 0) }
    }
}

func courseErrorMessage(_ error: Error) -> String {
    if case IPhoneSessionError.forbidden = error {
        return "경로를 보려면 다시 로그인해 주세요."
    }
    if case IPhoneSessionError.invalidResponse = error {
        return "경로 정보를 확인할 수 없어요. 다시 시도해 주세요."
    }
    if case IPhoneSessionError.unavailable = error {
        return CourseRequestError.unavailable.errorDescription ?? "서버에 연결할 수 없어요."
    }
    if let resourceError = error as? IPhoneResourceError {
        let courseError: CourseRequestError = switch resourceError {
        case .invalidInput: .invalidInput
        case .conflict, .tripConflict: .conflict
        case .missing: .missing
        case .vehicleLimit, .unavailable: .unavailable
        }
        return courseError.errorDescription ?? "경로를 불러올 수 없어요."
    }
    return (error as? LocalizedError)?.errorDescription ?? "경로를 불러올 수 없어요. 다시 시도해 주세요."
}
