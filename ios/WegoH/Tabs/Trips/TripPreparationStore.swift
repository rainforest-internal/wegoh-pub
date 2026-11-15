import Foundation
import Observation

@MainActor
@Observable
final class TripPreparationStore {
    private(set) var detail: IPhoneTripDetail?
    private(set) var loading = false
    private(set) var busy = false
    private(set) var needsRefresh = false
    private(set) var errorMessage: String?
    private(set) var hasLeftTrip = false
    private(set) var vehicles: [ProfileVehicle] = []
    private(set) var previewRemotePreferences = TripRemotePreferences()
    let isPreview: Bool
    let previewActorName: String?
    let previewDateLabel: String?
    let previewCourseStops: [String: [String]]
    let previewAvailableCourses: [IPhoneTripCourse]
    private let tripID: String
    private let session: SessionManager?
    private let account: AccountSession?
    private let api: any IPhoneTripServing
    private let onMutation: (@MainActor () async -> Void)?
    private var read: UUID?
    private var vehicleRead: UUID?
    private var signalRead: UUID?
    private var storedSignals: [IPhoneTripSignal] = []
    private var signalsCarID: String?
    private let activityAPI: any IPhoneTripActivityServing
    var activeSignals: [IPhoneTripSignal] {
        guard isCurrent, detail?.state == .active, detail?.myCar?.id == signalsCarID else { return [] }
        return storedSignals.filter(\.inProgress)
    }
    var accountIsCurrent: Bool { isCurrent }

    init(tripID: String, session: SessionManager, api: any IPhoneTripServing = IPhoneTripAPI(), activityAPI: any IPhoneTripActivityServing = IPhoneTripActivityAPI(), onMutation: (@MainActor () async -> Void)? = nil) {
        self.tripID = tripID
        self.session = session
        account = session.current
        self.api = api
        self.activityAPI = activityAPI
        self.onMutation = onMutation
        isPreview = false
        previewActorName = nil
        previewDateLabel = nil
        previewCourseStops = [:]
        previewAvailableCourses = []
    }

    init(preview: TripPreview, actorName: String? = nil) {
        let api = TripPreparationPreviewAPI(preview: preview, actorName: actorName)
        self.api = api
        activityAPI = IPhoneTripActivityAPI()
        onMutation = nil
        tripID = api.tripID
        session = nil
        account = nil
        isPreview = true
        previewActorName = api.actorName
        previewDateLabel = preview.dateLabel
        previewCourseStops = api.courseStops
        previewAvailableCourses = api.courseOptions
        if preview.id == "gangneung" {
            previewRemotePreferences = TripRemotePreferences(enabled: true, groups: Set(TripRemoteGroup.allCases))
        }
    }

    func load() async {
        guard read == nil, !busy else { return }
        let stamp = UUID()
        read = stamp
        loading = detail == nil
        errorMessage = nil
        defer { if read == stamp { read = nil; loading = false } }
        do {
            var value = try await request { try await $0.detail(self.tripID, token: $1) }
            guard read == stamp else { return }
            if !isPreview, value.me?.state == .accepted, value.state == .planned || value.state == .active,
               !value.locationConsent {
                busy = true
                defer { busy = false }
                try await request { try await $0.setLocationSharing(self.tripID, enabled: true, token: $1) }
                guard read == stamp else { throw CancellationError() }
                value = try await request { try await $0.detail(self.tripID, token: $1) }
                guard read == stamp else { throw CancellationError() }
                guard value.locationConsent else { throw IPhoneSessionError.invalidResponse }
            }
            detail = value
            needsRefresh = false
        } catch is CancellationError {
            if read == stamp, !isCurrent { discardProtectedData(for: IPhoneSessionError.invalidSession) }
        } catch {
            if read == stamp, !discardProtectedData(for: error), isCurrent {
                errorMessage = tripPreparationErrorMessage(error)
            }
        }
    }

