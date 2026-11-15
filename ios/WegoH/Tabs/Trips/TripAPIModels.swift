import Foundation

enum IPhoneTripState: String, Codable {
    case planned, active, completed, cancelled
}

enum IPhoneTripMemberState: String, Codable {
    case pending, accepted
}

/// Server-judged departure readiness: accepted, in a car, and either a driver with a connected
/// vehicle or a passenger who chose both pickup and drop.
enum IPhoneTripMemberReadiness: String, Codable {
    case invited, needsCar, needsVehicle, needsPlaces, ready
}

struct IPhoneTripList: Codable, Equatable {
    var trips: [IPhoneTripSummary]
    var invitations: [IPhoneTripInvitation]

    var isValid: Bool {
        let ids = trips.map(\.id) + invitations.map(\.id)
        return Set(ids).count == ids.count && trips.allSatisfy(\.isValid) && invitations.allSatisfy(\.isValid)
    }
}

struct IPhoneTripSummary: Codable, Equatable, Identifiable {
    struct RoutePreview: Codable, Equatable {
        var name: String
        var courseId: String
        var ref: String
        var isValid: Bool { validTripText(name, max: 80) && validCourseID(courseId) && validCourseID(ref) }
    }
    var id: String
    var title: String
    var startDate: String?
    var endDate: String?
    var state: IPhoneTripState
    var isOwner: Bool
    var ownerName: String
    var memberCount: Int
    var carCount: Int
    var routePreview: [RoutePreview]? = nil

    var isValid: Bool {
        validTripID(id) && validTripText(title, max: 40) && validTripText(ownerName, max: 64)
            && (1...20).contains(memberCount) && (0...memberCount).contains(carCount)
            && validTripDates(start: startDate, end: endDate)
            && (routePreview.map { $0.count <= 4 && $0.allSatisfy(\.isValid) } ?? true)
    }
}

struct IPhoneTripInvitation: Codable, Equatable, Identifiable {
    var tripId: String
    var title: String
    var ownerName: String
    var id: String { tripId }
    var isValid: Bool { validTripID(tripId) && validTripText(title, max: 40) && validTripText(ownerName, max: 64) }
}

struct IPhoneTripPermissions: Codable, Equatable {
    var invite: Bool
    var edit: Bool
}

struct IPhoneTripPerson: Codable, Equatable, Identifiable {
    var id: String
    var name: String
    var isValid: Bool { validTripAccountID(id) && validTripText(name, max: 64) }
}

struct IPhoneTripMember: Codable, Equatable, Identifiable {
    var id: String
    var name: String
    var state: IPhoneTripMemberState
    var isMe: Bool
    var isOwner: Bool
    var hasVehicle: Bool
    var carId: String?
    var readiness: IPhoneTripMemberReadiness
    var role: IPhoneTripRole? = nil

    var isValid: Bool {
        validTripAccountID(id) && validTripText(name, max: 64) && (carId.map(validTripID) ?? true)
            && (state == .pending) == (readiness == .invited)
    }
}

struct IPhoneTripPassenger: Codable, Equatable, Identifiable {
    var id: String
    var name: String
    var isMe: Bool
    var isValid: Bool { validTripAccountID(id) && validTripText(name, max: 64) }
}

enum IPhoneTripPlaceKind: String, Codable {
    case pickup, drop, signal
}

struct IPhoneTripCarPlace: Codable, Equatable {
    var id: String?
    var kind: IPhoneTripPlaceKind?
    var name: String
    var lat: Double?
    var lng: Double?
    var addedBy: String?
    var selectedBy: [String]?
    var selectionCount: Int
    var createdAt: String? = nil

