import Foundation

struct TripCourseRoutePresentation {
    let isCurrent: Bool
    let isComplete: Bool
    let stopStates: [RouteStop.State]
    let progress: Double?

    init(course: IPhoneTripCourse, car: IPhoneTripCar?) {
        let stops = course.stops ?? []
        let recordedComplete = car.map { course.completedCarIds?.contains($0.id) == true } ?? false
        guard let car, let plan = car.routePlan else {
            isCurrent = false
            isComplete = recordedComplete
            stopStates = stops.map { _ in recordedComplete ? .arrived : .planned }
            progress = recordedComplete && !stops.isEmpty ? 1 : nil
            return
        }
        let shared = plan.segments.first { $0.segment == "shared" }?.items ?? []
        let nextIndex = plan.next.flatMap { shared.firstIndex(of: $0) }
        let nextCourse = nextIndex.flatMap { index in shared[index...].first { $0.type == "course" } }
        isCurrent = plan.phase == .shared && nextCourse?.courseId == course.packId
        if isCurrent, !recordedComplete, plan.joinBarrier.released, course.packId == plan.joinPoint.courseId,
           stops.count == 1, stops.first?.id == plan.joinPoint.ref {
            stopStates = [.arrived]
            isComplete = false
            progress = nil
            return
        }
        let states: [RouteStop.State] = stops.map { stop in
            let item = IPhoneTripRouteItem(type: "course", ref: stop.id, courseId: course.packId)
            guard let index = shared.firstIndex(of: item) else { return recordedComplete ? .arrived : .planned }
            switch plan.phase {
            case .drop, .done: return .arrived
            case .pickup: return .planned
            case .waiting:
                return plan.joinBarrier.arrivedCarIds.contains(car.id) && item.ref == plan.joinPoint.ref
                    && item.courseId == plan.joinPoint.courseId ? .arrived : .planned
            case .shared:
                guard let nextIndex else { return recordedComplete ? .arrived : .planned }
                if index < nextIndex { return .arrived }
                return index == nextIndex ? .next : .planned
            }
        }
        stopStates = states
        isComplete = recordedComplete || (!states.isEmpty && states.allSatisfy { $0 == .arrived })
        progress = stops.isEmpty ? nil : Double(states.filter { $0 == .arrived }.count) / Double(stops.count)
    }
}

extension IPhoneTripRoutePlan {
    var awaitingJoinCourseCompletion: Bool {
        phase == .shared && joinBarrier.released
            && next == IPhoneTripRouteItem(type: "course", ref: joinPoint.ref, courseId: joinPoint.courseId)
            && segments.first(where: { $0.segment == "shared" })?.items.filter({ $0.courseId == joinPoint.courseId }).count == 1
    }
}

/// 위치 공유 좌표로 서버가 계산한 실시간 진행을 진행 바와 문구로 바꾼다. 거리는 직선 거리다.
enum TripLiveProgressPresentation {
    /// 내 차 진행 바의 '지금 여기' 위치. next 직전 장소가 같은 진행 바에 있을 때만 그린다.
    static func position(stops: [RouteStop], progress: IPhoneTripPlanProgress?) -> Double? {
        guard let fraction = progress?.legFraction,
              let next = stops.firstIndex(where: { $0.state == .next }), next > 0 else { return nil }
        return Double(next - 1) + fraction
    }

    /// 내 차 탑승자용 남은 거리. 1km 미만은 50m, 이상은 0.1km 단위.
    static func ownDistance(_ meters: Int) -> String {
        if meters < 1000 { return "직선 약 \(max(50, Int((Double(meters) / 50).rounded()) * 50))m" }
        return "직선 약 " + String(format: "%.1f", Double(meters) / 1000) + "km"
    }

    /// 다른 차용 대략 거리. 0.5km 단위이며 1km 미만은 묶어서 보여 준다.
    static func approximateDistance(_ meters: Int) -> String {
        if meters < 1000 { return "직선 1km 이내" }
        let rounded = (Double(meters) / 500).rounded() / 2
        return "직선 약 " + (rounded.truncatingRemainder(dividingBy: 1) == 0 ? String(Int(rounded)) : String(format: "%.1f", rounded)) + "km"
    }

    /// 다른 차 한 줄 요약. 단계만 알 때는 단계 이름, 공유 경로 기준 진행이 있으면 남은 거리를 붙인다.
    static func companionSummary(_ status: IPhoneTripRouteStatus?) -> String? {
        guard let status else { return nil }
        switch status.phase {
        case .waiting: return "합류 지점 도착"
        case .drop, .done: return status.phase.displayTitle
        case .pickup, .shared:
            guard let progress = status.progress else { return status.phase.displayTitle }
            return (status.phase == .pickup ? "합류 지점까지 " : "다음 장소까지 ") + approximateDistance(progress.remainingMeters)
        }
    }

    /// 공유 코스를 함께 달리는 다른 차를 현재 코스 진행 바에 놓는다. stops는 TripFullRouteSection의 장소다.
    static func companions(detail: IPhoneTripDetail, stops: [RouteStop]) -> [RouteStrip.Marker] {
        detail.cars.filter { $0.id != detail.myCar?.id }.compactMap { car in
            guard let status = car.routeStatus, status.phase == .shared, let progress = status.progress,
                  let fraction = progress.legFraction,
                  let target = stops.firstIndex(where: { $0.id == "course:\(progress.target.courseId ?? ""):\(progress.target.ref)" }),
                  let previous = stops[..<target].lastIndex(where: { $0.id.hasPrefix("course:") }) else { return nil }
            let number = car.ordinal ?? ((detail.cars.firstIndex { $0.id == car.id } ?? 0) + 1)
            return RouteStrip.Marker(id: car.id, label: "\(number)", position: Double(previous) + Double(target - previous) * fraction,
                                     accessibilityText: "\(number)호차 \(stops[target].title) 가는 중")
        }
    }
}
