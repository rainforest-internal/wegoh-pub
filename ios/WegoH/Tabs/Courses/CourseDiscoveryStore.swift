import Foundation
import Observation

@MainActor
@Observable
final class CourseDiscoveryStore {
    private(set) var library: CourseDiscoveryLibrary?
    private(set) var detail: CourseDiscoveryDetail?
    private(set) var creator: CourseDiscoveryPublicCreator?
    private(set) var trips: [IPhoneTripSummary] = []
    private(set) var detailLoading = false
    private(set) var creatorLoading = false
    private(set) var tripsLoading = false
    private(set) var loading = false
    private(set) var busy = false
    private(set) var needsRefresh = false
    private(set) var errorMessage: String?
    private let session: SessionManager
    private let account: AccountSession?
    private let api: any CourseDiscoveryServing
    private let tripAPI: any IPhoneTripServing
    private let courseAPI: any IPhoneCourseServing
    private let cardPlaces = CourseCardPlaces()
    private var read: UUID?
    private var detailRead: UUID?
    private var creatorRead: UUID?
    private var tripsRead: UUID?
    private var query = ""
    private var tags: [String] = []

    init(session: SessionManager, api: (any CourseDiscoveryServing)? = nil, tripAPI: (any IPhoneTripServing)? = nil,
         courseAPI: (any IPhoneCourseServing)? = nil) {
        self.session = session
        account = session.current
        var configuration: URLSessionConfiguration?
        #if DEBUG
        configuration = CourseDiscoveryUIFixture.configuration ?? CourseUIFixture.profileConfigurationIfRequested()
        #endif
        self.api = api ?? CourseDiscoveryAPI(configuration: configuration)
        self.tripAPI = tripAPI ?? IPhoneTripAPI(configuration: configuration)
        self.courseAPI = courseAPI ?? IPhoneCourseAPI(configuration: configuration)
    }

    func load(query: String = "", tags: [String] = []) async {
        guard !busy else { return }
        let stamp = UUID()
        read = stamp
        self.query = query
        self.tags = tags
        loading = true
        errorMessage = nil
        defer { if read == stamp { loading = false; read = nil } }
        do {
            let value = try await request { try await self.api.library(query: query, tags: tags, token: $0) }
            guard read == stamp else { return }
            library = value
            needsRefresh = false
        } catch {
            guard read == stamp else { return }
            handle(error)
        }
    }

    func refresh() async { await load(query: query, tags: tags) }

    func loadDetail(_ item: CourseDiscoveryItem) async {
        guard !busy else { return }
        let stamp = UUID()
        detailRead = stamp
        detailLoading = true
        defer { if detailRead == stamp { detailLoading = false; detailRead = nil } }
        if detail?.pack.id != item.id || detail?.pack.version != item.version { detail = nil }
        errorMessage = nil
        do {
            let value = try await request { try await self.api.detail(item, token: $0) }
            guard detailRead == stamp else { return }
            detail = value
        } catch {
            guard detailRead == stamp else { return }
            if !isReadTransportFailure(error) { detail = nil }
            handle(error)
        }
    }

    func loadCreator(_ item: CourseDiscoveryItem) async {
        guard let id = item.creatorId else {
            creatorRead = nil; creatorLoading = false; creator = nil
            errorMessage = "이 창작자의 공개 정보를 찾을 수 없어요."
            return
        }
        await loadCreator(id: id)
    }

    func loadCreator(id: String) async {
        guard !busy else { return }
        let stamp = UUID()
        creatorRead = stamp
        creatorLoading = true
        defer { if creatorRead == stamp { creatorLoading = false; creatorRead = nil } }
        if creator?.creator.id != id { creator = nil }
        errorMessage = nil
        guard validDiscoveryAccountID(id) else { creator = nil; errorMessage = "이 창작자의 공개 정보를 찾을 수 없어요."; return }
        do {
            let value = try await request { try await self.api.creator(id, token: $0) }
            guard creatorRead == stamp else { return }
            creator = value
        } catch {
            guard creatorRead == stamp else { return }
            if !isReadTransportFailure(error) { creator = nil }
            handle(error)
        }
    }

    func previewRoute(for item: CourseDiscoveryItem, points: [CourseCoordinate]) async throws -> CourseRoute {
        guard currentAccount != nil else { clear(); throw CancellationError() }
        return try await cardPlaces.route(for: CourseCardRevision(item), points: points) {
            try await self.request { try await self.courseAPI.route(points, token: $0) }
        }
    }

    func cover(_ item: CourseDiscoveryItem) async throws -> Data? {
        guard item.hasCover, let images = api as? any CourseDiscoveryCoverServing else { return nil }
        do { return try await request { try await images.cover(item, token: $0) } }
        catch { _ = discardProtectedData(error); throw error }
    }

    func loadTrips() async {
        guard !busy else { return }
        let stamp = UUID()
        tripsRead = stamp
        tripsLoading = true
        defer { if tripsRead == stamp { tripsLoading = false; tripsRead = nil } }
        errorMessage = nil
        do {
            let value = try await request { try await self.tripAPI.list(token: $0) }
            guard tripsRead == stamp else { return }
            trips = value.trips.filter { $0.state == .planned || $0.state == .active }
        } catch {
            guard tripsRead == stamp else { return }
            trips = []
            handle(error)
        }
    }