    func loadVehicles() async {
        guard vehicleRead == nil else { return }
        let stamp = UUID()
        vehicleRead = stamp
        defer { if vehicleRead == stamp { vehicleRead = nil } }
        do {
            let value: [ProfileVehicle]
            if isPreview {
                try Task.checkCancellation()
                guard detail?.me != nil else { throw TripPreparationError.previewActorMissing }
                value = [ProfileVehicle(profile: IPhoneVehicleProfile(
                    deviceId: "preview-vehicle", plateNumber: "123가4567", name: "샘플 차량", defaultName: "샘플 차량", revision: 0))]
            } else {
                guard let session, let current = session.current, current.accountID == account?.accountID
                else { throw IPhoneSessionError.invalidSession }
                value = try await session.withToken(for: current) { try await IPhoneProfileAPI().vehicles(token: $0) }
            }
            guard vehicleRead == stamp, isCurrent else { throw CancellationError() }
            vehicles = value
        } catch is CancellationError {
            if vehicleRead == stamp, !isCurrent { discardProtectedData(for: IPhoneSessionError.invalidSession) }
        } catch {
            if vehicleRead == stamp, !discardProtectedData(for: error), isCurrent {
                errorMessage = tripPreparationErrorMessage(error)
            }
        }
    }

    func createCar(name: String, seats: Int, remote: TripRemotePreferences = .init()) async throws {
        guard remote.isValid else { throw IPhoneTripRequestError.invalidInput }
        try await write { api, token in _ = try await api.createCar(self.tripID, name: name, seats: seats, remotePolicy: remote.policy, token: token) }
        if isPreview { previewRemotePreferences = remote }
    }

    func setRole(accountID: String, role: IPhoneTripRole) async throws {
        guard let detail, detail.isOwner else { throw IPhoneSessionError.forbidden }
        try await write { try await $0.setRole(self.tripID, accountID: accountID, role: role, revision: detail.revision, token: $1) }
    }

    func setRemotePreferences(_ preferences: TripRemotePreferences) async throws {
        guard preferences.isValid, let car = detail?.myCar, car.isMine else { throw IPhoneSessionError.forbidden }
        try await write { try await $0.setRemotePolicy(self.tripID, carID: car.id, policy: preferences.policy, token: $1) }
        if isPreview { previewRemotePreferences = preferences }
    }

    func activityRequest<T>(_ work: (String) async throws -> T) async throws -> T {
        guard !isPreview else { throw TripPreparationError.previewUnsupported }
        return try await request { _, token in try await work(token) }
    }

    func setPreviewRemotePreferences(_ preferences: TripRemotePreferences) {
        guard isPreview, preferences.isValid else { return }
        previewRemotePreferences = preferences
    }

    func ride(carID: String) async throws {
        try await write { try await $0.ride(self.tripID, carID: carID, token: $1) }
    }

    func leaveCar() async throws {
        try await write { try await $0.leaveCar(self.tripID, token: $1) }
    }

    func addCourse(packID: String) async throws {
        try await write { try await $0.addCourse(self.tripID, packID: packID, token: $1) }
    }

    func saveMyPlaces(_ draft: IPhoneTripMyPlacesDraft) async throws {
        guard let detail, let car = detail.myCar, car.iRide, !car.isMine else { throw IPhoneSessionError.forbidden }
        guard draft.isValid else { throw IPhoneTripRequestError.invalidInput }
        guard detail.routeContractVersion != 2 || detail.state == .planned else {
            throw IPhoneTripRequestError.routeConflict("TRIP_ROUTE_PLAN_LOCKED")
        }
        try await write { try await $0.saveMyPlaces(self.tripID, carID: car.id, draft: draft, token: $1) }
    }

    func prioritizeCourses(packIDs: [String], revision: Int) async throws {
        guard let detail, detail.isOwner else { throw IPhoneSessionError.forbidden }
        guard detail.state == .planned else { throw TripPreparationError.notPreparing }
        guard Set(packIDs) == Set(detail.courses.map(\.packId)) else { throw IPhoneTripRequestError.invalidInput }
        try await write { try await $0.prioritizeCourses(self.tripID, packIDs: packIDs, revision: revision, token: $1) }
    }

    func invite(accountID: String) async throws {
        try await write { try await $0.addMember(self.tripID, accountID: accountID, token: $1) }
    }

    func addCarPlace(carID: String, kind: IPhoneTripPlaceKind, name: String, lat: Double, lng: Double) async throws {
        try await write { api, token in
            _ = try await api.addCarPlace(self.tripID, carID: carID, kind: kind, name: name, lat: lat, lng: lng, token: token)
        }
    }

    func removeCarPlace(carID: String, placeID: String) async throws {
        try await write { try await $0.removeCarPlace(self.tripID, carID: carID, placeID: placeID, token: $1) }
    }

