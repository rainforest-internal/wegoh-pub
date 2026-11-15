import Foundation

enum IPhoneTripRoutePhase: String, Codable, CaseIterable {
    case pickup, waiting, shared, drop, done
}

struct IPhoneTripRouteItem: Codable, Equatable, Hashable {
    var type: String
    var ref: String
    var courseId: String? = nil

    var isValid: Bool {
        switch type {
        case "course": validCourseID(ref) && (courseId.map(validCourseID) ?? false)
        case "pickup", "drop", "signal": validTripID(ref) && courseId == nil
        default: false
        }
    }
}

/// 다른 차도 보는 공유 경로 기준 대략 진행. target은 합류 지점(pickup) 또는 다음 공유 코스 장소(shared).
struct IPhoneTripStatusProgress: Codable, Equatable {
    var target: IPhoneTripRouteItem
    var remainingMeters: Int
    var legFraction: Double?
    var isValid: Bool {
        target.type == "course" && target.isValid && validTripMeters(remainingMeters) && validTripLegFraction(legFraction)
    }
}

/// 같은 차 탑승자에게만 오는 routePlan.next까지의 실시간 진행. 위치 공유 좌표 기준 직선 거리이며 도착을 뜻하지 않는다.
struct IPhoneTripPlanProgress: Codable, Equatable {
    var remainingMeters: Int
    var legFraction: Double?
    var isValid: Bool { validTripMeters(remainingMeters) && validTripLegFraction(legFraction) }
}

struct IPhoneTripRouteStatus: Codable, Equatable {
    var phase: IPhoneTripRoutePhase
    var joinEtaSeconds: Int?
    var progress: IPhoneTripStatusProgress? = nil
    var isValid: Bool {
        validTripEtaSeconds(joinEtaSeconds)
            && (progress.map { $0.isValid && (phase == .pickup || phase == .shared) } ?? true)
    }
}

struct IPhoneTripRoutePlan: Codable, Equatable {
    struct Segment: Codable, Equatable {
        var segment: String
        var items: [IPhoneTripRouteItem]
    }
    struct JoinPoint: Codable, Equatable {
        var courseId: String
        var ref: String
        var name: String
        var lat: Double
        var lng: Double
    }
    struct JoinBarrier: Codable, Equatable {
        var arrivedCarIds: [String]
        var totalCarCount: Int
        var released: Bool
    }
    var contractVersion: Int
    var phase: IPhoneTripRoutePhase
    var segments: [Segment]
    var joinPoint: JoinPoint
    var joinEtaSeconds: Int?
    var progressRevision: Int
    var next: IPhoneTripRouteItem?
    var joinBarrier: JoinBarrier
    var progress: IPhoneTripPlanProgress? = nil

    var isValid: Bool {
        guard contractVersion == 2, validTripEtaSeconds(joinEtaSeconds), validTripRevision(progressRevision),
              segments.map(\.segment) == ["pickup", "shared", "drop"],
              validCourseID(joinPoint.courseId), validCourseID(joinPoint.ref),
              validTripText(joinPoint.name, max: 80), validTripCoordinates(lat: joinPoint.lat, lng: joinPoint.lng),
              (1...20).contains(joinBarrier.totalCarCount),
              joinBarrier.arrivedCarIds.count <= joinBarrier.totalCarCount,
              joinBarrier.arrivedCarIds.allSatisfy(validTripID),
              Set(joinBarrier.arrivedCarIds).count == joinBarrier.arrivedCarIds.count else { return false }
        let items = segments.flatMap(\.items)
        guard items.count <= 130, items.allSatisfy(\.isValid), Set(items).count == items.count,
              segments[0].items.allSatisfy({ ["pickup", "signal"].contains($0.type) }),
              segments[1].items.allSatisfy({ ["course", "signal"].contains($0.type) }),
              segments[2].items.allSatisfy({ ["drop", "signal"].contains($0.type) }),
              segments[1].items.contains(.init(type: "course", ref: joinPoint.ref, courseId: joinPoint.courseId)),
              next.map({ items.contains($0) }) ?? true,
              progress.map({ $0.isValid && next != nil }) ?? true else { return false }
        return true
    }

    func referencesAreValid(car: IPhoneTripCar, courses: [IPhoneTripCourse], visibleCarIDs: Set<String>) -> Bool {
        guard isValid, Set(joinBarrier.arrivedCarIds).isSubset(of: visibleCarIDs),
              let course = courses.first(where: { $0.packId == joinPoint.courseId }),
              let first = course.stops?.first, first.id == joinPoint.ref,
              first.name == joinPoint.name, first.lat == joinPoint.lat, first.lng == joinPoint.lng else { return false }
        return segments.flatMap(\.items).allSatisfy { item in
            if item.type == "course" {
                return courses.first { $0.packId == item.courseId }?.stops?.contains { $0.id == item.ref } == true
            }
            return car.places.contains { $0.id == item.ref && $0.kind?.rawValue == item.type }
        }
    }
}

enum IPhoneTripPlaceSelection: Encodable, Equatable {
    case existing(String)
    case new(name: String, lat: Double, lng: Double)

    var isValid: Bool {
        switch self {
        case .existing(let id): validTripID(id)
        case .new(let name, let lat, let lng): validTripText(name, max: 40) && validTripCoordinates(lat: lat, lng: lng)
        }
    }

    private enum CodingKeys: String, CodingKey { case placeId, name, lat, lng }
    func encode(to encoder: Encoder) throws {
        var box = encoder.container(keyedBy: CodingKeys.self)
        switch self {
        case .existing(let id): try box.encode(id, forKey: .placeId)
        case .new(let name, let lat, let lng):
            try box.encode(name.trimmingCharacters(in: .whitespacesAndNewlines), forKey: .name)
            try box.encode(lat, forKey: .lat)
            try box.encode(lng, forKey: .lng)
        }
    }
}

struct IPhoneTripMyPlacesDraft: Encodable, Equatable {
    var revision: Int
    var pickup: IPhoneTripPlaceSelection?
    var drop: IPhoneTripPlaceSelection?
    var dropAtPickup: Bool

    var isValid: Bool {
        (1...Int(Int32.max)).contains(revision) && (pickup?.isValid ?? true) && (drop?.isValid ?? true)
            && (!dropAtPickup || (pickup != nil && drop == nil))
    }

    private enum CodingKeys: String, CodingKey { case revision, pickup, drop, dropAtPickup }
    func encode(to encoder: Encoder) throws {
        var box = encoder.container(keyedBy: CodingKeys.self)
        try box.encode(revision, forKey: .revision)
        try box.encode(pickup, forKey: .pickup)
        try box.encode(drop, forKey: .drop)
        try box.encode(dropAtPickup, forKey: .dropAtPickup)
    }
}

func validTripRevision(_ value: Int) -> Bool { (0...Int(Int32.max)).contains(value) }

private func validTripMeters(_ value: Int) -> Bool { (0...Int(Int32.max)).contains(value) }

private func validTripLegFraction(_ value: Double?) -> Bool { value.map { $0.isFinite && (0...1).contains($0) } ?? true }

private func validTripEtaSeconds(_ value: Int?) -> Bool {
    value.map { (0...Int(Int32.max)).contains($0) } ?? true
}
