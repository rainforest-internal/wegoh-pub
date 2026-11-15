import SwiftUI

extension IPhoneTripRoutePhase {
    var displayTitle: String {
        switch self { case .pickup: "타는 곳으로 이동 중"; case .waiting: "합류 대기"; case .shared: "경로 주행 중"; case .drop: "내리는 곳으로 이동 중"; case .done: "주행 완료" }
    }
}

extension IPhoneTripDetail {
    var canUseTripSignals: Bool {
        state == .active && myCar != nil && myCar?.routePlan?.phase != .done
    }
    var signalAvailabilityExplanation: String {
        state == .active && myCar == nil ? "탈 차를 먼저 골라 주세요." : "여행이 끝나 새 손들기를 보낼 수 없어요."
    }
}

struct TripSegmentBand: View {
    let detail: IPhoneTripDetail
    var body: some View {
        VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
            ScrollViewReader { proxy in
                ScrollView(.horizontal) {
                    HStack(spacing: WegoTokens.Space.small) {
                        segment("타는 곳", personal: true, current: phase == .pickup, past: phase != nil && phase != .pickup)
                            .id("pickup")
                        ForEach(Array(detail.courses.enumerated()), id: \.element.id) { index, course in
                            let progress = TripCourseRoutePresentation(course: course, car: detail.myCar)
                            segment("경로 \(index + 1)", personal: false,
                                    current: progress.isCurrent, past: progress.isComplete)
                                .id("course-" + course.id)
                        }
                        segment("내리는 곳", personal: true, current: phase == .drop, past: phase == .done)
                            .id("drop")
                    }
                }.scrollIndicators(.hidden)
                    .onAppear { proxy.scrollTo(currentSegmentID, anchor: .center) }
                    .onChange(of: currentSegmentID) { _, value in proxy.scrollTo(value, anchor: .center) }
            }
            if phase == .waiting { Text("모든 차가 합류 지점에 도착하면 공유 경로가 시작돼요.").font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.accent) }
        }.accessibilityIdentifier("tripSegmentBand")
    }
    private var phase: IPhoneTripRoutePhase? { detail.myCar?.routePlan?.phase }
    private var currentSegmentID: String {
        if phase == .drop || phase == .done { return "drop" }
        if phase == .shared,
           let course = detail.courses.first(where: { TripCourseRoutePresentation(course: $0, car: detail.myCar).isCurrent }) {
            return "course-" + course.id
        }
        return "pickup"
    }
    private func segment(_ title: String, personal: Bool, current: Bool, past: Bool) -> some View {
        Text(title).font(WegoTokens.Typography.label.weight(.semibold))
            .padding(.horizontal, WegoTokens.Space.medium).padding(.vertical, WegoTokens.Space.small)
            .frame(minHeight: WegoTokens.Metrics.tripRouteSegmentMinimumHeight)
            .foregroundStyle(current || !personal ? WegoTokens.Palette.onInk : WegoTokens.Palette.text)
            .background(current ? WegoTokens.Palette.accent : personal ? WegoTokens.Palette.background : WegoTokens.Palette.ink,
                        in: RoundedRectangle(cornerRadius: WegoTokens.Radius.routeSegment))
            .overlay {
                if personal && !current { RoundedRectangle(cornerRadius: WegoTokens.Radius.routeSegment)
                    .strokeBorder(WegoTokens.Palette.personalRouteBorder, style: StrokeStyle(lineWidth: WegoTokens.Metrics.hairlineWidth, dash: [WegoTokens.Space.xSmall, WegoTokens.Space.xSmall])) }
            }.opacity(past ? WegoTokens.Opacity.pastRouteSegment : 1)
            .accessibilityLabel(title + (current ? ", 현재 구간" : past ? ", 지난 구간" : personal ? ", 우리 차만" : ", 공유 경로"))
    }
}

