import SwiftUI
import UIKit

struct SettingsView: View {
    @Environment(SessionManager.self) private var session
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @StateObject private var permissions = WalkthroughPermissions()

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: WegoTokens.Space.screen) {
                Text("설정").font(WegoTokens.Typography.hero)
                    .foregroundStyle(WegoTokens.Palette.text)
                    .frame(minHeight: WegoTokens.Metrics.settingsHeaderHeight)
                    .accessibilityAddTraits(.isHeader)
                NavigationLink { ProfileSettingsView().toolbar(.visible, for: .navigationBar).toolbar(.hidden, for: .tabBar) } label: { accountCard }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("settingsAccount")
                VStack(spacing: 0) {
                    NavigationLink { ProfileSettingsView().toolbar(.visible, for: .navigationBar).toolbar(.hidden, for: .tabBar) } label: {
                        SettingsMenuLabel("프로필", detail: "이름과 친구 코드", icon: "person")
                    }
                    .accessibilityIdentifier("settingsProfile")
                    Divider().overlay(WegoTokens.Palette.divider)
                    NavigationLink { DevicePermissionSettingsView().toolbar(.visible, for: .navigationBar).toolbar(.hidden, for: .tabBar) } label: {
                        SettingsMenuLabel("권한 설정", detail: "이 iPhone의 위치, 마이크, 카메라", icon: "checkmark.shield")
                    }
                    .accessibilityIdentifier("settingsPermissions")
                    Divider().overlay(WegoTokens.Palette.divider)
                    NavigationLink { NotificationSettingsView().toolbar(.visible, for: .navigationBar).toolbar(.hidden, for: .tabBar) } label: {
                        SettingsMenuLabel("알림 설정", detail: "친구 요청·여행 초대·손들기 반응", icon: "bell.badge")
                    }
                    .accessibilityIdentifier("settingsNotifications")
                    Divider().overlay(WegoTokens.Palette.divider)
                    NavigationLink {
                        VehicleSettingsView().id(session.current?.accountID)
                            .toolbar(.visible, for: .navigationBar).toolbar(.hidden, for: .tabBar)
                    } label: {
                        SettingsMenuLabel("연결 차량 설정", detail: "QR 스캔·코드 입력과 연결 해제", icon: "car")
                    }
                    .accessibilityIdentifier("settingsVehicles")
                }
                .buttonStyle(.plain)
                VStack(alignment: .leading, spacing: WegoTokens.Space.compact) {
                    Text("이 iPhone의 권한")
                        .font(WegoTokens.Typography.label.weight(.semibold))
                        .foregroundStyle(WegoTokens.Palette.secondary)
                        .accessibilityAddTraits(.isHeader)
                    if dynamicTypeSize.isAccessibilitySize {
                        VStack(spacing: WegoTokens.Space.small) { permissionTiles }
                    } else {
                        HStack(alignment: .top, spacing: WegoTokens.Space.small) { permissionTiles }
                    }
                }
            }
            .padding(.horizontal, WegoTokens.Space.screen)
            .padding(.bottom, WegoTokens.Space.screen)
        }
        .scrollBounceBehavior(.basedOnSize)
        .safeAreaInset(edge: .bottom, spacing: 0) {
            if session.phase == .signedIn || session.phase == .restoreFailed || session.phase == .logoutPending || session.phase == .signingOut {
                Button { Task { await session.signOut() } } label: {
                    Group {
                        if session.phase == .signingOut { WegoButtonLoadingLabel("로그아웃 중…") }
                        else { Text(session.phase == .logoutPending ? "로그아웃 다시 시도" : "이 iPhone에서 로그아웃") }
                    }
                    .font(WegoTokens.Typography.body)
                    .foregroundStyle(WegoTokens.Palette.text)
                    .padding(.vertical, WegoTokens.Space.compact)
                    .frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.primaryButtonHeight)
                    .background(WegoTokens.Palette.background, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.control))
                    .overlay { RoundedRectangle(cornerRadius: WegoTokens.Radius.control).strokeBorder(WegoTokens.Palette.divider) }
                }
                .buttonStyle(.plain)
                .disabled(session.phase == .signingOut)
                .accessibilityIdentifier("settingsLogout")
                .padding(.horizontal, WegoTokens.Space.screen)
                .padding(.vertical, WegoTokens.Space.compact)
                .background(WegoTokens.Palette.background)
            }
        }
        .background(WegoTokens.Palette.background)
        .navigationTitle("설정")
        .toolbar(.hidden, for: .navigationBar)
        .onChange(of: scenePhase) { _, phase in permissions.updateScene(phase) }
        .onAppear { permissions.updateScene(scenePhase) }
        .onDisappear { permissions.updateScene(.background) }
    }

    private var connectionLabel: String {
        switch session.phase {
        case .signedIn: "로그인됨"
        case .signedOut: "로그인 필요"
        case .signingIn: "로그인 중"
        case .checkingSession: "확인 중"
        case .restoreFailed: "확인 필요"
        case .signingOut: "로그아웃 중"
        case .logoutPending: "로그아웃 미완료"
        }
    }

    private var accountCard: some View {
        VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
            HStack(spacing: WegoTokens.Space.compact) {
                Group {
                    if let account = session.current {
                        Text(String(account.displayName.prefix(2))).font(WegoTokens.Typography.label.weight(.bold))
                    } else { Image(systemName: "person").font(WegoTokens.Typography.cardTitle) }
                }
                .foregroundStyle(WegoTokens.Palette.ink)
                .frame(width: WegoTokens.Metrics.settingsAvatarSize, height: WegoTokens.Metrics.settingsAvatarSize)
                .background(WegoTokens.Palette.onInk, in: Circle())
                .accessibilityHidden(true)
                VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                    Text("앱 계정").font(WegoTokens.Typography.caption)
                        .foregroundStyle(WegoTokens.Palette.onInkSecondary)
                    Text(session.current?.displayName ?? (session.phase == .signedOut ? "로그인해 주세요" : connectionLabel))
                        .font(WegoTokens.Typography.cardTitle)
                        .foregroundStyle(WegoTokens.Palette.onInk)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                HStack(spacing: WegoTokens.Space.xSmall) {
                    if session.phase == .signedIn {
                        Circle().fill(WegoTokens.Palette.accent)
                            .frame(width: WegoTokens.Metrics.settingsStatusDotSize, height: WegoTokens.Metrics.settingsStatusDotSize)
                    }
                    Text(connectionLabel).font(WegoTokens.Typography.caption.weight(.semibold))
                        .fixedSize(horizontal: false, vertical: true)
                }
                .foregroundStyle(WegoTokens.Palette.ink)
                .padding(.horizontal, WegoTokens.Space.small)
                .padding(.vertical, WegoTokens.Space.xSmall)
                .background(WegoTokens.Palette.onInk, in: Capsule())
            }
            Rectangle().fill(WegoTokens.Palette.inkDivider).frame(height: WegoTokens.Metrics.hairlineWidth)
                .accessibilityHidden(true)
            if let account = session.current {
                HStack(alignment: .top, spacing: WegoTokens.Space.small) {
                    Text("로그인 만료").foregroundStyle(WegoTokens.Palette.onInkSecondary)
                    Spacer(minLength: WegoTokens.Space.small)
                    Text(account.expiresAt.formatted(date: .abbreviated, time: .shortened))
                        .foregroundStyle(WegoTokens.Palette.onInk)
                        .multilineTextAlignment(.trailing)
                }
                .font(WegoTokens.Typography.caption)
                .fixedSize(horizontal: false, vertical: true)
            } else if let message = session.message ?? (session.phase == .signedOut ? "로그인하고 내 계정을 연결해 주세요." : nil) {
                Text(message)
                    .font(WegoTokens.Typography.label)
                    .foregroundStyle(WegoTokens.Palette.onInkSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(WegoTokens.Space.screen)
        .background(WegoTokens.Palette.ink, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.hero))
    }

    @ViewBuilder private var permissionTiles: some View {
        permissionTile("위치", status: permissions.locationLabel, id: "settingsLocationStatus")
        permissionTile("마이크", status: permissions.microphoneLabel, id: "settingsMicrophoneStatus")
        permissionTile("카메라", status: permissions.cameraLabel, id: "settingsCameraStatus")
    }

    private func permissionTile(_ title: String, status: String, id: String) -> some View {
        VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
            Text(title).font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
            Text(status).font(WegoTokens.Typography.label.weight(.semibold))
                .foregroundStyle(status == "허용됨" ? WegoTokens.Palette.accent : WegoTokens.Palette.text)
        }
        .fixedSize(horizontal: false, vertical: true)
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(WegoTokens.Space.compact)
        .background(WegoTokens.Palette.surface, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.control))
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier(id)
    }
}

