import SwiftUI

struct VehicleSettingsView: View {
    @Environment(SessionManager.self) private var session
    @State private var vehicles: [LinkedVehicle] = []
    @State private var entry: VehicleLinkMethod?
    @State private var disconnect: LinkedVehicle?
    @State private var message: String?
    @State private var loading = false
    @State private var hasLoaded = false
    @State private var revokingID: String?
    @State private var operationID = UUID()
    @State private var showsLogin = false
    @State private var rename: ProfileEdit?
    @State private var renameLoadingID: String?
    private let api = IPhoneVehicleAPI()
    private let profileAPI = IPhoneProfileAPI()
    private var canRename: Bool { session.current?.scopes.contains("account:write") == true }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: WegoTokens.Space.large) {
                if session.phase == .signedIn {
                    SectionHeader("연결된 차량")
                    if !hasLoaded && (loading || message == nil) {
                        WegoLoadingView("연결된 차량 확인 중", layout: .list)
                    } else if hasLoaded && loading && revokingID == nil {
                        WegoLoadingView("연결된 차량 새로 확인 중", layout: .row)
                    }
                    if vehicles.isEmpty && hasLoaded {
                        WegoCard(.ink, padding: WegoTokens.Space.screen) {
                            VStack(alignment: .leading, spacing: WegoTokens.Space.large) {
                                Text("iPhone과 차량을 연결해요")
                                    .font(WegoTokens.Typography.cardTitle)
                                RouteStrip(stops: ["iPhone", "차량"], onInk: true)
                                Text("차량의 WegoH 연결 화면에서 QR이나 8자리 코드를 확인하세요.")
                                    .font(WegoTokens.Typography.label)
                                    .foregroundStyle(WegoTokens.Palette.onInkSecondary)
                            }
                        }
                        if !loading && message == nil {
                            Text("연결된 차량이 없어요.")
                                .font(WegoTokens.Typography.label)
                                .foregroundStyle(WegoTokens.Palette.secondary)
                        }
                    }
                    ForEach(vehicles) { vehicle in
                        WegoCard(.ink, padding: WegoTokens.Space.screen) {
                            VStack(alignment: .leading, spacing: WegoTokens.Space.large) {
                                HStack(alignment: .top, spacing: WegoTokens.Space.medium) {
                                    Label(vehicle.name, systemImage: "car.fill")
                                        .font(WegoTokens.Typography.cardTitle)
                                        .frame(maxWidth: .infinity, alignment: .leading)
                                    StatusPill("연결됨", tone: .soft, onInk: true)
                                }
                                RouteStrip(stops: ["iPhone", "차량"], progress: 1, onInk: true)
                                Button(role: .destructive) { disconnect = vehicle } label: {
                                    Group {
                                        if revokingID == vehicle.id { WegoButtonLoadingLabel("연결 해제 중…", onAccent: true) }
                                        else { Text("연결 해제") }
                                    }
                                        .font(WegoTokens.Typography.action)
                                        .foregroundStyle(WegoTokens.Palette.onInk)
                                        .frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.touchTarget)
                                        .overlay {
                                            RoundedRectangle(cornerRadius: WegoTokens.Radius.control)
                                                .strokeBorder(WegoTokens.Palette.onInkSecondary,
                                                              lineWidth: WegoTokens.Metrics.hairlineWidth)
                                        }
                                        .contentShape(Rectangle())
                                }
                                .buttonStyle(.plain)
                                .disabled(loading)
                                .accessibilityIdentifier("vehicleDisconnect-" + vehicle.id)
                            }
                        }
                        Button { Task { await beginRename(vehicle) } } label: {
                            WegoRow(systemImage: "pencil", title: "차량 이름 바꾸기",
                                    subtitle: renameLoadingID == vehicle.id ? "차량 정보를 확인하고 있어요" : "연결 차량 목록과 리모컨에 보이는 이름이에요")
                        }
                        .buttonStyle(.plain)
                        .disabled(!canRename || loading || renameLoadingID != nil)
                        .accessibilityIdentifier("vehicleRename-" + vehicle.id)
                        NavigationLink { VehicleFunctionalPermissionsView(vehicle: vehicle) } label: {
                            WegoRow(systemImage: "checkmark.shield", title: vehicle.name + " 기능 허용",
                                    subtitle: "이 차량에서 사용할 기능을 확인해요")
                        }
                        .buttonStyle(.plain)
                        .accessibilityIdentifier("vehicleFunctionalPermissions-" + vehicle.id)
                    }
                    if let message {
                        if !hasLoaded && !loading {
                            WegoLoadingFailureView(message: message) { Task { await loadVehicles() } }
                        } else if hasLoaded {
                            Text(message).font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.secondary)
                        }
                    }
                    VStack(spacing: WegoTokens.Space.compact) {
                        Button { entry = .scan } label: {
                            Label("차량 QR 스캔", systemImage: "qrcode.viewfinder")
                        }
                        .buttonStyle(.wego(.primary))
                        .accessibilityIdentifier("vehicleScan")
                        Button { entry = .code } label: {
                            Label("코드 직접 입력", systemImage: "keyboard")
                        }
                        .buttonStyle(.wego(.soft))
                        .accessibilityIdentifier("vehicleEnterCode")
                        Button("새로고침") { Task { await loadVehicles() } }
                            .buttonStyle(.wego(.plain))
                            .disabled(loading)
                            .accessibilityIdentifier("vehicleRefresh")
                    }
                    if !vehicles.isEmpty {
                        Text("차량은 1대만 연결할 수 있어요. 다른 차량을 연결하려면 현재 연결을 먼저 해제해 주세요.")
                            .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                        if !canRename {
                            Text("차량 이름을 바꾸려면 로그아웃 후 다시 로그인해 주세요.")
                                .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                        }
                    }
                } else if session.phase == .checkingSession || session.phase == .signingOut {
                    WegoLoadingView(session.phase == .signingOut ? "로그아웃 중" : "로그인 확인 중", layout: .list)
                } else {
                    WegoCard(.surface) {
                        VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
                            Text("내 계정으로 로그인한 뒤 차량을 연결할 수 있어요.")
                            Button("로그인") { showsLogin = true }
                                .buttonStyle(.wego(.primary))
                                .accessibilityIdentifier("vehicleLogin")
                        }
                    }
                }
            }
            .padding(WegoTokens.Space.screen)
        }
        .background(WegoTokens.Palette.background)
        .foregroundStyle(WegoTokens.Palette.text)
        .scrollBounceBehavior(.always, axes: .vertical)
        .refreshable { await loadVehicles() }
        .navigationTitle("연결 차량 설정")
        .navigationBarTitleDisplayMode(.inline)
        .task(id: session.current?.accountID) {
            operationID = UUID()
            loading = false
            hasLoaded = false
            revokingID = nil
            vehicles = []
            message = nil
            entry = nil
            disconnect = nil
            rename = nil
            renameLoadingID = nil
            await loadVehicles()
        }
        .sheet(item: $entry, onDismiss: { Task { await loadVehicles() } }) { method in
            VehicleLinkView(initialMethod: method).id(session.current?.accountID)
        }
        .sheet(item: $rename) { item in
            if let account = session.current {
                ProfileEditView(item: item, account: account, api: profileAPI) { _, _ in
                    Task { await loadVehicles() }
                }
            }
        }
        .navigationDestination(isPresented: $showsLogin) {
            LoginView(secondaryTitle: "닫기") { showsLogin = false }
                .toolbar(.hidden, for: .navigationBar, .tabBar)
        }
        .alert("이 차량의 연결을 해제할까요?", isPresented: Binding(
            get: { disconnect != nil }, set: { if !$0 { disconnect = nil } }
        ), presenting: disconnect) { vehicle in
            Button("연결 해제", role: .destructive) { Task { await revoke(vehicle) } }
            Button("취소", role: .cancel) {}
        } message: { vehicle in
            Text("\(vehicle.name)에서 내 계정을 더 이상 사용할 수 없어요.")
        }
    }

    @MainActor private func loadVehicles() async {
        guard !loading, let account = session.current, session.phase == .signedIn else { return }
        let id = UUID()
        operationID = id
        loading = true
        defer { if operationID == id { loading = false } }
        do {
            let result = try await session.withToken(for: account) { try await api.vehicles(token: $0) }
            guard operationID == id, session.current == account else { return }
            vehicles = result
            hasLoaded = true
            message = nil
        } catch is CancellationError {}
        catch { if operationID == id, session.current == account { message = error.localizedDescription } }
    }

    /// Reads the current profile so the rename keeps the plate and uses the latest revision.
    @MainActor private func beginRename(_ vehicle: LinkedVehicle) async {
        guard canRename, renameLoadingID == nil, let account = session.current else { return }
        renameLoadingID = vehicle.id
        defer { renameLoadingID = nil }
        do {
            let profile = try await session.withToken(for: account) { try await profileAPI.vehicle(vehicle.id, token: $0) }
            guard session.current == account else { return }
            rename = ProfileEdit(field: .vehicleName, value: profile.name, vehicle: profile)
        } catch is CancellationError {}
        catch { if session.current == account { message = profileErrorMessage(error) } }
    }

    @MainActor private func revoke(_ vehicle: LinkedVehicle) async {
        guard !loading, let account = session.current else { return }
        let id = UUID()
        operationID = id
        loading = true
        revokingID = vehicle.id
        defer { if operationID == id { loading = false; revokingID = nil } }
        do {
            try await session.withToken(for: account) { try await api.revoke(vehicle, token: $0) }
            guard operationID == id, session.current == account else { return }
            vehicles.removeAll { $0.id == vehicle.id }
            message = nil
        } catch is CancellationError {}
        catch { if operationID == id, session.current == account { message = error.localizedDescription } }
    }
}