    var isValid: Bool {
        guard validTripText(name, max: kind == .signal ? 80 : 40), (0...20).contains(selectionCount) else { return false }
        guard let id else {
            return (kind == nil || (kind == .signal && selectionCount == 0))
                && lat == nil && lng == nil && addedBy == nil && selectedBy == nil && createdAt == nil
        }
        guard validTripID(id), let kind, let lat, let lng, validTripCoordinates(lat: lat, lng: lng) else { return false }
        if kind == .signal { return addedBy == nil && selectedBy == nil && createdAt == nil && selectionCount == 0 }
        guard let addedBy, validTripAccountID(addedBy), let selectedBy, let createdAt,
              !createdAt.isEmpty, createdAt.utf8.count <= 64 else { return false }
        return selectedBy.count == selectionCount && Set(selectedBy).count == selectedBy.count
            && selectedBy.allSatisfy(validTripAccountID)
    }

    private enum CodingKeys: String, CodingKey {
        case id, kind, name, lat, lng, addedBy, createdAt, selectedBy
    }
}

extension IPhoneTripCarPlace {
    init(from decoder: Decoder) throws {
        let box = try decoder.container(keyedBy: CodingKeys.self)
        id = try box.decodeIfPresent(String.self, forKey: .id)
        kind = try box.decodeIfPresent(IPhoneTripPlaceKind.self, forKey: .kind)
        name = try box.decode(String.self, forKey: .name)
        lat = try box.decodeIfPresent(Double.self, forKey: .lat)
        lng = try box.decodeIfPresent(Double.self, forKey: .lng)
        addedBy = try box.decodeIfPresent(String.self, forKey: .addedBy)
        createdAt = try box.decodeIfPresent(String.self, forKey: .createdAt)
        if id == nil {
            selectedBy = nil
            selectionCount = try box.decode(Int.self, forKey: .selectedBy)
        } else {
            selectedBy = try box.decodeIfPresent([String].self, forKey: .selectedBy)
            selectionCount = selectedBy?.count ?? 0
        }
    }

    func encode(to encoder: Encoder) throws {
        var box = encoder.container(keyedBy: CodingKeys.self)
        try box.encodeIfPresent(id, forKey: .id)
        try box.encodeIfPresent(kind, forKey: .kind)
        try box.encode(name, forKey: .name)
        try box.encodeIfPresent(lat, forKey: .lat)
        try box.encodeIfPresent(lng, forKey: .lng)
        try box.encodeIfPresent(addedBy, forKey: .addedBy)
        try box.encodeIfPresent(createdAt, forKey: .createdAt)
        if id == nil { try box.encode(selectionCount, forKey: .selectedBy) }
        else { try box.encodeIfPresent(selectedBy, forKey: .selectedBy) }
    }
}

struct IPhoneTripCar: Codable, Equatable, Identifiable {
    var id: String
    var name: String
    var seats: Int
    var driverId: String
    var driverName: String
    var isMine: Bool
    var iRide: Bool
    var driverVehicleReady: Bool
    var passengers: [IPhoneTripPassenger]
    var places: [IPhoneTripCarPlace] = []
    var remotePolicy: IPhoneTripRemotePolicy? = nil
    var routePlan: IPhoneTripRoutePlan? = nil
    var routeStatus: IPhoneTripRouteStatus? = nil
    var routeRevision: Int? = nil
    var routeOrder: [IPhoneTripRouteItem]? = nil
    var routeNext: IPhoneTripRouteItem? = nil
    var ordinal: Int? = nil

    var isValid: Bool {
        validTripID(id) && validTripText(name, max: 20) && (1...8).contains(seats)
            && validTripAccountID(driverId) && validTripText(driverName, max: 64)
            && passengers.count <= seats && passengers.allSatisfy { $0.isValid && $0.id != driverId }
            && Set(passengers.map(\.id)).count == passengers.count
            && (remotePolicy?.isValid ?? true)
            && (routePlan?.isValid ?? true) && (routeStatus?.isValid ?? true)
            && (routeRevision.map(validTripRevision) ?? true)
            && (routeOrder.map { $0.count <= 130 && $0.allSatisfy(\.isValid) && Set($0).count == $0.count } ?? true)
            && (routeNext?.isValid ?? true)
            && (ordinal.map { (1...Int(Int32.max)).contains($0) } ?? true)
            && places.count <= 70 && places.allSatisfy(\.isValid)
            && Set(places.compactMap(\.id)).count == places.compactMap(\.id).count
    }
}

