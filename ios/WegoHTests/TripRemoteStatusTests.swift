import Foundation
import XCTest
@testable import WegoH

private final class RemoteStatusHTTPStub: URLProtocol {
    static var response: [String: Any] = [:]
    static var status = 200
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func stopLoading() { }
    override func startLoading() {
        do {
            let response = HTTPURLResponse(url: request.url!, statusCode: Self.status, httpVersion: nil,
                                           headerFields: ["Content-Type": "application/json"])!
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: try JSONSerialization.data(withJSONObject: Self.response))
            client?.urlProtocolDidFinishLoading(self)
        } catch { client?.urlProtocol(self, didFailWithError: error) }
    }
}

@MainActor
final class TripRemoteStatusTests: XCTestCase {
    private let device = String(repeating: "d", count: 32)
    private let requestID = String(repeating: "e", count: 32)

    func testForegroundAndExpiredSupportRefreshWithoutSendingOrDiscardingDrafts() async throws {
        let (store, _, api, _) = try await context()
        let (fresh, action) = try await supportedToggle(store, api, seated: true)
        let key = store.draftKey(remote: fresh, action: action, seat: "ROW_1_RIGHT")
        let before = store.drafts
        var reads = api.remoteReads
        await store.maintainSupport(refreshImmediately: true, pause: { _ in throw CancellationError() })
        XCTAssertEqual(api.remoteReads, reads + 1)
        XCTAssertEqual(store.drafts.count, before.count)
        XCTAssertEqual(store.draft(key).enabled, false)
        var stale = fresh
        let formatter = ISO8601DateFormatter()
        stale.actions[0].support?.observedAt = formatter.string(from: .now.addingTimeInterval(-20))
        stale.actions[0].support?.expiresAt = formatter.string(from: .now.addingTimeInterval(-1))
        api.remoteValues = [stale]
        await store.load()
        XCTAssertFalse(try XCTUnwrap(store.remotes.first?.actions.first?.support).isCurrent)
        api.remoteValues = [fresh]
        reads = api.remoteReads
        await store.maintainSupport(refreshImmediately: false, pause: { _ in throw CancellationError() })
        XCTAssertEqual(api.remoteReads, reads + 1)
        XCTAssertTrue(try XCTUnwrap(store.remotes.first?.actions.first?.support).isFresh)
        XCTAssertFalse(store.refreshingSupport)
        XCTAssertEqual(api.commandCount, 0)
    }

    func testAutomaticSupportRefreshFailureKeepsCacheAndNeverResends() async throws {
        let (store, _, api, _) = try await context()
        let (fresh, _) = try await supportedToggle(store, api, seated: true)
        let reads = api.remoteReads
        api.failure = IPhoneResourceError.unavailable
        await store.maintainSupport(refreshImmediately: true, pause: { delay in
            XCTAssertEqual(delay, 2)
            throw CancellationError()
        })
        XCTAssertEqual(api.remoteReads, reads + 1)
        XCTAssertEqual(store.remotes.first?.id, fresh.id)
        XCTAssertNotNil(store.statusNotice)
        XCTAssertFalse(store.refreshingSupport)
        XCTAssertEqual(api.commandCount, 0)
    }

    func testSupportReadRetriesTransientFailureAndMissingSnapshotWithoutSending() async throws {
        for missingCount in 0...2 {
            let (store, _, api, _) = try await context()
            let (fresh, _) = try await supportedToggle(store, api, seated: true)
            if missingCount > 0 {
                var unknown = fresh
                if missingCount == 1 { unknown.actions[0].support = nil }
                else {
                    var action = unknown.actions[0]
                    action.id = "hvac.ac"; action.support = nil
                    unknown.actions.append(action)
                }
                api.remoteValues = [unknown]
                await store.load()
            } else {
                api.failure = IPhoneResourceError.unavailable
            }
            let reads = api.remoteReads
            var pauses = 0
            await store.maintainSupport(refreshImmediately: missingCount == 0, pause: { delay in
                pauses += 1
                if pauses == 1 {
                    XCTAssertEqual(delay, 2)
                    api.failure = nil
                    api.remoteValues = [fresh]
                } else { throw CancellationError() }
            })
            XCTAssertGreaterThanOrEqual(api.remoteReads, reads + 1)
            XCTAssertEqual(pauses, 2)
            XCTAssertTrue(try XCTUnwrap(store.remotes.first?.actions.first?.support).isFresh)
            XCTAssertEqual(api.commandCount, 0)
        }
    }

    func testSupportRetryBackoffIsCappedAndCancellationNeverSendsCommands() async throws {
        let (store, _, api, _) = try await context()
        let (fresh, _) = try await supportedToggle(store, api, seated: true)
        let reads = api.remoteReads
        api.failure = IPhoneResourceError.unavailable
        var delays: [TimeInterval] = []
        await store.maintainSupport(refreshImmediately: true, pause: { delay in
            delays.append(delay)
            if delays.count == 5 { throw CancellationError() }
        })
        XCTAssertEqual(delays, [2, 5, 10, 30, 30])
        XCTAssertEqual(api.remoteReads, reads + 5)
        XCTAssertEqual(store.remotes.first?.id, fresh.id)
        XCTAssertFalse(store.refreshingSupport)
        XCTAssertEqual(api.commandCount, 0)
    }

    func testSupportUsesReportedAreasBoundsAndStepAndMissingSupportIsUnknown() throws {
        let now = Date()
        let formatter = ISO8601DateFormatter()
        let support: [String: Any] = ["status": "known", "available": true,
            "areas": [["id": "ROW_1_RIGHT", "min": 15, "max": 30, "step": 0.5],
                      ["id": "ROW_2_LEFT", "min": 15, "max": 30, "step": 0.5]], "zones": [[String]](),
            "observedAt": formatter.string(from: now), "expiresAt": formatter.string(from: now.addingTimeInterval(90))]
        var json: [String: Any] = ["id": "hvac.temperature", "revision": 1, "label": "온도", "argumentKind": "hvac-celsius", "support": support]
        func decode() throws -> IPhoneTripRemote.Action {
            try JSONDecoder().decode(IPhoneTripRemote.Action.self, from: JSONSerialization.data(withJSONObject: json))
        }
        let action = try decode()
        XCTAssertTrue(action.isValid)
        let actual = try XCTUnwrap(action.support)
        XCTAssertTrue(actual.isFresh)
        XCTAssertEqual(actual.areas.map(\.id), ["ROW_1_RIGHT", "ROW_2_LEFT"])
        let area = try XCTUnwrap(actual.areas.first)
        XCTAssertTrue(area.contains(22.5))
        XCTAssertFalse(area.contains(22.25))
        XCTAssertFalse(area.contains(14.5))
        XCTAssertFalse(area.contains(30.5))
        var driver = support; driver["areas"] = [["id": "ROW_1_LEFT", "min": 15, "max": 30, "step": 0.5]]; json["support"] = driver
        XCTAssertFalse(try decode().isValid, "The driver seat is never a remote target, matching the server's 400")
        json["support"] = support
        var expired = support; expired["observedAt"] = formatter.string(from: now.addingTimeInterval(-100))
        expired["expiresAt"] = formatter.string(from: now.addingTimeInterval(-10)); json["support"] = expired
        XCTAssertFalse(try XCTUnwrap(decode().support).isFresh)
        json.removeValue(forKey: "support")
        XCTAssertNil(try decode().support)
        XCTAssertTrue(try decode().isValid)
        json["support"] = ["status": "unknown", "available": false, "areas": [], "zones": [], "observedAt": NSNull(), "expiresAt": NSNull()]
        XCTAssertFalse(try XCTUnwrap(decode().support).isFresh)
    }

