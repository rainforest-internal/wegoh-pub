import XCTest
@testable import WegoH

@MainActor
final class TripRouteMapTests: XCTestCase {
    func testRepeatedPlaceKeepsBothVisitNumbersWithoutDroppingTheRouteStop() {
        let markers = [WegoMapMarker(id: "pickup", name: "출발", latitude: 37.5, longitude: 127),
                       WegoMapMarker(id: "shared-1", name: "경유", latitude: 37.51, longitude: 127),
                       WegoMapMarker(id: "shared-2", name: "목적지", latitude: 37.52, longitude: 127),
                       WegoMapMarker(id: "drop", name: "돌아오기", latitude: 37.5, longitude: 127)]
        let visible = TripRouteMap.numberedMarkers(markers)
        XCTAssertEqual(visible.map(\.sequenceLabel), ["1·4", "2", "3"])
        XCTAssertEqual(markers.count, 4)
        XCTAssertEqual(visible.map(\.id), ["pickup", "shared-1", "shared-2"])
    }

    func testLongTripSplitsIntoSupportedRequestsAndCachesRoadGeometry() async throws {
        let points = (0..<5).map { CourseCoordinate(lat: 37.5 + Double($0) * 0.001, lng: 127) }
        let cache = TripRouteGeometryCache()
        var requests: [[CourseCoordinate]] = []
        let load: ([CourseCoordinate]) async throws -> CourseRoute = { values in
            requests.append(values)
            XCTAssertTrue((2...3).contains(values.count))
            return CourseRoute(distanceMeters: 100, durationSeconds: 20, path: values)
        }
        let value = try await cache.route(for: points, load: load)
        XCTAssertEqual(requests, [Array(points[0...2]), Array(points[2...4])])
        XCTAssertEqual(value.path, points)
        XCTAssertEqual(value.distanceMeters, 200)
        XCTAssertEqual(value.durationSeconds, 40)
        _ = try await cache.route(for: points, load: load)
        XCTAssertEqual(requests.count, 2)
        let reversed = try await cache.route(for: Array(points.reversed()), load: load)
        XCTAssertEqual(reversed.path, Array(points.reversed()))
        XCTAssertEqual(requests.count, 4)
    }

    func testConsecutiveDuplicateCoordinatesDoNotMakeZeroLengthRouteRequests() async throws {
        let point = CourseCoordinate(lat: 37.5, lng: 127)
        let result = try await TripRouteGeometryCache().route(for: [point, point]) { _ in
            XCTFail("A repeated position needs no directions call")
            throw URLError(.badURL)
        }
        XCTAssertTrue(result.path.isEmpty)
    }

    func testPartialRouteFailureRetainsOnlySuccessfulLegAndRetriesTheFailedLeg() async throws {
        let points = (0..<4).map { CourseCoordinate(lat: 37.5 + Double($0) * 0.001, lng: 127) }
        let cache = TripRouteGeometryCache()
        var requests = 0
        do {
            _ = try await cache.route(for: points) { values in
                requests += 1
                if requests == 2 { throw URLError(.notConnectedToInternet) }
                return CourseRoute(distanceMeters: 1, durationSeconds: 1, path: values)
            }
            XCTFail("A failed leg must not produce a complete route")
        } catch { }
        let value = try await cache.route(for: points) { values in
            requests += 1
            return CourseRoute(distanceMeters: 1, durationSeconds: 1, path: values)
        }
        XCTAssertEqual(requests, 3)
        XCTAssertEqual(value.path, points)
    }

