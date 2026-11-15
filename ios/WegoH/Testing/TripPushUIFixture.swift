#if DEBUG
import notify
import Foundation

enum TripPushUIFixture {
    static var requested: Bool {
        let args = ProcessInfo.processInfo.arguments
        return args.contains("-trip-push-invitation-ui") && args.contains("-course-discovery-live-ui")
    }
    static let tripID = String(repeating: "c", count: 32)
    private static let actor = "team-" + String(repeating: "a", count: 40)
    private static let title = "강릉 바다 여행"

    static let existingTripID = String(repeating: "a", count: 32)
    private static var foreground: Bool {
        ProcessInfo.processInfo.arguments.contains("-trip-push-foreground-ui")
    }
    private static let arrivalLock = NSLock()
    private static var arrived = false

    @MainActor private static var sent = false
    @MainActor static func bind(session: SessionManager) {
        guard requested, session.phase == .signedIn, session.current?.accountID == actor, !sent else { return }
        sent = true
        let info = ["accountId": actor, "eventId": String(repeating: "e", count: 32),
                    "kind": "trip_invitation", "tripId": tripID]
        guard let notification = IPhonePushNotification(userInfo: ["wegoh": info]) else { return }
        let push = IPhonePushManager.shared
        if foreground {
            push.bindForUITesting(session: session)
            var token: Int32 = 0
            notify_register_dispatch("io.wegoh.iphone.tests.tripInvitationArrived", &token, .main) { registered in
                notify_cancel(registered)
                arrivalLock.withLock { arrived = true }
                if !ProcessInfo.processInfo.arguments.contains("-trip-push-muted-ui") {
                    Task { @MainActor in push.receiveForeground(notification) }
                }
            }
        } else {
            push.receive(notification)
            push.bindForUITesting(session: session)
        }
    }

    private static var responseStatus: String?
    private static var queriedNonmemberDetail = false

    static func response(path: String, method: String, request: URLRequest) throws -> (Int, [String: Any])? {
        guard requested else { return nil }
        if path == "trips/" + tripID, method == "GET", responseStatus != "accepted" {
            queriedNonmemberDetail = true
            return (403, ["detail": "TRIP_MEMBERSHIP_REQUIRED"])
        }
        if path == "trips", method == "GET" {
            if queriedNonmemberDetail { return (503, ["detail": "UNEXPECTED_MEMBER_DETAIL"]) }
            let invitation = ["tripId": tripID, "title": title, "ownerName": "테스트 방장"]
            let incoming = !foreground || arrivalLock.withLock { arrived }
            let pending = incoming && responseStatus == nil && !ProcessInfo.processInfo.arguments.contains("-trip-push-expired")
            let member: [String: Any] = ["id": tripID, "title": title, "state": "planned", "isOwner": false,
                                         "ownerName": "테스트 방장", "memberCount": 2, "carCount": 0]
            var trips = responseStatus == "accepted" ? [member] : []
            if foreground {
                trips.append(["id": existingTripID, "title": "남해 드라이브", "state": "planned", "isOwner": true,
                              "ownerName": "테스트 사용자", "memberCount": 1, "carCount": 0])
            }
            return (200, ["trips": trips, "invitations": pending ? [invitation] : []])
        }
        if path == "trips/" + tripID + "/respond", method == "POST" {
            let fields: [String: Bool]
            if let data = request.httpBody {
                fields = try JSONDecoder().decode([String: Bool].self, from: data)
            } else if let stream = request.httpBodyStream {
                stream.open(); defer { stream.close() }
                fields = try JSONSerialization.jsonObject(with: stream) as? [String: Bool] ?? [:]
            } else { fields = [:] }
            guard !queriedNonmemberDetail, let accept = fields["accept"], fields["locationConsent"] == accept,
                  responseStatus == nil else { return (400, ["detail": "INVALID_TEST_INVITATION_RESPONSE"]) }
            responseStatus = accept ? "accepted" : "declined"
            return (200, ["status": accept ? "accepted" : "declined"])
        }
        return nil
    }
}
#endif