    func testSupportBooleanNullBoundsGlobalAndNormalizedWindowRules() throws {
        let formatter = ISO8601DateFormatter(), now = Date()
        let times: [String: Any] = ["status": "known", "available": true, "zones": [[String]](),
            "observedAt": formatter.string(from: now), "expiresAt": formatter.string(from: now.addingTimeInterval(90))]
        func support(_ areas: [[String: Any]]) throws -> IPhoneTripRemote.Support {
            var json = times; json["areas"] = areas
            return try JSONDecoder().decode(IPhoneTripRemote.Support.self, from: JSONSerialization.data(withJSONObject: json))
        }
        let toggle = try support([["id": "ROW_1_RIGHT", "min": NSNull(), "max": NSNull(), "step": NSNull()]])
        XCTAssertTrue(toggle.isValid(kind: "seat-switch"))
        XCTAssertTrue(try support([]).isValid(kind: "switch"))
        XCTAssertFalse(toggle.isValid(kind: "switch"))
        let window = try support([["id": "ROW_1_RIGHT", "min": 0.0, "max": 100.0, "step": 1.0]])
        XCTAssertTrue(window.isValid(kind: "window-position"))
        XCTAssertFalse(try support([["id": "ROW_1_LEFT", "min": 0, "max": 100, "step": 1]]).isValid(kind: "window-position"))
        XCTAssertFalse(try support([["id": "ROW_1_LEFT", "min": NSNull(), "max": NSNull(), "step": NSNull()]]).isValid(kind: "seat-switch"))
        XCTAssertFalse(try support([["id": "ROW_3_LEFT", "min": 0, "max": 100, "step": 1]]).isValid(kind: "window-position"))
        let heat = try support([["id": "ROW_1_RIGHT", "min": 0, "max": 3, "step": 1]])
        XCTAssertTrue(heat.isValid(kind: "seat-level"))
        XCTAssertFalse(try XCTUnwrap(heat.areas.first).contains(4))
    }

    func testSupportZonesMustGroupReportedSeatsOnly() throws {
        let formatter = ISO8601DateFormatter(), now = Date()
        func support(_ zones: Any, ids: [String] = ["ROW_1_RIGHT", "ROW_2_LEFT", "ROW_2_RIGHT"]) throws -> IPhoneTripRemote.Support {
            let json: [String: Any] = ["status": "known", "available": true, "zones": zones,
                "areas": ids.map { ["id": $0, "min": NSNull(), "max": NSNull(), "step": NSNull()] },
                "observedAt": formatter.string(from: now), "expiresAt": formatter.string(from: now.addingTimeInterval(90))]
            return try JSONDecoder().decode(IPhoneTripRemote.Support.self, from: JSONSerialization.data(withJSONObject: json))
        }
        let shared = try support([["ROW_2_LEFT", "ROW_2_RIGHT"]])
        XCTAssertTrue(shared.isValid(kind: "seat-switch"))
        XCTAssertEqual(shared.zone(of: "ROW_2_RIGHT"), ["ROW_2_LEFT", "ROW_2_RIGHT"])
        XCTAssertEqual(shared.zone(of: "ROW_1_RIGHT"), ["ROW_1_RIGHT"])
        for zones in [[["ROW_2_LEFT"]], [["ROW_2_LEFT", "ROW_2_LEFT"]], [["ROW_2_LEFT", "ROW_3_LEFT"]],
                      [["ROW_2_LEFT", "ROW_2_RIGHT"], ["ROW_2_RIGHT", "ROW_1_RIGHT"]]] {
            XCTAssertFalse(try support(zones).isValid(kind: "seat-switch"), "\(zones)")
        }
        XCTAssertFalse(try support([["ROW_1_LEFT", "ROW_1_RIGHT"]], ids: ["ROW_1_LEFT", "ROW_1_RIGHT"]).isValid(kind: "seat-switch"),
                       "A zone shared with the driver seat cannot be reported")
        XCTAssertFalse(try support([["ROW_2_LEFT", "ROW_2_RIGHT"]]).isValid(kind: "window-position"))
        XCTAssertThrowsError(try JSONDecoder().decode(IPhoneTripRemote.Support.self, from: JSONSerialization.data(withJSONObject: [
            "status": "known", "available": true, "areas": [["id": "ROW_1_RIGHT", "min": NSNull(), "max": NSNull(), "step": NSNull()]],
            "observedAt": formatter.string(from: now), "expiresAt": formatter.string(from: now.addingTimeInterval(90))])),
            "zones is part of the support contract")
    }

