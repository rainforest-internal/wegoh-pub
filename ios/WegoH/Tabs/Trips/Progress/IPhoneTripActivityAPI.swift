import Foundation

struct IPhoneTripSignalDestination: Codable, Equatable {
    var name: String
    var latitude: Double
    var longitude: Double
    var isValid: Bool { validTripText(name, max: 80) && validTripCoordinates(lat: latitude, lng: longitude) }
}

struct IPhoneTripSignal: Decodable, Identifiable {
    struct CandidateDetails: Decodable {
        var routeName: String?
        var direction: String?
        var fromLeadMeters: Int?
        var detourSeconds: Int?
        var isValid: Bool {
            (routeName.map { validTripText($0, max: 100) } ?? true)
                && (direction.map { validTripText($0, max: 80) } ?? true)
                && (fromLeadMeters.map { (0...Int(Int32.max)).contains($0) } ?? true)
                && (detourSeconds.map { (-Int(Int32.max)...Int(Int32.max)).contains($0) } ?? true)
        }
    }
    struct Counts: Decodable { var agree: Int; var pass: Int; var required: Int? }
    struct Group: Decodable, Identifiable {
        var carId: String
        var carName: String
        var choice: String?
        var responderAccountId: String?
        var responderName: String?
        var responseSource: String? = nil
        var id: String { carId }
    }
    var id: String
    var accountId: String
    var kind: String
    var destination: IPhoneTripSignalDestination?
    var contextState: String
    var inProgress: Bool
    var resolution: String
    var agreed: Bool
    var canRespond: Bool?
    var myGroupChoice: String?
    var requesterCarId: String?
    var groupVotes: Counts?
    var groupResponses: [Group]?
    var candidateDetails: CandidateDetails? = nil
    /// 장소 없이 보낸 요청은 동의 대상이 없다. 운전자가 세울 곳을 정하고 요청자가 완료·취소해야 끝난다.
    var waitsForRequester: Bool { destination == nil && inProgress && resolution == "pending" }
    /// 받은 요청에 이 차가 응답하지 못하는 이유. 장소 없는 요청은 동의할 대상이 없어 운전자가 세울 곳을 정하므로 보이지 않는다.
    func responseUnavailableCaption(isSender: Bool, canRespond: Bool) -> String? {
        guard inProgress, !isSender, !canRespond, !waitsForRequester else { return nil }
        return myGroupChoice != nil ? "우리 차에서 이미 응답했어요." : "이 차에서 응답할 수 없는 요청이에요."
    }
    var isValid: Bool {
        validTripID(id) && validTripAccountID(accountId) && TripSignalReason.allCases.map(\.serverKind).contains(kind)
            && (destination?.isValid ?? true) && ["valid", "reconfirm"].contains(contextState)
            && ["pending", "agreed", "passed", "completed", "cancelled", "reconfirm"].contains(resolution)
            && (myGroupChoice == nil || ["agree", "pass"].contains(myGroupChoice!))
            && (requesterCarId.map(validTripID) ?? true)
            && (candidateDetails?.isValid ?? true)
            && (groupVotes.map { (0...20).contains($0.agree) && (0...20).contains($0.pass) && ($0.required.map { (0...20).contains($0) } ?? true) } ?? true)
            && (groupResponses ?? []).count <= 20
            && (groupResponses ?? []).allSatisfy {
                validTripID($0.carId) && validTripText($0.carName, max: 20) && ($0.choice == nil || ["agree", "pass"].contains($0.choice!))
                    && ($0.responderAccountId.map(validTripAccountID) ?? true) && ($0.responderName.map { validTripText($0, max: 64) } ?? true)
                    && ($0.responseSource.map { ["native", "iphone", "web"].contains($0) } ?? true)
            }
    }
}

