import SwiftUI

struct TripCarsView: View {
    let store: TripPreparationStore
    @Environment(\.dismiss) private var dismiss
    @State private var showsCreate = false
    @State private var message: String?
    @State private var confirmsLeave = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
                Text("차를 고르면 타는 곳·내리는 곳도 함께 보여요.").font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.secondary)
                if let detail = store.detail {
                    ForEach((detail.rideInvites ?? []).filter { $0.accountId == detail.me?.id }) { invite in
                        WegoCard(.soft) {
                            Text("\(detail.cars.first(where: { $0.id == invite.carId }).map { detail.numberedName($0) } ?? "일행의 차")에서 탑승을 초대했어요")
                                .font(WegoTokens.Typography.section)
                            HStack {
                                Button("거절") { respond(invite, accept: false) }.buttonStyle(.wego(.plain))
                                Button("이 차 타기") { respond(invite, accept: true) }.buttonStyle(.wego(.primary))
                            }
                        }.disabled(store.busy || store.needsRefresh)
                    }
                    Text("차 \(detail.cars.count)대").font(WegoTokens.Typography.section)
                    ForEach(detail.cars) { car in
                        let selected = car.isMine || car.iRide
                        let canRide = !detail.cars.contains(where: \.isMine) && !car.isMine && (car.iRide || car.passengers.count < car.seats)
                        TripPreparingCarCard(car: car.previewCard(named: detail.numberedName(car)), selected: selected,
                                             riders: detail.riders(in: car),
                                             selectedLabel: car.isMine ? "내가 운전하는 차" : "내가 탄 차",
                                             actionTitle: canRide ? (car.iRide ? "내리기" : detail.myCar == nil ? "이 차 타기" : "이 차로 바꾸기") : nil,
                                             action: canRide ? { Task {
                            do {
                                if car.iRide { confirmsLeave = true; return }
                                else { try await store.ride(carID: car.id) }
                                message = nil
                            } catch { message = error.localizedDescription }
                        } } : nil, roleMembers: detail.roleMembers(in: car))
                        .disabled(store.busy || store.needsRefresh)
                    }
                    if detail.cars.contains(where: \.isMine) {
                        Text("내가 운전하는 차가 있어요. 다른 차의 동승자로 바꿀 수 없어요.")
                            .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                    }
                    if !detail.unassigned.isEmpty { TripUnassignedMembers(names: detail.unassigned.map(\.name)) }
                }
                if let message { Text(message).font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.danger) }
            }
            .padding(WegoTokens.Space.screen)
        }
        .background(WegoTokens.Palette.background)
        .foregroundStyle(WegoTokens.Palette.text)
        .navigationTitle("탈 차 고르기").navigationBarTitleDisplayMode(.inline)
        .toolbar { ToolbarItem(placement: .cancellationAction) { Button("완료") { dismiss() } } }
        .safeAreaInset(edge: .bottom) {
            if store.detail?.cars.contains(where: \.isMine) == false {
                Button { showsCreate = true } label: {
                    Label("내 차로 운전할게요", systemImage: "plus").font(WegoTokens.Typography.action)
                        .frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.primaryButtonHeight)
                        .foregroundStyle(WegoTokens.Palette.accent)
                        .background(WegoTokens.Palette.accentSoft, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.control))
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain).disabled(store.busy)
                .padding(WegoTokens.Space.screen).background(WegoTokens.Palette.background)
            }
        }
        .sheet(isPresented: $showsCreate) { NavigationStack { TripCarCreateHost(store: store) } }
        .alert("이 차에서 내릴까요?", isPresented: $confirmsLeave) {
            Button("취소", role: .cancel) { }
            Button("내리기", role: .destructive) {
                Task { do { try await store.leaveCar(); message = nil } catch { message = tripPreparationErrorMessage(error) } }
            }
        } message: { Text("선택한 차에서 내리고 탈 차가 미정인 상태로 바뀌어요.") }
    }
    private func respond(_ invitation: IPhoneTripRideInvitation, accept: Bool) {
        Task { do { try await store.respondToRideInvitation(invitation, accept: accept); message = nil } catch { message = tripPreparationErrorMessage(error) } }
    }
}

struct TripCarCreateHost: View {
    let store: TripPreparationStore
    @State private var loading = true
    @State private var error: String?

    var body: some View {
        Group {
            if loading { WegoLoadingView("연결된 차량 확인 중", layout: .detail) }
            else if !store.accountIsCurrent { Text("로그인을 다시 확인해 주세요.") }
            else if let error {
                WegoLoadingFailureView(message: error) { Task { await load() } }
                    .padding(WegoTokens.Space.screen)
            }
            else {
                TripCarCreateView(vehicles: store.vehicles,
                                  suggestedName: "\(store.detail?.me?.name ?? "내")의 차", isPreview: store.isPreview,
                                  reloadVehicles: { await store.loadVehicles() }) { name, seats, remote in
                    try await store.createCar(name: name, seats: seats, remote: remote)
                }
            }
        }
        .task { await load() }
    }

