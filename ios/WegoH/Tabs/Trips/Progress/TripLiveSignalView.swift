import SwiftUI
import Observation

@MainActor @Observable
final class TripLiveSignalStore {
    enum Step { case reason, places, response }
    var reason: TripSignalReason = .restroom
    var facilities: Set<TripSignalFacility> = [.restroom]
    var selectedID: String?
    private(set) var step: Step = .reason
    private var loadedCandidates: [IPhoneTripSignalCandidate] = []
    var candidates: [IPhoneTripSignalCandidate] { preparation.accountIsCurrent && preparation.detail?.myCar?.id == loadedCarID ? loadedCandidates : [] }
    private(set) var basis: String?
    private(set) var leadCarID: String?
    private(set) var partial = false
    private var loadedSignal: IPhoneTripSignal?
    /// 이 시트에서 보낸 손들기 id. 보낸 직후 목록 조회가 실패해도 새로고침이 같은 요청을 찾게 지역 변수가 아닌 속성으로 든다.
    private(set) var sentSignalID: String?
    private var loadedCarID: String?
    var signal: IPhoneTripSignal? { preparation.accountIsCurrent && preparation.detail?.myCar?.id == loadedCarID ? loadedSignal : nil }
    private(set) var busy = false
    private(set) var message: String?
    private(set) var needsRefresh = false
    let preparation: TripPreparationStore
    private let api: any IPhoneTripActivityServing
    private let location = TripSignalLocation()
    private let locationProvider: (() async throws -> TripSignalLocation.Point)?
    var selected: IPhoneTripSignalCandidate? { candidates.first { $0.id == selectedID } }
    var canSend: Bool { !busy && !needsRefresh && preparation.accountIsCurrent && step == .places && (selectedID == nil || selected != nil) && preparation.detail?.canUseTripSignals == true }
    var isSender: Bool { signal?.accountId == preparation.detail?.me?.id }
    var canRespond: Bool { !busy && !needsRefresh && preparation.accountIsCurrent && signal?.canRespond == true && signal?.inProgress == true && signal?.resolution == "pending" }