struct TripRouteOverviewView: View {
    let store: TripPreparationStore
    let editPlaces: () -> Void
    let addCourse: () -> Void
    var createCourse: (() -> Void)? = nil
    var compact = false
    var showDetails: (() -> Void)? = nil
    @State private var message: String?
    var body: some View {
        if let detail = store.detail {
            VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
                HStack {
                    Text("전체 경로").font(WegoTokens.Typography.section)
                    Spacer()
                    if let showDetails {
                        Button("자세히 ›", action: showDetails)
                            .font(WegoTokens.Typography.caption.weight(.semibold))
                            .foregroundStyle(WegoTokens.Palette.accent)
                            .frame(minHeight: WegoTokens.Metrics.touchTarget)
                    }
                }
                preparationBand(detail)
                if compact {
                    Text("점선은 우리 차만, 채운 칸은 모든 차가 함께 달려요.")
                        .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                } else {
                Text("① 타는 곳 · 우리 차만").font(WegoTokens.Typography.section)
                personalPlaces(detail, kind: .pickup)
                if let first = detail.courses.first?.stops?.first {
                    Label("여기서 모두 만나요 · \(first.name)", systemImage: "mappin.circle")
                        .font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.accent).tripProgressCard(selected: true)
                }
                Text("② 공유 경로 · 모든 차 함께").font(WegoTokens.Typography.section)
                if !detail.courses.isEmpty {
                    WegoCard(.ink) {
                        VStack(alignment: .leading, spacing: WegoTokens.Space.large) {
                            ForEach(Array(detail.courses.enumerated()), id: \.element.id) { index, course in
                                VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                                    Text("\(index + 1). \(course.title)").font(WegoTokens.Typography.cardTitle)
                                    if let stops = course.stops, !stops.isEmpty {
                                        RouteStrip(stops: stops.map(\.name), onInk: true)
                                    }
                                    if detail.isOwner && detail.state == .planned && detail.courses.count > 1 {
                                        HStack {
                                            orderButton("위로", symbol: "arrow.up", index: index, offset: -1, detail: detail).disabled(index == 0)
                                            orderButton("아래로", symbol: "arrow.down", index: index, offset: 1, detail: detail).disabled(index == detail.courses.count - 1)
                                        }
                                        .foregroundStyle(WegoTokens.Palette.routeHighlight)
                                    }
                                }
                            }
                        }
                    }
                }
                HStack(alignment: .top, spacing: WegoTokens.Space.small) {
                    Button(action: addCourse) {
                        Label("내 경로에서 추가", systemImage: "plus")
                    }.buttonStyle(.wego(.soft)).disabled(store.busy || store.needsRefresh)
                        .accessibilityIdentifier("tripPreparingAddCourse")
                    if let createCourse {
                        Button(action: createCourse) {
                            Label("새 경로 만들기", systemImage: "plus")
                                .font(WegoTokens.Typography.action)
                                .foregroundStyle(WegoTokens.Palette.secondary)
                                .padding(.horizontal, WegoTokens.Space.medium)
                                .padding(.vertical, WegoTokens.Space.compact)
                                .frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.primaryButtonHeight)
                                .overlay {
                                    RoundedRectangle(cornerRadius: WegoTokens.Radius.control)
                                        .strokeBorder(WegoTokens.Palette.divider,
                                                      style: StrokeStyle(lineWidth: WegoTokens.Metrics.hairlineWidth,
                                                                         dash: [WegoTokens.Space.xSmall, WegoTokens.Metrics.timelineWidth]))
                                }
                                .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain).disabled(store.busy || store.needsRefresh || store.isPreview)
                        .accessibilityIdentifier("tripPreparingCreateCourse")
                    }
                }
                Text("③ 내리는 곳 · 우리 차만").font(WegoTokens.Typography.section)
                personalPlaces(detail, kind: .drop)
                if let message { Text(message).font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.danger) }
                Text("타는 곳·내리는 곳 순서는 운전자가 차량 화면에서 정해요. 공유 경로 순서는 여행 만든 사람이 정해요.")
                    .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                }
            }
        }
    }
    private func preparationBand(_ detail: IPhoneTripDetail) -> some View {
        GeometryReader { geometry in
            let count = min(4, max(3, detail.courses.count + 2))
            let width = (geometry.size.width - WegoTokens.Space.xSmall * CGFloat(count - 1)) / CGFloat(count)
            let personalWidth = detail.courses.isEmpty ? (geometry.size.width - WegoTokens.Space.xSmall * 2) / 4 : width
            ScrollView(.horizontal) {
                HStack(spacing: WegoTokens.Space.xSmall) {
                    routeCell("타는 곳", subtitle: "우리 차만", personal: true, width: personalWidth)
                    if detail.courses.isEmpty {
                        Button(action: addCourse) {
                            routeCell("경로 추가", subtitle: "모든 차 함께", personal: true, width: personalWidth * 2)
                        }.buttonStyle(.plain).disabled(store.busy || store.needsRefresh)
                    }
                    ForEach(Array(detail.courses.enumerated()), id: \.element.id) { index, course in
                        routeCell("경로 \(index + 1)", subtitle: course.title, personal: false,
                                  width: width)
                    }
                    routeCell("내리는 곳", subtitle: "우리 차만", personal: true, width: personalWidth)
                }
            }.scrollIndicators(.hidden)
        }
        .frame(height: WegoTokens.Metrics.primaryButtonHeight + WegoTokens.Space.medium)
    }

    private func routeCell(_ title: String, subtitle: String, personal: Bool, width: CGFloat) -> some View {
        VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
            Text(title).font(WegoTokens.Typography.label.weight(.semibold)).lineLimit(1)
            Text(subtitle).font(WegoTokens.Typography.caption).lineLimit(1)
                .foregroundStyle(personal ? WegoTokens.Palette.secondary : WegoTokens.Palette.onInkSecondary)
        }
        .padding(WegoTokens.Space.small)
        .frame(width: width, alignment: .leading)
        .frame(maxHeight: .infinity)
        .foregroundStyle(personal ? WegoTokens.Palette.text : WegoTokens.Palette.onInk)
        .background(personal ? WegoTokens.Palette.background : WegoTokens.Palette.ink,
                    in: RoundedRectangle(cornerRadius: WegoTokens.Radius.routeSegment))
        .overlay {
            if personal {
                RoundedRectangle(cornerRadius: WegoTokens.Radius.routeSegment)
                    .strokeBorder(WegoTokens.Palette.personalRouteBorder,
                                  style: StrokeStyle(lineWidth: WegoTokens.Metrics.hairlineWidth, dash: [WegoTokens.Space.xSmall, WegoTokens.Space.xSmall]))
            }
        }
    }

    private func personalPlaces(_ detail: IPhoneTripDetail, kind: IPhoneTripPlaceKind) -> some View {
        VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
            if let car = detail.myCar {
                Text(detail.numberedName(car)).font(WegoTokens.Typography.label.weight(.semibold))
                let places = car.places.filter { place in
                    place.kind == kind && (place.selectedBy?.isEmpty == false || car.routeOrder?.contains { $0.ref == place.id } == true)
                }
                ForEach(Array(places.enumerated()), id: \.offset) { index, place in
                    VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                        Text("\(index + 1). \(place.name)").font(WegoTokens.Typography.section)
                        Text(detail.members.filter { place.selectedBy?.contains($0.id) == true }.map { $0.isMe ? "나" : $0.name }.joined(separator: ", "))
                            .font(WegoTokens.Typography.caption)
                    }
                }
                if places.isEmpty { Text(kind == .pickup ? "고른 타는 곳이 없어요." : "고른 내리는 곳이 없어요.").font(WegoTokens.Typography.label) }
                if car.iRide {
                    Button(action: editPlaces) {
                        Text(kind == .pickup ? "타는 곳 바꾸기" : "내리는 곳 정하기").font(WegoTokens.Typography.action)
                            .frame(minHeight: WegoTokens.Metrics.touchTarget).contentShape(Rectangle())
                    }.foregroundStyle(WegoTokens.Palette.accent)
                        .accessibilityIdentifier(kind == .pickup ? "tripMyPickup" : "tripMyDrop")
                }
            } else { Text("탈 차를 고르면 우리 차 경로를 볼 수 있어요.").font(WegoTokens.Typography.label) }
        }.padding(WegoTokens.Space.medium).frame(maxWidth: .infinity, alignment: .leading)
            .overlay { RoundedRectangle(cornerRadius: WegoTokens.Radius.card).strokeBorder(WegoTokens.Palette.personalRouteBorder,
                style: StrokeStyle(lineWidth: WegoTokens.Metrics.hairlineWidth, dash: [WegoTokens.Space.xSmall, WegoTokens.Space.xSmall])) }
    }
    private func orderButton(_ title: String, symbol: String, index: Int, offset: Int, detail: IPhoneTripDetail) -> some View {
        Button {
            var ids = detail.courses.map(\.id); ids.swapAt(index, index + offset)
            Task { do { try await store.prioritizeCourses(packIDs: ids, revision: detail.revision); message = nil } catch { message = tripPreparationErrorMessage(error) } }
        } label: {
            Label(title, systemImage: symbol).font(WegoTokens.Typography.action)
                .frame(minHeight: WegoTokens.Metrics.touchTarget).contentShape(Rectangle())
        }
            .disabled(store.busy || store.needsRefresh).accessibilityIdentifier("tripCourseOrder-\(index)-\(offset)")
    }
}

