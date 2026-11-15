import Foundation

struct IPhonePushNotification: Equatable, Sendable {
    enum Kind: String, Sendable { case friendRequest = "friend_request", friendAccepted = "friend_accepted", tripInvitation = "trip_invitation", handRaise = "hand_raise", handRaiseReaction = "hand_raise_reaction" }
    let eventID: String
    let accountID: String
    let kind: Kind
    let tripID: String?
    var isFriendEvent: Bool { kind == .friendRequest || kind == .friendAccepted }

    init?(userInfo: [AnyHashable: Any]) {
        guard let value = userInfo["wegoh"] as? [String: Any],
              let event = value["eventId"] as? String, event.range(of: #"\A[a-f0-9]{32}\z"#, options: .regularExpression) != nil,
              let account = value["accountId"] as? String, account.range(of: #"\Ateam-[a-f0-9]{40}\z"#, options: .regularExpression) != nil,
              let rawKind = value["kind"] as? String, let kind = Kind(rawValue: rawKind) else { return nil }
        let trip = value["tripId"] as? String
        if kind != .friendRequest && kind != .friendAccepted {
            guard let trip, validTripID(trip) else { return nil }
        } else if value["tripId"] != nil { return nil }
        self.eventID = event; self.accountID = account; self.kind = kind; self.tripID = trip
    }
}

struct IPhonePushAPI {
    private struct Receipt: Decodable { let registered: Bool }
    private let http: IPhoneSessionAPI
    init(configuration: URLSessionConfiguration? = nil) { http = IPhoneSessionAPI(configuration: configuration) }

    func register(installationID: String, deviceToken: Data, environment: String, token: String) async throws {
        guard UUID(uuidString: installationID) != nil, (32...256).contains(deviceToken.count),
              ["sandbox", "production"].contains(environment) else { throw IPhoneResourceError.invalidInput }
        let fields = ["installationId": installationID, "deviceToken": deviceToken.map { String(format: "%02x", $0) }.joined(), "environment": environment]
        let data = try await http.resource("push/installation", method: "PUT", payload: JSONSerialization.data(withJSONObject: fields), token: token)
        guard (try? JSONDecoder().decode(Receipt.self, from: data).registered) == true else { throw IPhoneSessionError.invalidResponse }
    }

    func unregister(installationID: String, token: String) async throws {
        let data = try await http.resource("push/installation", method: "DELETE", payload: JSONSerialization.data(withJSONObject: ["installationId": installationID]), token: token)
        guard (try? JSONDecoder().decode(Receipt.self, from: data).registered) == false else { throw IPhoneSessionError.invalidResponse }
    }
}
