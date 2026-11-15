import SwiftUI

struct TripCarCreateView: View {
    let vehicles: [ProfileVehicle]
    let suggestedName: String
    var isPreview = false
    var reloadVehicles: () async -> Void = { }
    let onCreate: (String, Int, TripRemotePreferences) async throws -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var seats = 3
    @State private var saving = false
    @State private var message: String?
    @State private var showingProfile = false
    @State private var remotePreferences = TripRemotePreferences()

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: WegoTokens.Space.large) {
                if isPreview { Text("샘플 차량으로 동작을 미리 볼 수 있어요.").font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary) }
                vehicleSection
                VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                    HStack {
                        Text("이름 · 필수")
                        Spacer()
                        Text("\(name.count)/20").foregroundStyle(WegoTokens.Palette.secondary)
                    }
                    .font(WegoTokens.Typography.caption)
                    TextField("예: 우리 가족 차", text: $name)
                        .font(WegoTokens.Typography.body)
                        .padding(WegoTokens.Space.medium)
                        .background(WegoTokens.Palette.surface, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.field))
                        .accessibilityLabel("차 이름")
                        .accessibilityIdentifier("tripCarName")
                        .onChange(of: name) { _, value in name = String(value.prefix(20)) }
                }
                VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                    Text("탑승 가능 인원").font(WegoTokens.Typography.label.weight(.semibold))
                    HStack(spacing: WegoTokens.Space.small) {
                        HStack(spacing: WegoTokens.Space.xSmall) {
                            ForEach(0..<seats + 1, id: \.self) { index in
                                RoundedRectangle(cornerRadius: WegoTokens.Space.xSmall)
                                    .fill(index == 0 ? WegoTokens.Palette.ink : WegoTokens.Palette.accent)
                                    .frame(maxWidth: .infinity)
                                    .frame(height: WegoTokens.Space.screen)
                            }
                        }
                        .accessibilityHidden(true)
                        Spacer(minLength: WegoTokens.Space.xSmall)
                        seatButton("minus", label: "인원 줄이기", disabled: seats == 1) { seats -= 1 }
                        Text("\(seats)명").font(WegoTokens.Typography.action).monospacedDigit().fixedSize()
                            .accessibilityIdentifier("tripCarSeats")
                        seatButton("plus", label: "인원 늘리기", disabled: seats == 8) { seats += 1 }
                    }
                    .padding(WegoTokens.Space.compact)
                    .background(WegoTokens.Palette.surface, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.control))
                    Text("운전자를 제외한 인원이에요. 1~8명까지 선택할 수 있어요.")
                        .font(WegoTokens.Typography.caption)
                        .foregroundStyle(WegoTokens.Palette.secondary)
                }
                TripRemotePermissionSection(preferences: $remotePreferences, available: true)
                if let message {
                    Text(message).font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.danger)
                        .accessibilityIdentifier("tripCarCreateError")
                }
            }
            .padding(WegoTokens.Space.screen)
        }
        .disabled(saving)
        .scrollDismissesKeyboard(.interactively)
        .foregroundStyle(WegoTokens.Palette.text)
        .background(WegoTokens.Palette.background)
        .navigationTitle("차 만들기")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) { Button("취소") { dismiss() }.disabled(saving) }
        }
        .safeAreaInset(edge: .bottom) {
            VStack(spacing: WegoTokens.Space.small) {
                Text("차를 만들면 내가 운전자가 되고, 일행이 이 차를 고를 수 있어요.")
                    .font(WegoTokens.Typography.caption)
                    .foregroundStyle(WegoTokens.Palette.secondary)
                Button {
                    Task {
                        saving = true
                        message = nil
                        do {
                            try await onCreate(name.trimmingCharacters(in: .whitespacesAndNewlines), seats, remotePreferences)
                            dismiss()
                        } catch is CancellationError { }
                        catch { message = error.localizedDescription }
                        saving = false
                    }
                } label: {
                    HStack {
                        if saving { WegoButtonLoadingLabel("차 만드는 중…", onAccent: true) }
                        else { Text("차 만들기") }
                    }
                    .font(WegoTokens.Typography.action)
                    .frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.primaryButtonHeight)
                }
                .buttonStyle(WegoPrimaryButtonStyle())
                .disabled(saving || !remotePreferences.isValid || name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || vehicles.count != 1 || vehicles.first?.profile.plateNumber.isEmpty != false)
                .accessibilityIdentifier("tripCarCreateSave")
            }
            .padding(.horizontal, WegoTokens.Space.screen)
            .padding(.vertical, WegoTokens.Space.small)
            .background(WegoTokens.Palette.background)
        }
        .onAppear { if name.isEmpty { name = String((vehicles.count == 1 ? vehicles[0].name : suggestedName).prefix(20)) } }
        .navigationDestination(isPresented: $showingProfile) { ProfileSettingsView() }
        .onChange(of: showingProfile) { _, showing in
            if !showing { Task { await reloadVehicles() } }
        }
        .interactiveDismissDisabled(saving)
    }

    private var vehicleSection: some View {
        VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
            Text("운전할 차량").font(WegoTokens.Typography.label.weight(.semibold))
            if vehicles.count == 1, let vehicle = vehicles.first {
                HStack(spacing: WegoTokens.Space.compact) {
                    Image(systemName: "car.side").foregroundStyle(WegoTokens.Palette.accent)
                        .frame(width: WegoTokens.Metrics.touchTarget, height: WegoTokens.Metrics.touchTarget)
                        .background(WegoTokens.Palette.accentSoft, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.field))
                        .accessibilityHidden(true)
                    VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                        Text(vehicle.name).font(WegoTokens.Typography.section)
                        Text(vehicle.profile.plateNumber.isEmpty ? "차량 번호 미등록" : vehicle.profile.plateNumber)
                            .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                    }
                    Spacer()
                    Image(systemName: vehicle.profile.plateNumber.isEmpty ? "exclamationmark.circle" : "checkmark.circle.fill")
                        .foregroundStyle(WegoTokens.Palette.accent).accessibilityHidden(true)
                }
                .padding(WegoTokens.Space.compact)
                .overlay { RoundedRectangle(cornerRadius: WegoTokens.Radius.control).strokeBorder(WegoTokens.Palette.accent) }
                .accessibilityElement(children: .combine)
                if vehicle.profile.plateNumber.isEmpty {
                    Text("차량 번호를 등록하면 차를 만들 수 있어요.")
                        .font(WegoTokens.Typography.caption)
                        .foregroundStyle(WegoTokens.Palette.secondary)
                    if !isPreview {
                        Button { showingProfile = true } label: {
                            Text("차량 번호 등록").font(WegoTokens.Typography.action)
                                .foregroundStyle(WegoTokens.Palette.accent)
                                .frame(minHeight: WegoTokens.Metrics.touchTarget)
                                .contentShape(Rectangle())
                        }
                            .accessibilityIdentifier("tripCarRegisterPlate")
                    }
                }
            } else {
                Text(vehicles.isEmpty ? "먼저 운전할 차량을 연결해 주세요." : "연결 차량을 한 대로 정리한 뒤 다시 열어 주세요.")
                    .font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.secondary)
            }
            if !isPreview {
                HStack(spacing: WegoTokens.Space.xSmall) {
                    Text("연결된 차량만 고를 수 있어요.")
                    NavigationLink("연결 차량 설정") { VehicleSettingsView() }
                }
                .font(WegoTokens.Typography.caption)
            }
        }
    }

    private func seatButton(_ symbol: String, label: String, disabled: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: symbol).font(WegoTokens.Typography.label)
                .frame(width: WegoTokens.Metrics.touchTarget, height: WegoTokens.Metrics.touchTarget)
                .background(WegoTokens.Palette.background, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.field))
                .contentShape(Rectangle())
        }
        .disabled(disabled || saving)
        .buttonStyle(.plain)
        .accessibilityLabel(label)
    }
}
