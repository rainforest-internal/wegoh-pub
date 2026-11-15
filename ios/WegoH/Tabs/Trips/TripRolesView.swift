import SwiftUI

struct TripRolesView: View {
    let store: TripPreparationStore
    @Environment(\.dismiss) private var dismiss
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @State private var message: String?
    @State private var pendingRole: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
                LazyVGrid(columns: Array(repeating: GridItem(.flexible(), alignment: .top),
                                         count: dynamicTypeSize.isAccessibilitySize ? 1 : 3),
                          alignment: .leading, spacing: WegoTokens.Space.small) {
                    ForEach([IPhoneTripRole.dj, .food, .rest]) { role in
                        WegoCard(.surface, padding: WegoTokens.Space.compact) {
                            VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                                Text(role.title).font(WegoTokens.Typography.section)
                                Text(role.detail).font(WegoTokens.Typography.label)
                            }
                        }
                    }
                }
                if let detail = store.detail {
                    Text(detail.isOwner ? "한 사람은 역할 하나만 맡아요. 역할은 권한을 바꾸지 않아요." : "여행 만든 사람만 역할을 바꿀 수 있어요.")
                        .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                    ForEach(detail.cars) { car in
                        Text(detail.numberedName(car)).font(WegoTokens.Typography.section)
                        ForEach(detail.members.filter { $0.id == car.driverId || car.passengers.map(\.id).contains($0.id) }) { member in
                            memberRow(member, editable: detail.isOwner)
                        }
                    }
                    if !detail.unassigned.isEmpty {
                        Text("차 미정").font(WegoTokens.Typography.section)
                        ForEach(detail.members.filter { $0.carId == nil && $0.state == .accepted }) { member in
                            memberRow(member, editable: detail.isOwner)
                        }
                    }
                }
                if let message { Text(message).font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.danger) }
            }.padding(WegoTokens.Space.screen)
        }
        .foregroundStyle(WegoTokens.Palette.text).background(WegoTokens.Palette.background)
        .navigationTitle("역할 정하기").navigationBarTitleDisplayMode(.inline)
        .toolbar { ToolbarItem(placement: .confirmationAction) { Button("완료") { dismiss() }.disabled(store.busy) } }
    }

    private func memberRow(_ member: IPhoneTripMember, editable: Bool) -> some View {
        VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
            HStack(spacing: WegoTokens.Space.compact) {
                AvatarBadge(name: member.name, tone: member.isMe ? .accent : store.detail?.cars.contains(where: { $0.driverId == member.id }) == true ? .ink : .soft)
                TripMemberRoleLabel(member: member)
                if member.isMe { Text("· 나").font(WegoTokens.Typography.caption) }
                Spacer(minLength: 0)
                let identity = [member.isOwner ? "만든 사람" : nil,
                                store.detail?.cars.contains(where: { $0.driverId == member.id }) == true ? "운전자" : nil]
                    .compactMap { $0 }.joined(separator: " · ")
                if !identity.isEmpty {
                    Text(identity).font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                }
            }
            if editable {
                LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: WegoTokens.Space.xSmall), count: dynamicTypeSize.isAccessibilitySize ? 1 : 4)) {
                    ForEach(IPhoneTripRole.allCases) { role in
                        let selected = (member.role ?? .member) == role
                        Button {
                            Task {
                                pendingRole = member.id + ":" + role.rawValue
                                defer { pendingRole = nil }
                                do { try await store.setRole(accountID: member.id, role: role); message = nil }
                                catch { message = error.localizedDescription }
                            }
                        } label: {
                            Group {
                                if pendingRole == member.id + ":" + role.rawValue {
                                    HStack(spacing: WegoTokens.Space.xSmall) { WegoLoadingSpinner(); Text(role.title) }
                                }
                                else { Text(role.title) }
                            }.font(WegoTokens.Typography.caption.weight(.semibold))
                                .frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.touchTarget)
                                .foregroundStyle(selected ? WegoTokens.Palette.onInk : WegoTokens.Palette.text)
                                .background(selected ? WegoTokens.Palette.ink : WegoTokens.Palette.background,
                                            in: RoundedRectangle(cornerRadius: WegoTokens.Radius.field))
                                .overlay { RoundedRectangle(cornerRadius: WegoTokens.Radius.field)
                                    .strokeBorder(selected ? .clear : WegoTokens.Palette.divider, lineWidth: WegoTokens.Metrics.hairlineWidth) }
                        }.buttonStyle(TripRoleChoiceStyle(selected: selected)).disabled(store.busy || store.needsRefresh || selected)
                            .accessibilityLabel("\(member.name), \(role.title)")
                            .accessibilityAddTraits(selected ? .isSelected : [])
                            .accessibilityIdentifier("tripRole-\(member.id)-\(role.rawValue)")
                    }
                }
            }
            Divider().overlay(WegoTokens.Palette.divider)
        }.padding(.vertical, WegoTokens.Space.small)
    }
}

struct TripMemberRoleLabel: View {
    let member: IPhoneTripMember

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: WegoTokens.Space.xSmall) {
            StatusPill((member.role ?? .member).title, tone: .soft)
                .fixedSize()
            Text(member.name).font(WegoTokens.Typography.caption)
                .fixedSize(horizontal: false, vertical: true)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\((member.role ?? .member).title), \(member.name)")
        .accessibilityIdentifier("tripMemberRole-\(member.id)")
    }
}

struct TripRoleLabels: View {
    let members: [IPhoneTripMember]

    var body: some View {
        WegoChipLayout {
            ForEach(members) { member in TripMemberRoleLabel(member: member) }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct TripRoleChoiceStyle: ButtonStyle {
    let selected: Bool
    @Environment(\.isEnabled) private var enabled
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .contentShape(Rectangle())
            .opacity(selected || enabled ? 1 : WegoTokens.Opacity.controlDisabled)
    }
}

struct TripRemotePolicyView: View {
    let store: TripPreparationStore
    @Environment(\.dismiss) private var dismiss
    @State private var preferences = TripRemotePreferences()
    @State private var message: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
                if store.detail?.myCar?.isMine == true {
                    TripRemotePermissionSection(preferences: $preferences)
                    if let message { Text(message).foregroundStyle(WegoTokens.Palette.danger).font(WegoTokens.Typography.label) }
                    ActionButton(title: store.busy ? "저장 중…" : "허용 범위 저장", isLoading: store.busy) {
                        Task {
                            do { try await store.setRemotePreferences(preferences); dismiss() }
                            catch { message = error.localizedDescription }
                        }
                    }.disabled(store.busy || store.needsRefresh || !preferences.isValid)
                        .accessibilityIdentifier("tripRemotePolicySave")
                } else { Text("운전자만 동승자 리모컨 허용을 바꿀 수 있어요.").font(WegoTokens.Typography.label) }
            }.padding(WegoTokens.Space.screen)
        }
        .foregroundStyle(WegoTokens.Palette.text).background(WegoTokens.Palette.background)
        .navigationTitle("동승자 리모컨").navigationBarTitleDisplayMode(.inline)
        .toolbar { ToolbarItem(placement: .cancellationAction) { Button("취소") { dismiss() }.disabled(store.busy) } }
        .onAppear { preferences = store.isPreview ? store.previewRemotePreferences : TripRemotePreferences(policy: store.detail?.myCar?.remotePolicy) }
        .interactiveDismissDisabled(store.busy)
    }
}