    func testSeatOptionsFollowReportedZonesAndFallBackToFourSeatsOnlyWithoutSupport() throws {
        let now = ISO8601DateFormatter().string(from: Date())
        func action(_ id: String, _ kind: String, _ ids: [String]?, zones: [[String]] = [], available: Bool = true) -> IPhoneTripRemote.Action {
            let support = ids.map { ids in
                IPhoneTripRemote.Support(status: "known", available: available,
                    areas: ids.map { IPhoneTripRemote.Support.Area(id: $0, min: nil, max: nil, step: nil) },
                    zones: zones, observedAt: now, expiresAt: now)
            }
            return IPhoneTripRemote.Action(id: id, revision: 1, label: id, argumentKind: kind, support: support)
        }
        let cabin = ["ROW_1_LEFT", "ROW_1_RIGHT", "ROW_2_LEFT", "ROW_2_CENTER", "ROW_2_RIGHT"]
        let power = action("hvac.power", "seat-switch", cabin, zones: [cabin])
        let heat = action("seat.heat", "seat-level", ["ROW_1_LEFT", "ROW_1_RIGHT", "ROW_2_LEFT", "ROW_2_RIGHT"])
        XCTAssertEqual(TripRemoteSeats.options([power, heat]), ["ROW_1_RIGHT", "ROW_2_LEFT", "ROW_2_RIGHT"],
                       "A cabin-wide zone must not add a centre seat that nothing controls on its own")
        XCTAssertEqual(TripRemoteSeats.options([power]), ["ROW_1_RIGHT"], "A shared zone is reachable through its first non-driver seat")
        let third = action("seat.ventilation", "seat-level", ["ROW_3_LEFT", "ROW_3_RIGHT"])
        XCTAssertEqual(TripRemoteSeats.options([power, heat, third]).suffix(2), ["ROW_3_LEFT", "ROW_3_RIGHT"])
        let fan = action("hvac.fan", "hvac-fan", ["ROW_1_LEFT", "ROW_1_RIGHT", "ROW_2_LEFT", "ROW_2_RIGHT"],
                         zones: [["ROW_1_LEFT", "ROW_1_RIGHT"], ["ROW_2_LEFT", "ROW_2_RIGHT"]])
        XCTAssertEqual(TripRemoteSeats.options([fan]), ["ROW_2_LEFT"], "Fan writes the whole SDK zone, so the driver's front zone is never offered")
        XCTAssertEqual(fan.support?.zone(of: "ROW_2_RIGHT"), ["ROW_2_LEFT", "ROW_2_RIGHT"])
        let temperature = action("hvac.temperature", "hvac-celsius", ["ROW_1_LEFT", "ROW_1_RIGHT", "ROW_2_LEFT", "ROW_2_RIGHT"],
                                 zones: [["ROW_1_LEFT", "ROW_2_LEFT"]])
        XCTAssertEqual(TripRemoteSeats.options([temperature]), ["ROW_1_RIGHT", "ROW_2_RIGHT"],
                       "A seat zone shared with the driver is never offered")
        let windows = action("window.position", "window-position", ["ROW_1_LEFT", "ROW_1_RIGHT"])
        XCTAssertEqual(TripRemoteSeats.options([windows]), ["ROW_1_RIGHT"])
        for (candidate, seat) in [(fan, "ROW_1_LEFT"), (fan, "ROW_1_RIGHT"), (temperature, "ROW_2_LEFT"), (windows, "ROW_1_LEFT")] {
            XCTAssertFalse(TripRemoteSeats.allows(candidate.id, seat: seat, support: try XCTUnwrap(candidate.support)))
        }
        XCTAssertTrue(TripRemoteSeats.allows(power.id, seat: "ROW_2_LEFT", support: try XCTUnwrap(power.support)))
        XCTAssertFalse(TripRemoteSeats.fallback.contains(TripRemoteSeats.driver))
        let unknown = action("hvac.power", "seat-switch", nil)
        let light = action("light.cabin", "switch", [])
        XCTAssertTrue(TripRemoteSeats.usesFallback([unknown, light]))
        XCTAssertEqual(TripRemoteSeats.options([unknown, light]), TripRemoteSeats.fallback)
        XCTAssertEqual(TripRemoteSeats.options([light]), [], "Whole-car switches need no seat")
        let unsupported = action("seat.heat", "seat-level", [], available: false)
        XCTAssertFalse(TripRemoteSeats.usesFallback([unsupported, unknown]))
        XCTAssertEqual(TripRemoteSeats.options([unsupported, unknown]), [])
    }

    func testRemote422SupportFailuresKeepTypedReasonAndDoNotResubmit() async throws {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [RemoteStatusHTTPStub.self]
        let api = IPhoneTripActivityAPI(configuration: config)
        let action = IPhoneTripRemote.Action(id: "light.cabin", revision: 1, label: "실내등", argumentKind: "switch")
        let remote = IPhoneTripRemote(deviceId: device, ownerName: "운전자", deviceName: "차", grantRevision: 3, actions: [action])
        RemoteStatusHTTPStub.status = 422
        defer { RemoteStatusHTTPStub.status = 200 }
        for code in ["VEHICLE_CONTROL_UNSUPPORTED", "VEHICLE_CONTROL_AREA_UNSUPPORTED", "VEHICLE_CONTROL_VALUE_UNSUPPORTED"] {
            RemoteStatusHTTPStub.response = ["detail": code]
            do {
                _ = try await api.command(String(repeating: "a", count: 32), remote: remote, action: action,
                    seat: "ROW_2_LEFT", value: true, token: String(repeating: "T", count: 43))
                XCTFail("Accepted unsupported control")
            } catch IPhoneResourceError.tripConflict(let actual) { XCTAssertEqual(actual, code) }
        }
    }

    func testRemoteCommandReceiverOffAndDisconnectAreVehicleStateNotLostPermission() async throws {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [RemoteStatusHTTPStub.self]
        let api = IPhoneTripActivityAPI(configuration: config)
        let action = IPhoneTripRemote.Action(id: "light.cabin", revision: 1, label: "실내등", argumentKind: "switch")
        let remote = IPhoneTripRemote(deviceId: device, ownerName: "운전자", deviceName: "차", grantRevision: 3, actions: [action])
        defer { RemoteStatusHTTPStub.status = 200 }
        func send() async throws {
            _ = try await api.command(String(repeating: "a", count: 32), remote: remote, action: action,
                seat: "ROW_1_LEFT", value: true, token: String(repeating: "T", count: 43))
        }
        for (status, detail, code) in [(403, "FUNCTIONAL_PURPOSE_REQUIRED", "VEHICLE_REMOTE_RECEIVER_OFF"),
                                       (404, "DEVICE_UNAVAILABLE", "VEHICLE_REMOTE_DISCONNECTED")] {
            RemoteStatusHTTPStub.status = status
            RemoteStatusHTTPStub.response = ["detail": detail]
            do { try await send(); XCTFail("Accepted a command the vehicle cannot receive") }
            catch IPhoneResourceError.tripConflict(let actual) {
                XCTAssertEqual(actual, code)
                let error = IPhoneResourceError.tripConflict(actual)
                XCTAssertTrue(TripLiveRemoteStore.vehicleNotReceiving(error))
                XCTAssertFalse(tripActivityAccessLost(error))
                XCTAssertFalse(tripPreparationErrorMessage(error).contains("로그인"))
                XCTAssertTrue(tripPreparationErrorMessage(error).contains("운전자"))
            }
        }
        XCTAssertTrue(tripPreparationErrorMessage(IPhoneResourceError.tripConflict("VEHICLE_REMOTE_RECEIVER_OFF")).contains("리모컨 받기"))
        RemoteStatusHTTPStub.status = 403
        RemoteStatusHTTPStub.response = ["detail": "Current trip remote permission required"]
        do { try await send(); XCTFail("Accepted a withdrawn remote permission") } catch IPhoneSessionError.forbidden { }
        RemoteStatusHTTPStub.status = 404
        RemoteStatusHTTPStub.response = ["detail": "Device request unavailable"]
        do { try await send(); XCTFail("Accepted a missing trip") } catch IPhoneResourceError.missing { }
        let body = try JSONSerialization.data(withJSONObject: ["detail": "FUNCTIONAL_PURPOSE_REQUIRED"])
        XCTAssertNil(tripRemoteReceiverReason(path: "trips/a/vehicle-remotes", method: "GET", status: 403, data: body))
        XCTAssertNil(tripRemoteReceiverReason(path: "trips/a/cars/c/remote-policy", method: "POST", status: 403, data: body))
    }

