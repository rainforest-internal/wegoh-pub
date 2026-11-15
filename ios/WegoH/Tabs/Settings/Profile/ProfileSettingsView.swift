import SwiftUI
import UIKit

struct ProfileSettingsView: View {
    @Environment(SessionManager.self) private var session
    @State private var showsLogin = false

    var body: some View {
        Group {
            if session.phase == .signedIn, let account = session.current {
                ProfileContent(account: account) { accountSection }.id(account.accountID)
            } else {
                ScrollView {
                    accountSection
                        .padding(.horizontal, WegoTokens.Space.screen)
                        .padding(.vertical, WegoTokens.Space.compact)
                }
                .background(WegoTokens.Palette.background)
            }
        }
        .navigationTitle("프로필")
        .navigationBarTitleDisplayMode(.inline)
        .navigationDestination(isPresented: $showsLogin) {
            LoginView(secondaryTitle: "닫기") { showsLogin = false }
                .toolbar(.hidden, for: .navigationBar, .tabBar)
        }
    }

    private var accountSection: some View {
        ProfileSection(title: "앱 계정") {
            VStack(alignment: .leading, spacing: 0) {
                switch session.phase {
                case .signedIn:
                    if let account = session.current {
                        LabeledContent("로그인 만료") {
                            Text(account.expiresAt.formatted(date: .abbreviated, time: .shortened))
                                .foregroundStyle(WegoTokens.Palette.text)
                                .multilineTextAlignment(.trailing)
                        }
                        .font(WegoTokens.Typography.body)
                        .foregroundStyle(WegoTokens.Palette.secondary)
                        .padding(.vertical, WegoTokens.Space.medium)
                        Divider().overlay(WegoTokens.Palette.divider)
                        Button("로그아웃", role: .destructive) { Task { await session.signOut() } }
                            .foregroundStyle(WegoTokens.Palette.danger)
                            .accessibilityIdentifier("profileLogout")
                            .profileAccountAction()
                    }
                case .checkingSession, .signingOut:
                    WegoLoadingView(session.phase == .signingOut ? "로그아웃 중…" : "로그인 확인 중…", layout: .row)
                        .padding(.vertical, WegoTokens.Space.medium)
                case .restoreFailed, .logoutPending:
                    if let message = session.message { accountMessage(message) }
                    if session.phase == .logoutPending {
                        Button("로그아웃 다시 시도") { Task { await session.signOut() } }
                            .profileAccountAction()
                    } else {
                        Button("다시 확인") { Task { await session.restore() } }
                            .profileAccountAction()
                        Divider().overlay(WegoTokens.Palette.divider)
                        Button("이 iPhone에서 로그아웃", role: .destructive) { Task { await session.signOut() } }
                            .foregroundStyle(WegoTokens.Palette.danger)
                            .profileAccountAction()
                    }
                case .signedOut, .signingIn:
                    LabeledContent("로그인 상태", value: "로그인 필요")
                        .font(WegoTokens.Typography.body)
                        .padding(.vertical, WegoTokens.Space.medium)
                    if let message = session.message { accountMessage(message) }
                    Divider().overlay(WegoTokens.Palette.divider)
                    Button("로그인") { showsLogin = true }
                        .profileAccountAction()
                        .accessibilityIdentifier("profileLogin")
                }
            }
            .padding(.horizontal, WegoTokens.Space.medium)
            .background(WegoTokens.Palette.surface, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.card))
        }
    }

    private func accountMessage(_ message: String) -> some View {
        Text(message).font(WegoTokens.Typography.label)
            .foregroundStyle(WegoTokens.Palette.secondary)
            .fixedSize(horizontal: false, vertical: true)
            .padding(.vertical, WegoTokens.Space.compact)
    }
}

private extension View {
    func profileAccountAction() -> some View {
        buttonStyle(ProfileAccountButtonStyle())
    }
}

private struct ProfileAccountButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(WegoTokens.Typography.body)
            .frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.settingsDetailRowHeight, alignment: .leading)
            .contentShape(Rectangle())
    }
}

private struct ProfileSection<Content: View>: View {
    let title: String
    @ViewBuilder var content: () -> Content

    var body: some View {
        VStack(alignment: .leading, spacing: WegoTokens.Space.compact) {
            Text(title).font(WegoTokens.Typography.label.weight(.semibold))
                .foregroundStyle(WegoTokens.Palette.secondary)
                .accessibilityAddTraits(.isHeader)
            content()
        }
    }
}

