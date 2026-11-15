import SwiftUI

struct TripProgressView: View {
    let detail: IPhoneTripDetail
    let isPreview: Bool
    let courseStops: [String: [String]]
    var preparation: TripPreparationStore? = nil
    var versusAPI = IPhoneTripDrivingVersusAPI()
    var musicAPI: any IPhoneTripMusicServing = IPhoneTripMusicAPI()
    var voice: TripVoiceStore? = nil
    @Binding var remotePreferences: TripRemotePreferences
    @State private var signal = TripSignalPreviewStore()
    @State private var sheet: ProgressSheet?
    @State private var permissionDraft = TripRemotePreferences()
    @State private var carPositions: IPhoneTripLocations?
    @Environment(\.scenePhase) private var scenePhase

    private enum ProgressSheet: String, Identifiable {
        case signal, remote, permissions, locations, versus, music, cars
        var id: Self { self }
    }
    var body: some View {
        VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
            if isPreview {
                HStack {
                    Text("디자인 미리보기 · 실제 차량·위치·음성을 사용하지 않아요.")
                        .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                    Spacer(minLength: 0)
                    Menu {
                        Button("받은 손들기 요청 보기") { signal.showReceived(); sheet = .signal }.disabled(signal.isOpen)
                        Button("운전자 리모컨 허용 화면 보기") { sheet = .permissions }
                    } label: { Image(systemName: "ellipsis.circle").frame(minWidth: WegoTokens.Metrics.touchTarget, minHeight: WegoTokens.Metrics.touchTarget) }
                        .accessibilityLabel("미리보기 시나리오").accessibilityIdentifier("tripProgressScenarios")
                }
            }
            if let car = detail.myCar { myCarCard(car) }
            else { Text("이 여행에서 선택한 차가 없어요.").font(WegoTokens.Typography.label) }
            if !isPreview {
                TripRouteMap(detail: detail, showsTitle: false, onPresentation: { showing in
                    if showing { voice?.deactivate() }
                    else { Task { await voice?.activate() } }
                }, cars: carMarkers)
            }
            TripRoutePhaseContent(detail: detail)
            if !otherCars.isEmpty {
                Text("다른 차").font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.secondary)
                ForEach(otherCars) { car in
                    Button { sheet = .cars } label: { otherCarRow(car) }
                        .buttonStyle(.plain).accessibilityIdentifier("tripProgressCar-" + car.id)
                }
            }
            Text("함께 즐기기").font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.secondary)
            VStack(spacing: 0) {
                if let preparation, detail.myCar != nil {
                    TripDrivingVersusSummary(preparation: preparation, api: versusAPI, compact: true)
                }
                if preparation != nil && !isPreview {
                    Button { sheet = .music } label: {
                        activityRow("여행 플레이리스트", systemImage: "music.note.list")
                    }.buttonStyle(.plain).accessibilityIdentifier("tripProgressMusic")
                }
                Button { sheet = .locations } label: {
                    activityRow("일행 위치", systemImage: "mappin.circle")
                }.buttonStyle(.plain).accessibilityIdentifier("tripProgressLocations")
            }
            .padding(WegoTokens.Space.small)
            .background(WegoTokens.Palette.surface, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.control))
        }
        .task(id: carPollKey) { await pollCarPositions() }
        .onChange(of: sheet) { _, value in
            if value != nil { voice?.deactivate() }
            if value == .permissions { permissionDraft = remotePreferences }
        }
        .sheet(item: $sheet, onDismiss: { Task { await voice?.activate() } }) { destination in
            if destination == .remote, !isPreview, let preparation { TripLiveRemoteView(preparation: preparation) }
            else { NavigationStack {
                switch destination {
                case .cars: if let preparation { TripCarsView(store: preparation) }
                case .versus: if let preparation { TripDrivingVersusView(preparation: preparation, api: versusAPI) }
                case .music: if let preparation { TripMusicView(preparation: preparation, api: musicAPI) }
                case .signal: if isPreview { TripSignalPreviewView(store: signal) }
                case .remote:
                    if isPreview { TripRemotePreviewView(carName: detail.myCar.map { detail.numberedName($0) } ?? "샘플 차량", ownerName: detail.myCar?.driverName ?? "운전자", preferences: remotePreferences) }
                case .permissions:
                    if !isPreview, let preparation { TripRemotePolicyView(store: preparation) }
                    else {
                    ScrollView {
                        VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
                            Text("운전자 화면 미리보기 · 실제 허용은 변경하지 않아요.")
                                .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                            TripRemotePermissionSection(preferences: $permissionDraft)
                        }.padding(WegoTokens.Space.screen)
                    }
                    .background(WegoTokens.Palette.background).navigationTitle("동승자 리모컨")
                    .toolbar {
                        ToolbarItem(placement: .confirmationAction) {
                            Button("완료") { remotePreferences = permissionDraft; sheet = nil }.disabled(!permissionDraft.isValid)
                        }
                        ToolbarItem(placement: .cancellationAction) { Button("취소") { sheet = nil } }
                    }
                    }
                case .locations:
                    if let preparation, !isPreview { TripMemberLocationsView(store: preparation) }
                    else {
                    VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
                        Text(isPreview ? "디자인 미리보기 · 실제 위치는 조회하거나 전송하지 않아요." : "일행 지도 표시는 연결 준비 중이에요.")
                            .font(WegoTokens.Typography.body)
                        Spacer()
                    }.padding(WegoTokens.Space.screen).background(WegoTokens.Palette.background)
                        .navigationTitle("일행 위치")
                        .toolbar { ToolbarItem(placement: .cancellationAction) { Button("닫기") { sheet = nil } } }
                    }
                }
            } }
        }
    }

    private var otherCars: [IPhoneTripCar] { detail.cars.filter { $0.id != detail.myCar?.id } }
    private var carMarkers: [WegoMapMarker] { TripRouteMap.otherCarMarkers(detail: detail, page: carPositions) }
    private var carPollKey: String { "\(detail.id)|\(detail.state == .active)|\(scenePhase == .active)|\(preparation?.accountIsCurrent == true)" }

    private func carLocationCaption(_ car: IPhoneTripCar) -> String? {
        guard let page = carPositions, let position = page.cars.first(where: { $0.carId == car.id }) else { return nil }
        return (page.age(of: position) ?? 0) > tripCarLocationStaleSeconds ? "지도에 이전 위치 표시" : "지도에 현재 위치 표시"
    }

    /// 진행 중 여행 화면이 앞에 있을 때만 다른 차 위치를 읽는다. 실패하면 오래된 위치를 남기지 않는다.
    private func pollCarPositions() async {
        guard let preparation, !isPreview, detail.state == .active, scenePhase == .active, preparation.accountIsCurrent
        else { carPositions = nil; return }
        repeat {
            do {
                let page = try await preparation.locations()
                guard !Task.isCancelled else { return }
                carPositions = page.tripId == detail.id ? page : nil
            } catch is CancellationError { return }
            catch { carPositions = nil }
            do { try await Task.sleep(for: .seconds(tripCarLocationRefreshSeconds)) } catch { return }
        } while !Task.isCancelled
    }

    private func myCarCard(_ car: IPhoneTripCar) -> some View {
        WegoCard(.surface) {
            HStack(spacing: WegoTokens.Space.compact) {
                AvatarBadge(name: "\(car.ordinal ?? ((detail.cars.firstIndex { $0.id == car.id } ?? 0) + 1))호", tone: .ink,
                            size: WegoTokens.Metrics.tripMemberAvatarSize)
                VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                    Text(car.isMine ? "내가 운전하는 차" : "내가 탄 차")
                        .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.accent)
                    Text(detail.numberedName(car)).font(WegoTokens.Typography.section)
                }
                Spacer(minLength: 0)
                if car.driverVehicleReady {
                    Label("연결 차량", systemImage: "checkmark.circle.fill")
                        .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                }
            }
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(alignment: .top, spacing: WegoTokens.Space.medium) {
                    passenger(car.driverId, name: car.driverName, driver: true)
                    ForEach(car.passengers) { person in
                        passenger(person.id, name: person.name, driver: false)
                    }
                }
            }
            Button { sheet = car.isMine ? .permissions : .remote } label: {
                HStack(spacing: WegoTokens.Space.compact) {
                    Image(systemName: "slider.horizontal.3").accessibilityHidden(true)
                    VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                        Text(car.isMine ? "동승자 리모컨 허용" : "이 차 리모컨").font(WegoTokens.Typography.action)
                        Text(remoteSummary(car)).font(WegoTokens.Typography.caption)
                            .foregroundStyle(WegoTokens.Palette.onInkSecondary)
                    }.frame(maxWidth: .infinity, alignment: .leading)
                    Image(systemName: "chevron.right").font(WegoTokens.Typography.caption).accessibilityHidden(true)
                }
                .padding(WegoTokens.Space.compact)
                .frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.touchTarget, alignment: .leading)
                .foregroundStyle(WegoTokens.Palette.onInk)
                .background(WegoTokens.Palette.ink, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.field))
                .contentShape(Rectangle())
            }.buttonStyle(.plain)
                .disabled(preparation.map { $0.busy || $0.needsRefresh || !$0.accountIsCurrent } ?? !isPreview)
                .accessibilityIdentifier(car.isMine ? "tripLiveRemotePolicy" : "tripLiveRemote")
        }.accessibilityElement(children: .contain).accessibilityIdentifier("tripProgressMyCar")
    }

    private func passenger(_ id: String, name: String, driver: Bool) -> some View {
        let member = detail.members.first { $0.id == id }
        return VStack(spacing: WegoTokens.Space.xSmall) {
            AvatarBadge(name: name, tone: driver ? .ink : .neutral, size: WegoTokens.Metrics.tripMemberAvatarSize)
                .accessibilityHidden(true)
                .overlay { Circle().strokeBorder(member?.isMe == true ? WegoTokens.Palette.accent : .clear, lineWidth: WegoTokens.Metrics.hairlineWidth) }
            Text(name + (member?.isMe == true ? " · 나" : "")).font(WegoTokens.Typography.caption)
            Text((driver ? "운전" : "동승") + (member?.role.flatMap { $0 == .member ? nil : " · " + $0.title } ?? ""))
                .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
        }.accessibilityElement(children: .combine)
    }

    private func remoteSummary(_ car: IPhoneTripCar) -> String {
        let preferences = isPreview ? remotePreferences : TripRemotePreferences(policy: car.remotePolicy)
        let actions = isPreview ? preferences.policy.actions : car.remotePolicy?.actions ?? []
        if !preferences.enabled && preferences.disabledByVehicleChange { return tripRemoteVehicleChangeNotice }
        guard preferences.enabled, !actions.isEmpty else { return "현재 허용한 조작이 없어요" }
        let groups = TripRemoteGroup.allCases.filter { $0.actionIDs.contains(where: actions.contains) }.map(\.title).joined(separator: "·")
        return "\(groups) · \(car.driverName)님이 허용한 \(actions.count)개"
    }

    private func otherCarRow(_ car: IPhoneTripCar) -> some View {
        HStack(spacing: WegoTokens.Space.compact) {
            AvatarBadge(name: "\(car.ordinal ?? ((detail.cars.firstIndex { $0.id == car.id } ?? 0) + 1))호", tone: .ink,
                        size: WegoTokens.Metrics.tripMemberAvatarSize)
            VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                Text(detail.numberedName(car)).font(WegoTokens.Typography.label.weight(.semibold))
                Text(([car.driverName + " 운전"] + car.passengers.map(\.name)).joined(separator: " · "))
                    .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                if let caption = carLocationCaption(car) {
                    Label(caption, systemImage: "location.fill")
                        .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.accent)
                }
            }.frame(maxWidth: .infinity, alignment: .leading)
            if let summary = TripLiveProgressPresentation.companionSummary(car.routeStatus) {
                Text(summary).font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.accent)
                    .multilineTextAlignment(.trailing)
            }
            Image(systemName: "chevron.right").font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                .accessibilityHidden(true)
        }.padding(WegoTokens.Space.compact)
            .frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.touchTarget, alignment: .leading)
            .background(WegoTokens.Palette.background, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.control))
            .overlay { RoundedRectangle(cornerRadius: WegoTokens.Radius.control).strokeBorder(WegoTokens.Palette.divider, lineWidth: WegoTokens.Metrics.hairlineWidth) }
            .contentShape(Rectangle())
    }

    private func activityRow(_ title: String, systemImage: String) -> some View {
        HStack(spacing: WegoTokens.Space.compact) {
            Image(systemName: systemImage).foregroundStyle(WegoTokens.Palette.accent)
                .frame(width: WegoTokens.Metrics.tripChecklistIconSize).accessibilityHidden(true)
            Text(title).font(WegoTokens.Typography.label.weight(.semibold)).frame(maxWidth: .infinity, alignment: .leading)
            Image(systemName: "chevron.right").font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                .accessibilityHidden(true)
        }.padding(WegoTokens.Space.small)
            .frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.touchTarget, alignment: .leading)
            .contentShape(Rectangle())
    }
}
