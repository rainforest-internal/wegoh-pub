import Foundation
import XCTest
@testable import WegoH

private final class DrivingVersusHTTPStub: URLProtocol {
    static var respond: ((URLRequest) throws -> (Int, [String: Any]))?
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        do {
            let (status, object) = try XCTUnwrap(Self.respond)(request)
            let response = try XCTUnwrap(HTTPURLResponse(url: XCTUnwrap(request.url), statusCode: status,
                httpVersion: "HTTP/1.1", headerFields: ["Content-Type": "application/json", "Cache-Control": "private, no-store"]))
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: try JSONSerialization.data(withJSONObject: object))
            client?.urlProtocolDidFinishLoading(self)
        } catch { client?.urlProtocol(self, didFailWithError: error) }
    }
    override func stopLoading() {}
}

final class TripDrivingVersusTests: XCTestCase {
    private let tripID = String(repeating: "a", count: 32)
    private let firstCar = String(repeating: "b", count: 32)
    private let secondCar = String(repeating: "c", count: 32)
    private let token = String(repeating: "T", count: 43)

    override func tearDown() {
        DrivingVersusHTTPStub.respond = nil
        super.tearDown()
    }
    private func api() -> IPhoneTripDrivingVersusAPI {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [DrivingVersusHTTPStub.self]
        return IPhoneTripDrivingVersusAPI(configuration: configuration)
    }
    private func course(state: String = "pending", score: Int? = nil) -> [String: Any] {
        ["packId": "coast", "version": 1, "state": state, "score": score as Any? ?? NSNull()]
    }
    private func car(_ id: String, state: String = "pending", average: Double? = nil,
                     count: Int = 0, courses: [[String: Any]]? = nil) -> [String: Any] {
        ["carId": id, "name": id == firstCar ? "1호차" : "2호차", "participating": true,
         "state": state, "averageScore": average as Any? ?? NSNull(), "measuredCourseCount": count,
         "courses": courses ?? [course()]]
    }
    private func payload(state: String = "pending", reason: String? = "final-reports-pending",
                         cars: [[String: Any]]? = nil, winners: [String] = [], tied: Bool = false) -> [String: Any] {
        ["kind": "safe-driving-versus", "automatic": true, "state": state,
         "reason": reason as Any? ?? NSNull(), "cars": cars ?? [car(firstCar), car(secondCar)],
         "winnerCarIds": winners, "tied": tied]
    }
    private func decode(_ object: [String: Any]) throws -> IPhoneTripDrivingVersus {
        try JSONDecoder().decode(IPhoneTripDrivingVersus.self, from: JSONSerialization.data(withJSONObject: object))
    }
    private func finalCars() -> [[String: Any]] {
        [car(firstCar, state: "ready", average: 90, count: 1, courses: [course(state: "final", score: 90)]),
         car(secondCar, state: "ready", average: 95, count: 1, courses: [course(state: "final", score: 95)])]
    }

    func testComparisonUsesMyCarAsLeftScoreAndStrongestOtherCar() throws {
        let third = String(repeating: "d", count: 32)
        var rows = [car(firstCar, state: "ready", courses: []), car(secondCar, state: "ready", courses: []), car(third, state: "ready", courses: [])]
        for index in rows.indices { rows[index]["totalScore"] = [80, 90, 95][index]; rows[index]["final"] = false }
        var object = payload(cars: rows); object["scope"] = "trip"
        let summary = TripScoreComparison(value: try decode(object), ownCarID: secondCar,
                                          carNames: [third: "3호차 · 일행의 차"])
        XCTAssertEqual(summary.scores, "90 : 95")
        XCTAssertEqual(summary.subtitle, "여행 전체 · 3호차가 5점 앞서요")
    }

    func testComparisonKeepsMissingAndLegacyScoresPending() throws {
        var rows = [car(firstCar, state: "ready", courses: []), car(secondCar, courses: [])]
        rows[0]["totalScore"] = 100; rows[0]["final"] = false; rows[1]["final"] = false
        var object = payload(cars: rows); object["scope"] = "trip"
        let missing = TripScoreComparison(value: try decode(object), ownCarID: firstCar, carNames: [:])
        XCTAssertNil(missing.scores)
        XCTAssertEqual(missing.subtitle, "여행 전체 · 집계 중")
        let legacy = TripScoreComparison(value: try decode(payload(cars: finalCars())), ownCarID: firstCar, carNames: [:])
        XCTAssertNil(legacy.scores)
    }

