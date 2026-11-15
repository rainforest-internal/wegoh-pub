import CryptoKit
import Foundation

enum TripPreparationError: Error, LocalizedError, Equatable {
    case busy, refreshRequired, previewActorMissing, previewUnsupported, invalidName, invalidSeats
    case unavailableCar, full, driverCannotRide, alreadyDriving, ownerRequired, notReady, notPreparing

    var errorDescription: String? {
        switch self {
        case .busy: "다른 변경을 처리하고 있어요. 잠시 후 다시 시도해 주세요."
        case .refreshRequired: "최신 여행 정보를 불러온 뒤 다시 시도해 주세요."
        case .previewActorMissing: "이 샘플의 참여자 중에서 미리보기 사용자를 지정해 주세요."
        case .previewUnsupported: "이 작업은 샘플 미리보기에서 지원하지 않아요. 실제 여행에서 이용해 주세요."
        case .invalidName: "차 이름을 1~20자로 입력해 주세요."
        case .invalidSeats: "운전자를 제외한 탑승 가능 인원을 1~8명으로 정해 주세요."
        case .unavailableCar: "이 차를 찾을 수 없어요. 차량 목록을 다시 확인해 주세요."
        case .full: "이 차는 만석이에요. 다른 차를 골라 주세요."
        case .driverCannotRide: "운전 중인 차가 있어요. 운전자는 다른 차에 탈 수 없어요."
        case .alreadyDriving: "이미 이 여행에서 운전 중이에요. 차는 한 대만 만들 수 있어요."
        case .ownerRequired: "여행 시작은 여행 만든 사람만 할 수 있어요."
        case .notReady: "일행의 탈 차와 경로를 정한 뒤 시작해 주세요."
        case .notPreparing: "준비 중인 여행에서만 변경할 수 있어요."
        }
    }
}

@MainActor
final class TripPreparationPreviewAPI: IPhoneTripServing {
    let tripID: String
    let actorName: String
    let courseStops: [String: [String]]
    let courseOptions: [IPhoneTripCourse]
    private let actorID: String?
    private var snapshot: IPhoneTripDetail

    init(preview: TripPreview, actorName explicitActor: String? = nil) {
        let name = explicitActor ?? (preview.id == "yangpyeong" ? "사용자A" : ["gapyeong", "gangneung"].contains(preview.id) ? "사용자D" : "사용자E")
        actorName = name
        let tripID = Self.identifier("trip:\(preview.id)")
        self.tripID = tripID
        let members = preview.members.enumerated().map { index, memberName in
            IPhoneTripMember(id: "team-" + String(Self.digest("\(preview.id):member:\(index)").prefix(40)),
                             name: memberName, state: .accepted, isMe: memberName == name,
                             isOwner: memberName == preview.ownerName, hasVehicle: true, carId: nil, readiness: .needsCar, role: memberName == "사용자C" ? .dj : memberName == "사용자D" ? .food : memberName == "사용자E" ? .rest : .member)
        }
        actorID = members.first { $0.name == name }?.id
        let ownerID = members.first { $0.isOwner }?.id ?? "team-" + String(repeating: "0", count: 40)
        let preparation = preview.preparation
        var cars: [IPhoneTripCar] = []
        for car in preparation?.cars ?? [] {
            guard let driver = members.first(where: { $0.name == car.driverName }) else { continue }
            var removedDriver = false
            let passengers = car.members.compactMap { memberName -> IPhoneTripPassenger? in
                if memberName == car.driverName && !removedDriver { removedDriver = true; return nil }
                guard let member = members.first(where: { $0.name == memberName }) else { return nil }
                return IPhoneTripPassenger(id: member.id, name: member.name, isMe: member.isMe)
            }
            cars.append(IPhoneTripCar(id: Self.identifier("\(preview.id):car:\(car.id)"), name: car.title,
                                      seats: car.passengerCapacity, driverId: driver.id, driverName: driver.name,
                                      isMine: driver.isMe, iRide: passengers.contains(where: \.isMe),
                                      driverVehicleReady: true, passengers: passengers))
        }
        var options: [IPhoneTripCourse] = []
        var stops: [String: [String]] = [:]
        let allCourses = (TripPreviewData.myTrips.flatMap { $0.preparation?.courses ?? [] }) + (preparation?.courses ?? [])
        for course in allCourses where stops[course.id] == nil {
            stops[course.id] = course.stops
            options.append(IPhoneTripCourse(packId: course.id, title: course.title, version: 1, stopCount: course.stops.count))
        }
        courseStops = stops
        courseOptions = options
        snapshot = IPhoneTripDetail(id: tripID, title: preview.title, description: preview.summary,
                                   startDate: nil, endDate: nil,
                                   state: IPhoneTripState(rawValue: Self.stateName(preview.state)) ?? .planned,
                                   revision: 1, isOwner: actorID == ownerID, ownerId: ownerID,
                                   myPermissions: IPhoneTripPermissions(invite: actorID == ownerID, edit: actorID == ownerID),
                                   members: members, cars: cars, unassigned: [],
                                   courses: (preparation?.courses ?? []).map {
                                       IPhoneTripCourse(packId: $0.id, title: $0.title, version: 1, stopCount: $0.stops.count)
                                   }, locationConsent: true)
        Self.rebuild(&snapshot, actorID: actorID)
    }

