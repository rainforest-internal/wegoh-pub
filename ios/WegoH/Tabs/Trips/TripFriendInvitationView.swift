import SwiftUI
import Observation

struct TripFriendInvitationChoice: Identifiable {
    let id: String
    let name: String
    let code: String
    var memberState: IPhoneTripMemberState? = nil

    var status: String? {
        switch memberState {
        case .pending: "초대 보냄"
        case .accepted: "참여 중"
        case nil: nil
        }
    }
}

@MainActor
@Observable
final class TripFriendInvitationModel {
    private(set) var friends: [TripFriendInvitationChoice] = []
    private(set) var selected: Set<String> = []
    private(set) var sent: Set<String> = []
    private(set) var failures: [String: String] = [:]
    private(set) var loading = false
    private(set) var hasLoaded = false
    private(set) var sending = false
    private(set) var error: String?
    private(set) var completedCount = 0
    private(set) var totalCount = 0
    private var generation = UUID()

    func invalidate() {
        generation = UUID()
        friends = []
        hasLoaded = false
        selected = []
        sent = []
        failures = [:]
        error = nil
    }

    func status(for friend: TripFriendInvitationChoice) -> String? {
        sent.contains(friend.id) ? "초대 보냄" : friend.status
    }

    func toggle(_ friend: TripFriendInvitationChoice) {
        guard !sending, !loading, status(for: friend) == nil else { return }
        if !selected.insert(friend.id).inserted { selected.remove(friend.id) }
    }

    func reload(_ load: () async throws -> [TripFriendInvitationChoice]) async {
        guard !loading, !sending else { return }
        loading = true
        let stamp = generation
        error = nil
        defer { loading = false }
        do {
            let values = try await load()
            guard generation == stamp else { return }
            friends = values
            hasLoaded = true
            selected.formIntersection(friends.filter { status(for: $0) == nil }.map(\.id))
        } catch is CancellationError { }
        catch { if generation == stamp { self.error = tripPreparationErrorMessage(error) } }
    }

    func send(canContinue: () -> Bool, invite: (String) async throws -> Void) async {
        guard !sending, !loading, canContinue() else { return }
        let targets = friends.filter { selected.contains($0.id) && status(for: $0) == nil }
        guard !targets.isEmpty else { return }
        sending = true
        let stamp = generation
        error = nil
        failures = [:]
        totalCount = targets.count
        completedCount = 0
        defer { sending = false }
        for friend in targets {
            guard canContinue() else {
                error = "여행 정보를 다시 불러온 뒤 남은 친구를 초대해 주세요."
                break
            }
            do {
                try await invite(friend.id)
                guard generation == stamp else { return }
                sent.insert(friend.id)
                selected.remove(friend.id)
            } catch is CancellationError { break }
            catch {
                guard generation == stamp else { return }
                failures[friend.id] = tripPreparationErrorMessage(error)
            }
            completedCount += 1
        }
    }
}

struct TripFriendInvitationView: View {
    let store: TripPreparationStore
    let load: () async throws -> [TripFriendInvitationChoice]
    @Environment(\.dismiss) private var dismiss
    @State private var model = TripFriendInvitationModel()

    private var canInvite: Bool {
        store.accountIsCurrent && store.detail?.state == .planned
            && (store.detail?.isOwner == true || store.detail?.myPermissions.invite == true)
            && !store.busy && !store.needsRefresh
    }