    func testComparisonShowsTieWithoutInventingWinner() throws {
        var rows = [car(firstCar, state: "ready", courses: []), car(secondCar, state: "ready", courses: [])]
        for index in rows.indices { rows[index]["totalScore"] = 95; rows[index]["final"] = false }
        var object = payload(cars: rows); object["scope"] = "trip"
        let summary = TripScoreComparison(value: try decode(object), ownCarID: firstCar, carNames: [:])
        XCTAssertEqual(summary.scores, "95 : 95")
        XCTAssertEqual(summary.subtitle, "여행 전체 · 같은 점수예요")
    }

    func testTripTotalDoesNotExposeLegacyCourseAverageAndValidatesWinners() throws {
        var rows = [car(firstCar, state: "ready", courses: []), car(secondCar, state: "ready", courses: [])]
        for index in rows.indices { rows[index]["totalScore"] = index == 0 ? 85 : 95; rows[index]["final"] = true }
        var object = payload(state: "final", reason: nil, cars: rows, winners: [secondCar])
        object["scope"] = "trip"
        let total = try decode(object)
        XCTAssertTrue(total.isValid)
        XCTAssertEqual(total.cars.map(\.totalScore), [85, 95])
        XCTAssertTrue(total.cars.allSatisfy { $0.averageScore == nil && $0.courses.isEmpty })
        rows[1]["totalScore"] = 101
        object["cars"] = rows
        XCTAssertFalse(try decode(object).isValid)
    }

    func testAutomaticPendingNeverInventsMissingScoresOrWinners() throws {
        let value = try decode(payload())
        XCTAssertTrue(value.isValid)
        XCTAssertTrue(value.automatic)
        XCTAssertEqual(value.state, "pending")
        XCTAssertEqual(value.reason, "final-reports-pending")
        XCTAssertTrue(value.winnerCarIds.isEmpty)
        XCTAssertFalse(value.tied)
        XCTAssertTrue(value.cars.allSatisfy { $0.averageScore == nil && $0.measuredCourseCount == 0 })
        XCTAssertTrue(value.cars.flatMap(\.courses).allSatisfy { $0.state == "pending" && $0.score == nil })
        var manual = payload()
        manual["automatic"] = false
        XCTAssertFalse(try decode(manual).isValid)
    }

    func testFinalUsesServerWinnerAndPreservesServerTieOrder() throws {
        let final = try decode(payload(state: "final", reason: nil, cars: finalCars(), winners: [secondCar]))
        XCTAssertTrue(final.isValid)
        XCTAssertEqual(final.winnerCarIds, [secondCar])
        XCTAssertFalse(final.tied)
        let tiedCars = [firstCar, secondCar].map {
            car($0, state: "ready", average: 90, count: 1, courses: [course(state: "final", score: 90)])
        }
        let tie = try decode(payload(state: "final", reason: nil, cars: tiedCars,
                                     winners: [secondCar, firstCar], tied: true))
        XCTAssertTrue(tie.isValid)
        XCTAssertEqual(tie.winnerCarIds, [secondCar, firstCar])
        XCTAssertTrue(tie.tied)
    }

    func testUnmeasurableCourseRemainsNullAndHasNoFallbackWin() throws {
        let value = try decode(payload(state: "unavailable", reason: "insufficient-measurements", cars: [
            car(firstCar, state: "unavailable", courses: [course(state: "unavailable")]),
            car(secondCar, state: "ready", average: 95, count: 1, courses: [course(state: "final", score: 95)])
        ]))
        XCTAssertTrue(value.isValid)
        XCTAssertNil(value.cars[0].averageScore)
        XCTAssertEqual(value.cars[0].measuredCourseCount, 0)
        XCTAssertEqual(value.cars[0].courses[0].state, "unavailable")
        XCTAssertNil(value.cars[0].courses[0].score)
        XCTAssertTrue(value.winnerCarIds.isEmpty)
        XCTAssertFalse(value.tied)
    }

    func testSharingUnavailableHidesRestrictedScoresAndAllWinners() throws {
        let hidden = car(firstCar, state: "sharing-unavailable", courses: [course(state: "sharing-unavailable")])
        let object = payload(state: "unavailable", reason: "sharing-unavailable", cars: [hidden, finalCars()[1]])
        let value = try decode(object)
        XCTAssertTrue(value.isValid)
        XCTAssertNil(value.cars[0].averageScore)
        XCTAssertNil(value.cars[0].courses[0].score)
        XCTAssertTrue(value.winnerCarIds.isEmpty)
        XCTAssertFalse(value.tied)
        var leakedAverage = hidden
        leakedAverage["averageScore"] = 95
        XCTAssertFalse(try decode(payload(state: "unavailable", reason: "sharing-unavailable",
                                          cars: [leakedAverage, finalCars()[1]])).isValid)
        var leakedCourse = hidden
        leakedCourse["courses"] = [course(state: "sharing-unavailable", score: 95)]
        XCTAssertFalse(try decode(payload(state: "unavailable", reason: "sharing-unavailable",
                                          cars: [leakedCourse, finalCars()[1]])).isValid)
    }