struct IPhoneTripSignalCandidate: Decodable, Identifiable {
    var name: String
    var lat: Double
    var lng: Double
    var verdict: String
    var fromLeadMeters: Double?
    var detourSeconds: Double?
    var facilities: [String: Bool]?
    var routeName: String? = nil
    var direction: String? = nil
    var candidateReceipt: String? = nil
    var id: String { "\(lat),\(lng),\(name)" }
    var isValid: Bool {
        validTripText(name, max: 80) && validTripCoordinates(lat: lat, lng: lng)
            && ["ahead", "off_route", "heading"].contains(verdict)
            && (fromLeadMeters.map { $0.isFinite && $0 >= 0 } ?? true)
            && (detourSeconds.map(\.isFinite) ?? true)
            && (routeName.map { validTripText($0, max: 100) } ?? true)
            && (direction.map { validTripText($0, max: 80) } ?? true)
            && (candidateReceipt.map { !$0.isEmpty && $0.utf8.count <= 2048 && $0.range(of: #"\A[A-Za-z0-9_-]+\z"#, options: .regularExpression) != nil } ?? true)
    }
    var destination: IPhoneTripSignalDestination { .init(name: name, latitude: lat, longitude: lng) }
}

struct IPhoneTripCandidatePage: Decodable {
    struct Car: Decodable { var carId: String; var state: String; var alongMeters: Double? }
    var cars: [Car]? = nil
    var basis: String
    var partial: Bool
    var candidates: [IPhoneTripSignalCandidate]
}

struct IPhoneTripRemote: Decodable, Identifiable {
    struct Action: Decodable, Identifiable {
        var id: String
        var revision: Int
        var label: String
        var argumentKind: String
        var support: Support? = nil
        var isValid: Bool {
            let kinds = ["hvac.temperature": "hvac-celsius", "hvac.fan": "hvac-fan", "hvac.power": "seat-switch",
                         "hvac.ac": "seat-switch", "hvac.air_cleaner": "seat-switch", "seat.heat": "seat-level",
                         "seat.ventilation": "seat-level", "window.position": "window-position", "light.cabin": "switch",
                         "light.reading": "seat-switch", "light.ambient": "seat-switch"]
            return kinds[id] == argumentKind && revision == 1 && validTripText(label, max: 80)
                && (support?.isValid(kind: argumentKind) ?? true)
        }
    }
    struct Support: Decodable {
        struct Area: Decodable, Identifiable {
            var id: String
            var min: Double?
            var max: Double?
            var step: Double?
            func contains(_ value: Double) -> Bool {
                guard value.isFinite, let min, let max, (min...max).contains(value) else { return false }
                guard let step else { return true }
                let offset = (value - min) / step
                return abs(offset - offset.rounded()) <= 0.000001
            }
        }
        var status: String
        var available: Bool
        var areas: [Area]
        /// 하나의 SDK 조절 구역으로 묶여 함께 바뀌는 좌석 묶음. 묶음에 없는 좌석은 단독 조절이다.
        var zones: [[String]] = []
        var observedAt: String?
        var expiresAt: String?
        var validUntil: Date? { expiresAt.flatMap(Self.date) }
        var isCurrent: Bool { validUntil.map { $0 > .now } == true }
        var isFresh: Bool { status == "known" && available && isCurrent }
        /// 이 좌석을 바꾸면 함께 바뀌는 좌석(자기 자신 포함).
        func zone(of seat: String) -> [String] { zones.first { $0.contains(seat) } ?? [seat] }
        func isValid(kind: String) -> Bool {
            guard ["known", "unknown"].contains(status), areas.count <= 8,
                  Set(areas.map(\.id)).count == areas.count else { return false }
            if observedAt == nil || expiresAt == nil {
                guard observedAt == nil && expiresAt == nil && status == "unknown" else { return false }
            } else {
                guard let observed = observedAt.flatMap(Self.date), let expires = expiresAt.flatMap(Self.date),
                      expires >= observed, expires.timeIntervalSince(observed) <= 90 else { return false }
            }
            if status == "unknown" || !available { return !available && areas.isEmpty && zones.isEmpty }
            if kind == "switch" { return areas.isEmpty && zones.isEmpty }
            let reported = Set(areas.map(\.id)), grouped = zones.flatMap { $0 }
            guard zones.count <= 4, zones.allSatisfy({ $0.count >= 2 }), Set(grouped).count == grouped.count,
                  Set(grouped).isSubset(of: reported), kind != "window-position" || zones.isEmpty else { return false }
            // 운전석(좌석·창문)은 원격 조작에서 빼며 서버도 400으로 거절한다.
            let seats = Set(TripRemoteSeats.order).subtracting([TripRemoteSeats.driver])
            let windows: Set<String> = ["ROW_1_RIGHT", "ROW_2_LEFT", "ROW_2_RIGHT"]
            return !areas.isEmpty && areas.allSatisfy { area in
                guard (kind == "window-position" ? windows : seats).contains(area.id) else { return false }
                if kind == "seat-switch" { return area.min == nil && area.max == nil && area.step == nil }
                guard let min = area.min, let max = area.max, min.isFinite, max.isFinite, min <= max else { return false }
                if kind == "hvac-celsius" {
                    return min >= 0 && max <= 50 && (area.step.map { $0.isFinite && $0 > 0 } ?? true)
                }
                let limit: Double = kind == "seat-level" ? 10 : 100
                return min >= 0 && max <= limit && min.rounded() == min && max.rounded() == max && area.step == 1
                    && (kind != "window-position" || (min == 0 && max == 100))
            }
        }
        private static func date(_ value: String) -> Date? {
            let formatter = ISO8601DateFormatter()
            formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            if let date = formatter.date(from: value) { return date }
            formatter.formatOptions = [.withInternetDateTime]
            return formatter.date(from: value)
        }
    }
    var deviceId: String
    var ownerName: String
    var deviceName: String
    var grantRevision: Int
    var actions: [Action]
    var requests: [IPhoneTripRemoteRequest]? = nil
    var id: String { deviceId }
    var isValid: Bool {
        validTripID(deviceId) && (0...Int(Int32.max)).contains(grantRevision) && validTripText(ownerName, max: 64) && validTripText(deviceName, max: 80)
            && actions.count <= 11 && Set(actions.map(\.id)).count == actions.count && actions.allSatisfy(\.isValid)
            && (requests.map { $0.count <= 5 && Set($0.map(\.id)).count == $0.count
                && $0.allSatisfy { request in request.isValid && request.targetDeviceId == deviceId
                    && actions.contains { $0.id == request.capabilityId && $0.revision == request.capabilityRevision } } } ?? true)
    }
}

struct IPhoneTripRemoteRequest: Decodable, Identifiable {
    var id: String
    var tripId: String
    var targetDeviceId: String
    var capabilityId: String
    var capabilityRevision: Int
    var stage: String
    var lastAcknowledgedStage: String?
    var reason: String?
    var mayHaveExecuted: Bool
    var physicalExecutionVerified: Bool
    var createdAt: String
    var expiresAt: String

    static let stages: Set<String> = ["queued", "delivered", "received", "sdk-accepted", "state-confirmed", "unknown", "rejected", "cancelled", "expired"]
    static let terminal: Set<String> = ["state-confirmed", "unknown", "rejected", "cancelled", "expired"]
    var isValid: Bool {
        guard validTripID(id), validTripID(tripId), validTripID(targetDeviceId),
              Self.stages.contains(stage), lastAcknowledgedStage.map(Self.stages.contains) ?? true,
              !physicalExecutionVerified, capabilityRevision == 1,
              let created = Self.date(createdAt), let expires = Self.date(expiresAt), expires >= created else { return false }
        return true
    }
    private static func date(_ value: String) -> Date? {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = formatter.date(from: value) { return date }
        formatter.formatOptions = [.withInternetDateTime]
        return formatter.date(from: value)
    }
}

struct IPhoneTripRemoteReceipt: Decodable {
    var id: String
    var stage: String
    var physicalExecutionVerified: Bool
    var reason: String? = nil
    var mayHaveExecuted: Bool? = nil
}

protocol IPhoneTripActivityServing {
    func signals(_ tripID: String, token: String) async throws -> [IPhoneTripSignal]
    func candidates(_ tripID: String, reason: TripSignalReason, facilities: Set<TripSignalFacility>, location: TripSignalLocation.Point,
                    destination: IPhoneTripCourseStop?, token: String) async throws -> IPhoneTripCandidatePage
    /// 서버가 만든 손들기 id를 돌려준다. 다른 차 동의 없이 바로 끝난 요청도 이 id로 결과를 찾는다.
    func send(_ tripID: String, reason: TripSignalReason, destination: IPhoneTripSignalDestination?, token: String) async throws -> String
    func send(_ tripID: String, reason: TripSignalReason, destination: IPhoneTripSignalDestination?, candidateReceipt: String?, token: String) async throws -> String
    func vote(_ tripID: String, signalID: String, agree: Bool, token: String) async throws -> Bool
    func finish(_ tripID: String, signalID: String, cancelled: Bool, token: String) async throws
    func remotes(_ tripID: String, token: String) async throws -> [IPhoneTripRemote]
    func command(_ tripID: String, remote: IPhoneTripRemote, action: IPhoneTripRemote.Action, seat: String, value: Any, token: String) async throws -> IPhoneTripRemoteReceipt
}

extension IPhoneTripActivityServing {
    func send(_ tripID: String, reason: TripSignalReason, destination: IPhoneTripSignalDestination?, candidateReceipt: String?, token: String) async throws -> String {
        try await send(tripID, reason: reason, destination: destination, token: token)
    }
}

struct IPhoneTripActivityAPI: IPhoneTripActivityServing {
    private let transport: IPhoneSessionAPI
    init(configuration: URLSessionConfiguration? = nil) { transport = IPhoneSessionAPI(configuration: configuration) }
    private func path(_ tripID: String) throws -> String {
        guard validTripID(tripID) else { throw IPhoneTripRequestError.invalidInput }
        return "trips/" + tripID
    }
    private func request<T: Decodable>(_ path: String, method: String = "GET", payload: Data? = nil, token: String, status: Int = 200) async throws -> T {
        let data = try await transport.resource(path, method: method, payload: payload, token: token, status: status)
        do { return try JSONDecoder().decode(T.self, from: data) }
        catch { throw IPhoneSessionError.invalidResponse }
    }
    func signals(_ tripID: String, token: String) async throws -> [IPhoneTripSignal] {
        struct Page: Decodable { var signals: [IPhoneTripSignal] }
        let page: Page = try await request(path(tripID) + "/signals", token: token)
        guard page.signals.count <= 50, page.signals.allSatisfy(\.isValid) else { throw IPhoneSessionError.invalidResponse }
        return page.signals
    }
    func candidates(_ tripID: String, reason: TripSignalReason, facilities: Set<TripSignalFacility>,
                    location: TripSignalLocation.Point, destination: IPhoneTripCourseStop?, token: String) async throws -> IPhoneTripCandidatePage {
        var point: [String: Any] = ["lat": location.lat, "lng": location.lng]
        if let heading = location.heading, heading.isFinite, (0...360).contains(heading) { point["heading"] = heading }
        guard destination != nil || point["heading"] != nil else { throw TripSignalLocation.Failure.heading }
        var body: [String: Any] = ["kind": reason.serverKind, "requiredFacilities": facilities.map(\.serverID).sorted(), "location": point]
        if let destination { body["destination"] = ["lat": destination.lat, "lng": destination.lng] }
        let page: IPhoneTripCandidatePage = try await request(path(tripID) + "/signals/candidates", method: "POST",
            payload: JSONSerialization.data(withJSONObject: body), token: token)
        guard ["route", "heading"].contains(page.basis), page.candidates.count <= 10,
              page.candidates.allSatisfy(\.isValid) else { throw IPhoneSessionError.invalidResponse }
        return page
    }
    func send(_ tripID: String, reason: TripSignalReason, destination: IPhoneTripSignalDestination?, token: String) async throws -> String {
        try await send(tripID, reason: reason, destination: destination, candidateReceipt: nil, token: token)
    }
    func send(_ tripID: String, reason: TripSignalReason, destination: IPhoneTripSignalDestination?, candidateReceipt: String?, token: String) async throws -> String {
        guard destination?.isValid ?? true,
              candidateReceipt.map({ !$0.isEmpty && $0.utf8.count <= 2048 && $0.range(of: #"\A[A-Za-z0-9_-]+\z"#, options: .regularExpression) != nil }) ?? true
        else { throw IPhoneTripRequestError.invalidInput }
        struct Body: Encodable { var kind: String; var destination: IPhoneTripSignalDestination?; var candidateReceipt: String? }
        struct Receipt: Decodable { var id: String; var status: String }
        let receipt: Receipt = try await request(path(tripID) + "/signals", method: "POST",
            payload: JSONEncoder().encode(Body(kind: reason.serverKind, destination: destination, candidateReceipt: candidateReceipt)), token: token, status: 201)
        guard validTripID(receipt.id), receipt.status == "sent" else { throw IPhoneSessionError.invalidResponse }
        return receipt.id
    }
    func vote(_ tripID: String, signalID: String, agree: Bool, token: String) async throws -> Bool {
        guard validTripID(signalID) else { throw IPhoneTripRequestError.invalidInput }
        struct Receipt: Decodable { var status: String; var choice: String; var already: Bool? }
        let receipt: Receipt = try await request(path(tripID) + "/signals/" + signalID + "/vote", method: "POST",
            payload: JSONEncoder().encode(["choice": agree ? "agree" : "pass"]), token: token)
        guard receipt.status == "saved", ["agree", "pass"].contains(receipt.choice) else { throw IPhoneSessionError.invalidResponse }
        return receipt.already ?? false
    }
    func finish(_ tripID: String, signalID: String, cancelled: Bool, token: String) async throws {
        guard validTripID(signalID) else { throw IPhoneTripRequestError.invalidInput }
        struct Receipt: Decodable { var status: String }
        let expected = cancelled ? "cancelled" : "completed"
        let receipt: Receipt = try await request(path(tripID) + "/signals/" + signalID + "/finish", method: "POST",
            payload: JSONEncoder().encode(["result": expected]), token: token)
        guard receipt.status == expected else { throw IPhoneSessionError.invalidResponse }
    }
    func remotes(_ tripID: String, token: String) async throws -> [IPhoneTripRemote] {
        struct Page: Decodable { var tripId: String; var remotes: [IPhoneTripRemote] }
        let page: Page = try await request(path(tripID) + "/vehicle-remotes", token: token)
        guard page.tripId == tripID, page.remotes.count <= 1, page.remotes.allSatisfy({ remote in remote.isValid
            && (remote.requests?.allSatisfy { $0.tripId == tripID } ?? true) }) else { throw IPhoneSessionError.invalidResponse }
        return page.remotes
    }
    func command(_ tripID: String, remote: IPhoneTripRemote, action: IPhoneTripRemote.Action, seat: String, value: Any, token: String) async throws -> IPhoneTripRemoteReceipt {
        guard remote.isValid, action.isValid, remote.actions.contains(where: { $0.id == action.id && $0.revision == action.revision }) else { throw IPhoneTripRequestError.invalidInput }
        // 운전석(좌석·창문)은 원격 조작에서 빼며 서버도 400으로 거절한다.
        let seats = Set(TripRemoteSeats.order).subtracting([TripRemoteSeats.driver])
        let windows: Set<String> = ["ROW_1_RIGHT", "ROW_2_LEFT", "ROW_2_RIGHT"]
        let valid: Bool
        switch action.argumentKind {
        case "hvac-celsius": valid = seats.contains(seat) && (value as? Double).map { $0.isFinite && (0...50).contains($0) } == true
        case "hvac-fan": valid = seats.contains(seat) && (value as? Int).map { (0...100).contains($0) } == true
        case "seat-level": valid = seats.contains(seat) && (value as? Int).map { (0...10).contains($0) } == true
        case "window-position": valid = windows.contains(seat) && (value as? Int).map { (0...100).contains($0) } == true
        case "seat-switch": valid = seats.contains(seat) && value is Bool
        case "switch": valid = value is Bool
        default: valid = false
        }
        guard valid else { throw IPhoneTripRequestError.invalidInput }
        if let support = action.support, support.isFresh {
            if action.argumentKind != "switch" {
                guard let area = support.areas.first(where: { $0.id == seat }) else {
                    throw IPhoneResourceError.tripConflict("VEHICLE_CONTROL_AREA_UNSUPPORTED")
                }
                if let number = value as? NSNumber, !(value is Bool), !area.contains(number.doubleValue) {
                    throw IPhoneResourceError.tripConflict("VEHICLE_CONTROL_VALUE_UNSUPPORTED")
                }
            }
        } else if action.support?.status == "known", action.support?.isCurrent == true, action.support?.available == false {
            throw IPhoneResourceError.tripConflict("VEHICLE_CONTROL_UNSUPPORTED")
        }
        var arguments: [String: Any] = ["value": value]
        if action.argumentKind == "window-position" { arguments["window"] = seat }
        else if action.argumentKind != "switch" { arguments["seat"] = seat }
        let body: [String: Any] = ["eventId": UUID().uuidString, "grantRevision": remote.grantRevision,
            "capabilityId": action.id, "capabilityRevision": action.revision, "arguments": arguments]
        let result: IPhoneTripRemoteReceipt = try await request(path(tripID) + "/vehicle-remotes/" + remote.id + "/commands", method: "POST",
            payload: JSONSerialization.data(withJSONObject: body), token: token, status: 201)
        guard validTripID(result.id), !result.physicalExecutionVerified,
              ["queued", "delivered", "received", "sdk-accepted", "state-confirmed", "unknown", "rejected", "cancelled", "expired"].contains(result.stage)
        else { throw IPhoneSessionError.invalidResponse }
        return result
    }
}

func tripActivityAccessLost(_ error: Error) -> Bool {
    switch error {
    case IPhoneSessionError.invalidSession, IPhoneSessionError.forbidden, IPhoneResourceError.missing, IPhoneTripRequestError.missing: true
    default: false
    }
}