    func testReceiverOffKeepsSheetAndUnsentClimateInputAndReappliesSameValue() async throws {
        let (store, _, activity, _) = try await context()
        let temperature = IPhoneTripRemote.Action(id: "hvac.temperature", revision: 1, label: "온도", argumentKind: "hvac-celsius")
        let fan = IPhoneTripRemote.Action(id: "hvac.fan", revision: 1, label: "풍량", argumentKind: "hvac-fan")
        activity.remoteValues[0].actions = [temperature, fan]
        await store.load()
        let remote = try XCTUnwrap(store.remotes.first)
        let tempKey = store.draftKey(remote: remote, action: temperature, seat: "ROW_1_RIGHT")
        let fanKey = store.draftKey(remote: remote, action: fan, seat: "ROW_1_RIGHT")
        store.setTemperature(23, key: tempKey); store.setLevel(5, key: fanKey)
        let reads = activity.remoteReads
        activity.commandFailure = IPhoneResourceError.tripConflict("VEHICLE_REMOTE_RECEIVER_OFF")
        await store.sendBundle(remote: remote, seat: "ROW_1_RIGHT", commands: [(temperature, 23.0), (fan, 5)])
        XCTAssertEqual(store.remotes.first?.id, remote.id)
        XCTAssertEqual(activity.remoteReads, reads)
        XCTAssertEqual(store.draft(tempKey).temperature, 23)
        XCTAssertEqual(store.draft(fanKey).level, 5)
        XCTAssertFalse(store.draft(tempKey).toggleLocked)
        XCTAssertTrue(store.climateValueChanged(tempKey))
        XCTAssertFalse(store.commandInFlight)
        let toast = try XCTUnwrap(store.feedback?.message)
        XCTAssertTrue(toast.contains("리모컨 받기"))
        XCTAssertFalse(toast.contains("로그인"))
        XCTAssertFalse(store.message?.contains("권한") == true)
        XCTAssertEqual(activity.commandCount, 1)
        activity.commandFailure = nil
        await store.sendBundle(remote: remote, seat: "ROW_1_RIGHT", commands: [(temperature, 23.0), (fan, 5)])
        XCTAssertEqual(activity.commandCount, 3)
        XCTAssertTrue(store.draft(tempKey).toggleLocked)

        let (revoked, _, revokedAPI, _) = try await context()
        let available = try XCTUnwrap(revoked.remotes.first)
        revokedAPI.commandFailure = IPhoneSessionError.forbidden
        await revoked.send(remote: available, action: try XCTUnwrap(available.actions.first), seat: "ROW_1_LEFT", value: true)
        XCTAssertTrue(revoked.remotes.isEmpty)
        XCTAssertTrue(revoked.message?.contains("허용 범위") == true)
    }

    func testRealGETDecodesRequestProgressAndRejectsForeignOrPhysicalSuccessClaims() async throws {
        let trip = String(repeating: "a", count: 32)
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [RemoteStatusHTTPStub.self]
        let api = IPhoneTripActivityAPI(configuration: config)
        let request: [String: Any] = ["id": requestID, "tripId": trip, "targetDeviceId": device,
            "capabilityId": "light.cabin", "capabilityRevision": 1, "stage": "rejected",
            "lastAcknowledgedStage": "received", "reason": NSNull(), "mayHaveExecuted": false,
            "physicalExecutionVerified": false, "createdAt": "2026-11-13T05:00:00.000000+00:00",
            "expiresAt": "2026-11-13T05:00:30.000000+00:00"]
        var remote: [String: Any] = ["deviceId": device, "ownerName": "운전자", "deviceName": "차", "grantRevision": 3,
            "actions": [["id": "light.cabin", "revision": 1, "label": "실내등", "argumentKind": "switch"]], "requests": [request]]
        RemoteStatusHTTPStub.response = ["tripId": trip, "remotes": [remote]]
        let values = try await api.remotes(trip, token: String(repeating: "T", count: 43))
        XCTAssertEqual(values.first?.requests?.first?.id, requestID)
        XCTAssertEqual(values.first?.requests?.first?.stage, "rejected")
        XCTAssertNil(values.first?.requests?.first?.reason)
        for (key, value) in [("tripId", String(repeating: "b", count: 32) as Any),
                             ("targetDeviceId", String(repeating: "b", count: 32)),
                             ("capabilityId", "window.position"), ("stage", "physical-success"),
                             ("physicalExecutionVerified", true)] {
            var invalid = request; invalid[key] = value
            remote["requests"] = [invalid]
            RemoteStatusHTTPStub.response = ["tripId": trip, "remotes": [remote]]
            do { _ = try await api.remotes(trip, token: String(repeating: "T", count: 43)); XCTFail("Accepted invalid request field \(key)") }
            catch IPhoneSessionError.invalidResponse { }
        }
    }

    func testQueuedCommandIsReplacedBySameRequestTerminalFeedbackWithoutAnotherPOST() async throws {
        let (store, _, activity, _) = try await context()
        let remote = try XCTUnwrap(store.remotes.first)
        let action = try XCTUnwrap(remote.actions.first)
        await store.send(remote: remote, action: action, seat: "ROW_2_LEFT", value: true)
        let id = try XCTUnwrap(store.commandResults.first?.id)
        activity.remoteValues[0].requests = [request(id: id, trip: try XCTUnwrap(store.preparation.detail).id, stage: "state-confirmed")]
        await store.observeCommandStatuses(pause: { await Task.yield() })
        XCTAssertEqual(store.commandResults.first?.stage, "state-confirmed")
        XCTAssertEqual(store.commandResults.first?.title, "차량 응답 확인")
        XCTAssertFalse(try XCTUnwrap(store.commandResults.first).needsObservation)
        XCTAssertFalse(store.message?.contains("전달 대기") == true)
        XCTAssertTrue(store.message?.contains("실제 작동 여부") == true)
        XCTAssertEqual(activity.commandCount, 1)
    }