    func testSharedStopsAndOnlyAssignedCarsSelectedPlacesAppearInTravelOrder() {
        let course = IPhoneTripCourse(packId: "coast", title: "강릉", version: 1, stopCount: 1,
                                      stops: [.init(id: "sea", name: "안목해변", lat: 37.771, lng: 128.949)])
        let pickup = IPhoneTripCarPlace(id: "pickup1", kind: .pickup, name: "강릉역", lat: 37.764, lng: 128.900,
                                        selectedBy: ["me"], selectionCount: 1)
        var unselected = pickup
        unselected.id = "unused"
        unselected.selectedBy = []
        var anonymous = pickup
        anonymous.id = nil
        anonymous.lat = nil
        anonymous.lng = nil
        var car = IPhoneTripCar(id: "car", name: "우리 차", seats: 2, driverId: "driver", driverName: "사용자H",
                                isMine: false, iRide: true, driverVehicleReady: true, passengers: [],
                                places: [pickup, unselected, anonymous])
        var markers = TripRouteMap.markers(courses: [course], car: car)
        XCTAssertEqual(markers.map(\.name), ["강릉역", "안목해변"])
        XCTAssertEqual(markers.map(\.latitude), [37.764, 37.771])
        XCTAssertEqual(markers.map(\.longitude), [128.900, 128.949])

        car.routeOrder = [.init(type: "course", ref: "sea", courseId: "coast"), .init(type: "pickup", ref: "pickup1")]
        markers = TripRouteMap.markers(courses: [course], car: car)
        XCTAssertEqual(markers.map(\.name), ["안목해변", "강릉역"])

        car.iRide = false
        XCTAssertEqual(TripRouteMap.markers(courses: [course], car: car).map(\.name), ["안목해변"])
        var summary = course
        summary.stops = nil
        XCTAssertTrue(TripRouteMap.markers(courses: [summary], car: nil).isEmpty)
    }

    func testOtherCarMarkersSkipMyCarAndUnknownCarsAndMarkLatePositions() throws {
        let me = String(repeating: "1", count: 32), friend = String(repeating: "2", count: 32), third = String(repeating: "3", count: 32)
        let mine = IPhoneTripCar(id: String(repeating: "a", count: 32), name: "내 차", seats: 2, driverId: me, driverName: "나",
            isMine: true, iRide: false, driverVehicleReady: true, passengers: [], ordinal: 1)
        let other = IPhoneTripCar(id: String(repeating: "b", count: 32), name: "우리 차", seats: 2, driverId: friend, driverName: "친구",
            isMine: false, iRide: false, driverVehicleReady: true, passengers: [], ordinal: 2)
        let late = IPhoneTripCar(id: String(repeating: "c", count: 32), name: "캠핑카", seats: 2, driverId: third, driverName: "셋째",
            isMine: false, iRide: false, driverVehicleReady: false, passengers: [], ordinal: 3)
        let detail = IPhoneTripDetail(id: String(repeating: "d", count: 32), title: "여행", description: "",
            startDate: nil, endDate: nil, state: .active, revision: 1, isOwner: true, ownerId: me,
            myPermissions: .init(invite: true, edit: true), members: [], cars: [mine, other, late], unassigned: [],
            courses: [], locationConsent: true)
        func row(_ id: String, _ captured: String) -> [String: Any] {
            ["carId": id, "source": "vehicle", "latitude": 37.5, "longitude": 127.0, "accuracyMeters": NSNull(), "capturedAt": captured]
        }
        let json: [String: Any] = ["tripId": detail.id, "serverNow": "2026-11-13T01:01:00Z", "shareId": NSNull(), "locations": [],
            "cars": [row(mine.id, "2026-11-13T01:01:00Z"), row(other.id, "2026-11-13T01:00:55Z"),
                     row(late.id, "2026-11-13T01:00:20Z"), row(String(repeating: "e", count: 32), "2026-11-13T01:01:00Z")]]
        let page = try JSONDecoder().decode(IPhoneTripLocations.self, from: JSONSerialization.data(withJSONObject: json))
        let markers = TripRouteMap.otherCarMarkers(detail: detail, page: page)
        XCTAssertEqual(markers.map(\.name), ["2호차", "3호차 · 이전 위치"])
        XCTAssertTrue(markers.allSatisfy(\.isVehicle))
        XCTAssertEqual(markers.map(\.id), ["car:" + other.id, "car:" + late.id])
        var foreign = page; foreign.tripId = String(repeating: "f", count: 32)
        XCTAssertTrue(TripRouteMap.otherCarMarkers(detail: detail, page: foreign).isEmpty)
        XCTAssertTrue(TripRouteMap.otherCarMarkers(detail: detail, page: nil).isEmpty)
    }
}