    var body: some View {
        Group {
            if !store.accountIsCurrent || store.detail == nil {
                Text("여행 참여 상태를 다시 확인해 주세요.").padding(WegoTokens.Space.screen)
            } else {
                ScrollView {
                    VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
                        Text("함께 갈 친구를 선택한 뒤 한 번에 초대해요.")
                            .font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.secondary)
                        if model.loading || (!model.hasLoaded && model.error == nil) {
                            WegoLoadingView("친구를 불러오는 중", layout: model.hasLoaded ? .row : .list)
                                .accessibilityIdentifier("tripInviteLoading")
                        }
                        if let error = model.error {
                            Text(error).font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.danger)
                        }
                        if store.needsRefresh && !model.loading {
                            Text("저장한 초대는 유지돼요. 여행 정보를 다시 불러온 뒤 남은 친구를 초대해 주세요.")
                                .font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.secondary)
                        }
                        if model.error != nil || (store.needsRefresh && !model.loading) {
                            Button("다시 불러오기") { Task { await reload() } }
                                .disabled(model.sending || model.loading).accessibilityIdentifier("tripInviteReload")
                        }
                        if model.hasLoaded && model.friends.isEmpty && model.error == nil {
                            Text("초대할 친구가 없어요.").font(WegoTokens.Typography.body).foregroundStyle(WegoTokens.Palette.secondary)
                        }
                        if !model.sent.isEmpty {
                            Text("\(model.sent.count)명에게 초대를 보냈어요.").font(WegoTokens.Typography.label)
                                .accessibilityIdentifier("tripInviteSummary")
                        }
                        ForEach(model.friends) { friend in friendRow(friend) }
                    }.padding(WegoTokens.Space.screen)
                }
                .safeAreaInset(edge: .bottom) {
                    Button { Task { await model.send(canContinue: { canInvite }, invite: store.invite) } } label: {
                        Group {
                            if model.sending { WegoButtonLoadingLabel("초대 중 \(model.completedCount)/\(model.totalCount)", onAccent: true) }
                            else { Text("\(model.selected.count)명 초대") }
                        }
                        .font(WegoTokens.Typography.action)
                        .frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.primaryButtonHeight)
                    }
                    .buttonStyle(WegoPrimaryButtonStyle())
                    .disabled(model.selected.isEmpty || model.loading || model.sending || !canInvite)
                    .accessibilityIdentifier("tripInviteSendSelected")
                    .padding(WegoTokens.Space.screen).background(WegoTokens.Palette.background)
                }
            }
        }
        .foregroundStyle(WegoTokens.Palette.text).background(WegoTokens.Palette.background)
        .navigationTitle("친구 초대").navigationBarTitleDisplayMode(.inline)
        .toolbar { ToolbarItem(placement: .cancellationAction) { Button("완료") { dismiss() }.disabled(model.sending) } }
        .interactiveDismissDisabled(model.sending)
        .task { await reload() }
        .onChange(of: store.accountIsCurrent) { _, current in if !current { model.invalidate() } }
        .onChange(of: store.detail == nil) { _, missing in if missing { model.invalidate() } }
    }

    private func friendRow(_ friend: TripFriendInvitationChoice) -> some View {
        let status = model.status(for: friend)
        return VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
            Button { model.toggle(friend) } label: {
                HStack(spacing: WegoTokens.Space.small) {
                    VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                        Text(friend.name).font(WegoTokens.Typography.section)
                        Text(friend.code).font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                        if let status { Text(status).font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary) }
                    }
                    Spacer(minLength: WegoTokens.Space.small)
                    Image(systemName: status != nil ? "checkmark.circle.fill" : model.selected.contains(friend.id) ? "checkmark.circle.fill" : "circle")
                        .font(WegoTokens.Typography.cardTitle).foregroundStyle(WegoTokens.Palette.accent).accessibilityHidden(true)
                }
                .frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.touchTarget)
                .padding(WegoTokens.Space.medium)
                .background(WegoTokens.Palette.surface, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.control))
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain).disabled(status != nil || model.loading || model.sending || !canInvite)
            .accessibilityLabel("\(friend.name), \(friend.code)")
            .accessibilityValue(status ?? (model.selected.contains(friend.id) ? "선택됨" : "선택 안 됨"))
            .accessibilityIdentifier("tripInviteFriend-" + friend.id)
            if let failure = model.failures[friend.id] {
                Text("\(friend.name) · \(failure)").font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.danger)
                    .accessibilityIdentifier("tripInviteFailure-" + friend.id)
            }
        }
    }

    private func reload() async {
        await model.reload {
            if store.needsRefresh { await store.load() }
            guard store.accountIsCurrent, store.detail != nil else { throw IPhoneSessionError.invalidSession }
            guard !store.needsRefresh else { throw TripPreparationError.refreshRequired }
            return try await load()
        }
    }
}