    func testClimateBundleKeepsIndependentRequestResultsAndMayHaveExecuted() async throws {
        let (store, _, activity, _) = try await context()
        let temperature = IPhoneTripRemote.Action(id: "hvac.temperature", revision: 1, label: "온도", argumentKind: "hvac-celsius")
        let fan = IPhoneTripRemote.Action(id: "hvac.fan", revision: 1, label: "풍량", argumentKind: "hvac-fan")
        activity.remoteValues[0].actions = [temperature, fan]
        await store.load()
        let remote = try XCTUnwrap(store.remotes.first)
        await store.sendBundle(remote: remote, seat: "ROW_2_LEFT", commands: [(temperature, 22.5), (fan, 3)])
        XCTAssertEqual(store.commandResults.count, 2)
        let trip = try XCTUnwrap(store.preparation.detail).id
        activity.remoteValues[0].requests = store.commandResults.map { status in
            var value = request(id: status.id, trip: trip, stage: status.actionID == temperature.id ? "state-confirmed" : "unknown")
            value.capabilityId = status.actionID
            if status.actionID == fan.id { value.reason = "lease-expired"; value.mayHaveExecuted = true }
            return value
        }
        await store.observeCommandStatuses(pause: { await Task.yield() })
        XCTAssertEqual(store.commandResults.first(where: { $0.actionID == temperature.id })?.stage, "state-confirmed")
        let uncertain = try XCTUnwrap(store.commandResults.first(where: { $0.actionID == fan.id }))
        XCTAssertEqual(uncertain.stage, "unknown")
        XCTAssertTrue(uncertain.mayHaveExecuted)
        XCTAssertEqual(uncertain.reasonTitle, "차량의 처리 확인 시간이 지났어요.")
        XCTAssertEqual(activity.commandCount, 2)
    }

    func testRejectedWithoutSDKReasonDoesNotInventAnUnsupportedSeatCause() async throws {
        let (store, _, activity, _) = try await context()
        let remote = try XCTUnwrap(store.remotes.first), action = try XCTUnwrap(remote.actions.first)
        await store.send(remote: remote, action: action, seat: "ROW_2_LEFT", value: true)
        let id = try XCTUnwrap(store.commandResults.first?.id)
        activity.remoteValues[0].requests = [request(id: id, trip: try XCTUnwrap(store.preparation.detail).id, stage: "rejected")]
        await store.observeCommandStatuses(pause: { await Task.yield() })
        XCTAssertEqual(store.commandResults.first?.reasonTitle, "차량이 명령을 거절했어요.")
        XCTAssertEqual(activity.commandCount, 1)
        XCTAssertEqual(activity.remoteReads, 2)
    }

    func testDrivingRestrictedRejectionExplainsTheVehicleWasMoving() async throws {
        let (store, _, activity, _) = try await context()
        let remote = try XCTUnwrap(store.remotes.first), action = try XCTUnwrap(remote.actions.first)
        await store.send(remote: remote, action: action, seat: "ROW_2_LEFT", value: true)
        let id = try XCTUnwrap(store.commandResults.first?.id)
        var value = request(id: id, trip: try XCTUnwrap(store.preparation.detail).id, stage: "rejected")
        value.reason = "driving-restricted"
        activity.remoteValues[0].requests = [value]
        await store.observeCommandStatuses(pause: { await Task.yield() })
        XCTAssertEqual(store.commandResults.first?.reasonTitle, "주행 중이라 차량이 실행하지 않았어요.")
        XCTAssertEqual(activity.commandCount, 1)
    }

    func testMissingRequestStopsAsUnconfirmedAndManualRefreshOnlyReads() async throws {
        let (store, _, activity, _) = try await context()
        let remote = try XCTUnwrap(store.remotes.first), action = try XCTUnwrap(remote.actions.first)
        await store.send(remote: remote, action: action, seat: "ROW_2_LEFT", value: true)
        activity.remoteValues[0].requests = []
        await store.observeCommandStatuses(pause: { await Task.yield() })
        XCTAssertTrue(try XCTUnwrap(store.commandResults.first).confirmationUnavailable)
        XCTAssertEqual(store.commandResults.first?.stage, "queued")
        XCTAssertTrue(store.statusNotice?.contains("결과를 확인할 수 없어요") == true)
        await store.refreshCommandStatuses()
        XCTAssertEqual(activity.commandCount, 1)
    }

    func testObservationHasABoundAndCancellationDoesNotRetryTheCommand() async throws {
        let (store, _, activity, _) = try await context()
        let remote = try XCTUnwrap(store.remotes.first), action = try XCTUnwrap(remote.actions.first)
        await store.send(remote: remote, action: action, seat: "ROW_2_LEFT", value: true)
        let id = try XCTUnwrap(store.commandResults.first?.id)
        activity.remoteValues[0].requests = [request(id: id, trip: try XCTUnwrap(store.preparation.detail).id, stage: "received")]
        await store.observeCommandStatuses(maximumReads: 2, pause: { await Task.yield() })
        XCTAssertEqual(activity.remoteReads, 3)
        XCTAssertTrue(try XCTUnwrap(store.commandResults.first).confirmationUnavailable)
        await store.refreshCommandStatuses()
        let reads = activity.remoteReads
        let observing = Task { await store.observeCommandStatuses(pause: { try await Task.sleep(for: .seconds(60)) }) }
        for _ in 0..<1000 where activity.remoteReads == reads { await Task.yield() }
        XCTAssertEqual(activity.remoteReads, reads + 1)
        observing.cancel()
        await observing.value
        XCTAssertEqual(activity.remoteReads, reads + 1)
        XCTAssertEqual(activity.commandCount, 1)
    }

    func testRevocationAndLateLogoutResponseCannotRestoreOldRemoteResults() async throws {
        let (store, _, activity, session) = try await context()
        let remote = try XCTUnwrap(store.remotes.first), action = try XCTUnwrap(remote.actions.first)
        await store.send(remote: remote, action: action, seat: "ROW_2_LEFT", value: true)
        activity.pauseRead = true
        let observing = Task { await store.refreshCommandStatuses() }
        for _ in 0..<1000 where activity.pendingRead == nil { await Task.yield() }
        let pending = try XCTUnwrap(activity.pendingRead)
        await session.signOut()
        pending.resume(returning: activity.remoteValues)
        await observing.value
        XCTAssertTrue(store.commandResults.isEmpty)
        XCTAssertTrue(store.remotes.isEmpty)
        XCTAssertEqual(activity.commandCount, 1)
        let (revoked, _, revokedAPI, _) = try await context()
        let available = try XCTUnwrap(revoked.remotes.first)
        await revoked.send(remote: available, action: try XCTUnwrap(available.actions.first), seat: "ROW_2_LEFT", value: true)
        revokedAPI.failure = IPhoneSessionError.forbidden
        await revoked.refreshCommandStatuses()
        XCTAssertTrue(revoked.commandResults.isEmpty)
        XCTAssertTrue(revoked.remotes.isEmpty)
    }