struct TripRoutePhaseContent: View {
    let detail: IPhoneTripDetail
    var body: some View {
        WegoCard(.outlined) {
            if let car = detail.myCar, let plan = car.routePlan {
                HStack(alignment: .center, spacing: WegoTokens.Space.small) {
                    Text(phaseTitle(plan)).font(WegoTokens.Typography.caption.weight(.semibold))
                        .foregroundStyle(WegoTokens.Palette.accent)
                        .padding(.horizontal, WegoTokens.Space.small).padding(.vertical, WegoTokens.Space.xSmall)
                        .background(WegoTokens.Palette.accentSoft, in: Capsule())
                        .accessibilityIdentifier("tripRoutePhase")
                    Spacer(minLength: 0)
                    fullRouteLink
                }
                VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                    Text(nextTitle(plan, car: car)).font(WegoTokens.Typography.section)
                    if let guidance = guidanceTitle(plan, car: car) {
                        Label(guidance, systemImage: "location.north.line.fill")
                            .font(WegoTokens.Typography.caption.weight(.semibold))
                            .foregroundStyle(WegoTokens.Palette.accent)
                            .accessibilityIdentifier("tripRouteGuidance")
                    }
                    if plan.phase == .waiting {
                        Text("합류 \(plan.joinBarrier.arrivedCarIds.count)/\(plan.joinBarrier.totalCarCount)대 · \(plan.joinPoint.name)")
                            .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                    } else if let section = TripFullRouteSection.sections(detail: detail).first(where: \.isCurrent), !section.isPersonal {
                        Text("\(section.subtitle) · 장소 \(section.stops.count)곳 중 \(section.stops.filter { $0.state == .arrived }.count)곳 지남")
                            .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                    }
                    if plan.phase == .pickup || plan.phase == .waiting, let seconds = plan.joinEtaSeconds {
                        Text(tripJoinETALabel(seconds)).font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                    }
                    if let progress = plan.progress {
                        Text("지금 여기 · 다음 장소까지 " + TripLiveProgressPresentation.ownDistance(progress.remainingMeters))
                            .font(WegoTokens.Typography.caption.weight(.semibold)).foregroundStyle(WegoTokens.Palette.accent)
                            .accessibilityIdentifier("tripRouteLiveProgress")
                    }
                }
                let stops = plan.phase == .shared
                    ? TripFullRouteSection.sections(detail: detail).first(where: \.isCurrent)?.stops ?? []
                    : phaseStops(plan, car: car)
                if !stops.isEmpty && plan.phase != .done {
                    if stops.count <= 3 {
                        RouteStrip(stops: stops.map(\.title),
                                   progress: stops.firstIndex(where: { $0.state == .next })
                                       ?? (stops.allSatisfy { $0.state == .arrived } ? stops.indices.last : nil),
                                   position: TripLiveProgressPresentation.position(stops: stops, progress: plan.progress),
                                   companions: plan.phase == .shared ? TripLiveProgressPresentation.companions(detail: detail, stops: stops) : [])
                    } else {
                        // 장소가 많으면 목록으로 보여 주고, 지금 달리는 구간만 짧은 진행 바로 함께 보여 준다.
                        if let position = TripLiveProgressPresentation.position(stops: stops, progress: plan.progress) {
                            let from = Int(position.rounded(.down))
                            let window = Array(stops[from...min(from + 2, stops.count - 1)])
                            RouteStrip(stops: window.map(\.title), progress: 1, position: position - Double(from),
                                       companions: plan.phase == .shared ? TripLiveProgressPresentation.companions(detail: detail, stops: stops)
                                           .compactMap { (marker: RouteStrip.Marker) -> RouteStrip.Marker? in
                                               let local = marker.position - Double(from)
                                               return (0...Double(window.count - 1)).contains(local) ? RouteStrip.Marker(id: marker.id, label: marker.label,
                                                   position: local, accessibilityText: marker.accessibilityText) : nil
                                           } : [])
                        }
                        RouteList(stops: stops)
                    }
                }
                Text("안내와 도착 확인은 운전자의 차량 화면에서 해요.")
                    .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
            } else {
                HStack {
                    Text("지금 경로").font(WegoTokens.Typography.label.weight(.semibold))
                    Spacer(minLength: 0)
                    fullRouteLink
                }
                if let course = detail.courses.first(where: { TripCourseRoutePresentation(course: $0, car: detail.myCar).isCurrent }) ?? detail.courses.first {
                    Text(course.title).font(WegoTokens.Typography.section)
                    Text("장소 \(course.stopCount)곳").font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                } else { Text("현재 경로를 확인할 수 없어요. 새로고침해 주세요.").font(WegoTokens.Typography.label) }
            }
        }
    }

    private var fullRouteLink: some View {
        NavigationLink { TripFullRouteView(detail: detail) } label: {
            HStack(spacing: WegoTokens.Space.xSmall) {
                Text("이동 경로")
                Image(systemName: "chevron.right").accessibilityHidden(true)
            }.font(WegoTokens.Typography.caption.weight(.semibold)).foregroundStyle(WegoTokens.Palette.accent)
                .frame(minHeight: WegoTokens.Metrics.touchTarget).contentShape(Rectangle())
        }.buttonStyle(.plain).accessibilityIdentifier("tripFullRoute")
    }

    private func phaseTitle(_ plan: IPhoneTripRoutePlan) -> String {
        if plan.phase == .shared, let next = plan.next,
           let index = detail.courses.firstIndex(where: { $0.packId == next.courseId }) {
            return "공유 경로 \(index + 1) · 모든 차 함께"
        }
        return plan.phase.displayTitle + (plan.phase == .pickup || plan.phase == .drop ? " · 우리 차만" : "")
    }
    private func phaseStops(_ plan: IPhoneTripRoutePlan, car: IPhoneTripCar) -> [RouteStop] {
        let pickup = plan.phase == .pickup || plan.phase == .waiting
        var items = plan.segments.first(where: { $0.segment == (pickup ? "pickup" : "drop") })?.items ?? []
        if pickup { items.append(.init(type: "course", ref: plan.joinPoint.ref, courseId: plan.joinPoint.courseId)) }
        let nextIndex = plan.next.flatMap { items.firstIndex(of: $0) }
        return items.enumerated().compactMap { index, item in
            let name = item.type == "course" ? plan.joinPoint.name : car.places.first(where: { $0.id == item.ref })?.name
            guard let name else { return nil }
            let state: RouteStop.State
            if plan.phase == .done || plan.phase == .waiting { state = .arrived }
            else if let nextIndex { state = index < nextIndex ? .arrived : index == nextIndex ? .next : .planned }
            else { state = .planned }
            return RouteStop(id: item.ref, title: name, subtitle: item.type == "course" ? "합류 지점" : nil, state: state)
        }
    }

    /// The driver's current navigation target when it differs from the next place awaiting arrival.
    private func guidanceTitle(_ plan: IPhoneTripRoutePlan, car: IPhoneTripCar) -> String? {
        guard plan.phase != .done, let target = car.routeNext, target != plan.next else { return nil }
        let name: String?
        if target.type == "course" {
            name = detail.courses.first { $0.packId == target.courseId }?.stops?.first { $0.id == target.ref }?.name
        } else { name = car.places.first { $0.id == target.ref }?.name }
        return name.map { "길 안내 중 · " + $0 }
    }

    private func nextTitle(_ plan: IPhoneTripRoutePlan, car: IPhoneTripCar) -> String {
        if plan.phase == .waiting { return "모든 차가 합류하기를 기다려요" }
        if plan.phase == .done { return "우리 차 경로를 마쳤어요" }
        if plan.awaitingJoinCourseCompletion { return "공유 경로 진행 중" }
        guard let next = plan.next else { return "다음 장소를 확인해 주세요" }
        if next.type == "course", let course = detail.courses.first(where: { $0.id == next.courseId }), let stop = course.stops?.first(where: { $0.id == next.ref }) { return "다음 장소 · " + stop.name }
        if let place = car.places.first(where: { $0.id == next.ref }) { return "다음 \(next.type == "pickup" ? "타는 곳" : next.type == "drop" ? "내리는 곳" : "경유지") · " + place.name }
        return "다음 장소를 다시 확인해 주세요"
    }
}

