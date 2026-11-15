import XCTest
@testable import WegoH

@MainActor
final class TripCompletedTests: XCTestCase {
    private let firstCar = String(repeating: "a", count: 32)
    private let secondCar = String(repeating: "b", count: 32)

    func testMissingCompletionFieldsRemainUnknownAndDoNotCreateASafetyScore() throws {
        let raw = #"{"packId":"fortress","title":"성곽길","version":1,"stopCount":3}"#
        let course = try JSONDecoder().decode(IPhoneTripCourse.self, from: Data(raw.utf8))
        XCTAssertTrue(course.isValid)
        XCTAssertNil(course.addedByName)
        XCTAssertNil(course.stops)
        XCTAssertNil(course.completedCarIds)
        let model = TripCompletedModel(detail: detail(courses: [course]))
        XCTAssertFalse(model.isPreview)
        XCTAssertNil(model.completedCarCount)
        XCTAssertFalse(model.allRoutesCompleted)
        XCTAssertTrue(model.routeNames.isEmpty)
    }

    func testOptionalCourseFieldsValidateStopIDsCoordinatesCountsAndCompletionIDs() throws {
        let raw = #"{"packId":"fortress","title":"성곽길","version":1,"stopCount":1,"addedByName":"사용자D","stops":[{"id":"stop-janganmun","name":"장안문","lat":37.288,"lng":127.015}],"completedCarIds":["aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"]}"#
        var course = try JSONDecoder().decode(IPhoneTripCourse.self, from: Data(raw.utf8))
        XCTAssertTrue(course.isValid)
        XCTAssertEqual(course.stops?.first?.id, "stop-janganmun")
        XCTAssertEqual(course.addedByName, "사용자D")
        course.completedCarIds = ["not-a-car"]
        XCTAssertFalse(course.isValid)
        course.completedCarIds = [firstCar, firstCar]
        XCTAssertFalse(course.isValid)
        course.completedCarIds = []
        course.stops?[0].lat = .infinity
        XCTAssertFalse(course.isValid)
        course.stops?[0].lat = 91
        XCTAssertFalse(course.isValid)
        course.stops?[0].lat = 37.288
        course.stops?[0].id = "../stop"
        XCTAssertFalse(course.isValid)
        course.stops?[0].id = "stop-janganmun"
        course.stopCount = 2
        XCTAssertFalse(course.isValid)
        course.stops = []
        XCTAssertTrue(course.isValid)
        course.stops = [IPhoneTripCourseStop(id: "same", name: "장안문", lat: 37.288, lng: 127.015),
                        IPhoneTripCourseStop(id: "same", name: "화홍문", lat: 37.287, lng: 127.017)]
        XCTAssertFalse(course.isValid)
    }

    func testCompletionCountUsesCarsThatCompletedEveryCourseAndRejectsForeignCars() {
        var first = IPhoneTripCourse(packId: "fortress", title: "성곽길", version: 1, stopCount: 1,
                                    addedByName: "사용자D", stops: [.init(id: "gate", name: "장안문", lat: 37.288, lng: 127.015)],
                                    completedCarIds: [firstCar, secondCar])
        var second = IPhoneTripCourse(packId: "village", title: "행궁동", version: 1, stopCount: 1,
                                     completedCarIds: [firstCar])
        let partial = detail(courses: [first, second])
        XCTAssertTrue(partial.isValid)
        let model = TripCompletedModel(detail: partial)
        XCTAssertEqual(model.completedCarCount, 1)
        XCTAssertFalse(model.allRoutesCompleted)
        XCTAssertEqual(model.routeNames, ["장안문"])
        second.completedCarIds = [firstCar, secondCar]
        let allVisible = TripCompletedModel(detail: detail(courses: [first, second]))
        XCTAssertEqual(allVisible.completedCarCount, 2)
        XCTAssertFalse(allVisible.allRoutesCompleted)
        second.completedCarIds = nil
        XCTAssertNil(TripCompletedModel(detail: detail(courses: [first, second])).completedCarCount)
        first.completedCarIds = []
        XCTAssertEqual(TripCompletedModel(detail: detail(courses: [first])).completedCarCount, 0)
        first.completedCarIds = [String(repeating: "c", count: 32)]
        XCTAssertFalse(detail(courses: [first]).isValid)
    }

    func testCompletedDesignSampleMatchesTheReadOnlyFivePersonTwoCarDesign() throws {
        let source = try XCTUnwrap(TripPreviewData.pastTrips.first { $0.id == "suwon" })
        let model = TripCompletedModel(preview: source)
        XCTAssertTrue(model.isPreview)
        XCTAssertEqual(model.memberCount, 5)
        XCTAssertEqual(model.carCount, 2)
        XCTAssertEqual(model.ownerName, "사용자D")
        XCTAssertEqual(model.dateLabel, "10월 24일 (토)")
        XCTAssertTrue(model.allRoutesCompleted)
        XCTAssertEqual(model.routeNames, ["장안문", "화홍문", "행궁동"])
        XCTAssertEqual(model.cars.flatMap(\.memberNames).count, model.memberCount)
        XCTAssertEqual(source.state, .completed)
    }

    private func detail(courses: [IPhoneTripCourse]) -> IPhoneTripDetail {
        let owner = "team-" + String(repeating: "a", count: 40)
        let other = "team-" + String(repeating: "b", count: 40)
        return IPhoneTripDetail(id: String(repeating: "d", count: 32), title: "실계정 완료 여행", description: "기록",
            startDate: nil, endDate: nil, state: .completed, revision: 1, isOwner: true, ownerId: owner,
            myPermissions: .init(invite: true, edit: true),
            members: [.init(id: owner, name: "방장", state: .accepted, isMe: true, isOwner: true, hasVehicle: true, carId: firstCar, readiness: .ready),
                      .init(id: other, name: "두 번째 운전자", state: .accepted, isMe: false, isOwner: false, hasVehicle: true, carId: secondCar, readiness: .ready)],
            cars: [.init(id: firstCar, name: "첫 차", seats: 3, driverId: owner, driverName: "방장", isMine: true,
                         iRide: false, driverVehicleReady: true, passengers: []),
                   .init(id: secondCar, name: "둘째 차", seats: 3, driverId: other, driverName: "두 번째 운전자", isMine: false,
                         iRide: false, driverVehicleReady: true, passengers: [])],
            unassigned: [], courses: courses, locationConsent: false)
    }
}