struct IPhoneTripCourseStop: Codable, Equatable, Identifiable {
    var id: String
    var name: String
    var lat: Double
    var lng: Double

    var isValid: Bool {
        validCourseID(id) && validTripText(name, max: 80) && name.utf16.count <= 80
            && validTripCoordinates(lat: lat, lng: lng)
    }
}

struct IPhoneTripCourse: Codable, Equatable, Identifiable {
    var packId: String
    var title: String
    var version: Int
    var stopCount: Int
    var addedByName: String? = nil
    var stops: [IPhoneTripCourseStop]? = nil
    var completedCarIds: [String]? = nil
    var drivingScores: [IPhoneTripDrivingScore]? = nil
    var id: String { packId }
    var isValid: Bool {
        guard validCourseID(packId), validTripText(title, max: 120), (1...Int(Int32.max)).contains(version),
              (1...6).contains(stopCount), addedByName.map({ validTripText($0, max: 64) }) ?? true
        else { return false }
        if let stops {
            guard stops.isEmpty || stops.count == stopCount,
                  stops.allSatisfy(\.isValid), Set(stops.map(\.id)).count == stops.count else { return false }
        }
        if let completedCarIds {
            guard completedCarIds.count <= 20, completedCarIds.allSatisfy(validTripID),
                  Set(completedCarIds).count == completedCarIds.count else { return false }
        }
        if let drivingScores {
            guard drivingScores.count <= 1, drivingScores.allSatisfy(\.isValid) else { return false }
        }
        return true
    }
}

/// Owner-only pre-start check of a planned trip: one running trip per person.
struct IPhoneTripStartConflict: Codable, Equatable {
    struct ActiveTrip: Codable, Equatable, Identifiable {
        var tripId: String
        var title: String
        var isOwner: Bool
        var id: String { tripId }
    }
    var activeTrips: [ActiveTrip]
    var busyMemberIds: [String]
}

struct IPhoneTripDetail: Codable, Equatable, Identifiable {
    var id: String
    var title: String
    var description: String
    var startDate: String?
    var endDate: String?
    var state: IPhoneTripState
    var revision: Int
    var isOwner: Bool
    var ownerId: String
    var myPermissions: IPhoneTripPermissions
    var members: [IPhoneTripMember]
    var cars: [IPhoneTripCar]
    var unassigned: [IPhoneTripPerson]
    var courses: [IPhoneTripCourse]
    var locationConsent: Bool
    var routeContractVersion: Int? = nil
    var rideInvites: [IPhoneTripRideInvitation]? = nil
    var startConflict: IPhoneTripStartConflict? = nil

    var me: IPhoneTripMember? { members.first(where: \.isMe) }
    /// Accepted members still in another running trip; the trip cannot start until they end it.
    var busyMemberNames: [String] {
        (startConflict?.busyMemberIds ?? []).compactMap { id in members.first { $0.id == id }?.name }
    }
    var myCar: IPhoneTripCar? { cars.first { $0.isMine || $0.iRide } }
    private var startConflictIsValid: Bool {
        guard let startConflict else { return true }
        let busy = startConflict.busyMemberIds
        return isOwner && state == .planned
            && startConflict.activeTrips.allSatisfy { validTripID($0.tripId) && $0.tripId != id && validTripText($0.title, max: 40) }
            && Set(startConflict.activeTrips.map(\.tripId)).count == startConflict.activeTrips.count
            && Set(busy).count == busy.count
            && busy.allSatisfy { id in members.contains { $0.id == id && $0.state == .accepted && !$0.isMe } }
    }