struct ProfileEdit: Identifiable {
    let field: ProfileField
    let value: String
    var vehicle: IPhoneVehicleProfile? = nil
    var id: String { field.id + (vehicle?.id ?? "") }
}

private struct ProfileContent<AccountContent: View>: View {
    @Environment(SessionManager.self) private var session
    let account: AccountSession
    @ViewBuilder var accountContent: () -> AccountContent
    @State private var loading = ProfileLoadStore()
    @State private var edit: ProfileEdit?
    @State private var copyConfirmation: UUID?
    private var api: IPhoneProfileAPI {
        #if DEBUG
        if let config = CourseUIFixture.profileConfigurationIfRequested() { return IPhoneProfileAPI(configuration: config) }
        #endif
        return IPhoneProfileAPI()
    }
    private var canEdit: Bool { account.scopes.contains("account:write") }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: WegoTokens.Space.large) {
                identityHeader
                ProfileSection(title: "내 정보") {
                    VStack(alignment: .leading, spacing: 0) {
                        Button { edit = ProfileEdit(field: .name, value: loading.profile?.displayName ?? account.displayName) } label: {
                            profileRow("이름", value: loading.profile?.displayName ?? account.displayName)
                        }.disabled(!canEdit || loading.profile == nil).accessibilityIdentifier("profileEditName")
                        if let profile = loading.profile {
                            Divider().overlay(WegoTokens.Palette.divider)
                            Button { edit = ProfileEdit(field: .handle, value: profile.handle) } label: {
                                profileRow("친구 코드", value: profile.handle)
                            }.disabled(!canEdit).accessibilityIdentifier("profileEditHandle")
                        }
                        if loading.profileLoading || (loading.profile == nil && loading.error == nil) { WegoLoadingView("프로필 확인 중", layout: loading.profile == nil ? .detail : .row).padding(.vertical, WegoTokens.Space.compact) }
                        if let error = loading.error {
                            if loading.profile == nil && !loading.profileLoading {
                                WegoLoadingFailureView(message: error) { Task { await load() } }
                            } else {
                                Text(error).font(WegoTokens.Typography.label)
                                    .foregroundStyle(WegoTokens.Palette.secondary)
                                    .padding(.vertical, WegoTokens.Space.compact)
                            }
                        }
                    }
                    .buttonStyle(.plain)
                    .padding(.horizontal, WegoTokens.Space.medium)
                    .background(WegoTokens.Palette.surface, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.card))
                    if !canEdit {
                        Text("프로필을 앱에서 수정하려면 로그아웃 후 다시 로그인해 주세요.")
                            .font(WegoTokens.Typography.caption)
                            .foregroundStyle(WegoTokens.Palette.secondary)
                    }
                }
                ProfileSection(title: "내 차량") {
                    ForEach(loading.vehicles) { vehicle in
                        VStack(alignment: .leading, spacing: 0) {
                            Button {
                                edit = ProfileEdit(field: .vehicleName, value: vehicle.profile.name, vehicle: vehicle.profile)
                            } label: {
                                HStack(spacing: WegoTokens.Space.compact) {
                                    Image(systemName: "car").font(WegoTokens.Typography.cardTitle)
                                        .foregroundStyle(WegoTokens.Palette.accent)
                                        .frame(width: WegoTokens.Metrics.touchTarget, height: WegoTokens.Metrics.touchTarget)
                                        .background(WegoTokens.Palette.accentSoft, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.control))
                                        .accessibilityHidden(true)
                                    Text(vehicle.name).font(WegoTokens.Typography.section)
                                        .foregroundStyle(WegoTokens.Palette.text)
                                        .fixedSize(horizontal: false, vertical: true)
                                        .frame(maxWidth: .infinity, alignment: .leading)
                                    if canEdit { editIcon }
                                }
                                .padding(.vertical, WegoTokens.Space.compact)
                                .contentShape(Rectangle())
                            }
                            .disabled(!canEdit)
                            .accessibilityLabel("차량 이름")
                            .accessibilityValue(vehicle.name)
                            .accessibilityIdentifier("profileEditVehicleName-\(vehicle.id)")
                            Divider().overlay(WegoTokens.Palette.divider)
                            Button {
                                edit = ProfileEdit(field: .plate, value: vehicle.profile.plateNumber, vehicle: vehicle.profile)
                            } label: {
                                profileRow("차량 번호", value: vehicle.profile.plateNumber.isEmpty ? "등록 안 됨" : vehicle.profile.plateNumber)
                            }
                            .disabled(!canEdit).accessibilityIdentifier("profileEditPlate-\(vehicle.id)")
                        }
                        .buttonStyle(.plain)
                        .padding(.horizontal, WegoTokens.Space.medium)
                        .background(WegoTokens.Palette.background, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.card))
                        .overlay { RoundedRectangle(cornerRadius: WegoTokens.Radius.card).strokeBorder(WegoTokens.Palette.divider) }
                    }
                    if let vehicleError = loading.vehicleError { Text(vehicleError).font(WegoTokens.Typography.label) }
                    else if !loading.hasLoadedVehicles { WegoLoadingView("차량 정보 확인 중", layout: .row) }
                    else if loading.vehicles.isEmpty && loading.hasLoadedVehicles {
                        Text("연결된 차량이 없어요.").font(WegoTokens.Typography.body)
                            .foregroundStyle(WegoTokens.Palette.secondary)
                    }
                    Text("차량 이름은 연결 차량 목록과 리모컨에, 등록한 차량 번호는 친구 프로필에도 표시돼요.")
                        .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                        .padding(.horizontal, WegoTokens.Space.xSmall)
                }
                accountContent()
            }
            .padding(.horizontal, WegoTokens.Space.screen)
            .padding(.vertical, WegoTokens.Space.compact)
        }
        .scrollBounceBehavior(.always, axes: .vertical)
        .refreshable { await load() }
        .background(WegoTokens.Palette.background)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button { Task { await load() } } label: { Image(systemName: "arrow.clockwise") }
                    .disabled(loading.isLoading).accessibilityLabel("새로고침").accessibilityIdentifier("profileRefresh")
            }
        }
        .task { await load() }
        .sheet(item: $edit) { item in
            ProfileEditView(item: item, account: account, api: api) { value, vehicle in
                if item.field == .name {
                    loading.profile?.displayName = value
                    session.updateDisplayName(value, for: account)
                } else if item.field == .handle { loading.profile?.handle = value }
                else if let vehicle, let index = loading.vehicles.firstIndex(where: { $0.id == vehicle.id }) { loading.vehicles[index].profile = vehicle }
            }
        }
    }

    private var identityHeader: some View {
        HStack(spacing: WegoTokens.Space.medium) {
            Text(String((loading.profile?.displayName ?? account.displayName).prefix(2)))
                .font(WegoTokens.Typography.title)
                .foregroundStyle(WegoTokens.Palette.onInk)
                .frame(width: WegoTokens.Metrics.profileAvatarSize, height: WegoTokens.Metrics.profileAvatarSize)
                .background(WegoTokens.Palette.ink, in: Circle())
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                Text(loading.profile?.displayName ?? account.displayName).font(WegoTokens.Typography.title)
                    .foregroundStyle(WegoTokens.Palette.text)
                if let profile = loading.profile {
                    Button {
                        UIPasteboard.general.string = profile.handle
                        copyConfirmation = UUID()
                        UIAccessibility.post(notification: .announcement, argument: "친구 코드를 복사했어요")
                    } label: {
                        HStack(spacing: WegoTokens.Space.xSmall) {
                            Text("친구 코드 · \(profile.handle)")
                            Image(systemName: "doc.on.doc").accessibilityHidden(true)
                        }
                        .font(WegoTokens.Typography.caption.weight(.semibold))
                        .foregroundStyle(WegoTokens.Palette.accent)
                        .padding(.horizontal, WegoTokens.Space.compact).padding(.vertical, WegoTokens.Space.xSmall)
                        .frame(minHeight: WegoTokens.Metrics.touchTarget)
                        .background(WegoTokens.Palette.accentSoft, in: Capsule())
                        .contentShape(Capsule())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("친구 코드 복사")
                    .accessibilityValue(profile.handle)
                    .accessibilityIdentifier("profileCopyFriendCode")
                    .sensoryFeedback(.impact(weight: .light), trigger: copyConfirmation) { _, value in value != nil }
                    if copyConfirmation != nil {
                        Text("친구 코드를 복사했어요").font(WegoTokens.Typography.caption)
                            .foregroundStyle(WegoTokens.Palette.secondary)
                            .accessibilityIdentifier("profileFriendCodeCopied")
                    }
                }
            }
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .accessibilityElement(children: .contain)
        .onChange(of: loading.profile?.handle) { _, _ in copyConfirmation = nil }
    }

    private var editIcon: some View {
        Image(systemName: "pencil").font(WegoTokens.Typography.body)
            .foregroundStyle(WegoTokens.Palette.accent).accessibilityHidden(true)
    }

    private func profileRow(_ label: String, value: String) -> some View {
        HStack(spacing: WegoTokens.Space.compact) {
            Text(label).foregroundStyle(WegoTokens.Palette.secondary)
            Spacer(minLength: WegoTokens.Space.small)
            Text(value).foregroundStyle(WegoTokens.Palette.text)
                .multilineTextAlignment(.trailing)
                .accessibilityIdentifier(label == "이름" ? "profileAccountName" : "profileValue")
            if canEdit { editIcon }
        }
        .font(WegoTokens.Typography.body)
        .padding(.vertical, WegoTokens.Space.compact)
        .frame(minHeight: WegoTokens.Metrics.settingsDetailRowHeight)
        .contentShape(Rectangle())
    }

    private func load() async {
        guard let current = session.current, current == account else { return }
        await loading.load(session: session, account: current, api: api)
    }
}