struct TripFullRouteSection: Identifiable {
    let id: String
    let title: String
    let subtitle: String
    let stops: [RouteStop]
    let isCurrent: Bool
    var isPersonal: Bool { id == "pickup" || id == "drop" }
    var isPast: Bool { !isCurrent && !stops.isEmpty && stops.allSatisfy { $0.state == .arrived } }

    static func sections(detail: IPhoneTripDetail) -> [Self] {
        let car = detail.myCar
        let plan = car?.routePlan
        let order = plan?.segments.flatMap(\.items) ?? car?.routeOrder ?? []
        let nextIndex = (plan?.next ?? car?.routeNext).flatMap { order.firstIndex(of: $0) }
        func stop(_ item: IPhoneTripRouteItem) -> RouteStop? {
            let name: String?
            if item.type == "course" {
                name = detail.courses.first { $0.packId == item.courseId }?.stops?.first { $0.id == item.ref }?.name
            } else { name = car?.places.first { $0.id == item.ref }?.name }
            guard let name else { return nil }
            let index = order.firstIndex(of: item)
            let state: RouteStop.State
            if plan?.phase == .done || detail.state == .completed { state = .arrived }
            else if let index, let nextIndex { state = index < nextIndex ? .arrived : index == nextIndex ? .next : .planned }
            else { state = .planned }
            return RouteStop(id: "\(item.type):\(item.courseId ?? ""):\(item.ref)", title: name,
                             subtitle: item.type == "signal" ? "손들기 경유지" : nil, state: state)
        }
        func personal(_ kind: IPhoneTripPlaceKind) -> [RouteStop] {
            if let segment = plan?.segments.first(where: { $0.segment == kind.rawValue }) {
                return segment.items.compactMap(stop)
            }
            if !order.isEmpty { return order.filter { $0.type == kind.rawValue }.compactMap(stop) }
            return (car?.places ?? []).filter { $0.kind == kind && $0.selectedBy?.isEmpty == false }.compactMap { place in
                place.id.map { RouteStop(id: $0, title: place.name) }
            }
        }
        let shared = plan?.segments.first { $0.segment == "shared" }?.items ?? order.filter { $0.type == "course" }
        var pickup = personal(.pickup)
        if let plan, plan.phase == .pickup || plan.phase == .waiting,
           var join = stop(.init(type: "course", ref: plan.joinPoint.ref, courseId: plan.joinPoint.courseId)) {
            if plan.phase == .waiting { join.state = .arrived }
            pickup.append(join)
        }
        var result: [Self] = [.init(id: "pickup", title: "타는 곳", subtitle: "우리 차만", stops: pickup,
                                    isCurrent: plan?.phase == .pickup || plan?.phase == .waiting)]
        for (index, course) in detail.courses.enumerated() {
            let items = shared.enumerated().filter { offset, item in
                if item.type == "course" { return item.courseId == course.packId }
                return (shared.dropFirst(offset + 1).first { $0.type == "course" }?.courseId
                        ?? shared.prefix(offset).last { $0.type == "course" }?.courseId) == course.packId
            }.map(\.element)
            let stops = items.isEmpty ? (course.stops ?? []).map { RouteStop(id: $0.id, title: $0.name) } : items.compactMap(stop)
            result.append(.init(id: "course:" + course.packId, title: "경로 \(index + 1)", subtitle: course.title,
                                stops: stops, isCurrent: plan?.phase == .shared && plan?.next.map(items.contains) == true))
        }
        result.append(.init(id: "drop", title: "내리는 곳", subtitle: "우리 차만", stops: personal(.drop), isCurrent: plan?.phase == .drop))
        return result
    }
}

