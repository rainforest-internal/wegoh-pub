import SwiftUI

struct TripPreparingCarCard: View {
    let car: TripPreparingCarPreview
    let selected: Bool
    let riders: [TripCarRider]
    var selectedLabel = "내가 탄 차"
    var actionTitle: String? = nil
    var action: (() -> Void)? = nil
    var roleMembers: [IPhoneTripMember] = []
    @State private var showsRoster = false

    var body: some View {
        WegoCard(isFull ? .surface : .outlined) {
            VStack(alignment: .leading, spacing: WegoTokens.Space.compact) {
                HStack(alignment: .top, spacing: WegoTokens.Space.small) {
                    VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                        HStack(spacing: WegoTokens.Space.small) {
                            Text(car.title)
                                .font(WegoTokens.Typography.section)
                            if selected {
                                statusPill(selectedLabel, selected: true)
                            } else if isFull {
                                statusPill("만석", selected: false)
                            }
                        }
                        Text("운전자 \(car.driverName) · 탑승 \(passengerCount)/\(car.passengerCapacity)명")
                            .font(WegoTokens.Typography.caption)
                            .foregroundStyle(WegoTokens.Palette.secondary)
                    }
                    .accessibilityElement(children: .combine)
                    Spacer(minLength: WegoTokens.Space.xSmall)
                    memberChips
                }
                if !roleMembers.isEmpty { TripRoleLabels(members: roleMembers) }
                HStack(spacing: WegoTokens.Space.xSmall) {
                    ForEach(0..<max(0, car.passengerCapacity), id: \.self) { index in
                        Capsule()
                            .fill(index < passengerCount
                                  ? (isFull ? WegoTokens.Palette.secondary : WegoTokens.Palette.accent)
                                  : WegoTokens.Palette.divider)
                            .frame(height: WegoTokens.Space.xSmall)
                    }
                }
                .accessibilityHidden(true)
                if selected || !isFull, let actionTitle, let action {
                    Button(action: action) {
                        Text(actionTitle)
                            .font(WegoTokens.Typography.label.weight(.semibold))
                            .foregroundStyle(selected ? WegoTokens.Palette.text : WegoTokens.Palette.accent)
                            .frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.touchTarget)
                            .background(selected ? WegoTokens.Palette.background : WegoTokens.Palette.accentSoft,
                                        in: RoundedRectangle(cornerRadius: WegoTokens.Radius.field))
                            .overlay {
                                if selected {
                                    RoundedRectangle(cornerRadius: WegoTokens.Radius.field)
                                        .strokeBorder(WegoTokens.Palette.divider)
                                }
                            }
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("\(car.title), \(actionTitle)")
                }
            }
        }
        .overlay {
            RoundedRectangle(cornerRadius: WegoTokens.Radius.card)
                .strokeBorder(selected ? WegoTokens.Palette.accent : WegoTokens.Palette.divider,
                              lineWidth: selected ? WegoTokens.Metrics.selectedBorderWidth : WegoTokens.Metrics.hairlineWidth)
        }
        .sheet(isPresented: $showsRoster) {
            NavigationStack { TripCarRosterView(title: car.title, capacity: car.passengerCapacity, riders: riders) }
                .presentationDetents([.medium, .large])
        }
    }

    /// 겹친 아바타와 `+N`은 더보기처럼 보여 누르게 되므로, 눌렀을 때 가려진 사람까지 전체 탑승 명단을 연다.
    private var memberChips: some View {
        Button { showsRoster = true } label: {
            HStack(spacing: WegoTokens.Space.xSmall) {
                HStack(spacing: -WegoTokens.Space.xSmall) {
                    ForEach(Array(riders.prefix(3))) { rider in
                        AvatarBadge(name: rider.name, tone: rider.isDriver ? .ink : .soft, size: WegoTokens.Metrics.tripMemberAvatarSize)
                            .overlay { Circle().strokeBorder(WegoTokens.Palette.background, lineWidth: WegoTokens.Metrics.hairlineWidth) }
                    }
                    if riders.count > 3 {
                        Text("+\(riders.count - 3)")
                            .font(WegoTokens.Typography.caption.weight(.semibold))
                            .frame(minWidth: WegoTokens.Metrics.tripMemberAvatarSize, minHeight: WegoTokens.Metrics.tripMemberAvatarSize)
                            .background(WegoTokens.Palette.surface, in: Circle())
                    }
                }
                Image(systemName: "chevron.right")
                    .font(WegoTokens.Typography.caption.weight(.semibold))
                    .foregroundStyle(WegoTokens.Palette.secondary)
            }
            .foregroundStyle(WegoTokens.Palette.text)
            .frame(minHeight: WegoTokens.Metrics.touchTarget)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(car.title) 탑승 명단 보기")
        .accessibilityValue(riders.map(\.name).joined(separator: ", "))
        .accessibilityAddTraits(.isButton)
        .accessibilityIdentifier("tripCarRoster-\(car.id)")
    }

    private func statusPill(_ title: String, selected: Bool) -> some View {
        StatusPill(title, tone: selected ? .soft : .neutral)
    }

    private var passengerCount: Int { max(0, car.members.count - 1) }
    private var isFull: Bool { passengerCount >= car.passengerCapacity }
}

