import Foundation

struct IPhoneTripRideInvitation: Codable, Equatable, Identifiable {
    var id: String
    var carId: String
    var accountId: String
    var createdAt: String
    var isValid: Bool {
        validTripID(id) && validTripID(carId) && validTripAccountID(accountId)
            && !createdAt.isEmpty && createdAt.utf8.count <= 64
    }
}

struct IPhoneTripLocations: Decodable {
    struct Location: Decodable, Identifiable {
        var accountId: String
        var name: String
        var source: String
        var latitude: Double
        var longitude: Double
        var accuracyMeters: Double?
        var capturedAt: String
        var id: String { accountId }
        var isValid: Bool {
            validTripAccountID(accountId) && validTripText(name, max: 64)
                && ["phone", "vehicle"].contains(source)
                && validTripCoordinates(lat: latitude, lng: longitude)
                && (accuracyMeters.map { $0.isFinite && $0 >= 0 } ?? true)
                && !capturedAt.isEmpty && capturedAt.utf8.count <= 64
        }
    }
    /// 차 하나의 현재 위치. 서버가 공유 동의·차단·60초 최신성을 통과한 탑승자 위치로 만들며 경로 정보는 없다.
    struct Car: Decodable, Identifiable {
        var carId: String
        var source: String
        var latitude: Double
        var longitude: Double
        var accuracyMeters: Double?
        var capturedAt: String
        var id: String { carId }
        var isValid: Bool {
            validTripID(carId) && ["phone", "vehicle"].contains(source)
                && validTripCoordinates(lat: latitude, lng: longitude)
                && (accuracyMeters.map { $0.isFinite && $0 >= 0 } ?? true)
                && !capturedAt.isEmpty && capturedAt.utf8.count <= 64
        }
    }
    var tripId: String
    var serverNow: String
    var shareId: String?
    var locations: [Location]
    var cars: [Car]
    var isValid: Bool {
        validTripID(tripId) && !serverNow.isEmpty && serverNow.utf8.count <= 64
            && (shareId.map(validTripID) ?? true)
            && locations.count <= 20 && locations.allSatisfy(\.isValid)
            && Set(locations.map(\.id)).count == locations.count
            && cars.count <= 20 && cars.allSatisfy(\.isValid)
            && Set(cars.map(\.id)).count == cars.count
    }

    /// 서버 시각 기준 위치 경과 시간. 기기 시계가 어긋나도 늦은 위치를 같은 기준으로 구분한다.
    func age(of car: Car) -> TimeInterval? {
        guard let now = Self.date(serverNow), let captured = Self.date(car.capturedAt) else { return nil }
        return max(0, now.timeIntervalSince(captured))
    }

    private static func date(_ value: String) -> Date? {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = formatter.date(from: value) { return date }
        formatter.formatOptions = [.withInternetDateTime]
        return formatter.date(from: value)
    }
}

extension IPhoneTripAPI {
    private struct ManagementStatus: Decodable { var status: String }
    private struct ManagementTransition: Decodable { var tripId: String; var state: IPhoneTripState; var revision: Int }

    func update(_ tripID: String, draft: IPhoneTripDraft, token: String) async throws {
        guard draft.isValid else { throw IPhoneTripRequestError.invalidInput }
        let body: [String: Any] = ["title": draft.title.trimmingCharacters(in: .whitespacesAndNewlines),
            "description": draft.description.trimmingCharacters(in: .whitespacesAndNewlines),
            "startDate": draft.startDate.map { $0 as Any } ?? NSNull(), "endDate": draft.endDate.map { $0 as Any } ?? NSNull()]
        let value: ManagementStatus = try await request(path(tripID), method: "PATCH", payload: JSONSerialization.data(withJSONObject: body), token: token)
        guard value.status == "updated" else { throw IPhoneSessionError.invalidResponse }
    }

    func removeMember(_ tripID: String, accountID: String, token: String) async throws {
        guard validTripAccountID(accountID) else { throw IPhoneTripRequestError.invalidInput }
        let value: ManagementStatus = try await request(path(tripID) + "/members/" + accountID,
            method: "DELETE", payload: Data("{}".utf8), token: token)
        guard value.status == "removed" else { throw IPhoneSessionError.invalidResponse }
    }

    func cancel(_ tripID: String, revision: Int, token: String) async throws {
        try await transition(tripID, action: "cancel", revision: revision, expected: .cancelled, token: token)
    }

    func finish(_ tripID: String, revision: Int, token: String) async throws {
        try await transition(tripID, action: "finish", revision: revision, expected: .completed, token: token)
    }

    private func transition(_ tripID: String, action: String, revision: Int, expected: IPhoneTripState, token: String) async throws {
        guard validTripRevision(revision) else { throw IPhoneTripRequestError.invalidInput }
        let value: ManagementTransition = try await request(path(tripID) + "/" + action, method: "POST",
            payload: JSONEncoder().encode(["revision": revision]), token: token)
        guard value.tripId == tripID, value.state == expected, validTripRevision(value.revision), value.revision >= revision
        else { throw IPhoneSessionError.invalidResponse }
    }

    func updateCar(_ tripID: String, carID: String, name: String, seats: Int, token: String) async throws {
        guard validTripID(carID), validTripText(name, max: 20), (1...8).contains(seats) else { throw IPhoneTripRequestError.invalidInput }
        struct Body: Encodable { var name: String; var seats: Int }
        let value: ManagementStatus = try await request(path(tripID) + "/cars/" + carID, method: "PATCH",
            payload: JSONEncoder().encode(Body(name: name.trimmingCharacters(in: .whitespacesAndNewlines), seats: seats)), token: token)
        guard value.status == "updated" else { throw IPhoneSessionError.invalidResponse }
    }

    func deleteCar(_ tripID: String, carID: String, token: String) async throws {
        guard validTripID(carID) else { throw IPhoneTripRequestError.invalidInput }
        let value: ManagementStatus = try await request(path(tripID) + "/cars/" + carID, method: "DELETE", payload: Data("{}".utf8), token: token)
        guard value.status == "deleted" else { throw IPhoneSessionError.invalidResponse }
    }

    func removeCourse(_ tripID: String, packID: String, token: String) async throws {
        guard validCourseID(packID) else { throw IPhoneTripRequestError.invalidInput }
        let value: ManagementStatus = try await request(path(tripID) + "/courses/" + packID, method: "DELETE", payload: Data("{}".utf8), token: token)
        guard value.status == "removed" else { throw IPhoneSessionError.invalidResponse }
    }

    func respondToRideInvitation(_ tripID: String, carID: String, invitationID: String, accept: Bool, token: String) async throws {
        guard validTripID(carID), validTripID(invitationID) else { throw IPhoneTripRequestError.invalidInput }
        let value: ManagementStatus = try await request(path(tripID) + "/cars/" + carID + "/ride-invites/" + invitationID + "/respond",
            method: "POST", payload: JSONEncoder().encode(["accept": accept]), token: token)
        guard value.status == (accept ? "accepted" : "declined") else { throw IPhoneSessionError.invalidResponse }
    }

    func locations(_ tripID: String, token: String) async throws -> IPhoneTripLocations {
        let value: IPhoneTripLocations = try await request(path(tripID) + "/locations", token: token)
        guard value.tripId == tripID, value.isValid else { throw IPhoneSessionError.invalidResponse }
        return value
    }
}