    private func load() async {
        loading = true
        await store.loadVehicles()
        error = store.vehicles.isEmpty ? store.errorMessage : nil
        loading = false
    }
}

struct TripPickerItem: Identifiable {
    let id: String
    let title: String
    let subtitle: String
}

struct TripItemPicker: View {
    let title: String
    let emptyMessage: String
    let load: () async throws -> [TripPickerItem]
    let choose: (String) async throws -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var items: [TripPickerItem] = []
    @State private var pendingItemID: String?
    @State private var loading = true
    @State private var busy = false
    @State private var error: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
                if loading { WegoLoadingView("불러오는 중", layout: items.isEmpty ? .list : .row) }
                if let error {
                    if items.isEmpty && !loading {
                        WegoLoadingFailureView(message: error) { Task { await reload() } }
                    } else {
                        Text(error).font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.danger)
                        Button("다시 불러오기") { Task { await reload() } }.disabled(busy)
                    }
                } else if !loading && items.isEmpty { Text(emptyMessage).foregroundStyle(WegoTokens.Palette.secondary) }
                ForEach(items) { item in
                    Button {
                        Task {
                            busy = true
                            pendingItemID = item.id
                            defer { pendingItemID = nil }
                            do { try await choose(item.id); dismiss() }
                            catch is CancellationError { }
                            catch { self.error = error.localizedDescription }
                            busy = false
                        }
                    } label: {
                        HStack {
                            VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                                Text(item.title).font(WegoTokens.Typography.section)
                                Text(item.subtitle).font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                            }
                            Spacer()
                            if pendingItemID == item.id { WegoLoadingSpinner() }
                            else { Image(systemName: "plus.circle.fill").foregroundStyle(WegoTokens.Palette.accent) }
                        }
                        .frame(minHeight: WegoTokens.Metrics.touchTarget)
                        .padding(WegoTokens.Space.medium)
                        .background(WegoTokens.Palette.surface, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.control))
                        .contentShape(Rectangle())
                    }
                    .disabled(busy || loading)
                    .buttonStyle(.plain)
                }
            }
            .padding(WegoTokens.Space.screen)
        }
        .foregroundStyle(WegoTokens.Palette.text).background(WegoTokens.Palette.background)
        .navigationTitle(title).navigationBarTitleDisplayMode(.inline)
        .toolbar { ToolbarItem(placement: .cancellationAction) { Button("취소") { dismiss() }.disabled(busy) } }
        .interactiveDismissDisabled(busy)
        .task { await reload() }
    }

    private func reload() async {
        loading = true
        error = nil
        do { items = try await load() }
        catch is CancellationError { }
        catch { self.error = error.localizedDescription }
        loading = false
    }
}

struct TripPickupView: View {
    let store: TripPreparationStore
    @Environment(SessionManager.self) private var session
    @State private var kind: IPhoneTripPlaceKind?
    @State private var error: String?

    var body: some View {
        List {
            if let detail = store.detail, let car = detail.myCar {
                Section {
                    Text(car.name).font(WegoTokens.Typography.section)
                    Text("같은 차 일행과 타는 곳·내리는 곳을 함께 써요.").font(WegoTokens.Typography.caption)
                }
                ForEach([IPhoneTripPlaceKind.pickup, .drop], id: \.rawValue) { type in
                    Section(type == .pickup ? "타는 곳" : "내리는 곳") {
                        ForEach(car.places.filter { $0.kind == type }, id: \.id) { place in
                            HStack {
                                Text(place.name)
                                Spacer()
                                if let id = place.id, car.isMine || place.addedBy == detail.me?.id {
                                    Button("삭제", role: .destructive) {
                                        Task {
                                            do { try await store.removeCarPlace(carID: car.id, placeID: id) }
                                            catch { self.error = error.localizedDescription }
                                        }
                                    }
                                    .disabled(store.busy)
                                }
                            }
                        }
                        Button("장소 검색 후 추가") { kind = type }.disabled(store.busy)
                    }
                }
                if let error { Text(error).foregroundStyle(WegoTokens.Palette.danger) }
            }
        }
        .wegoSettingsList()
        .navigationTitle("타는 곳·내리는 곳").navigationBarTitleDisplayMode(.inline)
        .sheet(item: $kind) { type in
            NavigationStack {
                if store.isPreview {
                    Text("샘플에서는 실제 장소 검색·위치를 사용하지 않아요.").padding(WegoTokens.Space.screen)
                } else if let account = session.current {
                    CoursePlaceSearchView(account: account, api: IPhoneCourseAPI()) { place in
                        guard let car = store.detail?.myCar else { return }
                        Task {
                            do { try await store.addCarPlace(carID: car.id, kind: type, name: place.name, lat: place.lat, lng: place.lng) }
                            catch { self.error = error.localizedDescription }
                        }
                    }
                }
            }
        }
    }
}

extension IPhoneTripPlaceKind: Identifiable {
    var id: String { rawValue }
}