    var isValid: Bool {
        guard validTripID(id), validTripText(title, max: 40), validTripText(description, max: 300, multiline: true),
              validTripDates(start: startDate, end: endDate), (1...Int(Int32.max)).contains(revision), validTripAccountID(ownerId),
              (1...20).contains(members.count), members.allSatisfy(\.isValid),
              Set(members.map(\.id)).count == members.count,
              members.filter(\.isMe).count == 1, let me, me.state == .accepted,
              members.filter(\.isOwner).map(\.id) == [ownerId], isOwner == me.isOwner,
              [nil, 1, 2].contains(routeContractVersion),
              cars.count <= members.count, cars.allSatisfy(\.isValid), Set(cars.map(\.id)).count == cars.count,
              Set(cars.compactMap(\.ordinal)).count == cars.compactMap(\.ordinal).count,
              (rideInvites ?? []).count <= 380, (rideInvites ?? []).allSatisfy(\.isValid),
              Set((rideInvites ?? []).map(\.id)).count == (rideInvites ?? []).count,
              courses.count <= 10, courses.allSatisfy(\.isValid), Set(courses.map(\.id)).count == courses.count,
              startConflictIsValid
        else { return false }
        let accepted = Set(members.filter { $0.state == .accepted }.map(\.id))
        let assigned = cars.flatMap { [$0.driverId] + $0.passengers.map(\.id) }
        return Set(assigned).count == assigned.count && Set(assigned).isSubset(of: accepted)
            && cars.allSatisfy { car in
                car.isMine == (car.driverId == me.id) && car.iRide == car.passengers.contains { $0.id == me.id }
                    && car.passengers.allSatisfy { $0.isMe == ($0.id == me.id) }
                    && car.places.allSatisfy { $0.id == nil || isOwner || car.isMine || car.iRide }
                    && (car.routePlan == nil || (routeContractVersion == 2 && state != .planned && (car.isMine || car.iRide)))
                    && (car.routeStatus == nil || (routeContractVersion == 2 && state != .planned))
                    && (car.routePlan.map { plan in
                        plan.referencesAreValid(car: car, courses: courses, visibleCarIDs: Set(cars.map(\.id)))
                            && car.routeStatus?.phase == plan.phase
                    } ?? true)
                    && (routeContractVersion != 2 || car.isMine || car.iRide
                        || (car.places.isEmpty && car.routePlan == nil && car.routeOrder == nil
                            && car.routeNext == nil && car.routeRevision == nil))
            }
            && unassigned.allSatisfy(\.isValid) && Set(unassigned.map(\.id)).count == unassigned.count
            && Set(unassigned.map(\.id)).isSubset(of: accepted.subtracting(assigned))
            && courses.allSatisfy { course in
                (course.completedCarIds.map { Set($0).isSubset(of: Set(cars.map(\.id))) } ?? true)
                    && course.drivingScores.orEmpty.allSatisfy { $0.carId == myCar?.id }
            }
    }
}

struct IPhoneTripDraft: Encodable, Equatable {
    var title = ""
    var description = ""
    var startDate: String?
    var endDate: String?
    var memberIds: [String] = []
    var locationConsent = true

    var isValid: Bool {
        validTripText(title, max: 40) && validTripText(description, max: 300, multiline: true)
            && validTripDates(start: startDate, end: endDate)
            && memberIds.count <= 19 && Set(memberIds).count == memberIds.count
            && memberIds.allSatisfy(validTripAccountID)
    }
}