struct ProfileEditView: View {
    @Environment(SessionManager.self) private var session
    @Environment(\.dismiss) private var dismiss
    let item: ProfileEdit
    let account: AccountSession
    let api: any IPhoneProfileServing
    let onSaved: (String, IPhoneVehicleProfile?) -> Void
    @State private var value: String
    @State private var isSaving = false
    @State private var error: String?
    @FocusState private var inputFocused: Bool

    init(item: ProfileEdit, account: AccountSession, api: any IPhoneProfileServing,
         onSaved: @escaping (String, IPhoneVehicleProfile?) -> Void) {
        self.item = item; self.account = account; self.api = api; self.onSaved = onSaved
        _value = State(initialValue: item.value)
    }
    private var normalized: String { item.field.normalized(value) }
    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField(item.field == .vehicleName ? item.vehicle?.defaultName ?? item.field.title : item.field.title, text: $value)
                        .focused($inputFocused)
                        .textInputAutocapitalization(item.field == .name ? .words : .never)
                        .autocorrectionDisabled()
                        .keyboardType(item.field == .handle ? .asciiCapable : .default)
                        .onChange(of: value) { _, input in
                            let filtered = item.field.filteredInput(input)
                            if input != filtered { value = filtered }
                        }
                        .accessibilityIdentifier("profileEditInput")
                        .disabled(isSaving)
                } header: { Text(item.field.title) } footer: { Text(item.field.hint) }
                .listRowBackground(WegoTokens.Palette.background)
                if let error {
                    Section { Text(error).font(WegoTokens.Typography.label).accessibilityIdentifier("profileSaveError") }.listRowBackground(WegoTokens.Palette.background)
                }
            }
            .listStyle(.insetGrouped)
            .scrollContentBackground(.hidden)
            .background(WegoTokens.Palette.surface)
            .safeAreaInset(edge: .bottom) {
                ActionButton(title: isSaving ? "저장 중…" : "저장", isLoading: isSaving) { Task { await save() } }
                    .disabled(isSaving || normalized == item.value || !item.field.valid(normalized))
                    .accessibilityIdentifier("profileSave")
                    .background(WegoTokens.Palette.surface)
            }
            .navigationTitle("\(item.field.title) 수정")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("취소") { dismiss() }.disabled(isSaving) } }
            .interactiveDismissDisabled(isSaving)
            .task { inputFocused = true }
        }
    }
    private func save() async {
        guard !isSaving, normalized != item.value, item.field.valid(normalized) else { return }
        isSaving = true
        error = nil
        defer { isSaving = false }
        do {
            let result: (String, IPhoneVehicleProfile?) = try await session.withToken(for: account) { token in
                switch item.field {
                case .name: return (try await api.name(normalized, expected: item.value, token: token), nil)
                case .handle: return (try await api.handle(normalized, expected: item.value, token: token), nil)
                case .plate:
                    guard let vehicle = item.vehicle else { throw IPhoneResourceError.invalidInput }
                    let saved = try await api.plate(normalized, vehicle: vehicle, token: token)
                    return (saved.plateNumber, saved)
                case .vehicleName:
                    guard let vehicle = item.vehicle else { throw IPhoneResourceError.invalidInput }
                    let saved = try await api.vehicleName(normalized, vehicle: vehicle, token: token)
                    return (saved.name, saved)
                }
            }
            onSaved(result.0, result.1)
            dismiss()
        } catch is CancellationError { dismiss() }
        catch { self.error = profileErrorMessage(error) }
    }
}