    func list(token: String) async throws -> IPhoneTripList {
        let trip = try current(tripID)
        return IPhoneTripList(trips: [IPhoneTripSummary(id: trip.id, title: trip.title,
            startDate: trip.startDate, endDate: trip.endDate, state: trip.state, isOwner: trip.isOwner,
            ownerName: trip.members.first { $0.isOwner }?.name ?? "", memberCount: trip.members.count,
            carCount: trip.cars.count)], invitations: [])
    }

    func detail(_ tripID: String, token: String) async throws -> IPhoneTripDetail { try current(tripID) }

    func createCar(_ tripID: String, name: String, seats: Int, token: String) async throws -> String {
        let name = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard validTripText(name, max: 20) else { throw TripPreparationError.invalidName }
        guard (1...8).contains(seats) else { throw TripPreparationError.invalidSeats }
        let id = UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased()
        try mutate(tripID) { trip, me in
            guard !trip.cars.contains(where: { $0.driverId == me.id }) else { throw TripPreparationError.alreadyDriving }
            for index in trip.cars.indices { trip.cars[index].passengers.removeAll { $0.id == me.id } }
            trip.cars.append(IPhoneTripCar(id: id, name: name, seats: seats, driverId: me.id,
                driverName: me.name, isMine: true, iRide: false, driverVehicleReady: true, passengers: []))
        }
        return id
    }

    func createCar(_ tripID: String, name: String, seats: Int, remotePolicy: IPhoneTripRemotePolicy, token: String) async throws -> String {
        guard remotePolicy.isValid else { throw IPhoneTripRequestError.invalidInput }
        let id = try await createCar(tripID, name: name, seats: seats, token: token)
        if let index = snapshot.cars.firstIndex(where: { $0.id == id }) { snapshot.cars[index].remotePolicy = remotePolicy }
        return id
    }

    func setRole(_ tripID: String, accountID: String, role: IPhoneTripRole, revision: Int, token: String) async throws {
        try mutate(tripID) { trip, me in
            guard me.isOwner else { throw IPhoneSessionError.forbidden }
            guard trip.revision == revision else { throw IPhoneResourceError.conflict }
            guard let index = trip.members.firstIndex(where: { $0.id == accountID }) else { throw IPhoneResourceError.missing }
            if role == .dj, trip.members.contains(where: { $0.id != accountID && $0.role == .dj }) { throw IPhoneResourceError.conflict }
            trip.members[index].role = role
        }
    }

    func setRemotePolicy(_ tripID: String, carID: String, policy: IPhoneTripRemotePolicy, token: String) async throws {
        guard policy.isValid else { throw IPhoneTripRequestError.invalidInput }
        try mutate(tripID) { trip, me in
            guard let index = trip.cars.firstIndex(where: { $0.id == carID }), trip.cars[index].driverId == me.id else { throw IPhoneSessionError.forbidden }
            trip.cars[index].remotePolicy = policy
        }
    }

