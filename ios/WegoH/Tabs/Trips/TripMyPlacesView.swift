import SwiftUI

struct TripMyPlacesView: View {
    let store: TripPreparationStore
    var searchAPI: any IPhoneCourseServing = IPhoneCourseAPI()
    @Environment(SessionManager.self) private var session
    @Environment(\.dismiss) private var dismiss
    @State private var pickup: IPhoneTripPlaceSelection?
    @State private var drop: IPhoneTripPlaceSelection?
    @State private var dropAtPickup = true
    @State private var revision = 0
    @State private var carID: String?
    @State private var message: String?
    @State private var searchKind: Kind?
    private enum Kind: String, Identifiable { case pickup, drop; var id: Self { self } }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
                if let detail = store.detail, let car = detail.myCar {
                    WegoCard(.ink) {
                        HStack(alignment: .top, spacing: WegoTokens.Space.compact) {
                            AvatarBadge(name: car.driverName, tone: .neutral)
                            VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                                Text(detail.numberedName(car) + "에 타요").font(WegoTokens.Typography.cardTitle)
                                Text("정하면 운전자의 차량 화면 순서에 반영돼요.")
                                    .font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.onInkSecondary)
                            }
                        }
                    }
                    if !car.iRide { Text("동승자가 본인의 타는 곳과 내리는 곳을 정해요. 운전자는 차량 화면에서 우리 차 순서를 확인해 주세요.").font(WegoTokens.Typography.label) }
                    if locked { Text("출발한 여행의 타는 곳·내리는 곳은 바꿀 수 없어요.").font(WegoTokens.Typography.label) }
                    Text("타는 곳").font(WegoTokens.Typography.section)
                    choices(detail, car: car, kind: .pickup)
                    Text("내리는 곳").font(WegoTokens.Typography.section)
                    WegoCard(.surface) { Toggle(isOn: $dropAtPickup) {
                        VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                            Text("탄 곳에서 내리기").font(WegoTokens.Typography.section)
                            Text(selectionName(pickup, car: car) ?? "타는 곳을 먼저 골라 주세요").font(WegoTokens.Typography.label)
                        }
                    }.accessibilityIdentifier("tripDropAtPickup").disabled(!editable) }
                    if !dropAtPickup { choices(detail, car: car, kind: .drop) }
                    Text("운전자에게 따로 연락하지 않아도 돼요. 출발 전까지 정할 수 있어요.")
                        .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                    if let message {
                        Text(message).font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.danger).accessibilityIdentifier("tripMyPlacesError")
                        Button {
                            Task {
                                await store.load()
                                if store.detail != nil && !store.needsRefresh { carID = nil; initialize(); self.message = nil }
                            }
                        } label: {
                            Text("현재 선택 다시 불러오기").font(WegoTokens.Typography.action)
                                .frame(minHeight: WegoTokens.Metrics.touchTarget).contentShape(Rectangle())
                        }.foregroundStyle(WegoTokens.Palette.accent).disabled(store.busy).accessibilityIdentifier("tripMyPlacesReload")
                    }
                    if !draft.isValid { Text("장소를 고르거나, 탄 곳에서 내리기를 꺼 주세요. 장소 이름은 40자 이하여야 해요.").font(WegoTokens.Typography.caption) }
                } else { Text("현재 탈 차를 확인해 주세요.").font(WegoTokens.Typography.label) }
            }.padding(WegoTokens.Space.screen)
        }.foregroundStyle(WegoTokens.Palette.text).background(WegoTokens.Palette.background)
            .navigationTitle("타는 곳·내리는 곳").navigationBarTitleDisplayMode(.inline)
            .safeAreaInset(edge: .bottom) {
                Button { Task { await save() } } label: {
                    Group {
                        if store.busy { WegoButtonLoadingLabel("저장 중…", onAccent: true) }
                        else { Text("저장") }
                    }.font(WegoTokens.Typography.action)
                        .frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.primaryButtonHeight)
                }.buttonStyle(WegoPrimaryButtonStyle()).disabled(!editable || !draft.isValid)
                    .accessibilityIdentifier("tripMyPlacesSave").padding(WegoTokens.Space.screen).background(WegoTokens.Palette.background)
            }
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("취소") { dismiss() }.disabled(store.busy) } }
            .onAppear { initialize() }.interactiveDismissDisabled(store.busy)
            .sheet(item: $searchKind) { kind in NavigationStack {
                if store.isPreview { Text("샘플에서는 실제 장소 검색을 하지 않아요.").font(WegoTokens.Typography.label).padding(WegoTokens.Space.screen) }
                else if let account = session.current {
                    CoursePlaceSearchView(account: account, api: searchAPI) { place in
                        let value = IPhoneTripPlaceSelection.new(name: place.name, lat: place.lat, lng: place.lng)
                        if kind == .pickup { pickup = value } else { drop = value }
                    }
                }
            } }
    }
    private var locked: Bool { (store.detail?.routeContractVersion ?? 1) == 2 && store.detail?.state != .planned }
    private var editable: Bool { !store.busy && !store.needsRefresh && store.accountIsCurrent && store.detail?.myCar?.id == carID && store.detail?.myCar?.iRide == true && !locked }
    private var draft: IPhoneTripMyPlacesDraft { .init(revision: revision, pickup: pickup, drop: dropAtPickup ? nil : drop, dropAtPickup: dropAtPickup) }
    private func initialize() {
        guard carID == nil, let detail = store.detail, let car = detail.myCar else { return }
        carID = car.id; revision = detail.revision
        let selected = car.places.filter { $0.selectedBy?.contains(detail.me?.id ?? "") == true }
        let picked = selected.first { $0.kind == .pickup }, dropped = selected.first { $0.kind == .drop }
        pickup = picked.flatMap(\.id).map { .existing($0) }; drop = dropped.flatMap(\.id).map { .existing($0) }
        if let picked, let dropped { dropAtPickup = picked.lat == dropped.lat && picked.lng == dropped.lng }
        else { dropAtPickup = dropped == nil }
    }
    private func choices(_ detail: IPhoneTripDetail, car: IPhoneTripCar, kind: Kind) -> some View {
        VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
            Button { searchKind = kind } label: {
                Label("장소, 역, 주소 검색", systemImage: "magnifyingglass").font(WegoTokens.Typography.label)
                    .frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.touchTarget, alignment: .leading)
                    .padding(.horizontal, WegoTokens.Space.medium)
                    .padding(.vertical, WegoTokens.Space.small)
                    .background(WegoTokens.Palette.surface, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.control))
                    .contentShape(Rectangle())
            }.buttonStyle(.plain).disabled(!editable).accessibilityIdentifier("tripMyPlacesSearch-" + kind.rawValue)
            ForEach(Array(car.places.filter { $0.kind?.rawValue == kind.rawValue }.enumerated()), id: \.offset) { _, place in
                if let id = place.id {
                    Button { if kind == .pickup { pickup = .existing(id) } else { drop = .existing(id) } } label: {
                        HStack(alignment: .top) {
                            Image(systemName: "mappin.and.ellipse").font(WegoTokens.Typography.cardTitle)
                                .foregroundStyle(WegoTokens.Palette.accent)
                                .frame(minWidth: WegoTokens.Metrics.courseStopBadgeSize)
                                .accessibilityHidden(true)
                            VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                                Text(place.name).font(WegoTokens.Typography.section)
                                let others = detail.members.filter { !$0.isMe && place.selectedBy?.contains($0.id) == true }.map(\.name)
                                if !others.isEmpty { Text(others.joined(separator: ", ") + (kind == .pickup ? "님도 여기서 타요" : "님도 여기서 내려요"))
                                    .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.accent) }
                            }
                            Spacer()
                            Image(systemName: selection(kind) == .existing(id) ? "checkmark.circle.fill" : "circle").font(WegoTokens.Typography.cardTitle)
                                .foregroundStyle(selection(kind) == .existing(id) ? WegoTokens.Palette.accent : WegoTokens.Palette.divider)
                        }.frame(minHeight: WegoTokens.Metrics.touchTarget).contentShape(Rectangle())
                    }.buttonStyle(.plain).disabled(!editable).accessibilityValue(selection(kind) == .existing(id) ? "선택됨" : "선택 안 됨")
                        .accessibilityIdentifier("tripMyPlace-\(kind.rawValue)-\(id)")
                    Divider().overlay(WegoTokens.Palette.divider)
                }
            }
            if let selected = selection(kind), case .new(let name, _, _) = selected { Text("선택한 장소 · " + name).font(WegoTokens.Typography.label).tripProgressCard(selected: true) }
            Button { if kind == .pickup { pickup = nil; dropAtPickup = false } else { drop = nil } } label: {
                Text("나중에 정하기").font(WegoTokens.Typography.action)
                    .frame(minHeight: WegoTokens.Metrics.touchTarget).contentShape(Rectangle())
            }.disabled(!editable)
        }
    }
    private func selection(_ kind: Kind) -> IPhoneTripPlaceSelection? { kind == .pickup ? pickup : drop }
    private func selectionName(_ selection: IPhoneTripPlaceSelection?, car: IPhoneTripCar) -> String? {
        switch selection { case .existing(let id): car.places.first { $0.id == id }?.name; case .new(let name, _, _): name; case nil: nil }
    }
    private func save() async {
        guard editable, draft.isValid else { return }
        do { try await store.saveMyPlaces(draft); dismiss() }
        catch { message = tripPreparationErrorMessage(error) }
    }
}