private struct SettingsMenuLabel: View {
    let title: String
    let detail: String
    let icon: String

    init(_ title: String, detail: String, icon: String) {
        self.title = title
        self.detail = detail
        self.icon = icon
    }

    var body: some View {
        HStack(spacing: WegoTokens.Space.compact) {
            Image(systemName: icon).font(WegoTokens.Typography.cardTitle)
                .foregroundStyle(WegoTokens.Palette.accent)
                .frame(width: WegoTokens.Metrics.touchTarget, height: WegoTokens.Metrics.touchTarget)
                .background(WegoTokens.Palette.accentSoft, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.control))
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                Text(title).font(WegoTokens.Typography.section).foregroundStyle(WegoTokens.Palette.text)
                Text(detail).font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.secondary)
            }
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
            Image(systemName: "chevron.right").font(WegoTokens.Typography.label.weight(.semibold))
                .foregroundStyle(WegoTokens.Palette.secondary)
                .accessibilityHidden(true)
        }
        .padding(.vertical, WegoTokens.Space.compact)
        .frame(minHeight: WegoTokens.Metrics.settingsMenuHeight)
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
    }
}

private struct DevicePermissionSettingsView: View {
    @StateObject private var permissions = WalkthroughPermissions()
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: WegoTokens.Space.screen) {
                VStack(alignment: .leading, spacing: WegoTokens.Space.compact) {
                    Text("이 iPhone의 권한").font(WegoTokens.Typography.label.weight(.semibold))
                        .foregroundStyle(WegoTokens.Palette.secondary)
                        .accessibilityAddTraits(.isHeader)
                    DevicePermissionCard(title: "위치", icon: "mappin.and.ellipse", status: permissions.locationLabel,
                                         detail: "진행 중인 여행의 일행에게 현재 위치를 보여줘요.")
                        .accessibilityIdentifier("locationStatus")
                    DevicePermissionCard(title: "마이크", icon: "mic", status: permissions.microphoneLabel,
                                         detail: "워키토키 버튼을 누르고 일행에게 말할 때 사용해요.")
                        .accessibilityIdentifier("microphoneStatus")
                    DevicePermissionCard(title: "카메라", icon: "camera", status: permissions.cameraLabel,
                                         detail: "차량 화면에 표시된 연결 QR 코드를 스캔할 때 사용해요.")
                        .accessibilityIdentifier("cameraStatus")
                }
                VStack(spacing: WegoTokens.Space.compact) {
                    if permissions.hasPending {
                        Button(action: permissions.requestAll) {
                            Text("권한 설정").font(WegoTokens.Typography.action)
                                .padding(.vertical, WegoTokens.Space.compact)
                                .frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.primaryButtonHeight)
                        }
                        .buttonStyle(WegoPrimaryButtonStyle())
                        .disabled(permissions.isRequesting)
                        .accessibilityIdentifier("permissionsRequestPending")
                    }
                    Link(destination: URL(string: UIApplication.openSettingsURLString)!) {
                        HStack(spacing: WegoTokens.Space.small) {
                            Text("iPhone 설정 열기")
                            Image(systemName: "arrow.up.right").accessibilityHidden(true)
                        }
                            .font(WegoTokens.Typography.action)
                            .foregroundStyle(WegoTokens.Palette.accent)
                            .padding(.vertical, WegoTokens.Space.compact)
                            .frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.primaryButtonHeight)
                            .background(WegoTokens.Palette.accentSoft, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.control))
                    }
                    .disabled(permissions.isRequesting)
                    .accessibilityIdentifier("systemSettingsLink")
                    Text("내 위치를 일행에게 공유할지는 여행마다 선택해요.")
                        .font(WegoTokens.Typography.caption)
                        .foregroundStyle(WegoTokens.Palette.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.horizontal, WegoTokens.Space.xSmall)
                }
            }
            .padding(.horizontal, WegoTokens.Space.screen)
            .padding(.vertical, WegoTokens.Space.medium)
        }
        .scrollBounceBehavior(.basedOnSize)
        .background(WegoTokens.Palette.background)
        .navigationTitle("권한 설정")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear { permissions.updateScene(scenePhase) }
        .onChange(of: scenePhase) { _, phase in permissions.updateScene(phase) }
        .onDisappear { permissions.updateScene(.background) }
    }
}

