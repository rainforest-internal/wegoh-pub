import XCTest
@testable import WegoH

@MainActor
final class TripCourseRoutePresentationTests: XCTestCase {
    private let carID = String(repeating: "a", count: 32)
    private var course: IPhoneTripCourse {
        .init(packId: "coast", title: "공유 코스", version: 1, stopCount: 3,
              stops: ["join", "beach", "port"].map { .init(id: $0, name: $0, lat: 37.5, lng: 127) })
    }

    func testSingleJoinStartsTheSharedCourseWithoutMarkingItComplete() {
        var single = course
        single.stops = Array(course.stops!.prefix(1))
        single.stopCount = 1
        var own = car(phase: .shared, next: "join")
        own.routePlan!.segments[1].items = [.init(type: "course", ref: "join", courseId: "coast")]
        let value = TripCourseRoutePresentation(course: single, car: own)
        XCTAssertTrue(own.routePlan!.awaitingJoinCourseCompletion)
        XCTAssertTrue(value.isCurrent)
        XCTAssertFalse(value.isComplete)
        XCTAssertEqual(value.stopStates, [.arrived])
        XCTAssertNil(value.progress)
        let signal = IPhoneTripRouteItem(type: "signal", ref: String(repeating: "d", count: 32))
        own.routePlan!.segments[1].items.insert(signal, at: 0)
        own.routePlan!.next = signal
        XCTAssertFalse(own.routePlan!.awaitingJoinCourseCompletion)
        XCTAssertFalse(TripCourseRoutePresentation(course: single, car: own).isComplete)
        own.routePlan!.phase = .done
        own.routePlan!.next = nil
        XCTAssertTrue(TripCourseRoutePresentation(course: single, car: own).isComplete)
    }

    func testSharedProgressUsesServerNextForArrivedNextAndPlanned() {
        let value = TripCourseRoutePresentation(course: course, car: car(phase: .shared, next: "beach"))
        XCTAssertTrue(value.isCurrent)
        XCTAssertFalse(value.isComplete)
        XCTAssertEqual(value.stopStates, [.arrived, .next, .planned])
        XCTAssertEqual(value.progress ?? -1, 1.0 / 3, accuracy: 0.001)
    }

    func testPickupDoesNotFabricateAnySharedArrivalOrProgress() {
        let value = TripCourseRoutePresentation(course: course, car: car(phase: .pickup, next: "join"))
        XCTAssertFalse(value.isCurrent)
        XCTAssertFalse(value.isComplete)
        XCTAssertEqual(value.stopStates, [.planned, .planned, .planned])
        XCTAssertEqual(value.progress, 0)
    }

    func testWaitingOnlyMarksServerConfirmedJoinArrival() {
        let value = TripCourseRoutePresentation(course: course, car: car(phase: .waiting, next: "beach"))
        XCTAssertFalse(value.isCurrent)
        XCTAssertEqual(value.stopStates, [.arrived, .planned, .planned])
    }

    func testDropAndDoneShowSharedStopsCompleteWithoutMarkingCurrent() {
        for phase in [IPhoneTripRoutePhase.drop, .done] {
            let value = TripCourseRoutePresentation(course: course, car: car(phase: phase, next: nil))
            XCTAssertTrue(value.isComplete)
            XCTAssertFalse(value.isCurrent)
            XCTAssertEqual(value.stopStates, [.arrived, .arrived, .arrived])
            XCTAssertEqual(value.progress, 1)
        }
    }

    func testMissingCarOrMissingStopsDoesNotInventPlaceNamesOrCurrentCourse() {
        let value = TripCourseRoutePresentation(course: course, car: nil)
        XCTAssertFalse(value.isCurrent)
        XCTAssertEqual(value.stopStates, [.planned, .planned, .planned])
        var missing = course
        missing.stops = nil
        let unknown = TripCourseRoutePresentation(course: missing, car: car(phase: .shared, next: "beach"))
        XCTAssertTrue(unknown.stopStates.isEmpty)
        XCTAssertNil(unknown.progress)
        XCTAssertFalse(unknown.isComplete)
    }

    private func car(phase: IPhoneTripRoutePhase, next: String?) -> IPhoneTripCar {
        let items = ["join", "beach", "port"].map { IPhoneTripRouteItem(type: "course", ref: $0, courseId: "coast") }
        return .init(id: carID, name: "내 차", seats: 1, driverId: "team-" + String(repeating: "1", count: 40),
                     driverName: "사용자F", isMine: true, iRide: false, driverVehicleReady: true, passengers: [],
                     routePlan: .init(contractVersion: 2, phase: phase,
                        segments: [.init(segment: "pickup", items: []), .init(segment: "shared", items: items), .init(segment: "drop", items: [])],
                        joinPoint: .init(courseId: "coast", ref: "join", name: "join", lat: 37.5, lng: 127),
                        joinEtaSeconds: nil, progressRevision: 3, next: next.map { .init(type: "course", ref: $0, courseId: "coast") },
                        joinBarrier: .init(arrivedCarIds: [carID], totalCarCount: 2, released: phase != .waiting)))
    }
}