struct TripFullRouteView: View {
    let detail: IPhoneTripDetail
    @State private var expanded: Set<String>
    private var sections: [TripFullRouteSection] { TripFullRouteSection.sections(detail: detail) }
    private var current: TripFullRouteSection? { sections.first(where: \.isCurrent) }
    private var onInk: Bool { current?.isPersonal == true }
    private var uniqueStops: [RouteStop] {
        var seen = Set<String>()
        return sections.flatMap(\.stops).filter { seen.insert($0.id).inserted }
    }

    init(detail: IPhoneTripDetail) {
        self.detail = detail
        let pickup = detail.myCar?.routePlan?.phase == .pickup || detail.myCar?.routePlan?.phase == .waiting
        _expanded = State(initialValue: Set(TripFullRouteSection.sections(detail: detail).filter {
            !$0.isPast && (!pickup || $0.isPersonal)
        }.map(\.id)))
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
                VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                    Text(detail.title + " · " + dateLabel).font(WegoTokens.Typography.caption)
                        .foregroundStyle(WegoTokens.Palette.secondary)
                    if let car = detail.myCar {
                        Text(detail.numberedName(car)).font(WegoTokens.Typography.cardTitle)
                    }
                }
                statusCard
                legend
                VStack(spacing: WegoTokens.Space.small) {
                    ForEach(sections) { section in sectionView(section) }
                }
                Text("타는 곳·내리는 곳 순서는 운전자가, 공유 경로 순서는 여행 만든 사람이 정해요. 길 안내와 도착 확인은 운전자의 차량 화면에서 해요.")
                    .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
            }.padding(WegoTokens.Space.screen)
        }
        .background(WegoTokens.Palette.background).foregroundStyle(WegoTokens.Palette.text)
        .navigationTitle("이동 경로").navigationBarTitleDisplayMode(.inline)
        .toolbar(.hidden, for: .tabBar)
    }

    private var dateLabel: String {
        if let start = detail.startDate, let end = detail.endDate, start != end { return start + " – " + end }
        return detail.startDate ?? detail.endDate ?? "날짜 미정"
    }

    private var statusCard: some View {
        WegoCard(onInk ? .ink : .surface) {
            VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                HStack(spacing: WegoTokens.Space.small) {
                    Text("지금 · " + (detail.myCar?.routePlan?.phase == .waiting ? "합류 대기" : current?.title ?? "주행 완료"))
                        .font(WegoTokens.Typography.caption.weight(.semibold))
                        .padding(.horizontal, WegoTokens.Space.small).padding(.vertical, WegoTokens.Space.xSmall)
                        .foregroundStyle(onInk ? WegoTokens.Palette.ink : WegoTokens.Palette.onAccent)
                        .background(onInk ? WegoTokens.Palette.onInk : WegoTokens.Palette.accent, in: Capsule())
                    Text(detail.myCar?.routePlan?.phase == .done ? "주행 완료" : onInk ? "우리 차만 달리는 중" : "모든 차가 함께 달리는 중")
                        .font(WegoTokens.Typography.caption)
                }
                Text(nextTitle).font(WegoTokens.Typography.cardTitle)
                Text("장소 \(uniqueStops.count)곳 중 \(uniqueStops.filter { $0.state == .arrived }.count)곳 지났어요")
                    .font(WegoTokens.Typography.caption)
                HStack(alignment: .top, spacing: WegoTokens.Space.small) {
                    ForEach(sections) { section in
                        VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                            HStack(spacing: WegoTokens.Space.xSmall) {
                                ForEach(progressStops(section)) { stop in
                                    Capsule().fill(stop.state == .arrived
                                        ? (onInk ? WegoTokens.Palette.routeHighlight : WegoTokens.Palette.accent)
                                        : (onInk ? WegoTokens.Palette.inkDivider : WegoTokens.Palette.divider))
                                        .frame(height: WegoTokens.Space.small)
                                }
                                if progressStops(section).isEmpty { Capsule().fill(onInk ? WegoTokens.Palette.inkDivider : WegoTokens.Palette.divider).frame(height: WegoTokens.Space.small) }
                            }
                            Text(section.title).font(section.isCurrent ? WegoTokens.Typography.caption.weight(.bold) : WegoTokens.Typography.caption)
                        }.frame(maxWidth: .infinity, alignment: .leading)
                    }
                }.padding(.top, WegoTokens.Space.small)
                    .accessibilityElement(children: .ignore)
                    .accessibilityLabel("장소 \(uniqueStops.count)곳 중 \(uniqueStops.filter { $0.state == .arrived }.count)곳 지남")
            }
        }
    }

    private var nextTitle: String {
        if detail.myCar?.routePlan?.phase == .waiting { return "합류 지점에서 일행을 기다려요" }
        if detail.myCar?.routePlan?.phase == .done { return "우리 차 경로를 마쳤어요" }
        return uniqueStops.first { $0.state == .next }.map { "다음 · " + $0.title } ?? "다음 장소 확인 중"
    }

    private var legend: some View {
        HStack(spacing: WegoTokens.Space.medium) {
            legendLine("모든 차 함께", personal: false)
            legendLine("우리 차만", personal: true)
            Label("합류 지점", systemImage: "diamond.fill")
        }.font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
    }

    private func legendLine(_ title: String, personal: Bool) -> some View {
        HStack(spacing: WegoTokens.Space.xSmall) {
            Path { path in path.move(to: .init(x: 0, y: WegoTokens.Space.xSmall)); path.addLine(to: .init(x: WegoTokens.Space.medium, y: WegoTokens.Space.xSmall)) }
                .stroke(style: StrokeStyle(lineWidth: WegoTokens.Metrics.hairlineWidth, dash: personal ? [WegoTokens.Space.xSmall] : []))
                .frame(width: WegoTokens.Space.medium, height: WegoTokens.Space.small)
            Text(title)
        }
    }

    private func sectionView(_ section: TripFullRouteSection) -> some View {
        VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
            Button {
                if expanded.contains(section.id) { expanded.remove(section.id) }
                else { expanded.insert(section.id) }
            } label: {
                HStack(spacing: WegoTokens.Space.small) {
                    VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                        HStack(alignment: .firstTextBaseline, spacing: WegoTokens.Space.small) {
                            Text(section.title + (section.isPersonal ? "" : " · " + section.subtitle)).font(WegoTokens.Typography.section)
                            if section.isCurrent || section.isPast {
                                Text(section.isCurrent ? "현재 구간" : "완료").font(WegoTokens.Typography.caption)
                                    .padding(.horizontal, WegoTokens.Space.small).padding(.vertical, WegoTokens.Space.xSmall)
                                    .foregroundStyle(section.isCurrent ? WegoTokens.Palette.onAccent : WegoTokens.Palette.secondary)
                                    .background(section.isCurrent ? WegoTokens.Palette.accent : WegoTokens.Palette.surface, in: Capsule())
                            }
                        }
                        Text((section.isPersonal ? "우리 차만" : "모든 차 함께") + " · 장소 \(progressStops(section).count)곳")
                            .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                    }
                    Spacer(minLength: 0)
                    Image(systemName: expanded.contains(section.id) ? "chevron.up" : "chevron.down")
                        .font(WegoTokens.Typography.caption).accessibilityHidden(true)
                }
                .frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.touchTarget, alignment: .leading)
                .contentShape(Rectangle())
            }.buttonStyle(.plain).accessibilityValue(expanded.contains(section.id) ? "펼침" : "접힘")
                .accessibilityIdentifier("tripFullRouteSection-" + section.id)
            if expanded.contains(section.id) {
                ForEach(Array(section.stops.enumerated()), id: \.element.id) { index, stop in
                    timelineStop(stop, section: section, last: index == section.stops.count - 1)
                }
                if section.stops.isEmpty || (section.id == "drop" && myDropMissing) {
                    VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                        Text(section.isPersonal ? (section.id == "drop" ? "내리는 곳을 아직 정하지 않았어요" : "고른 타는 곳이 없어요") : "장소 정보를 확인할 수 없어요")
                        if section.id == "drop", myDropMissing { Text("내리는 곳은 출발 전에 정할 수 있어요.").font(WegoTokens.Typography.caption) }
                    }
                        .font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.secondary)
                        .padding(WegoTokens.Space.medium).frame(maxWidth: .infinity, alignment: .leading)
                        .overlay { RoundedRectangle(cornerRadius: WegoTokens.Radius.field).strokeBorder(WegoTokens.Palette.personalRouteBorder, style: StrokeStyle(lineWidth: WegoTokens.Metrics.hairlineWidth, dash: [WegoTokens.Space.xSmall])) }
                }
            } else if !section.stops.isEmpty {
                Text(section.stops.map(\.title).joined(separator: " → ")).font(WegoTokens.Typography.caption)
                    .foregroundStyle(WegoTokens.Palette.secondary)
            }
        }
        .padding(WegoTokens.Space.medium).frame(maxWidth: .infinity, alignment: .leading)
        .background(section.isCurrent ? WegoTokens.Palette.accentSoft : WegoTokens.Palette.surface,
                    in: RoundedRectangle(cornerRadius: WegoTokens.Radius.control))
    }

    private func timelineStop(_ stop: RouteStop, section: TripFullRouteSection, last: Bool) -> some View {
        HStack(alignment: .top, spacing: WegoTokens.Space.compact) {
            Color.clear.frame(width: WegoTokens.Metrics.tripChecklistIconSize)
            VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                HStack(alignment: .firstTextBaseline, spacing: WegoTokens.Space.small) {
                    Text(stop.title).font(WegoTokens.Typography.section)
                    if isMine(stop) { Text("나").font(WegoTokens.Typography.caption).padding(.horizontal, WegoTokens.Space.small).padding(.vertical, WegoTokens.Space.xSmall).foregroundStyle(WegoTokens.Palette.onInk).background(WegoTokens.Palette.ink, in: Capsule()) }
                    if isJoin(stop) { Text("합류 지점").font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.accent) }
                }
                Text(stop.state == .arrived ? "지남" : stop.state == .next ? "다음" : "예정")
                    .font(WegoTokens.Typography.caption).foregroundStyle(stop.state == .next ? WegoTokens.Palette.accent : WegoTokens.Palette.secondary)
                if isMine(stop) { Text(section.id == "pickup" ? "내가 타는 곳" : "내가 내리는 곳").font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary) }
                else if isJoin(stop) { Text("모든 차가 합류하는 곳").font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary) }
                else if let subtitle = stop.subtitle { Text(subtitle).font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary) }
            }.frame(maxWidth: .infinity, alignment: .leading)
                .padding(.bottom, last ? 0 : WegoTokens.Space.medium)
        }
        .frame(minHeight: WegoTokens.Metrics.permissionIconSize, alignment: .topLeading)
        .overlay(alignment: .topLeading) {
            ZStack(alignment: .topLeading) {
            GeometryReader { geometry in
                Path { path in
                    let x = WegoTokens.Metrics.tripChecklistIconSize / 2
                    path.move(to: .init(x: x, y: WegoTokens.Metrics.tripChecklistIconSize))
                    path.addLine(to: .init(x: x, y: geometry.size.height + WegoTokens.Space.medium))
                }.stroke(section.isPersonal ? WegoTokens.Palette.accent : WegoTokens.Palette.divider,
                         style: StrokeStyle(lineWidth: WegoTokens.Metrics.hairlineWidth, dash: section.isPersonal ? [WegoTokens.Space.xSmall] : []))
                    .opacity(last ? 0 : 1)
            }.allowsHitTesting(false)
            marker(stop).frame(width: WegoTokens.Metrics.tripChecklistIconSize, height: WegoTokens.Metrics.tripChecklistIconSize)
                .accessibilityHidden(true)
            }
        }
    }

    @ViewBuilder private func marker(_ stop: RouteStop) -> some View {
        if isJoin(stop) { Image(systemName: "diamond.fill").foregroundStyle(WegoTokens.Palette.ink) }
        else if stop.state == .arrived { Image(systemName: "checkmark.circle.fill").foregroundStyle(WegoTokens.Palette.accent) }
        else {
            Circle().fill(WegoTokens.Palette.background).frame(width: WegoTokens.Metrics.courseSummaryDotSize, height: WegoTokens.Metrics.courseSummaryDotSize)
                .overlay { Circle().strokeBorder(stop.state == .next ? WegoTokens.Palette.accent : WegoTokens.Palette.personalRouteBorder, lineWidth: stop.state == .next ? WegoTokens.Metrics.timelineWidth : WegoTokens.Metrics.hairlineWidth) }
                .padding(WegoTokens.Space.xSmall)
                .background(stop.state == .next ? WegoTokens.Palette.accentSoft : .clear, in: Circle())
        }
    }
    private func progressStops(_ section: TripFullRouteSection) -> [RouteStop] {
        section.id == "pickup" ? section.stops.filter { !isJoin($0) } : section.stops
    }
    private var myDropMissing: Bool {
        detail.myCar?.iRide == true && sections.first { $0.id == "drop" }?.stops.contains(where: isMine) != true
    }
    private func isJoin(_ stop: RouteStop) -> Bool {
        guard let point = detail.myCar?.routePlan?.joinPoint else { return false }
        return stop.id == "course:\(point.courseId):\(point.ref)"
    }
    private func isMine(_ stop: RouteStop) -> Bool {
        guard let me = detail.me?.id else { return false }
        return detail.myCar?.places.contains { place in
            place.selectedBy?.contains(me) == true && stop.id == "\(place.kind?.rawValue ?? "")::\(place.id ?? "")"
        } == true
    }
}

private func tripJoinETALabel(_ seconds: Int?) -> String {
    guard let seconds else { return "도착 예상 시간 미제공" }
    let duration = Duration.seconds(seconds).formatted(.units(allowed: [.hours, .minutes, .seconds], width: .abbreviated))
    return "합류까지 약 " + duration
}