    func testDraftsKeepEachSeatAndActionSeparateAndGlobalLightHasNoSeat() async throws {
        let (store, _, _, _) = try await context()
        let remote = try XCTUnwrap(store.remotes.first)
        let temperature = IPhoneTripRemote.Action(id: "hvac.temperature", revision: 1, label: "온도", argumentKind: "hvac-celsius")
        let fan = IPhoneTripRemote.Action(id: "hvac.fan", revision: 1, label: "풍량", argumentKind: "hvac-fan")
        let heat = IPhoneTripRemote.Action(id: "seat.heat", revision: 1, label: "열선", argumentKind: "seat-level")
        let left = store.draftKey(remote: remote, action: temperature, seat: "ROW_2_LEFT")
        let right = store.draftKey(remote: remote, action: temperature, seat: "ROW_1_RIGHT")
        store.setTemperature(20, key: left); store.setTemperature(25, key: right)
        let fanKey = store.draftKey(remote: remote, action: fan, seat: "ROW_2_LEFT")
        let heatKey = store.draftKey(remote: remote, action: heat, seat: "ROW_2_LEFT")
        store.setLevel(6, key: fanKey); store.setLevel(2, key: heatKey)
        XCTAssertEqual(store.draft(left).temperature, 20)
        XCTAssertEqual(store.draft(right).temperature, 25)
        XCTAssertEqual(store.draft(fanKey).level, 6)
        XCTAssertEqual(store.draft(heatKey).level, 2)
        let light = try XCTUnwrap(remote.actions.first)
        XCTAssertEqual(store.draftKey(remote: remote, action: light, seat: "ROW_2_LEFT"), store.draftKey(remote: remote, action: light, seat: "ROW_1_RIGHT"))
        var changed = remote; changed.grantRevision += 1
        XCTAssertNotEqual(left, store.draftKey(remote: changed, action: temperature, seat: "ROW_2_LEFT"))
        changed = remote; changed.deviceId = String(repeating: "f", count: 32)
        XCTAssertNotEqual(left, store.draftKey(remote: changed, action: temperature, seat: "ROW_2_LEFT"))
        store.discardDrafts()
        XCTAssertTrue(store.drafts.isEmpty)
    }

    func testClimateApplySendsOnlyChangedValues() async throws {
        let (store, _, _, _) = try await context()
        let remote = IPhoneTripRemote(deviceId: String(repeating: "d", count: 32), ownerName: "운전자", deviceName: "차", grantRevision: 1, actions: [])
        let temperature = IPhoneTripRemote.Action(id: "hvac.temperature", revision: 1, label: "설정 온도", argumentKind: "hvac-celsius")
        let fan = IPhoneTripRemote.Action(id: "hvac.fan", revision: 1, label: "풍량", argumentKind: "hvac-fan")
        let temperatureKey = store.draftKey(remote: remote, action: temperature, seat: "ROW_1_LEFT")
        let fanKey = store.draftKey(remote: remote, action: fan, seat: "ROW_1_LEFT")
        XCTAssertFalse(store.climateValueChanged(temperatureKey))
        XCTAssertFalse(store.climateValueChanged(fanKey))
        store.setTemperature(23, key: temperatureKey)
        XCTAssertTrue(store.climateValueChanged(temperatureKey))
        XCTAssertFalse(store.climateValueChanged(fanKey))
        store.setTemperature(22.5, key: temperatureKey)
        XCTAssertFalse(store.climateValueChanged(temperatureKey))
    }

    func testMultipleClimateResultsAreReportedPerItem() {
        func status(_ label: String, _ stage: String, unavailable: Bool = false, executed: Bool = false) -> TripRemoteCommandStatus {
            var value = TripRemoteCommandStatus(id: UUID().uuidString, deviceID: "d", actionID: label, label: label, stage: stage, reason: nil, mayHaveExecuted: executed)
            value.confirmationUnavailable = unavailable
            return value
        }
        // trackedCommands는 최신 명령이 앞에 온다: 풍량을 나중에 보냈다.
        let mixed = [status("풍량", "unknown", executed: true), status("설정 온도", "state-confirmed")]
        XCTAssertEqual(TripLiveRemoteStore.feedbackMessage(mixed, failed: false, unconfirmed: false),
                       "설정 온도는 적용했어요 · 풍량은 확인하지 못했어요. 차에서 확인해 주세요.")
        let both = [status("풍량", "state-confirmed"), status("설정 온도", "state-confirmed")]
        XCTAssertEqual(TripLiveRemoteStore.feedbackMessage(both, failed: false, unconfirmed: false), "설정 온도는 적용했어요 · 풍량은 적용했어요")
        XCTAssertEqual(TripLiveRemoteStore.feedbackMessage([status("설정 온도", "state-confirmed")], failed: false, unconfirmed: false), "적용했어요.")
        XCTAssertEqual(TripLiveRemoteStore.feedbackMessage([status("풍량", "rejected")], failed: true, unconfirmed: false), "적용하지 못했어요.")
    }

    func testToggleImmediatelyPostsOnceAndExactTerminalResponseUnlocks() async throws {
        let (store, _, activity, _) = try await context()
        let (remote, action) = try await supportedToggle(store, activity)
        let key = store.draftKey(remote: remote, action: action, seat: "ROW_2_LEFT")
        let sending = try XCTUnwrap(store.toggle(remote: remote, action: action, seat: "ROW_2_LEFT", enabled: true))
        XCTAssertFalse(store.draft(key).enabled)
        XCTAssertEqual(store.draft(key).requestedEnabled, true)
        XCTAssertTrue(store.draft(key).toggleLocked)
        XCTAssertNil(store.toggle(remote: remote, action: action, seat: "ROW_2_LEFT", enabled: false))
        XCTAssertTrue(store.commandInFlight)
        XCTAssertNil(store.feedback)
        await sending.value
        XCTAssertEqual(activity.commandCount, 1)
        let id = try XCTUnwrap(store.draft(key).requestID)
        activity.remoteValues[0].requests = [request(id: id, trip: try XCTUnwrap(store.preparation.detail).id, stage: "state-confirmed")]
        await store.refreshCommandStatuses()
        XCTAssertTrue(store.draft(key).enabled)
        XCTAssertFalse(store.draft(key).toggleLocked)
        XCTAssertEqual(activity.commandCount, 1)
        XCTAssertFalse(store.commandInFlight)
        XCTAssertEqual(store.feedback?.message, "적용했어요.")
    }