private struct DevicePermissionCard: View {
    let title: String
    let icon: String
    let status: String
    let detail: String
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    private var pending: Bool { status == "설정 전" }
    private var allowed: Bool { status == "허용됨" }
    private var unavailable: Bool { status == "허용 안 함" || status == "사용 제한" || status == "위치 서비스 꺼짐" }
    private var statusColor: Color {
        allowed ? WegoTokens.Palette.accent : (unavailable ? WegoTokens.Palette.danger : WegoTokens.Palette.text)
    }

    var body: some View {
        HStack(alignment: .top, spacing: WegoTokens.Space.compact) {
            Image(systemName: icon).font(WegoTokens.Typography.cardTitle)
                .foregroundStyle(unavailable ? WegoTokens.Palette.secondary : WegoTokens.Palette.accent)
                .frame(width: WegoTokens.Metrics.touchTarget, height: WegoTokens.Metrics.touchTarget)
                .background(unavailable ? WegoTokens.Palette.surface : WegoTokens.Palette.accentSoft,
                            in: RoundedRectangle(cornerRadius: WegoTokens.Radius.control))
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                if dynamicTypeSize.isAccessibilitySize {
                    VStack(alignment: .leading, spacing: WegoTokens.Space.small) { titleAndStatus }
                } else {
                    HStack(alignment: .firstTextBaseline, spacing: WegoTokens.Space.small) {
                        Text(title).font(WegoTokens.Typography.section)
                        Spacer(minLength: 0)
                        statusPill
                    }
                }
                Text(detail).font(WegoTokens.Typography.label)
                    .foregroundStyle(WegoTokens.Palette.secondary)
                    .lineSpacing(WegoTokens.Space.xSmall)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .foregroundStyle(WegoTokens.Palette.text)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(WegoTokens.Space.medium)
        .background(WegoTokens.Palette.background, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.card))
        .overlay {
            RoundedRectangle(cornerRadius: WegoTokens.Radius.card)
                .strokeBorder(pending ? WegoTokens.Palette.accent : WegoTokens.Palette.divider,
                              lineWidth: pending ? WegoTokens.Metrics.selectedBorderWidth : WegoTokens.Metrics.hairlineWidth)
        }
        .accessibilityElement(children: .combine)
    }

    @ViewBuilder private var titleAndStatus: some View {
        Text(title).font(WegoTokens.Typography.section)
        statusPill
    }

    private var statusPill: some View {
        Text(status).font(WegoTokens.Typography.caption.weight(.semibold))
            .foregroundStyle(statusColor)
            .padding(.horizontal, WegoTokens.Space.small)
            .padding(.vertical, WegoTokens.Space.xSmall)
            .background(allowed ? WegoTokens.Palette.accentSoft : WegoTokens.Palette.surface, in: Capsule())
            .overlay { if !allowed { Capsule().strokeBorder(unavailable ? WegoTokens.Palette.danger : WegoTokens.Palette.divider) } }
            .fixedSize(horizontal: false, vertical: true)
    }
}

extension View {
    func wegoSettingsList() -> some View {
        listStyle(.insetGrouped)
            .scrollContentBackground(.hidden)
            .background(WegoTokens.Palette.background)
    }

    func wegoListRows() -> some View {
        listRowBackground(WegoTokens.Palette.surface)
            .listRowSeparatorTint(WegoTokens.Palette.divider)
    }
}