    func ride(_ tripID: String, carID: String, token: String) async throws {
        try mutate(tripID) { trip, me in
            guard !trip.cars.contains(where: { $0.driverId == me.id }) else { throw TripPreparationError.driverCannotRide }
            guard let target = trip.cars.firstIndex(where: { $0.id == carID }) else { throw TripPreparationError.unavailableCar }
            if trip.cars[target].passengers.contains(where: { $0.id == me.id }) { return }
            guard trip.cars[target].passengers.count < trip.cars[target].seats else { throw TripPreparationError.full }
            for index in trip.cars.indices { trip.cars[index].passengers.removeAll { $0.id == me.id } }
            trip.cars[target].passengers.append(IPhoneTripPassenger(id: me.id, name: me.name, isMe: true))
        }
    }

    func leaveCar(_ tripID: String, token: String) async throws {
        try mutate(tripID) { trip, me in
            guard !trip.cars.contains(where: { $0.driverId == me.id }) else { throw TripPreparationError.driverCannotRide }
            for index in trip.cars.indices { trip.cars[index].passengers.removeAll { $0.id == me.id } }
        }
    }

    func addCourse(_ tripID: String, packID: String, token: String) async throws {
        guard let course = courseOptions.first(where: { $0.packId == packID }) else { throw TripPreparationError.previewUnsupported }
        try mutate(tripID) { trip, _ in
            guard !trip.courses.contains(where: { $0.packId == packID }), trip.courses.count < 10 else { throw IPhoneResourceError.conflict }
            trip.courses.append(course)
        }
    }

    func start(_ tripID: String, revision: Int, endActiveTrip: Bool, token: String) async throws {
        try mutate(tripID) { trip, me in
            guard me.isOwner else { throw TripPreparationError.ownerRequired }
            guard trip.revision == revision else { throw IPhoneResourceError.conflict }
            guard !trip.courses.isEmpty, trip.myCar != nil else { throw TripPreparationError.notReady }
            trip.state = .active
        }
    }

    func addCarPlace(_ tripID: String, carID: String, kind: IPhoneTripPlaceKind, name: String,
                     lat: Double, lng: Double, token: String) async throws -> String {
        guard kind == .pickup || kind == .drop, validTripText(name, max: 40),
              lat.isFinite, lng.isFinite, (-90...90).contains(lat), (-180...180).contains(lng)
        else { throw IPhoneResourceError.invalidInput }
        let id = UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased()
        try mutate(tripID) { trip, me in
            guard me.carId == carID, let index = trip.cars.firstIndex(where: { $0.id == carID })
            else { throw TripPreparationError.unavailableCar }
            trip.cars[index].places.append(IPhoneTripCarPlace(id: id, kind: kind, name: name, lat: lat, lng: lng,
                addedBy: me.id, selectedBy: [], selectionCount: 0,
                createdAt: ISO8601DateFormatter().string(from: .now)))
        }
        return id
    }

    func removeCarPlace(_ tripID: String, carID: String, placeID: String, token: String) async throws {
        try mutate(tripID) { trip, me in
            guard me.carId == carID, let car = trip.cars.firstIndex(where: { $0.id == carID }),
                  let place = trip.cars[car].places.firstIndex(where: { $0.id == placeID })
            else { throw IPhoneResourceError.missing }
            guard trip.cars[car].places[place].kind != .signal,
                  trip.cars[car].places[place].addedBy == me.id || trip.cars[car].driverId == me.id
            else { throw IPhoneSessionError.forbidden }
            trip.cars[car].places.remove(at: place)
        }
    }

