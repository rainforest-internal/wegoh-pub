import SwiftUI

struct TripRemotePreviewView: View {
    let carName: String
    let ownerName: String
    let preferences: TripRemotePreferences
    @Environment(\.dismiss) private var dismiss
    @State private var seat = Seat.rearLeft
    @State private var temperature = 22.5
    @State private var fan = 3
    @State private var power = true
    @State private var ac = true
    @State private var purifier = false
    @State private var window = 30.0
    @State private var cabin = false
    @State private var reading = true
    @State private var ambient = false
    @State private var heat = 0
    @State private var ventilation = 0
    @State private var message: String?

    private enum Seat: String, CaseIterable, Identifiable {
        case passenger = "조수석", rearLeft = "뒷좌석 왼쪽", middle = "가운데", rearRight = "뒷좌석 오른쪽"
        var id: Self { self }
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: WegoTokens.Space.large) {
                Text("디자인 미리보기 · 아래 값은 샘플이며 실제 차량 상태가 아니에요.")
                    .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                    Text(carName).font(WegoTokens.Typography.cardTitle)
                    Text(tripRemoteSummary(ownerName: ownerName, actionCount: preferences.actionCount)).font(WegoTokens.Typography.label)
                }.tripProgressCard(ink: true)
                if preferences.enabled, !preferences.allowedGroups.isEmpty {
                    VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                        Text("조절할 좌석").font(WegoTokens.Typography.section)
                        Picker("조절할 좌석", selection: $seat) {
                            ForEach(Seat.allCases) { Text($0.rawValue).tag($0) }
                        }.pickerStyle(.menu).accessibilityIdentifier("remoteSeatPicker")
                    }
                    if preferences.allowedGroups.contains(.climate) { climate }
                    if preferences.allowedGroups.contains(.windows) {
                        VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                            Text("창문 · \(seat.rawValue)").font(WegoTokens.Typography.section)
                            Text("창문 열림 \(Int(window))%").font(WegoTokens.Typography.body)
                            Slider(value: $window, in: 0...100, step: 1).accessibilityLabel("창문 열림")
                            Text("0%는 닫힘, 100%는 완전히 열림이에요.").font(WegoTokens.Typography.caption)
                            Button("\(Int(window))% 적용") { applied() }.font(WegoTokens.Typography.action)
                                .frame(minHeight: WegoTokens.Metrics.touchTarget)
                            if seat == .middle { Text("가운데 좌석에는 창문이 없어요.").font(WegoTokens.Typography.caption) }
                        }.disabled(seat == .middle).tripProgressCard()
                    }
                    if preferences.allowedGroups.contains(.lights) {
                        VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
                            Text("조명").font(WegoTokens.Typography.section)
                            Toggle("실내등 · 차 전체 · 정차 중에만", isOn: $cabin).onChange(of: cabin) { _, _ in applied() }
                            Toggle("독서등", isOn: $reading).disabled(seat == .middle).onChange(of: reading) { _, _ in applied() }
                            Toggle("무드등", isOn: $ambient).onChange(of: ambient) { _, _ in applied() }
                        }.font(WegoTokens.Typography.body).tripProgressCard()
                    }
                    if preferences.allowedGroups.contains(.seats) {
                        VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
                            Text("시트 · \(seat.rawValue)").font(WegoTokens.Typography.section)
                            Stepper("시트 열선 · \(heat)단계", value: $heat, in: 0...10).onChange(of: heat) { _, _ in applied() }
                            Stepper("시트 통풍 · \(ventilation)단계", value: $ventilation, in: 0...10).onChange(of: ventilation) { _, _ in applied() }
                            Text("시트 열선과 통풍은 정차 중에 사용할 수 있어요. 운전석은 원격으로 조절할 수 없어요. 현재 화면은 정차 샘플이에요.")
                                .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                        }.font(WegoTokens.Typography.body).tripProgressCard()
                    }
                } else {
                    Text("동승자 리모컨 허용이 꺼져 있어요.").font(WegoTokens.Typography.body)
                }
                if let message { Text(message).font(WegoTokens.Typography.caption).accessibilityIdentifier("remotePreviewMessage") }
            }.padding(WegoTokens.Space.screen)
        }
        .foregroundStyle(WegoTokens.Palette.text).background(WegoTokens.Palette.background)
        .navigationTitle("여행 리모컨").navigationBarTitleDisplayMode(.inline)
        .toolbar { ToolbarItem(placement: .cancellationAction) { Button("닫기") { dismiss() } } }
    }

    private var climate: some View {
        VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
            Text("공조 · \(seat.rawValue)").font(WegoTokens.Typography.section)
            Stepper(value: $temperature, in: 0...50, step: 0.5) {
                Text("설정 온도 \(temperature, specifier: "%.1f")°C")
            }.accessibilityIdentifier("remoteTemperature")
            Stepper("풍량 단계 · \(fan)", value: $fan, in: 0...100)
            ActionButton(title: "온도 \(String(format: "%.1f", temperature))°C · 풍량 \(fan) 적용") { applied() }
                .accessibilityIdentifier("remoteApplyClimate")
            Toggle("공조 전원", isOn: $power).onChange(of: power) { _, _ in applied() }
            Toggle("에어컨", isOn: $ac).onChange(of: ac) { _, _ in applied() }
            Toggle("공기청정", isOn: $purifier).onChange(of: purifier) { _, _ in applied() }
        }.font(WegoTokens.Typography.body).tripProgressCard()
    }
    private func applied() { message = "미리보기 값을 바꿨어요. 실제 차량에는 명령을 보내지 않았어요." }
}