    func testClimateFailureRestoresLastConfirmedValuesAndKeepsRemoteCache() async throws {
        let (store, _, activity, _) = try await context()
        let temperature = IPhoneTripRemote.Action(id: "hvac.temperature", revision: 1, label: "온도", argumentKind: "hvac-celsius")
        let fan = IPhoneTripRemote.Action(id: "hvac.fan", revision: 1, label: "풍량", argumentKind: "hvac-fan")
        activity.remoteValues[0].actions = [temperature, fan]
        await store.load()
        let remote = try XCTUnwrap(store.remotes.first)
        let tempKey = store.draftKey(remote: remote, action: temperature, seat: "ROW_1_RIGHT")
        let fanKey = store.draftKey(remote: remote, action: fan, seat: "ROW_1_RIGHT")
        await store.sendBundle(remote: remote, seat: "ROW_1_RIGHT", commands: [(temperature, 24.0), (fan, 4)])
        XCTAssertTrue(store.draft(tempKey).toggleLocked)
        XCTAssertTrue(store.draft(fanKey).toggleLocked)
        let tripID = try XCTUnwrap(store.preparation.detail).id
        activity.remoteValues[0].requests = store.commandResults.map { status in
            var value = request(id: status.id, trip: tripID, stage: "state-confirmed")
            value.capabilityId = status.actionID
            return value
        }
        await store.refreshCommandStatuses()
        XCTAssertFalse(store.draft(tempKey).toggleLocked)
        XCTAssertEqual(store.draft(tempKey).confirmedTemperature, 24)
        XCTAssertEqual(store.draft(fanKey).confirmedLevel, 4)
        store.setTemperature(25, key: tempKey); store.setLevel(5, key: fanKey)
        activity.commandFailure = IPhoneResourceError.conflict
        await store.sendBundle(remote: remote, seat: "ROW_1_RIGHT", commands: [(temperature, 25.0), (fan, 5)])
        XCTAssertEqual(store.draft(tempKey).temperature, 24)
        XCTAssertEqual(store.draft(fanKey).level, 4)
        XCTAssertFalse(store.draft(tempKey).toggleLocked)
        XCTAssertFalse(store.draft(fanKey).toggleLocked)
        XCTAssertEqual(store.remotes.first?.id, remote.id)
        XCTAssertEqual(activity.commandCount, 3)
    }

    func testToggleDefiniteRejectionRestoresOnlyPreviousLocalDraft() async throws {
        let (store, _, activity, _) = try await context()
        let (remote, action) = try await supportedToggle(store, activity)
        let key = store.draftKey(remote: remote, action: action, seat: "ROW_2_LEFT")
        let sending = try XCTUnwrap(store.toggle(remote: remote, action: action, seat: "ROW_2_LEFT", enabled: true))
        await sending.value
        let id = try XCTUnwrap(store.draft(key).requestID)
        activity.remoteValues[0].requests = [request(id: id, trip: try XCTUnwrap(store.preparation.detail).id, stage: "rejected")]
        await store.refreshCommandStatuses()
        XCTAssertFalse(store.draft(key).enabled)
        XCTAssertFalse(store.draft(key).toggleLocked)
        XCTAssertTrue(store.draft(key).notice?.contains("이전 입력값") == true)
        XCTAssertEqual(activity.commandCount, 1)
    }

    func testAmbiguousResultRestoresDisplayAndOnlyANewExplicitToggleSends() async throws {
        let (store, _, activity, _) = try await context()
        let (remote, action) = try await supportedToggle(store, activity)
        let key = store.draftKey(remote: remote, action: action, seat: "ROW_2_LEFT")
        try await XCTUnwrap(store.toggle(remote: remote, action: action, seat: "ROW_2_LEFT", enabled: true)).value
        let id = try XCTUnwrap(store.draft(key).requestID)
        var result = request(id: id, trip: try XCTUnwrap(store.preparation.detail).id, stage: "rejected")
        result.mayHaveExecuted = true
        activity.remoteValues[0].requests = [result]
        await store.refreshCommandStatuses()
        XCTAssertFalse(store.draft(key).enabled)
        XCTAssertTrue(store.draft(key).uncertain)
        XCTAssertFalse(store.draft(key).toggleLocked)
        XCTAssertTrue(store.draft(key).notice?.contains("응답을 확인하지 못했어요") == true)
        XCTAssertEqual(activity.commandCount, 1)
        try await XCTUnwrap(store.toggle(remote: remote, action: action, seat: "ROW_2_LEFT", enabled: true)).value
        XCTAssertEqual(activity.commandCount, 2)
    }

    func testNoReceiptFailureCannotBeMatchedToRecentRequestAndNeverRetries() async throws {
        for error: Error in [URLError(.timedOut), IPhoneSessionError.invalidResponse, IPhoneResourceError.unavailable] {
            let (store, _, activity, _) = try await context()
            let (remote, action) = try await supportedToggle(store, activity)
            let key = store.draftKey(remote: remote, action: action, seat: "ROW_2_LEFT")
            activity.commandFailure = error
            try await XCTUnwrap(store.toggle(remote: remote, action: action, seat: "ROW_2_LEFT", enabled: true)).value
            XCTAssertNil(store.draft(key).requestID)
            XCTAssertFalse(store.draft(key).enabled)
            XCTAssertTrue(store.draft(key).uncertain)
            activity.remoteValues[0].requests = [request(id: requestID, trip: try XCTUnwrap(store.preparation.detail).id, stage: "state-confirmed")]
            await store.refreshCommandStatuses()
            XCTAssertFalse(store.draft(key).toggleLocked)
            XCTAssertEqual(activity.commandCount, 1)
        }
    }

    func testOtherSeatDraftAndDiscardedScreenIgnoreLateToggleResponse() async throws {
        let (store, _, activity, _) = try await context()
        let (remote, action) = try await supportedToggle(store, activity, seated: true)
        let left = store.draftKey(remote: remote, action: action, seat: "ROW_2_LEFT")
        let right = store.draftKey(remote: remote, action: action, seat: "ROW_1_RIGHT")
        try await XCTUnwrap(store.toggle(remote: remote, action: action, seat: "ROW_2_LEFT", enabled: true)).value
        let id = try XCTUnwrap(store.draft(left).requestID)
        var result = request(id: id, trip: try XCTUnwrap(store.preparation.detail).id, stage: "rejected")
        result.capabilityId = action.id
        activity.remoteValues[0].requests = [result]
        await store.refreshCommandStatuses()
        XCTAssertFalse(store.draft(left).enabled)
        XCTAssertFalse(store.draft(right).enabled)
        XCTAssertNil(store.drafts[right])
        XCTAssertEqual(activity.sentSeats, ["ROW_2_LEFT"])
        activity.pauseCommand = true
        let pending = try XCTUnwrap(store.toggle(remote: remote, action: action, seat: "ROW_1_RIGHT", enabled: true))
        for _ in 0..<1000 where activity.pendingCommand == nil { await Task.yield() }
        let callback = try XCTUnwrap(activity.pendingCommand)
        store.discardDrafts()
        callback.resume(returning: .init(id: requestID, stage: "state-confirmed", physicalExecutionVerified: false))
        await pending.value
        XCTAssertTrue(store.drafts.isEmpty)
    }