    @MainActor
    func testUnavailableReasonMessagesKeepKnownAndFutureReasonsPrivate() throws {
        for (reason, message, stateTitle) in [
            ("course-unavailable", "공유 경로를 현재 확인할 수 없어 점수와 결과를 숨겼어요. 경로 공개 상태를 확인해 주세요.", "경로 공개 확인 필요"),
            ("report-authorization-changed", "점수를 보고한 뒤 공유 상태가 바뀌어 결과를 숨겼어요. 차량에서 공유 설정과 최종 보고를 확인해 주세요.", "최종 보고 확인 필요"),
            ("sharing-unavailable", "공유가 확인되지 않은 점수와 최종 결과를 숨겼어요.", "공유 확인 필요"),
            ("future-reason", "비교할 수 있는 측정 결과가 충분하지 않거나 여행이 일찍 종료됐어요.", "공유 확인 필요")
        ] {
            let hidden = car(firstCar, state: "sharing-unavailable", courses: [course(state: "sharing-unavailable")])
            let value = try decode(payload(state: "unavailable", reason: reason, cars: [hidden]))
            XCTAssertTrue(value.isValid)
            XCTAssertTrue(value.winnerCarIds.isEmpty)
            XCTAssertNil(value.cars.first?.averageScore)
            let card = TripDrivingVersusCard(value: value)
            XCTAssertEqual(card.unavailableReason, message)
            XCTAssertEqual(card.stateTitle("sharing-unavailable"), stateTitle)
            XCTAssertEqual(card.stateTitle("unavailable"), "측정 불가")
            XCTAssertEqual(card.stateTitle("future-state"), "집계 중")
        }
    }

    func testMixedCourseSharingKeepsAuthorizedFinalScoreAndHidesCarAverageAndResult() throws {
        var restricted = course(state: "sharing-unavailable")
        restricted["packId"] = "forest"
        let mixed = car(firstCar, state: "sharing-unavailable", count: 1,
                        courses: [course(state: "final", score: 90), restricted])
        let value = try decode(payload(state: "unavailable", reason: "sharing-unavailable",
                                       cars: [mixed, finalCars()[1]]))
        XCTAssertTrue(value.isValid)
        XCTAssertNil(value.cars[0].averageScore)
        XCTAssertEqual(value.cars[0].measuredCourseCount, 1)
        XCTAssertEqual(value.cars[0].courses[0].score, 90)
        XCTAssertNil(value.cars[0].courses[1].score)
        XCTAssertTrue(value.winnerCarIds.isEmpty)
        XCTAssertFalse(value.tied)
    }

    func testFinalCourseNeedsScoreAndFinalWinnerNeedsReadyMeasuredCar() throws {
        let missingScore = car(firstCar, state: "ready", average: 90, count: 1, courses: [course(state: "final")])
        XCTAssertFalse(try decode(payload(cars: [missingScore, finalCars()[1]])).isValid)
        for state in ["pending", "withdrawn", "sharing-unavailable", "unavailable"] {
            let notReady = car(firstCar, state: state)
            XCTAssertFalse(try decode(payload(state: "final", reason: nil, cars: [notReady, finalCars()[1]],
                                              winners: [firstCar])).isValid)
        }
        let missingAverage = car(firstCar, state: "ready", count: 1, courses: [course(state: "final", score: 90)])
        XCTAssertFalse(try decode(payload(state: "final", reason: nil, cars: [missingAverage, finalCars()[1]],
                                          winners: [firstCar])).isValid)
    }

    func testNonfinalWinnersUnknownWinnersAndContradictoryTieAreRejected() throws {
        for state in ["pending", "unavailable"] {
            XCTAssertFalse(try decode(payload(state: state, winners: [firstCar])).isValid)
            XCTAssertFalse(try decode(payload(state: state, tied: true)).isValid)
        }
        for winners in [[String(repeating: "d", count: 32)], [firstCar, firstCar]] {
            XCTAssertFalse(try decode(payload(state: "final", reason: nil, cars: finalCars(), winners: winners)).isValid)
        }
        XCTAssertFalse(try decode(payload(state: "final", reason: nil, cars: finalCars(),
                                          winners: [firstCar], tied: true)).isValid)
        XCTAssertFalse(try decode(payload(state: "final", reason: nil, cars: finalCars(),
                                          winners: [firstCar, secondCar], tied: false)).isValid)
    }

