import Foundation
import XCTest
@testable import WegoH

final class TripRoutePlanTests: XCTestCase {
    private let carID = String(repeating: "a", count: 32)
    private let placeID = String(repeating: "b", count: 32)

    private func plan() -> IPhoneTripRoutePlan {
        .init(contractVersion: 2, phase: .waiting,
              segments: [.init(segment: "pickup", items: [.init(type: "pickup", ref: placeID)]),
                         .init(segment: "shared", items: [.init(type: "course", ref: "join", courseId: "coast")]),
                         .init(segment: "drop", items: [])],
              joinPoint: .init(courseId: "coast", ref: "join", name: "합류", lat: 37.5, lng: 127),
              joinEtaSeconds: nil, progressRevision: 3, next: .init(type: "course", ref: "join", courseId: "coast"),
              joinBarrier: .init(arrivedCarIds: [carID], totalCarCount: 2, released: false))
    }

    func testLiveProgressDecodesAndRejectsOutOfRangeValues() throws {
        var value = plan()
        value.progress = .init(remainingMeters: 830, legFraction: 0.25)
        let decoded = try JSONDecoder().decode(IPhoneTripRoutePlan.self, from: JSONEncoder().encode(value))
        XCTAssertEqual(decoded.progress, .init(remainingMeters: 830, legFraction: 0.25))
        XCTAssertTrue(decoded.isValid)
        var json = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(plan())) as? [String: Any])
        json["progress"] = NSNull()
        XCTAssertNil(try JSONDecoder().decode(IPhoneTripRoutePlan.self, from: JSONSerialization.data(withJSONObject: json)).progress)
        for bad in [IPhoneTripPlanProgress(remainingMeters: -1, legFraction: nil), .init(remainingMeters: 10, legFraction: 1.5),
                    .init(remainingMeters: 10, legFraction: .nan)] {
            value.progress = bad
            XCTAssertFalse(value.isValid)
        }
        value.progress = .init(remainingMeters: 10, legFraction: nil)
        value.next = nil
        XCTAssertFalse(value.isValid)
        let target = IPhoneTripRouteItem(type: "course", ref: "beach", courseId: "coast")
        XCTAssertTrue(IPhoneTripRouteStatus(phase: .shared, joinEtaSeconds: nil,
                                            progress: .init(target: target, remainingMeters: 1200, legFraction: 0.4)).isValid)
        XCTAssertFalse(IPhoneTripRouteStatus(phase: .drop, joinEtaSeconds: nil,
                                             progress: .init(target: target, remainingMeters: 1200, legFraction: 0.4)).isValid)
        XCTAssertFalse(IPhoneTripRouteStatus(phase: .pickup, joinEtaSeconds: nil,
                                             progress: .init(target: .init(type: "pickup", ref: placeID), remainingMeters: 1200, legFraction: nil)).isValid)
    }

    func testLiveProgressPresentationPlacesMarkersAndRoundsDistances() {
        let stops = [RouteStop(id: "course:coast:join", title: "합류", state: .arrived),
                     RouteStop(id: "signal::" + placeID, title: "휴게소", state: .arrived),
                     RouteStop(id: "course:coast:beach", title: "해변", state: .next)]
        XCTAssertEqual(TripLiveProgressPresentation.position(stops: stops, progress: .init(remainingMeters: 500, legFraction: 0.5)), 1.5)
        XCTAssertNil(TripLiveProgressPresentation.position(stops: stops, progress: .init(remainingMeters: 500, legFraction: nil)))
        XCTAssertEqual(TripLiveProgressPresentation.ownDistance(1234), "직선 약 1.2km")
        XCTAssertEqual(TripLiveProgressPresentation.ownDistance(330), "직선 약 350m")
        XCTAssertEqual(TripLiveProgressPresentation.approximateDistance(3200), "직선 약 3km")
        XCTAssertEqual(TripLiveProgressPresentation.approximateDistance(1400), "직선 약 1.5km")
        XCTAssertEqual(TripLiveProgressPresentation.approximateDistance(600), "직선 1km 이내")
        let target = IPhoneTripRouteItem(type: "course", ref: "beach", courseId: "coast")
        XCTAssertEqual(TripLiveProgressPresentation.companionSummary(.init(phase: .pickup, joinEtaSeconds: nil,
            progress: .init(target: target, remainingMeters: 3200, legFraction: nil))), "합류 지점까지 직선 약 3km")
        XCTAssertEqual(TripLiveProgressPresentation.companionSummary(.init(phase: .shared, joinEtaSeconds: nil)), "경로 주행 중")
        XCTAssertEqual(TripLiveProgressPresentation.companionSummary(.init(phase: .waiting, joinEtaSeconds: nil)), "합류 지점 도착")
    }

    func testSignalWaypointsAreValidInPickupAndDropSegments() {
        for index in [0, 2] {
            var value = plan()
            let signal = IPhoneTripRouteItem(type: "signal", ref: String(repeating: "d", count: 32))
            value.segments[index].items.append(signal)
            value.next = signal
            XCTAssertTrue(value.isValid)
        }
    }

    func testAllFiveServerPhasesRoundTripWithoutInferringFromNextOrBarrier() throws {
        for phase in IPhoneTripRoutePhase.allCases {
            var value = plan()
            value.phase = phase
            let decoded = try JSONDecoder().decode(IPhoneTripRoutePlan.self, from: JSONEncoder().encode(value))
            XCTAssertEqual(decoded.phase, phase)
            XCTAssertTrue(decoded.isValid)
            XCTAssertNil(decoded.joinEtaSeconds)
        }
    }

    func testPlanRejectsBadVersionBoundsOrderUnknownItemsAndInvalidETA() throws {
        let valid = plan()
        var malformed: [IPhoneTripRoutePlan] = []
        var value = valid; value.contractVersion = 3; malformed.append(value)
        value = valid; value.progressRevision = -1; malformed.append(value)
        value = valid; value.progressRevision = Int(Int32.max) + 1; malformed.append(value)
        value = valid; value.joinEtaSeconds = -1; malformed.append(value)
        value = valid; value.joinEtaSeconds = Int(Int32.max) + 1; malformed.append(value)
        value = valid; value.segments.swapAt(0, 2); malformed.append(value)
        value = valid; value.segments[0].items[0].type = "course"; malformed.append(value)
        value = valid; value.segments[0].items.append(value.segments[0].items[0]); malformed.append(value)
        value = valid; value.next = .init(type: "signal", ref: String(repeating: "c", count: 32)); malformed.append(value)
        value = valid; value.joinBarrier.arrivedCarIds.append(carID); malformed.append(value)
        value = valid; value.joinBarrier.totalCarCount = 0; malformed.append(value)
        value = valid; value.joinPoint.lat = 91; malformed.append(value)
        value = valid; value.segments[1].items[0].courseId = nil; malformed.append(value)
        for bad in malformed { XCTAssertFalse(bad.isValid) }
        var json = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(valid)) as? [String: Any])
        json["progressRevision"] = true
        XCTAssertThrowsError(try JSONDecoder().decode(IPhoneTripRoutePlan.self, from: JSONSerialization.data(withJSONObject: json)))
        json["progressRevision"] = 0
        json["phase"] = "inferred"
        XCTAssertThrowsError(try JSONDecoder().decode(IPhoneTripRoutePlan.self, from: JSONSerialization.data(withJSONObject: json)))
    }

    func testServerJoinETAAcceptsUnknownZeroAndPositiveSeconds() throws {
        for eta in [nil, 0, 720, Int(Int32.max)] as [Int?] {
            var value = plan()
            value.joinEtaSeconds = eta
            let decoded = try JSONDecoder().decode(IPhoneTripRoutePlan.self, from: JSONEncoder().encode(value))
            XCTAssertTrue(decoded.isValid)
            XCTAssertEqual(decoded.joinEtaSeconds, eta)
            let status = IPhoneTripRouteStatus(phase: .pickup, joinEtaSeconds: eta)
            let decodedStatus = try JSONDecoder().decode(IPhoneTripRouteStatus.self, from: JSONEncoder().encode(status))
            XCTAssertTrue(decodedStatus.isValid)
            XCTAssertEqual(decodedStatus.joinEtaSeconds, eta)
        }
    }

    func testServerJoinETARejectsNegativeOverflowAndNonIntegerJSON() throws {
        for eta in [-1, Int(Int32.max) + 1] {
            XCTAssertFalse(IPhoneTripRouteStatus(phase: .waiting, joinEtaSeconds: eta).isValid)
        }
        for invalid in [true, "720", 1.5] as [Any] {
            let status: [String: Any] = ["phase": "pickup", "joinEtaSeconds": invalid]
            XCTAssertThrowsError(try JSONDecoder().decode(IPhoneTripRouteStatus.self, from: JSONSerialization.data(withJSONObject: status)))
            var route = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(plan())) as? [String: Any])
            route["joinEtaSeconds"] = invalid
            XCTAssertThrowsError(try JSONDecoder().decode(IPhoneTripRoutePlan.self, from: JSONSerialization.data(withJSONObject: route)))
        }
    }

    func testTripDetailWithServerJoinETAStillDecodesAndValidates() throws {
        let owner = "team-" + String(repeating: "1", count: 40)
        var route = plan()
        route.segments[0].items = []
        route.joinEtaSeconds = 720
        route.joinBarrier.totalCarCount = 1
        let car = IPhoneTripCar(id: carID, name: "내 차", seats: 1, driverId: owner, driverName: "사용자F",
            isMine: true, iRide: false, driverVehicleReady: true, passengers: [], routePlan: route,
            routeStatus: .init(phase: .waiting, joinEtaSeconds: 720))
        let detail = IPhoneTripDetail(id: String(repeating: "c", count: 32), title: "합류 여행", description: "",
            startDate: nil, endDate: nil, state: .active, revision: 1, isOwner: true, ownerId: owner,
            myPermissions: .init(invite: true, edit: true),
            members: [.init(id: owner, name: "사용자F", state: .accepted, isMe: true, isOwner: true, hasVehicle: true, carId: carID, readiness: .ready)],
            cars: [car], unassigned: [],
            courses: [.init(packId: "coast", title: "공유 코스", version: 1, stopCount: 1,
                stops: [.init(id: "join", name: "합류", lat: 37.5, lng: 127)])],
            locationConsent: false, routeContractVersion: 2)
        let decoded = try JSONDecoder().decode(IPhoneTripDetail.self, from: JSONEncoder().encode(detail))
        XCTAssertTrue(decoded.isValid)
        XCTAssertEqual(decoded.myCar?.routePlan?.joinEtaSeconds, 720)
        XCTAssertEqual(decoded.myCar?.routeStatus?.joinEtaSeconds, 720)
        for phase in IPhoneTripRoutePhase.allCases {
            var current = decoded
            current.cars[0].routePlan?.phase = phase
            XCTAssertEqual(current.canUseTripSignals, phase != .done)
            current.state = .completed
            XCTAssertFalse(current.canUseTripSignals)
        }
    }

    func testSelectionDraftRequiresExplicitNullsAndValidAtomicChoices() throws {
        let draft = IPhoneTripMyPlacesDraft(revision: 2, pickup: .existing(placeID), drop: nil, dropAtPickup: true)
        XCTAssertTrue(draft.isValid)
        let body = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(draft)) as? [String: Any])
        XCTAssertEqual(Set(body.keys), ["revision", "pickup", "drop", "dropAtPickup"])
        XCTAssertTrue(body["drop"] is NSNull)
        XCTAssertEqual((body["pickup"] as? [String: String])?["placeId"], placeID)
        var bad = draft; bad.pickup = nil; XCTAssertFalse(bad.isValid)
        bad = draft; bad.drop = .existing(placeID); XCTAssertFalse(bad.isValid)
        bad = draft; bad.revision = 0; XCTAssertFalse(bad.isValid)
        bad = draft; bad.pickup = .new(name: "위치", lat: .nan, lng: 127); XCTAssertFalse(bad.isValid)
        bad = draft; bad.pickup = .new(name: String(repeating: "가", count: 41), lat: 37, lng: 127); XCTAssertFalse(bad.isValid)
        XCTAssertTrue(IPhoneTripRouteStatus(phase: .pickup, joinEtaSeconds: 60).isValid)
    }

    func testFullRouteUsesDriverOrderAndKeepsSignalWithFollowingCourse() {
        let owner = "team-" + String(repeating: "1", count: 40)
        let dropID = String(repeating: "c", count: 32)
        let signalID = String(repeating: "d", count: 32)
        var route = plan()
        route.phase = .shared
        let signal = IPhoneTripRouteItem(type: "signal", ref: signalID)
        route.next = signal
        route.segments[1].items += [signal, .init(type: "course", ref: "end", courseId: "forest")]
        route.segments[2].items = [.init(type: "drop", ref: dropID)]
        let car = IPhoneTripCar(id: carID, name: "내 차", seats: 1, driverId: owner, driverName: "사용자F",
            isMine: true, iRide: false, driverVehicleReady: true, passengers: [],
            places: [.init(id: dropID, kind: .drop, name: "내릴 곳", selectionCount: 1),
                     .init(id: signalID, kind: .signal, name: "쉼터", selectionCount: 0),
                     .init(id: placeID, kind: .pickup, name: "탈 곳", selectionCount: 1)], routePlan: route)
        let detail = IPhoneTripDetail(id: dropID, title: "여행", description: "", startDate: nil, endDate: nil,
            state: .active, revision: 1, isOwner: true, ownerId: owner, myPermissions: .init(invite: true, edit: true),
            members: [], cars: [car], unassigned: [],
            courses: [.init(packId: "coast", title: "바다", version: 1, stopCount: 1,
                            stops: [.init(id: "join", name: "합류", lat: 37.5, lng: 127)]),
                      .init(packId: "forest", title: "숲", version: 1, stopCount: 1,
                            stops: [.init(id: "end", name: "산책길", lat: 37.6, lng: 127)])], locationConsent: false)
        let sections = TripFullRouteSection.sections(detail: detail)
        XCTAssertEqual(sections.map(\.title), ["타는 곳", "경로 1", "경로 2", "내리는 곳"])
        XCTAssertEqual(sections.map { $0.stops.map(\.title) }, [["탈 곳"], ["합류"], ["쉼터", "산책길"], ["내릴 곳"]])
        XCTAssertEqual(sections.filter(\.isCurrent).map(\.title), ["경로 2"])
        XCTAssertEqual(sections[2].stops.map(\.state), [.next, .planned])
        XCTAssertEqual(sections[0].stops.first?.state, .arrived)
        var empty = detail
        empty.cars[0].routePlan?.segments[0].items = []
        empty.cars[0].routePlan?.segments[2].items = []
        XCTAssertTrue(TripFullRouteSection.sections(detail: empty)[0].stops.isEmpty)
        XCTAssertTrue(TripFullRouteSection.sections(detail: empty)[3].stops.isEmpty)
        var pickup = detail
        pickup.cars[0].routePlan?.phase = .pickup
        pickup.cars[0].routePlan?.next = .init(type: "pickup", ref: placeID)
        let pickupSections = TripFullRouteSection.sections(detail: pickup)
        XCTAssertEqual(pickupSections[0].stops.map(\.title), ["탈 곳", "합류"])
        XCTAssertEqual(pickupSections[0].stops.map(\.state), [.next, .planned])
        XCTAssertTrue(pickupSections[0].isCurrent)
        pickup.cars[0].routePlan?.phase = .waiting
        XCTAssertEqual(TripFullRouteSection.sections(detail: pickup)[0].stops.last?.state, .arrived)
    }
}