    func testUnsupportedToggleAndExplicit422DoNotInventVehicleState() async throws {
        let (store, _, activity, _) = try await context()
        let unknownRemote = try XCTUnwrap(store.remotes.first)
        let unknownAction = try XCTUnwrap(unknownRemote.actions.first)
        XCTAssertNil(store.toggle(remote: unknownRemote, action: unknownAction, seat: nil, enabled: true))
        let (remote, action) = try await supportedToggle(store, activity, seated: true)
        XCTAssertNil(store.toggle(remote: remote, action: action, seat: nil, enabled: true))
        activity.commandFailure = IPhoneResourceError.tripConflict("VEHICLE_CONTROL_AREA_UNSUPPORTED")
        let key = store.draftKey(remote: remote, action: action, seat: "ROW_2_LEFT")
        try await XCTUnwrap(store.toggle(remote: remote, action: action, seat: "ROW_2_LEFT", enabled: true)).value
        XCTAssertFalse(store.draft(key).enabled)
        XCTAssertFalse(store.draft(key).toggleLocked)
        XCTAssertEqual(activity.commandCount, 1)
    }

    private func supportedToggle(_ store: TripLiveRemoteStore, _ activity: RemoteStatusTestAPI,
                                 seated: Bool = false) async throws -> (IPhoneTripRemote, IPhoneTripRemote.Action) {
        let formatter = ISO8601DateFormatter(), now = Date()
        let areas: [IPhoneTripRemote.Support.Area] = seated ? ["ROW_2_LEFT", "ROW_1_RIGHT"].map { .init(id: $0, min: nil, max: nil, step: nil) } : []
        let action = IPhoneTripRemote.Action(id: seated ? "hvac.power" : "light.cabin", revision: 1,
            label: "전원", argumentKind: seated ? "seat-switch" : "switch",
            support: .init(status: "known", available: true, areas: areas,
                observedAt: formatter.string(from: now), expiresAt: formatter.string(from: now.addingTimeInterval(90))))
        activity.remoteValues[0].actions = [action]
        await store.load()
        return (try XCTUnwrap(store.remotes.first), action)
    }

    private func request(id: String, trip: String, stage: String) -> IPhoneTripRemoteRequest {
        .init(id: id, tripId: trip, targetDeviceId: device, capabilityId: "light.cabin", capabilityRevision: 1,
              stage: stage, lastAcknowledgedStage: nil, reason: nil, mayHaveExecuted: false, physicalExecutionVerified: false,
              createdAt: "2026-11-13T05:00:00+00:00", expiresAt: "2026-11-13T05:00:30+00:00")
    }

    private func context() async throws -> (TripLiveRemoteStore, FeatureTripAPI, RemoteStatusTestAPI, SessionManager) {
        let preview = try XCTUnwrap(TripPreviewData.myTrips.first { $0.id == "yangpyeong" })
        let sample = TripPreparationPreviewAPI(preview: preview)
        var detail = try await sample.detail(sample.tripID, token: "")
        detail.state = .active
        let session = SessionManager(api: RemoteStatusTestAuth(accountID: try XCTUnwrap(detail.me).id), credentials: RemoteStatusTestCredentials())
        await session.restore()
        let tripAPI = FeatureTripAPI(value: detail), activity = RemoteStatusTestAPI()
        activity.remoteValues = [.init(deviceId: device, ownerName: "운전자", deviceName: "차", grantRevision: 3,
            actions: [.init(id: "light.cabin", revision: 1, label: "실내등", argumentKind: "switch")])]
        let preparation = TripPreparationStore(tripID: detail.id, session: session, api: tripAPI, activityAPI: activity)
        await preparation.load()
        let store = TripLiveRemoteStore(preparation: preparation, api: activity)
        await store.load()
        return (store, tripAPI, activity, session)
    }
}

@MainActor
private final class RemoteStatusTestAPI: IPhoneTripActivityServing {
    var remoteValues: [IPhoneTripRemote] = []
    var remoteReads = 0, commandCount = 0
    var failure: Error?
    var commandFailure: Error?
    var sentSeats: [String] = []
    var pauseCommand = false
    var pendingCommand: CheckedContinuation<IPhoneTripRemoteReceipt, Never>?
    var pauseRead = false
    var pendingRead: CheckedContinuation<[IPhoneTripRemote], Never>?
    func remotes(_ tripID: String, token: String) async throws -> [IPhoneTripRemote] {
        remoteReads += 1
        if let failure { throw failure }
        if pauseRead { return await withCheckedContinuation { pendingRead = $0 } }
        return remoteValues
    }
    func command(_ tripID: String, remote: IPhoneTripRemote, action: IPhoneTripRemote.Action, seat: String, value: Any, token: String) async throws -> IPhoneTripRemoteReceipt {
        commandCount += 1; sentSeats.append(seat)
        if let commandFailure { throw commandFailure }
        if pauseCommand { return await withCheckedContinuation { pendingCommand = $0 } }
        return .init(id: String(format: "%032x", commandCount), stage: "queued", physicalExecutionVerified: false)
    }
    func signals(_ tripID: String, token: String) async throws -> [IPhoneTripSignal] { [] }
    func candidates(_ tripID: String, reason: TripSignalReason, facilities: Set<TripSignalFacility>, location: TripSignalLocation.Point,
                    destination: IPhoneTripCourseStop?, token: String) async throws -> IPhoneTripCandidatePage { .init(basis: "route", partial: false, candidates: []) }
    func send(_ tripID: String, reason: TripSignalReason, destination: IPhoneTripSignalDestination?, token: String) async throws -> String { String(repeating: "e", count: 32) }
    func vote(_ tripID: String, signalID: String, agree: Bool, token: String) async throws -> Bool { false }
    func finish(_ tripID: String, signalID: String, cancelled: Bool, token: String) async throws { }
}

private final class RemoteStatusTestAuth: IPhoneSessionServing {
    let accountID: String
    init(accountID: String) { self.accountID = accountID }
    func restore(token: String) async throws -> AccountSession { .init(accountID: accountID, displayName: "시험 계정", expiresAt: .now.addingTimeInterval(3600), scopes: ["account:read", "trips:read", "trips:manage"]) }
    func beginLogin() async throws -> IPhoneLoginAttempt { throw IPhoneSessionError.unavailable }
    func exchange(_ attempt: IPhoneLoginAttempt, callbackURL: URL) async throws -> IPhoneSessionReceipt { throw IPhoneSessionError.unavailable }
    func cancel(_ attempt: IPhoneLoginAttempt) async throws { }
    func logout(token: String) async throws { }
}

@MainActor
private final class RemoteStatusTestCredentials: IPhoneCredentialStoring {
    var value: StoredIPhoneCredential? = .init(token: String(repeating: "S", count: 43), logoutPending: false)
    func load() throws -> StoredIPhoneCredential? { value }
    func saveToken(_ token: String) throws { value = .init(token: token, logoutPending: false) }
    func markLogoutPending() throws { value = value.map { .init(token: $0.token, logoutPending: true) } }
    func clearToken() throws { value = nil }
}