    init(preparation: TripPreparationStore, api: any IPhoneTripActivityServing = IPhoneTripActivityAPI(), locationProvider: (() async throws -> TripSignalLocation.Point)? = nil) {
        self.preparation = preparation; self.api = api; self.locationProvider = locationProvider
    }
    func next() {
        guard !busy, !needsRefresh else { return }
        facilities = switch reason { case .restroom: [.restroom]; case .nursing: [.nursing]; case .charging: [.charging]; case .fuel: [.fuel]; default: [] }
        loadedCandidates = []; selectedID = nil; basis = nil; leadCarID = nil; step = .places
    }
    func back() { guard !busy, !needsRefresh else { return }; step = .reason }
    func toggle(_ facility: TripSignalFacility) {
        guard !busy else { return }
        if facilities.contains(facility) { facilities.remove(facility) } else { facilities.insert(facility) }
        loadedCandidates = []; selectedID = nil; basis = nil; leadCarID = nil
    }
    func refresh() async {
        await work {
            guard let tripID = self.preparation.detail?.id else { throw IPhoneSessionError.invalidSession }
            let items = try await self.preparation.activityRequest { try await self.api.signals(tripID, token: $0) }
            // send와 같은 순서: 내가 보낸 요청을 먼저 유지하고, 없을 때만 진행 중 손들기·보고 있던 손들기를 고른다.
            self.loadedSignal = items.first { $0.id == self.sentSignalID } ?? items.first(where: \.inProgress)
                ?? items.first(where: { $0.id == self.signal?.id })
            self.needsRefresh = false
            if self.loadedSignal != nil { self.step = .response }
        }
    }
    func search() async {
        await work {
            guard let detail = self.preparation.detail, detail.state == .active else { throw IPhoneSessionError.invalidSession }
            guard detail.canUseTripSignals else { throw IPhoneTripRequestError.routeConflict(detail.myCar == nil ? "TRIP_SIGNAL_CAR_REQUIRED" : "TRIP_SIGNAL_ROUTE_FINISHED") }
            let point: TripSignalLocation.Point
            if let provider = self.locationProvider { point = try await provider() }
            else { point = try await self.location.current() }
            let result = try await self.preparation.activityRequest {
                try await self.api.candidates(detail.id, reason: self.reason, facilities: self.facilities,
                    location: point, destination: detail.courses.last?.stops?.last, token: $0)
            }
            self.loadedCandidates = result.candidates.filter { $0.verdict == "ahead" }
            self.loadedCandidates = self.loadedCandidates.filter { candidate in self.facilities.allSatisfy { candidate.facilities?[$0.serverID] == true } }
            self.leadCarID = result.cars?.filter { $0.state == "same_road" && $0.alongMeters?.isFinite == true }.max { ($0.alongMeters ?? 0) < ($1.alongMeters ?? 0) }?.carId
            self.basis = result.basis; self.partial = result.partial; self.selectedID = nil
        }
    }
    func send() async {
        guard canSend else { return }
        await work {
            guard let id = self.preparation.detail?.id else { throw IPhoneSessionError.invalidSession }
            let sentID = try await self.preparation.activityRequest { try await self.api.send(id, reason: self.reason, destination: self.selected?.destination,
                candidateReceipt: self.selected?.candidateReceipt, token: $0) }
            self.sentSignalID = sentID
            self.needsRefresh = true; self.step = .response
            let items = try await self.preparation.activityRequest { try await self.api.signals(id, token: $0) }
            // 다른 차 동의가 필요 없으면 서버가 바로 경로에 넣어 inProgress=false로 끝난다. 보낸 id로 결과를 찾는다.
            self.loadedSignal = items.first { $0.id == sentID } ?? items.first(where: \.inProgress); self.step = .response
            self.needsRefresh = false
            await self.preparation.load()
        }
    }
    func vote(agree: Bool) async {
        guard canRespond, let signal else { return }
        await work {
            guard let id = self.preparation.detail?.id else { throw IPhoneSessionError.invalidSession }
            let already = try await self.preparation.activityRequest { try await self.api.vote(id, signalID: signal.id, agree: agree, token: $0) }
            self.needsRefresh = true
            let items = try await self.preparation.activityRequest { try await self.api.signals(id, token: $0) }
            self.loadedSignal = items.first { $0.id == signal.id }
            self.needsRefresh = false
            if already { self.message = "우리 차에서 이미 응답했어요." }
            await self.preparation.load()
        }
    }
    func finish(cancelled: Bool) async {
        guard !busy, !needsRefresh, isSender, let signal, signal.inProgress else { return }
        await work {
            guard let id = self.preparation.detail?.id else { throw IPhoneSessionError.invalidSession }
            try await self.preparation.activityRequest { try await self.api.finish(id, signalID: signal.id, cancelled: cancelled, token: $0) }
            self.needsRefresh = true
            let items = try await self.preparation.activityRequest { try await self.api.signals(id, token: $0) }
            self.loadedSignal = items.first { $0.id == signal.id }
            self.needsRefresh = false
            await self.preparation.load()
        }
    }
    func stop() { location.cancel() }
    private func work(_ operation: () async throws -> Void) async {
        guard !busy, preparation.accountIsCurrent else { return }
        let carID = preparation.detail?.myCar?.id
        loadedCarID = carID
        busy = true; message = nil
        defer { busy = false }
        do {
            try await operation()
            if preparation.detail?.myCar?.id != carID { loadedSignal = nil; sentSignalID = nil; loadedCandidates = [] }
        }
        catch is CancellationError { }
        catch {
            message = needsRefresh ? "응답은 저장했지만 최신 손들기를 불러오지 못했어요. 새로고침해 주세요." : tripPreparationErrorMessage(error)
            if !preparation.accountIsCurrent || tripActivityAccessLost(error) {
                loadedSignal = nil; sentSignalID = nil; loadedCandidates = []; selectedID = nil
                await preparation.load()
            }
        }
    }
}