    func setStarred(_ item: CourseDiscoveryItem, _ starred: Bool) async throws {
        try await write { try await self.api.setStarred(item, starred: starred, token: $0) }
    }
    func followCreator(_ item: CourseDiscoveryItem) async throws {
        try await write { try await self.api.followCreator(item, token: $0) }
    }
    func unfollowCreator(followID: String) async throws {
        try await write { try await self.api.unfollowCreator(followID, token: $0) }
    }
    func setTagFollowed(tag: String, followed: Bool) async throws {
        try await write { try await self.api.setTagFollowed(tag, followed: followed, token: $0) }
    }
    func markRead(eventID: String) async throws {
        try await write { try await self.api.markRead(eventID, token: $0) }
    }
    func notInterested(_ item: CourseDiscoveryItem) async throws {
        try await write { try await self.api.notInterested(item, token: $0) }
    }
    func report(_ item: CourseDiscoveryItem, reason: String) async throws {
        try await write(removeDetail: item.key) { try await self.api.report(item, reason: reason, token: $0) }
    }
    func addToTrip(_ item: CourseDiscoveryItem, tripID: String) async throws {
        guard item.isValid, validTripID(tripID) else { throw CourseRequestError.invalidInput }
        try await write { try await self.tripAPI.addCourse(tripID, packID: item.id, token: $0) }
    }

    func copy(_ item: CourseDiscoveryItem) async throws -> CourseDraft {
        try beginWrite()
        defer { busy = false }
        do {
            let value = try await request { try await self.api.copy(item, token: $0) }
            guard let account = currentAccount else { clear(); throw CancellationError() }
            return CourseDraft(copy: value, author: account.displayName)
        } catch {
            handle(error)
            throw error
        }
    }

    private func write(removeDetail: String? = nil, _ mutation: (String) async throws -> Void) async throws {
        try beginWrite()
        defer { busy = false }
        do { try await request(mutation) }
        catch { handle(error); throw error }
        needsRefresh = true
        if let removeDetail, detail.map({ "\($0.pack.id):\($0.pack.version)" }) == removeDetail { detail = nil }
        do {
            library = try await request { try await self.api.library(query: self.query, tags: self.tags, token: $0) }
            if let current = detail {
                do { detail = try await request { try await self.api.detail(current.item, token: $0) } }
                catch IPhoneResourceError.missing { detail = nil }
                catch CourseRequestError.missing { detail = nil }
            }
            if let id = creator?.creator.id {
                do { creator = try await request { try await self.api.creator(id, token: $0) } }
                catch IPhoneResourceError.missing { creator = nil }
                catch CourseRequestError.missing { creator = nil }
            }
            needsRefresh = false
        } catch {
            if !discardProtectedData(error) {
                errorMessage = "변경은 저장했지만 최신 정보를 불러오지 못했어요. 다시 불러와 주세요."
            }
        }
    }

    private func beginWrite() throws {
        guard !busy else { throw TripPreparationError.busy }
        guard !needsRefresh else { throw TripPreparationError.refreshRequired }
        busy = true
        read = nil
        detailRead = nil
        creatorRead = nil
        tripsRead = nil
        loading = false
        detailLoading = false
        creatorLoading = false
        tripsLoading = false
        errorMessage = nil
    }

    private func request<T>(_ work: (String) async throws -> T) async throws -> T {
        try Task.checkCancellation()
        guard let account = currentAccount else { clear(); throw CancellationError() }
        return try await session.withToken(for: account, work)
    }

    private var currentAccount: AccountSession? {
        guard session.phase == .signedIn, let current = session.current, let account,
              current.accountID == account.accountID, current.expiresAt == account.expiresAt,
              current.scopes == account.scopes else { return nil }
        return current
    }

    private func isReadTransportFailure(_ error: Error) -> Bool {
        if case IPhoneSessionError.unavailable = error { return true }
        guard let error = error as? URLError else { return false }
        switch error.code {
        case .timedOut, .notConnectedToInternet, .networkConnectionLost,
             .cannotFindHost, .cannotConnectToHost, .dnsLookupFailed: return true
        default: return false
        }
    }

    private func handle(_ error: Error) {
        guard !discardProtectedData(error), !(error is CancellationError) else { return }
        errorMessage = courseErrorMessage(error)
    }

    @discardableResult
    private func discardProtectedData(_ error: Error) -> Bool {
        switch error {
        case IPhoneSessionError.invalidSession, IPhoneSessionError.forbidden:
            clear()
            errorMessage = courseErrorMessage(error)
            return true
        default:
            guard currentAccount == nil else { return false }
            clear()
            return true
        }
    }

    private func clear() {
        cardPlaces.clear()
        read = nil
        detailRead = nil
        creatorRead = nil
        tripsRead = nil
        library = nil
        detail = nil
        creator = nil
        trips = []
        loading = false
        detailLoading = false
        creatorLoading = false
        tripsLoading = false
        needsRefresh = true
    }
}