    func saveMyPlaces(_ tripID: String, carID: String, draft: IPhoneTripMyPlacesDraft, token: String) async throws {
        guard draft.isValid else { throw IPhoneTripRequestError.invalidInput }
        let current = try current(tripID)
        guard let car = current.cars.first(where: { $0.id == carID }), car.iRide, !car.isMine,
              let me = current.me else { throw IPhoneSessionError.forbidden }
        guard current.state == .planned else { throw TripPreparationError.notPreparing }
        let pickup = car.places.first { $0.kind == .pickup && $0.selectedBy?.contains(me.id) == true }
        let drop = car.places.first { $0.kind == .drop && $0.selectedBy?.contains(me.id) == true }
        func matches(_ choice: IPhoneTripPlaceSelection?, _ place: IPhoneTripCarPlace?) -> Bool {
            switch choice {
            case nil: return place == nil
            case .existing(let id): return place?.id == id
            case .new(let name, let lat, let lng):
                return place?.name == name.trimmingCharacters(in: .whitespacesAndNewlines) && place?.lat == lat && place?.lng == lng
            }
        }
        let sameDrop = draft.dropAtPickup
            ? (pickup != nil && drop != nil && pickup?.lat == drop?.lat && pickup?.lng == drop?.lng && pickup?.name == drop?.name)
            : matches(draft.drop, drop)
        if matches(draft.pickup, pickup) && sameDrop { return }
        try mutate(tripID) { trip, me in
            guard let index = trip.cars.firstIndex(where: { $0.id == carID }), trip.cars[index].iRide,
                  !trip.cars[index].isMine else { throw IPhoneSessionError.forbidden }
            guard trip.revision == draft.revision else { throw IPhoneTripRequestError.routeConflict("TRIP_PLACE_SELECTION_CHANGED") }
            var places = trip.cars[index].places
            func select(_ choice: IPhoneTripPlaceSelection?, kind: IPhoneTripPlaceKind) throws -> IPhoneTripCarPlace? {
                guard let choice else { return nil }
                switch choice {
                case .existing(let id):
                    guard let place = places.first(where: { $0.id == id && $0.kind == kind }) else { throw IPhoneTripRequestError.missing }
                    return place
                case .new(let name, let lat, let lng):
                    let clean = name.trimmingCharacters(in: .whitespacesAndNewlines)
                    if let place = places.first(where: { $0.kind == kind && $0.name == clean && $0.lat == lat && $0.lng == lng }) { return place }
                    guard places.filter({ $0.kind == kind }).count < 10 else { throw IPhoneTripRequestError.conflict }
                    let place = IPhoneTripCarPlace(id: UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased(),
                        kind: kind, name: clean, lat: lat, lng: lng, addedBy: me.id, selectedBy: [], selectionCount: 0,
                        createdAt: ISO8601DateFormatter().string(from: .now))
                    places.append(place)
                    return place
                }
            }
            let pickup = try select(draft.pickup, kind: .pickup)
            let dropChoice: IPhoneTripPlaceSelection?
            if draft.dropAtPickup, let pickup, let lat = pickup.lat, let lng = pickup.lng {
                dropChoice = .new(name: pickup.name, lat: lat, lng: lng)
            } else { dropChoice = draft.drop }
            let drop = try select(dropChoice, kind: .drop)
            for place in places.indices where places[place].kind == .pickup || places[place].kind == .drop {
                places[place].selectedBy?.removeAll { $0 == me.id }
                if places[place].id == pickup?.id || places[place].id == drop?.id { places[place].selectedBy?.append(me.id) }
                places[place].selectionCount = places[place].selectedBy?.count ?? 0
            }
            trip.cars[index].places = places
            trip.cars[index].routeRevision = (trip.cars[index].routeRevision ?? 0) + 1
        }
    }

    func prioritizeCourses(_ tripID: String, packIDs: [String], revision: Int, token: String) async throws {
        guard (2...10).contains(packIDs.count), Set(packIDs).count == packIDs.count,
              packIDs.allSatisfy(validCourseID), (1...Int(Int32.max)).contains(revision) else { throw IPhoneTripRequestError.invalidInput }
        try mutate(tripID) { trip, me in
            guard me.isOwner else { throw IPhoneSessionError.forbidden }
            guard trip.revision == revision, Set(packIDs) == Set(trip.courses.map(\.packId)) else {
                throw IPhoneTripRequestError.routeConflict("TRIP_REVISION_CONFLICT")
            }
            trip.courses = packIDs.compactMap { id in trip.courses.first { $0.packId == id } }
        }
    }