struct TripLiveSignalView: View {
    @State private var store: TripLiveSignalStore
    @Environment(\.dismiss) private var dismiss
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    init(preparation: TripPreparationStore, api: IPhoneTripActivityAPI = .init()) { _store = State(initialValue: TripLiveSignalStore(preparation: preparation, api: api)) }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
                if store.busy { WegoLoadingView("확인 중", layout: .row) }
                if let message = store.message { Text(message).font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.secondary) }
                if let detail = store.preparation.detail, !detail.canUseTripSignals { Text(detail.signalAvailabilityExplanation).font(WegoTokens.Typography.label) }
                switch store.step {
                case .reason: reasons
                case .places: places
                case .response: response
                }
            }.padding(WegoTokens.Space.screen)
        }
        .foregroundStyle(WegoTokens.Palette.text).background(WegoTokens.Palette.background)
        .scrollBounceBehavior(.always, axes: .vertical)
        .refreshable { await store.refresh() }
        .navigationTitle(store.step == .reason ? "손들기 1/2" : store.step == .places ? "손들기 2/2" : "손들기")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) { Button(store.step == .places ? "이유" : "닫기") { if store.step == .places { store.back() } else { dismiss() } }.disabled(store.busy) }
            if store.step == .response {
                ToolbarItem(placement: .topBarTrailing) {
                    Button { Task { await store.refresh() } } label: {
                        Image(systemName: "arrow.clockwise")
                            .frame(minWidth: WegoTokens.Metrics.touchTarget, minHeight: WegoTokens.Metrics.touchTarget)
                            .contentShape(Circle())
                    }.accessibilityLabel("새로고침").disabled(store.busy)
                }
            }
        }
        .safeAreaInset(edge: .bottom) { footer.padding(WegoTokens.Space.screen).background(WegoTokens.Palette.background) }
        .task { await store.refresh() }.onDisappear { store.stop() }
        .onReceive(NotificationCenter.default.publisher(for: TripSignalInbox.responseChanged)) { event in
            guard event.object as? String == store.preparation.detail?.id else { return }
            Task { await store.refresh() }
        }
    }
    private var reasons: some View {
        VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
            Text("무엇이 필요하세요?").font(WegoTokens.Typography.title)
            Text("하나를 고르면 일행 모두에게 알리고, 들를 곳을 함께 정해요.")
                .font(WegoTokens.Typography.body).foregroundStyle(WegoTokens.Palette.secondary)
            LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: WegoTokens.Space.small), count: dynamicTypeSize.isAccessibilitySize ? 1 : 3), spacing: WegoTokens.Space.small) {
                ForEach(TripSignalReason.allCases) { reason in
                    Button { store.reason = reason } label: {
                        VStack(spacing: WegoTokens.Space.small) {
                            if reason != .smoking {
                                Image(systemName: reason.symbol).font(WegoTokens.Typography.cardTitle).accessibilityHidden(true)
                            }
                            Text(reason.title).font(WegoTokens.Typography.label.weight(.semibold))
                        }.padding(WegoTokens.Space.compact).frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.tripSignalReasonTileHeight)
                            .background(store.reason == reason ? WegoTokens.Palette.accentSoft : WegoTokens.Palette.background,
                                        in: RoundedRectangle(cornerRadius: WegoTokens.Radius.control))
                            .overlay { RoundedRectangle(cornerRadius: WegoTokens.Radius.control).strokeBorder(store.reason == reason ? WegoTokens.Palette.accent : WegoTokens.Palette.divider) }
                            .contentShape(Rectangle())
                    }.buttonStyle(.plain).foregroundStyle(store.reason == reason ? WegoTokens.Palette.accent : WegoTokens.Palette.text)
                        .disabled(store.busy).accessibilityAddTraits(store.reason == reason ? .isSelected : [])
                        .accessibilityIdentifier("liveSignalReason-\(reason.serverKind)")
                }
            }
            WegoCard(.surface) {
                HStack(alignment: .top, spacing: WegoTokens.Space.compact) {
                    Image(systemName: "car.side").font(WegoTokens.Typography.section)
                        .foregroundStyle(WegoTokens.Palette.accent).accessibilityHidden(true)
                    Text("들를 곳은 맨 앞 차 기준으로 찾아요. 그래야 지나치지 않고 뒤차도 따라갈 수 있어요.")
                        .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                }
            }
        }
    }
    private var places: some View {
        VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
            Text("어디에 들를까요?").font(WegoTokens.Typography.title)
            Text(store.basis == "heading" ? "내 차 기준으로 앞에 있는 곳이에요." : store.leadCarID.map { "맨 앞 차(\(numbered($0, fallback: "일행 차량")))보다 앞에 있는 곳이에요." } ?? "맨 앞 차보다 앞에 있는 곳을 찾아요.")
                .font(WegoTokens.Typography.label)
            ScrollView(.horizontal) {
                HStack(spacing: WegoTokens.Space.small) {
                    ForEach(TripSignalFacility.allCases) { facility in
                        Button { store.toggle(facility) } label: {
                            Text((store.facilities.contains(facility) ? "✓ " : "") + facility.title)
                                .font(WegoTokens.Typography.caption).padding(WegoTokens.Space.small)
                                .frame(minHeight: WegoTokens.Metrics.touchTarget)
                                .foregroundStyle(store.facilities.contains(facility) ? WegoTokens.Palette.onInk : WegoTokens.Palette.text)
                                .background(store.facilities.contains(facility) ? WegoTokens.Palette.ink : WegoTokens.Palette.background, in: Capsule())
                                .overlay { Capsule().strokeBorder(store.facilities.contains(facility) ? .clear : WegoTokens.Palette.divider,
                                                                  lineWidth: WegoTokens.Metrics.hairlineWidth) }
                                .contentShape(Rectangle())
                        }.buttonStyle(.plain).disabled(store.busy).accessibilityAddTraits(store.facilities.contains(facility) ? .isSelected : [])
                    }
                }
            }
            Button { Task { await store.search() } } label: {
                Text("현재 위치로 후보 찾기").font(WegoTokens.Typography.action)
                    .frame(minHeight: WegoTokens.Metrics.touchTarget).contentShape(Rectangle())
            }.disabled(store.busy)
            Text("위치는 이번 검색에만 사용해요. 선택한 시설을 모두 갖춘 곳만 보여요.")
                .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
            if store.basis != nil {
                Text("조건에 맞는 곳 \(store.candidates.count)곳" + (store.partial ? " · 일부 결과" : ""))
                    .font(WegoTokens.Typography.caption)
            }
            ForEach(store.candidates) { candidate in
                Button { store.selectedID = candidate.id } label: {
                    VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                        HStack {
                            Text(candidate.name).font(WegoTokens.Typography.section)
                            Spacer()
                            if let meters = candidate.fromLeadMeters {
                                Text(String(format: "%.1fkm 앞", meters / 1000)).font(WegoTokens.Typography.label.weight(.semibold))
                                    .foregroundStyle(store.selectedID == candidate.id ? WegoTokens.Palette.accent : WegoTokens.Palette.text)
                            }
                            Image(systemName: store.selectedID == candidate.id ? "checkmark.circle.fill" : "circle")
                                .foregroundStyle(store.selectedID == candidate.id ? WegoTokens.Palette.accent : WegoTokens.Palette.divider)
                        }
                        if let seconds = candidate.detourSeconds { Text("들르면 \(seconds >= 0 ? "+" : "")\(Int(ceil(seconds / 60)))분").font(WegoTokens.Typography.caption) }
                        let road = [candidate.routeName, candidate.direction].compactMap { $0 }.joined(separator: " · ")
                        if !road.isEmpty { Text(road).font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary) }
                        Text(TripSignalFacility.allCases.filter { candidate.facilities?[$0.serverID] == true }.map(\.title).joined(separator: " · "))
                            .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                    }.tripProgressCard(selected: store.selectedID == candidate.id)
                }.buttonStyle(.plain).disabled(store.busy)
                    .accessibilityAddTraits(store.selectedID == candidate.id ? .isSelected : [])
            }
            Button { store.selectedID = nil } label: {
                HStack { Text("아무 데나 세워 주세요"); Spacer(); Image(systemName: store.selectedID == nil ? "checkmark.circle.fill" : "circle") }
                    .font(WegoTokens.Typography.section).tripProgressCard(selected: store.selectedID == nil)
            }.buttonStyle(.plain).disabled(store.busy)
            if let selected = store.selected {
                Text("모든 차가 동의하면 \(selected.name)이 다음 목적지 앞에 추가돼요.").font(WegoTokens.Typography.label)
                if let detail = store.preparation.detail, let car = detail.myCar {
                    let stops = proposedRouteStops(destinationName: selected.name, proposalID: selected.id, detail: detail, car: car)
                    if !stops.isEmpty {
                        SectionHeader("동의하면 이렇게 바뀌어요")
                        WegoCard(.surface) {
                            if stops.count <= 3 {
                                RouteStrip(stops: stops.map(\.title), progress: stops.firstIndex(where: { $0.state == .next }))
                            } else { RouteList(stops: stops) }
                        }
                    }
                }
            }
        }
    }
    private var response: some View {
        VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
            if let signal = store.signal {
                WegoCard(responseHasInk(signal) ? .ink : signal.resolution == "pending" ? .soft : .surface) {
                    VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                        Text(headline(signal)).font(WegoTokens.Typography.cardTitle)
                        Text(TripSignalReason.allCases.first { $0.serverKind == signal.kind }?.title ?? "손들기").font(WegoTokens.Typography.section)
                        if let requesterCarID = signal.requesterCarId {
                            Text(numbered(requesterCarID, fallback: "요청한 차")).font(WegoTokens.Typography.caption)
                        }
                        Text(signal.destination?.name ?? "장소는 운전자가 정해요").font(WegoTokens.Typography.body)
                        if let details = signal.candidateDetails {
                            let road = [details.routeName, details.direction].compactMap { $0 }.joined(separator: " · ")
                            if !road.isEmpty { Text(road).font(WegoTokens.Typography.caption) }
                            if let meters = details.fromLeadMeters, let seconds = details.detourSeconds {
                                Text(String(format: "맨 앞 차에서 %.1fkm 앞 · 들르면 %@%d분", Double(meters) / 1000,
                                            seconds >= 0 ? "+" : "", Int(ceil(Double(seconds) / 60))))
                                    .font(WegoTokens.Typography.caption)
                            }
                            Text("장소 검색 당시의 예상 거리·시간이에요.").font(WegoTokens.Typography.caption)
                        }
                        if let counts = signal.groupVotes {
                            let required = counts.required ?? signal.groupResponses?.count ?? 0
                            StatusPill("동의 \(counts.agree)/\(required)", onInk: responseHasInk(signal))
                            if required > 0 && responseHasInk(signal) {
                                ProgressView(value: Double(counts.agree), total: Double(required))
                                    .tint(WegoTokens.Palette.routeHighlight)
                                    .accessibilityLabel("다른 차 동의")
                                    .accessibilityValue("\(required)대 중 \(counts.agree)대")
                            }
                        }
                        if signal.resolution == "agreed", let detail = store.preparation.detail, let car = detail.myCar {
                            let stops = agreedRouteStops(detail, car: car)
                            if !stops.isEmpty { RouteList(stops: stops, onInk: true) }
                        }
                    }
                }
                if signal.resolution == "pending", !store.isSender,
                   let detail = store.preparation.detail, let car = detail.myCar {
                    let stops = proposedRouteStops(signal, detail: detail, car: car)
                    if !stops.isEmpty {
                        SectionHeader("동의하면 이렇게 바뀌어요")
                        WegoCard(.surface) {
                            if stops.count <= 3 {
                                RouteStrip(stops: stops.map(\.title), progress: stops.firstIndex(where: { $0.state == .next }))
                            } else { RouteList(stops: stops) }
                        }
                    }
                }
                if signal.waitsForRequester {
                    Text(store.isSender ? "차를 세우면 손들기 완료를 눌러 주세요." : "세울 곳은 운전자가 정해요.").font(WegoTokens.Typography.label)
                }
                if !(signal.groupResponses ?? []).isEmpty { Text("그룹별 응답").font(WegoTokens.Typography.section) }
                ForEach(signal.groupResponses ?? []) { group in
                    HStack(spacing: WegoTokens.Space.compact) {
                        if let driver = store.preparation.detail?.cars.first(where: { $0.id == group.carId })?.driverName {
                            AvatarBadge(name: driver, tone: .ink)
                        }
                        VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                            Text(numbered(group.carId, fallback: group.carName)).font(WegoTokens.Typography.section)
                            if let name = group.responderName {
                                Text(group.responseSource == "iphone" ? "\(name)님이 iPhone에서 답함" : "\(name)님이 응답했어요")
                                    .font(WegoTokens.Typography.caption)
                            }
                        }
                        Spacer()
                        StatusPill(group.choice == "agree" ? "동의" : group.choice == "pass" ? "다음에" : "응답 대기 중",
                                   tone: group.choice == "agree" ? .soft : .neutral)
                    }
                    .padding(.vertical, WegoTokens.Space.small)
                    Divider().overlay(WegoTokens.Palette.divider)
                }
                if signal.resolution == "agreed" {
                    Text("각 차의 다음 목적지 앞에 추가됐어요. 안내는 차 화면에서 시작해 주세요.").font(WegoTokens.Typography.label)
                }
                if signal.resolution == "passed" {
                    Text("다음에를 고른 차가 있어 요청을 마쳤어요. 경로는 그대로예요.").font(WegoTokens.Typography.label)
                    if let detail = store.preparation.detail, let car = detail.myCar {
                        let stops = agreedRouteStops(detail, car: car, courseID: (car.routePlan?.next ?? car.routeNext)?.courseId)
                        if !stops.isEmpty {
                            SectionHeader("경로는 그대로예요")
                            WegoCard(.surface) {
                                if stops.count <= 3 {
                                    RouteStrip(stops: stops.map(\.title), progress: stops.firstIndex(where: { $0.state == .next }))
                                } else { RouteList(stops: stops) }
                            }
                        }
                    }
                }
                if let caption = signal.responseUnavailableCaption(isSender: store.isSender, canRespond: store.canRespond) {
                    Text(caption).font(WegoTokens.Typography.caption)
                }
            } else { Text("진행 중인 손들기를 다시 확인해 주세요.").font(WegoTokens.Typography.label) }
        }
    }
    private func responseHasInk(_ signal: IPhoneTripSignal) -> Bool {
        (signal.resolution == "pending" && store.isSender) || signal.resolution == "agreed"
    }

    private func proposedRouteStops(_ signal: IPhoneTripSignal, detail: IPhoneTripDetail, car: IPhoneTripCar) -> [RouteStop] {
        guard let destination = signal.destination else { return [] }
        return proposedRouteStops(destinationName: destination.name, proposalID: signal.id, detail: detail, car: car)
    }

    private func proposedRouteStops(destinationName: String, proposalID: String, detail: IPhoneTripDetail, car: IPhoneTripCar) -> [RouteStop] {
        let courseID = (car.routePlan?.next ?? car.routeNext)?.courseId
        var stops = agreedRouteStops(detail, car: car, courseID: courseID)
        guard let nextIndex = stops.firstIndex(where: { $0.state == .next }) else { return [] }
        stops[nextIndex].state = .planned
        stops.insert(RouteStop(id: "proposed-" + proposalID, title: destinationName,
                               subtitle: "동의하면 추가할 장소", state: .next), at: nextIndex)
        return stops
    }

    private func agreedRouteStops(_ detail: IPhoneTripDetail, car: IPhoneTripCar, courseID: String? = nil) -> [RouteStop] {
        let order = car.routeOrder ?? []
        let next = car.routePlan?.next ?? car.routeNext
        let nextIndex = next.flatMap { order.firstIndex(of: $0) }
        return order.enumerated().compactMap { index, item in
            if let courseID, item.courseId != courseID { return nil }
            let name = item.type == "course"
                ? detail.courses.first(where: { $0.id == item.courseId })?.stops?.first(where: { $0.id == item.ref })?.name
                : car.places.first(where: { $0.id == item.ref })?.name
            guard let name else { return nil }
            let state: RouteStop.State
            if let nextIndex { state = index < nextIndex ? .arrived : index == nextIndex ? .next : .planned }
            else { state = .planned }
            return RouteStop(id: item.type + ":" + (item.courseId ?? "") + ":" + item.ref,
                             title: name, subtitle: item.type == "signal" ? "손들기" : nil, state: state)
        }
    }

    @ViewBuilder private var footer: some View {
        if store.step == .reason { ActionButton(title: "다음") { store.next() }.disabled(store.busy) }
        else if store.step == .places { ActionButton(title: "\(store.reason.title) 요청 보내기") { Task { await store.send() } }.disabled(!store.canSend) }
        else if let signal = store.signal {
            if store.canRespond {
                HStack(spacing: WegoTokens.Space.small) {
                    Button { Task { await store.vote(agree: false) } } label: {
                        Text("다음에").font(WegoTokens.Typography.action)
                            .frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.tripSignalResponseButtonHeight)
                            .contentShape(Rectangle())
                            .overlay { RoundedRectangle(cornerRadius: WegoTokens.Radius.control).strokeBorder(WegoTokens.Palette.divider) }
                    }
                    Button { Task { await store.vote(agree: true) } } label: {
                        Text("동의").font(WegoTokens.Typography.action).foregroundStyle(WegoTokens.Palette.onAccent)
                            .frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.tripSignalResponseButtonHeight)
                            .contentShape(Rectangle())
                    }.buttonStyle(WegoPrimaryButtonStyle())
                }.disabled(store.busy)
            } else if store.isSender && signal.inProgress {
                // safeAreaInset은 여러 뷰를 겹쳐 그리므로 완료·취소를 한 묶음으로 세로 배치한다.
                VStack(spacing: WegoTokens.Space.small) {
                    if signal.resolution == "agreed" || signal.waitsForRequester {
                        ActionButton(title: "손들기 완료") { Task { await store.finish(cancelled: false) } }
                    }
                    Button("손들기 취소", role: .destructive) { Task { await store.finish(cancelled: true) } }
                        .buttonStyle(.wego(.soft))
                }.disabled(store.busy)
            } else { ActionButton(title: "확인") { dismiss() } }
        }
    }
    private func headline(_ signal: IPhoneTripSignal) -> String {
        switch signal.resolution {
        case "agreed": "다음 목적지 앞에 추가했어요"
        case "passed": "다음에 들르기로 했어요"
        case "completed": "손들기를 마쳤어요"
        case "cancelled": "손들기를 취소했어요"
        case "reconfirm": "여행 상태가 바뀌었어요"
        default:
            if store.isSender && signal.waitsForRequester { "운전자에게 요청했어요" }
            else if store.canRespond || signal.waitsForRequester { "\(store.preparation.detail?.members.first { $0.id == signal.accountId }?.name ?? "일행")님이 손을 들었어요" }
            else { "동의 기다리는 중" }
        }
    }
    private func numbered(_ id: String, fallback: String) -> String {
        guard let detail = store.preparation.detail, let car = detail.cars.first(where: { $0.id == id }) else { return fallback }
        return detail.numberedName(car) + (car.id == detail.myCar?.id ? " · 우리 차" : "")
    }
}
