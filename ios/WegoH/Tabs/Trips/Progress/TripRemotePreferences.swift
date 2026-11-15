import SwiftUI

func tripRemoteSummary(ownerName: String, actionCount: Int) -> String {
    let name = ownerName.trimmingCharacters(in: .whitespacesAndNewlines).precomposedStringWithCanonicalMapping
    let subject: String
    if let last = name.unicodeScalars.last?.value, (0xAC00...0xD7A3).contains(last) {
        subject = name + ((last - 0xAC00) % 28 == 0 ? "가" : "이")
    } else {
        subject = name + "님이"
    }
    return "\(subject) 허용한 조작 \(actionCount)개 · 차 버튼 대신 여기서 조절해요"
}

enum TripRemoteGroup: String, CaseIterable, Identifiable {
    case climate, lights, windows, seats
    var id: Self { self }
    var title: String {
        switch self { case .climate: "공조"; case .lights: "조명"; case .windows: "창문"; case .seats: "시트" }
    }
    var detail: String {
        switch self {
        case .climate: "설정 온도 · 풍량 · 전원 · 에어컨 · 공기청정 · 운전석 제외"
        case .lights: "실내등은 정차 중에만 · 독서등 · 무드등 · 운전석 제외"
        case .windows: "창문 열림 · 운전석 제외"
        case .seats: "열선 · 통풍 · 정차 중에만 조절돼요 · 운전석 제외"
        }
    }
    var actionIDs: [String] {
        switch self {
        case .climate: ["hvac.temperature", "hvac.fan", "hvac.power", "hvac.ac", "hvac.air_cleaner"]
        case .lights: ["light.cabin", "light.reading", "light.ambient"]
        case .windows: ["window.position"]
        case .seats: ["seat.heat", "seat.ventilation"]
        }
    }
    var actionCount: Int { actionIDs.count }
}

let tripRemoteVehicleChangeNotice = "차량 연결이 바뀌어 리모컨 허용이 꺼졌어요"

struct TripRemotePreferences: Equatable {
    var enabled = false
    var groups: Set<TripRemoteGroup> = [.climate, .lights, .seats]
    /// 서버가 차량 로그아웃·재연결(기기 해제)로 허용을 끈 상태. 이때만 꺼진 정책에 이전 actions가 남는다
    /// (server/friend_vehicle_controls.py `revoke_device`). iPhone이 끌 때는 actions를 비워 보낸다.
    private(set) var disabledByVehicleChange = false
    var allowedGroups: Set<TripRemoteGroup> { enabled ? groups : [] }
    var actionCount: Int { allowedGroups.reduce(0) { $0 + $1.actionCount } }
    var isValid: Bool { !enabled || !groups.isEmpty }
    var summary: String {
        if !enabled && disabledByVehicleChange { return tripRemoteVehicleChangeNotice }
        guard !allowedGroups.isEmpty else { return "아직 허용한 조작이 없어요" }
        let titles = TripRemoteGroup.allCases.filter(allowedGroups.contains).map(\.title).joined(separator: "·")
        return "\(titles) · 조작 \(actionCount)개 허용"
    }
    var policy: IPhoneTripRemotePolicy { .init(enabled: enabled, actions: enabled ? groups.flatMap(\.actionIDs).sorted() : [], deviceId: nil) }
    init(enabled: Bool = false, groups: Set<TripRemoteGroup> = [.climate, .lights, .seats]) {
        self.enabled = enabled; self.groups = groups
    }
    init(policy: IPhoneTripRemotePolicy?) {
        enabled = policy?.enabled ?? false
        // 꺼진 정책은 보통 actions가 비어 있으므로, 다시 켤 때 고를 기본 그룹을 유지한다.
        // 차량 연결이 바뀌어 꺼진 정책은 이전 선택을 남기므로 그 그룹으로 되살린다.
        guard let policy, policy.enabled || !policy.actions.isEmpty else { return }
        disabledByVehicleChange = !policy.enabled
        groups = Set(TripRemoteGroup.allCases.filter { Set($0.actionIDs).isSubset(of: Set(policy.actions)) })
    }
}

struct TripRemotePermissionSection: View {
    @Binding var preferences: TripRemotePreferences
    var available = true

    var body: some View {
        VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
            Text("동승자 리모컨").font(WegoTokens.Typography.section)
            WegoCard(.surface) {
                Toggle(isOn: $preferences.enabled) {
                    VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                        Text("이 차 동승자에게 리모컨 허용").font(WegoTokens.Typography.label.weight(.semibold))
                        Text("동승자가 차 버튼에 손대지 않고 자기 폰으로 조절해요. 운전 중에 부탁받을 일도 줄어요.")
                            .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                    }
                }
                .accessibilityIdentifier("tripRemotePermissionToggle")
                .disabled(!available)
                if preferences.enabled {
                    VStack(spacing: 0) {
                        ForEach(TripRemoteGroup.allCases) { group in
                            Button {
                                if preferences.groups.contains(group) { preferences.groups.remove(group) }
                                else { preferences.groups.insert(group) }
                            } label: {
                                HStack(spacing: WegoTokens.Space.compact) {
                                    Image(systemName: preferences.groups.contains(group) ? "checkmark.square.fill" : "square")
                                        .foregroundStyle(WegoTokens.Palette.accent)
                                    VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                                        Text(group.title).font(WegoTokens.Typography.label.weight(.semibold))
                                        Text(group.detail).font(WegoTokens.Typography.caption)
                                            .foregroundStyle(WegoTokens.Palette.secondary)
                                    }
                                    Spacer(minLength: 0)
                                }
                                .frame(minHeight: WegoTokens.Metrics.touchTarget, alignment: .leading)
                                .padding(.vertical, WegoTokens.Space.small)
                                .contentShape(Rectangle())
                            }
                            .buttonStyle(.plain).disabled(!available)
                            .accessibilityLabel(group.title + ", " + group.detail)
                            .accessibilityValue(preferences.groups.contains(group) ? "허용" : "허용 안 함")
                            .accessibilityIdentifier("tripRemoteGroup-\(group.rawValue)")
                            if group != TripRemoteGroup.allCases.last { Divider().overlay(WegoTokens.Palette.divider) }
                        }
                    }
                    if !preferences.isValid {
                        Text("허용할 기능을 하나 이상 선택하거나 리모컨 허용을 꺼 주세요.")
                            .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.danger)
                    }
                }
            }
            Text(available
                 ? "여행이 시작돼야 리모컨이 열려요. 허용한 기능은 여행 화면에서 바꾸거나 끌 수 있고, 하차하거나 여행이 끝나면 자동으로 꺼져요."
                 : "동승자 리모컨 설정은 연결 준비 중이에요. 지금은 리모컨 허용 없이 차를 만들 수 있어요.")
                .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
        }
    }
}