    func testInvalidScoresAndPendingCourseScoresAreRejected() throws {
        for score in [-1, 101] {
            let invalid = car(firstCar, state: "ready", average: 90, count: 1, courses: [course(state: "final", score: score)])
            XCTAssertFalse(try decode(payload(cars: [invalid, finalCars()[1]])).isValid)
        }
        for average in [-0.1, 100.1] {
            let invalid = car(firstCar, state: "ready", average: average, count: 1, courses: [course(state: "final", score: 90)])
            XCTAssertFalse(try decode(payload(cars: [invalid, finalCars()[1]])).isValid)
        }
        let pendingScore = car(firstCar, courses: [course(state: "pending", score: 100)])
        XCTAssertFalse(try decode(payload(cars: [pendingScore, car(secondCar)])).isValid)
        let inventedAverage = car(firstCar, average: 100)
        XCTAssertFalse(try decode(payload(cars: [inventedAverage, car(secondCar)])).isValid)
        let mismatchedCount = car(firstCar, state: "ready", average: 90,
                                  courses: [course(state: "final", score: 90)])
        XCTAssertFalse(try decode(payload(cars: [mismatchedCount, finalCars()[1]])).isValid)
    }

    @MainActor
    func testLeavingCarImmediatelyHidesCachedComparisonForSameAccount() async throws {
        let preview = try XCTUnwrap(TripPreviewData.myTrips.first { $0.id == "yangpyeong" })
        let preparation = TripPreparationStore(preview: preview, actorName: "사용자A")
        await preparation.load()
        let accountID = try XCTUnwrap(preparation.detail?.me?.id)
        XCTAssertTrue(try XCTUnwrap(preparation.detail?.myCar).iRide)
        let response = payload()
        var requests = 0
        DrivingVersusHTTPStub.respond = { _ in
            requests += 1
            XCTFail("Preview requested real comparison data")
            return (200, response)
        }
        let store = TripDrivingVersusStore(preparation: preparation, api: api())
        await store.load()
        let visible = try XCTUnwrap(store.visibleValue)
        XCTAssertEqual(visible.state, "pending")
        XCTAssertEqual(visible.reason, "preview")
        XCTAssertTrue(visible.winnerCarIds.isEmpty)
        XCTAssertTrue(visible.cars.allSatisfy { $0.averageScore == nil && $0.measuredCourseCount == 0 && $0.courses.isEmpty })
        let context = store.contextID

        try await preparation.leaveCar()

        XCTAssertTrue(preparation.accountIsCurrent)
        XCTAssertEqual(preparation.detail?.me?.id, accountID)
        XCTAssertNil(preparation.detail?.myCar)
        XCTAssertNotEqual(store.contextID, context)
        XCTAssertNotNil(store.value)
        XCTAssertNil(store.visibleValue)
        XCTAssertEqual(requests, 0)
    }

    func testReadUsesOnlyAuthenticatedIPhoneTripGetWithoutNewConsentRequest() async throws {
        let object = payload()
        var reads = 0
        DrivingVersusHTTPStub.respond = { [self] request in
            reads += 1
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertEqual(request.url?.absoluteString, "https://ios-api-wegoh.devforest.io/v1/iphone/trips/" + tripID + "/driving-score")
            XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer " + token)
            XCTAssertEqual(request.value(forHTTPHeaderField: "Accept"), "application/json")
            XCTAssertNil(request.value(forHTTPHeaderField: "Cookie"))
            XCTAssertNil(request.httpBody)
            XCTAssertNil(request.httpBodyStream)
            return (200, object)
        }
        let value = try await api().load(tripID, token: token)
        XCTAssertEqual(value.state, "pending")
        XCTAssertTrue(value.winnerCarIds.isEmpty)
        XCTAssertEqual(reads, 1)
    }

    func testInvalidResponseIsRejectedAndAuthenticationOrHiddenTripDoesNotRetry() async throws {
        var calls = 0
        let invalid = payload(winners: [firstCar])
        DrivingVersusHTTPStub.respond = { _ in calls += 1; return (200, invalid) }
        do { _ = try await api().load(tripID, token: token); XCTFail("Nonfinal winner accepted") }
        catch IPhoneSessionError.invalidResponse { }
        for status in [401, 404] {
            DrivingVersusHTTPStub.respond = { _ in
                calls += 1
                return (status, ["detail": status == 401 ? "IPHONE_SESSION_REVOKED" : "Driving versus unavailable"])
            }
            do { _ = try await api().load(tripID, token: token); XCTFail("HTTP failure accepted") }
            catch IPhoneSessionError.invalidSession { XCTAssertEqual(status, 401) }
            catch IPhoneResourceError.missing { XCTAssertEqual(status, 404) }
        }
        XCTAssertEqual(calls, 3)
    }
}