    /// Starts the trip; `endActiveTrip` first finishes (owned) or leaves (joined) the starter's other running trip.
    func start(endActiveTrip: Bool = false) async throws {
        guard let detail else { throw TripPreparationError.notReady }
        do {
            try await write { try await $0.start(self.tripID, revision: detail.revision, endActiveTrip: endActiveTrip, token: $1) }
        } catch {
            let code: String? = switch error {
            case IPhoneTripRequestError.routeConflict(let code), IPhoneResourceError.tripConflict(let code): code
            default: nil
            }
            // A trip started elsewhere meanwhile: reload so startConflict shows what blocks the start.
            if let code, ["TRIP_ALREADY_ACTIVE", "TRIP_MEMBER_ALREADY_ACTIVE"].contains(code) {
                let message = errorMessage
                await load()
                if errorMessage == nil { errorMessage = message }
            }
            throw error
        }
    }

    func refreshVisibleState() async {
        await load()
        guard !Task.isCancelled, !isPreview, !busy, isCurrent, let detail, detail.state == .active else { return }
        await loadSignals()
    }

    func loadSignals() async {
        guard !isPreview, signalRead == nil, !busy, isCurrent, let detail, detail.state == .active else { return }
        let stamp = UUID(), carID = detail.myCar?.id
        signalRead = stamp
        defer { if signalRead == stamp { signalRead = nil } }
        do {
            let values = try await request { _, token in try await self.activityAPI.signals(self.tripID, token: token) }
            guard signalRead == stamp, isCurrent, self.detail?.state == .active, self.detail?.myCar?.id == carID else { return }
            storedSignals = values
            signalsCarID = carID
        } catch is CancellationError { }
        catch {
            guard signalRead == stamp else { return }
            storedSignals = []
            if !discardProtectedData(for: error), isCurrent { errorMessage = tripPreparationErrorMessage(error) }
        }
    }

    func updateTrip(_ draft: IPhoneTripDraft) async throws {
        guard detail?.isOwner == true || detail?.myPermissions.edit == true else { throw IPhoneSessionError.forbidden }
        try await write { try await $0.update(self.tripID, draft: draft, token: $1) }
    }

    func removeMember(accountID: String) async throws {
        guard let detail, detail.isOwner, accountID != detail.ownerId else { throw IPhoneSessionError.forbidden }
        try await write { try await $0.removeMember(self.tripID, accountID: accountID, token: $1) }
    }

    func leaveTrip() async throws {
        guard let detail, let me = detail.me, !detail.isOwner else { throw IPhoneSessionError.forbidden }
        try await write { try await $0.removeMember(self.tripID, accountID: me.id, token: $1) }
        hasLeftTrip = true
        self.detail = nil
        storedSignals = []
        vehicles = []
    }

    func cancelTrip() async throws {
        guard let detail, detail.isOwner, detail.state == .planned else { throw IPhoneSessionError.forbidden }
        try await write { try await $0.cancel(self.tripID, revision: detail.revision, token: $1) }
    }

    func finishTrip() async throws {
        guard let detail, detail.isOwner, detail.state == .active else { throw IPhoneSessionError.forbidden }
        try await write { try await $0.finish(self.tripID, revision: detail.revision, token: $1) }
    }

    func updateCar(carID: String, name: String, seats: Int) async throws {
        guard detail?.cars.contains(where: { $0.id == carID && $0.isMine }) == true else { throw IPhoneSessionError.forbidden }
        try await write { try await $0.updateCar(self.tripID, carID: carID, name: name, seats: seats, token: $1) }
    }

    func deleteCar(carID: String) async throws {
        guard let detail, detail.cars.contains(where: { $0.id == carID && ($0.isMine || detail.isOwner) }) else { throw IPhoneSessionError.forbidden }
        try await write { try await $0.deleteCar(self.tripID, carID: carID, token: $1) }
    }

    func removeCourse(packID: String) async throws {
        guard detail?.isOwner == true || detail?.myPermissions.edit == true else { throw IPhoneSessionError.forbidden }
        try await write { try await $0.removeCourse(self.tripID, packID: packID, token: $1) }
    }

    func respondToRideInvitation(_ invitation: IPhoneTripRideInvitation, accept: Bool) async throws {
        guard let detail, invitation.accountId == detail.me?.id,
              detail.rideInvites?.contains(where: { $0.id == invitation.id && $0.carId == invitation.carId }) == true
        else { throw IPhoneSessionError.forbidden }
        try await write { try await $0.respondToRideInvitation(self.tripID, carID: invitation.carId,
            invitationID: invitation.id, accept: accept, token: $1) }
    }