func validTripID(_ id: String) -> Bool {
    id.range(of: #"\A[0-9a-f]{32}\z"#, options: .regularExpression) != nil
}

func validTripAccountID(_ id: String) -> Bool {
    id.range(of: #"\Ateam-[0-9a-f]{40}\z"#, options: .regularExpression) != nil
}

func validTripCoordinates(lat: Double, lng: Double) -> Bool {
    lat.isFinite && lng.isFinite && (-90...90).contains(lat) && (-180...180).contains(lng)
}

func validTripText(_ value: String, max: Int, multiline: Bool = false) -> Bool {
    let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
    return (multiline || !trimmed.isEmpty) && trimmed.unicodeScalars.count <= max
        && value.unicodeScalars.allSatisfy { $0.properties.generalCategory != .control || (multiline && $0 == "\n") }
}

private func validTripDates(start: String?, end: String?) -> Bool {
    func day(_ raw: String) -> Int? {
        guard raw.range(of: #"\A[0-9]{4}-[0-9]{2}-[0-9]{2}\z"#, options: .regularExpression) != nil else { return nil }
        let parts = raw.split(separator: "-").compactMap { Int($0) }
        let (year, month, day) = (parts[0], parts[1], parts[2])
        guard year > 0, (1...12).contains(month) else { return nil }
        let leap = year.isMultiple(of: 4) && (!year.isMultiple(of: 100) || year.isMultiple(of: 400))
        let days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
        guard (1...days[month-1]).contains(day) else { return nil }
        let y = year - 1
        return y*365 + y/4 - y/100 + y/400 + days.prefix(month-1).reduce(0,+) + day
    }
    let first = start.flatMap(day), last = end.flatMap(day)
    guard (start == nil || first != nil) && (end == nil || last != nil) else { return false }
    if let first, let last { return (0...30).contains(last - first) }
    return true
}

enum IPhoneTripRole: String, Codable, CaseIterable, Identifiable {
    case member, dj, food, rest
    var id: Self { self }
    var title: String { switch self { case .member: "함께"; case .dj: "DJ"; case .food: "맛집"; case .rest: "쉼터" } }
    var detail: String { switch self { case .member: "함께 여행해요"; case .dj: "여행 음악을 골라요"; case .food: "먹을 곳을 찾아요"; case .rest: "쉬어 갈 곳을 찾아요" } }
}

struct IPhoneTripRemotePolicy: Codable, Equatable {
    var enabled: Bool
    var actions: [String]
    var deviceId: String?
    static let off = Self(enabled: false, actions: [], deviceId: nil)
    var isValid: Bool {
        Set(actions).count == actions.count && Set(actions).isSubset(of: Set(TripRemoteGroup.allCases.flatMap(\.actionIDs)))
            && (!enabled || !actions.isEmpty) && (deviceId.map(validTripID) ?? true)
    }
}

struct IPhoneTripDrivingScore: Codable, Equatable {
    var carId: String
    var score: Int?
    var accelerations: Int
    var brakings: Int
    var measurable: Bool
    var final: Bool
    var isValid: Bool {
        guard validTripID(carId), (0...Int(Int32.max)).contains(accelerations),
              (0...Int(Int32.max)).contains(brakings) else { return false }
        return measurable ? score == max(0, 100 - 5 * (accelerations + brakings)) : score == nil
    }
}

extension IPhoneTripDetail {
    func roleMembers(in car: IPhoneTripCar) -> [IPhoneTripMember] {
        let ids = Set([car.driverId] + car.passengers.map(\.id))
        return members.filter { ids.contains($0.id) && $0.state == .accepted && $0.role != nil && $0.role != .member }
    }

    /// 운전자를 맨 앞에 두고 동승자를 이어 붙인 차의 전체 탑승 명단. 역할은 같은 이름이 있어도 계정 ID로 맞춘다.
    func riders(in car: IPhoneTripCar) -> [TripCarRider] {
        let roles = Dictionary(members.filter { $0.state == .accepted }.map { ($0.id, $0.role) }, uniquingKeysWith: { first, _ in first })
        let driver = TripCarRider(id: car.driverId, name: car.driverName, isDriver: true, isMe: car.isMine,
                                  role: roles[car.driverId] ?? nil)
        return [driver] + car.passengers.map {
            TripCarRider(id: $0.id, name: $0.name, isDriver: false, isMe: $0.isMe, role: roles[$0.id] ?? nil)
        }
    }

    func numberedName(_ car: IPhoneTripCar) -> String {
        guard let i = cars.firstIndex(where: { $0.id == car.id }) else { return car.name }
        let plain = car.name.replacingOccurrences(of: #"^\d+호차 · "#, with: "", options: .regularExpression)
        return "\(car.ordinal ?? (i + 1))호차 · \(plain)"
    }
}

private extension Optional where Wrapped: RangeReplaceableCollection {
    var orEmpty: Wrapped { self ?? .init() }
}