    func create(_ draft: IPhoneTripDraft, token: String) async throws -> String { throw TripPreparationError.previewUnsupported }
    func respond(_ tripID: String, accept: Bool, locationConsent: Bool, token: String) async throws { throw TripPreparationError.previewUnsupported }
    func addMember(_ tripID: String, accountID: String, token: String) async throws { throw TripPreparationError.previewUnsupported }
    func setLocationSharing(_ tripID: String, enabled: Bool, token: String) async throws { throw TripPreparationError.previewUnsupported }

    private func current(_ tripID: String) throws -> IPhoneTripDetail {
        try Task.checkCancellation()
        guard tripID == self.tripID else { throw IPhoneResourceError.missing }
        guard actorID != nil else { throw TripPreparationError.previewActorMissing }
        let value = Self.project(snapshot)
        guard value.isValid else { throw IPhoneSessionError.invalidResponse }
        return value
    }

    private func mutate(_ tripID: String, _ change: (inout IPhoneTripDetail, IPhoneTripMember) throws -> Void) throws {
        _ = try current(tripID)
        var candidate = snapshot
        guard candidate.state == .planned, let me = candidate.me else { throw TripPreparationError.notPreparing }
        try change(&candidate, me)
        candidate.revision += 1
        Self.rebuild(&candidate, actorID: actorID)
        guard Self.project(candidate).isValid else { throw IPhoneSessionError.invalidResponse }
        snapshot = candidate
    }

    private static func project(_ snapshot: IPhoneTripDetail) -> IPhoneTripDetail {
        guard !snapshot.isOwner else { return snapshot }
        var result = snapshot
        for index in result.cars.indices where !result.cars[index].isMine && !result.cars[index].iRide {
            result.cars[index].places = result.cars[index].places.map { place in
                IPhoneTripCarPlace(id: nil, kind: place.kind == .signal ? .signal : nil, name: place.name,
                                  lat: nil, lng: nil, addedBy: nil, selectedBy: nil,
                                  selectionCount: place.kind == .signal ? 0 : place.selectionCount)
            }
        }
        return result
    }

    private static func rebuild(_ trip: inout IPhoneTripDetail, actorID: String?) {
        for index in trip.members.indices {
            let memberID = trip.members[index].id
            let carID = trip.cars.first {
                $0.driverId == memberID || $0.passengers.contains { $0.id == memberID }
            }?.id
            trip.members[index].carId = carID
            trip.members[index].readiness = readiness(of: trip.members[index], in: trip)
        }
        for index in trip.cars.indices {
            trip.cars[index].isMine = trip.cars[index].driverId == actorID
            trip.cars[index].iRide = trip.cars[index].passengers.contains { $0.id == actorID }
        }
        trip.unassigned = trip.members.filter { $0.state == .accepted && $0.carId == nil }.map { IPhoneTripPerson(id: $0.id, name: $0.name) }
    }

    private static func readiness(of member: IPhoneTripMember, in trip: IPhoneTripDetail) -> IPhoneTripMemberReadiness {
        guard member.state == .accepted else { return .invited }
        if let car = trip.cars.first(where: { $0.driverId == member.id }) { return car.driverVehicleReady ? .ready : .needsVehicle }
        guard let car = trip.cars.first(where: { $0.passengers.contains { $0.id == member.id } }) else { return .needsCar }
        let chosen = Set(car.places.filter { $0.selectedBy?.contains(member.id) == true }.compactMap(\.kind))
        return chosen.isSuperset(of: [.pickup, .drop]) ? .ready : .needsPlaces
    }

    private static func identifier(_ input: String) -> String { String(digest(input).prefix(32)) }
    private static func digest(_ input: String) -> String { SHA256.hash(data: Data(input.utf8)).map { String(format: "%02x", $0) }.joined() }
    private static func stateName(_ state: TripPreview.State) -> String {
        switch state { case .planned: "planned"; case .active: "active"; case .completed: "completed"; case .cancelled: "cancelled" }
    }
}