struct TripCarRosterView: View {
    let title: String
    let capacity: Int
    let riders: [TripCarRider]
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                Text(summary)
                    .font(WegoTokens.Typography.label)
                    .foregroundStyle(WegoTokens.Palette.secondary)
                ForEach(riders) { rider in row(rider) }
            }
            .padding(WegoTokens.Space.screen)
        }
        .background(WegoTokens.Palette.background)
        .foregroundStyle(WegoTokens.Palette.text)
        .navigationTitle(title).navigationBarTitleDisplayMode(.inline)
        .toolbar { ToolbarItem(placement: .confirmationAction) { Button("완료") { dismiss() } } }
    }

    private var passengerCount: Int { riders.filter { !$0.isDriver }.count }

    private var summary: String {
        let empty = max(0, capacity - passengerCount)
        return "운전자 1명 · 동승 \(passengerCount)/\(capacity)명" + (empty > 0 ? " · 빈 자리 \(empty)석" : " · 만석")
    }

    private func row(_ rider: TripCarRider) -> some View {
        HStack(spacing: WegoTokens.Space.compact) {
            AvatarBadge(name: rider.name, tone: rider.isDriver ? .ink : .soft)
                .accessibilityHidden(true)
            Text(rider.isMe ? "\(rider.name) (나)" : rider.name)
                .font(WegoTokens.Typography.section)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: WegoTokens.Space.xSmall)
            if let role = rider.role, role != .member { StatusPill(role.title, tone: .soft).fixedSize() }
            StatusPill(rider.isDriver ? "운전자" : "동승자", tone: rider.isDriver ? .soft : .neutral).fixedSize()
        }
        .frame(minHeight: WegoTokens.Metrics.touchTarget)
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("tripCarRosterRow-\(rider.id)")
    }
}

struct TripUnassignedMembers: View {
    let names: [String]

    var body: some View {
        VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
            Text("아직 안 고른 사람 \(names.count)명")
                .font(WegoTokens.Typography.caption)
                .foregroundStyle(WegoTokens.Palette.secondary)
                .accessibilityAddTraits(.isHeader)
            LazyVGrid(columns: [GridItem(.adaptive(minimum: WegoTokens.Metrics.tripUnassignedChipMinimumWidth),
                                         spacing: WegoTokens.Space.small, alignment: .leading)],
                      alignment: .leading, spacing: WegoTokens.Space.small) {
                ForEach(Array(names.enumerated()), id: \.offset) { _, name in
                    HStack(spacing: WegoTokens.Space.xSmall) {
                        Text(String(name.prefix(1)))
                            .font(WegoTokens.Typography.caption.weight(.semibold))
                            .frame(minWidth: WegoTokens.Metrics.tripMemberAvatarSize,
                                   minHeight: WegoTokens.Metrics.tripMemberAvatarSize)
                            .background(WegoTokens.Palette.surface, in: Circle())
                            .accessibilityHidden(true)
                        Text(name).font(WegoTokens.Typography.caption)
                    }
                    .padding(WegoTokens.Space.xSmall)
                    .foregroundStyle(WegoTokens.Palette.secondary)
                    .background(WegoTokens.Palette.background, in: Capsule())
                    .overlay {
                        Capsule().strokeBorder(WegoTokens.Palette.divider,
                                               style: StrokeStyle(lineWidth: WegoTokens.Metrics.hairlineWidth,
                                                                  dash: [WegoTokens.Metrics.hairlineWidth, WegoTokens.Space.xSmall]))
                    }
                    .accessibilityElement(children: .ignore)
                    .accessibilityLabel(name)
                }
            }
        }
    }
}