    func locations() async throws -> IPhoneTripLocations {
        guard detail?.state == .active else { throw IPhoneSessionError.forbidden }
        return try await request { try await $0.locations(self.tripID, token: $1) }
    }

    private func write(_ mutation: (any IPhoneTripServing, String) async throws -> Void) async throws {
        guard !busy else { throw TripPreparationError.busy }
        guard !needsRefresh else { throw TripPreparationError.refreshRequired }
        busy = true
        read = nil
        signalRead = nil
        loading = false
        errorMessage = nil
        defer { busy = false }
        do {
            try await request(mutation)
        } catch is CancellationError {
            if !isCurrent { discardProtectedData(for: IPhoneSessionError.invalidSession) }
            throw CancellationError()
        } catch {
            if !discardProtectedData(for: error), isCurrent { errorMessage = tripPreparationErrorMessage(error) }
            throw error
        }
        await onMutation?()
        do {
            let value = try await request { try await $0.detail(self.tripID, token: $1) }
            detail = value
            needsRefresh = false
        } catch is CancellationError {
            needsRefresh = true
            if !isCurrent { discardProtectedData(for: IPhoneSessionError.invalidSession) }
            throw CancellationError()
        } catch IPhoneSessionError.invalidSession {
            discardProtectedData(for: IPhoneSessionError.invalidSession)
            throw IPhoneSessionError.invalidSession
        } catch {
            if !discardProtectedData(for: error), isCurrent {
                needsRefresh = true
                errorMessage = "변경은 저장했지만 최신 정보를 불러오지 못했어요. 다시 불러와 주세요."
            }
        }
    }

    @discardableResult
    private func discardProtectedData(for error: Error) -> Bool {
        let lostAccess: Bool
        switch error {
        case IPhoneSessionError.invalidSession, IPhoneSessionError.forbidden,
             IPhoneResourceError.missing, IPhoneTripRequestError.missing: lostAccess = true
        default: lostAccess = !isCurrent
        }
        guard lostAccess else { return false }
        read = nil
        vehicleRead = nil
        signalRead = nil
        loading = false
        detail = nil
        vehicles = []
        storedSignals = []
        needsRefresh = true
        errorMessage = tripPreparationErrorMessage(error)
        return true
    }

    private func request<T>(_ work: (any IPhoneTripServing, String) async throws -> T) async throws -> T {
        try Task.checkCancellation()
        if isPreview {
            let value = try await work(api, "")
            try Task.checkCancellation()
            return value
        }
        guard let session, let current = session.current, current.accountID == account?.accountID else { throw IPhoneSessionError.invalidSession }
        return try await session.withToken(for: current) { try await work(api, $0) }
    }

    private var isCurrent: Bool {
        isPreview || (account != nil && session?.current?.accountID == account?.accountID && session?.phase == .signedIn)
    }
}

func tripPreparationErrorMessage(_ error: Error) -> String {
    switch error {
    case IPhoneSessionError.forbidden:
        "여행 준비 권한이 없어요. 여행 권한이 추가되기 전에 로그인했다면 다시 로그인해 주세요."
    case IPhoneSessionError.invalidResponse: "서버의 여행 응답을 확인할 수 없어요. 다시 시도해 주세요."
    case IPhoneSessionError.unavailable, IPhoneResourceError.unavailable:
        "여행 서버에 연결할 수 없어요. 잠시 후 다시 시도해 주세요."
    case IPhoneResourceError.tripConflict(let code):
        IPhoneTripRequestError.routeConflict(code).errorDescription ?? "여행 상태를 확인해 주세요."
    case IPhoneResourceError.conflict:
        "다른 곳에서 여행 준비가 바뀌었어요. 다시 불러온 뒤 확인해 주세요."
    case IPhoneResourceError.missing:
        "여행이나 차량을 찾을 수 없어요. 참여 상태를 다시 확인해 주세요."
    case IPhoneResourceError.invalidInput: "입력한 내용을 확인해 주세요."
    case IPhoneResourceError.vehicleLimit: "연결된 차량을 확인해 주세요."
    default: (error as? LocalizedError)?.errorDescription ?? "여행을 변경할 수 없어요. 다시 시도해 주세요."
    }
}
