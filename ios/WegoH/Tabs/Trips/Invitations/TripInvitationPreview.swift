import SwiftUI

struct TripInvitationPreview: View {
    let invitation: TripPreviewInvitation
    private let store: TripsPreviewStore?
    private let onRespond: ((Bool, Bool) async throws -> Void)?
    @State private var liveChoice: Bool?
    @State private var responding = false
    @State private var error: String?

    init(invitation: TripPreviewInvitation, store: TripsPreviewStore) {
        self.invitation = invitation
        self.store = store
        onRespond = nil
    }

    init(invitation: TripPreviewInvitation, onRespond: @escaping (Bool, Bool) async throws -> Void) {
        self.invitation = invitation
        store = nil
        self.onRespond = onRespond
    }
    @Environment(\.dismiss) private var dismiss
    @State private var confirmsDecline = false
    @State private var invitationUnavailable = false

    private var accepted: AcceptedTripPreview? {
        if let store { return store.accepted.first { $0.id == invitation.id } }
        return liveChoice.map { AcceptedTripPreview(invitation: invitation, locationConsent: $0) }
    }

    var body: some View {
        ZStack {
            invitationContent
                .allowsHitTesting(!confirmsDecline)
                .accessibilityHidden(confirmsDecline)
            if confirmsDecline { declineConfirmation }
        }
        .navigationBarBackButtonHidden(confirmsDecline)
    }

    private var invitationContent: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
                invitationCard
                details
                if let error { Text(error).font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.danger) }
                Text(invitationUnavailable ? "목록으로 돌아가 다른 여행을 확인해 주세요." : accepted == nil
                     ? "여행 일정과 일행 정보는 참여 후 확인할 수 있어요."
                     : "여행 목록에서 참여한 여행을 확인해 주세요.")
                    .font(WegoTokens.Typography.label)
                    .foregroundStyle(WegoTokens.Palette.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .padding(.horizontal, WegoTokens.Space.screen)
            .padding(.vertical, WegoTokens.Space.medium)
        }
        .background(WegoTokens.Palette.background)
        .foregroundStyle(WegoTokens.Palette.text)
        .navigationTitle("여행 초대")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar(.visible, for: .navigationBar)
        .toolbar(.hidden, for: .tabBar)
        .safeAreaInset(edge: .bottom, spacing: 0) {
            VStack(spacing: WegoTokens.Space.small) {
                if store != nil { invitationSampleNotice }
                if accepted == nil && !invitationUnavailable {
                    Button {
                        Task {
                            do { try await sendResponse(accept: true) }
                            catch is CancellationError { }
                            catch { self.error = tripPreparationErrorMessage(error) }
                        }
                    } label: {
                        invitationActionLabel("참여하기", isLoading: responding)
                    }
                    .buttonStyle(WegoPrimaryButtonStyle())
                    .accessibilityIdentifier("tripInvitationAccept")
                    Button { confirmsDecline = true } label: {
                        Group {
                            if responding { WegoButtonLoadingLabel("응답 확인 중…") }
                            else { Text("초대 거절") }
                        }
                        .font(WegoTokens.Typography.label)
                        .frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.touchTarget)
                        .foregroundStyle(WegoTokens.Palette.danger)
                        .contentShape(Rectangle())
                    }
                        .accessibilityIdentifier("tripInvitationDecline")
                } else {
                    Button { dismiss() } label: {
                        invitationActionLabel("여행 목록으로")
                    }
                    .buttonStyle(WegoPrimaryButtonStyle())
                    .accessibilityIdentifier("tripInvitationDone")
                }
            }
            .disabled(responding)
            .padding(.horizontal, WegoTokens.Space.screen)
            .padding(.vertical, WegoTokens.Space.small)
            .background(WegoTokens.Palette.background)
        }

    }

    private var declineConfirmation: some View {
        ZStack {
            WegoTokens.Palette.text.opacity(WegoTokens.Opacity.modalScrim)
                .ignoresSafeArea()
                .accessibilityHidden(true)
            WegoCard(.outlined, padding: WegoTokens.Space.screen, radius: WegoTokens.Radius.sheet) {
                VStack(spacing: WegoTokens.Space.medium) {
                    Text("초대를 거절할까요?")
                        .font(WegoTokens.Typography.cardTitle)
                        .accessibilityAddTraits(.isHeader)
                    Text("받은 초대 목록에서 이 초대가 사라져요.")
                        .font(WegoTokens.Typography.label)
                        .foregroundStyle(WegoTokens.Palette.secondary)
                    HStack(spacing: WegoTokens.Space.small) {
                        Button(role: .cancel) { confirmsDecline = false } label: {
                            Text("취소").font(WegoTokens.Typography.action)
                                .foregroundStyle(WegoTokens.Palette.secondary)
                                .frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.primaryButtonHeight)
                                .background(WegoTokens.Palette.surface,
                                            in: RoundedRectangle(cornerRadius: WegoTokens.Radius.control))
                                .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .accessibilityIdentifier("tripInvitationDeclineCancel")
                        Button(role: .destructive) {
                            confirmsDecline = false
                            Task {
                                do { try await sendResponse(accept: false); dismiss() }
                                catch { self.error = error.localizedDescription }
                            }
                        } label: {
                            Text("거절").font(WegoTokens.Typography.action)
                                .foregroundStyle(WegoTokens.Palette.onAccent)
                                .frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.primaryButtonHeight)
                                .background(WegoTokens.Palette.danger,
                                            in: RoundedRectangle(cornerRadius: WegoTokens.Radius.control))
                                .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .accessibilityIdentifier("tripInvitationDeclineConfirm")
                    }
                }
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
            }
            .padding(.horizontal, WegoTokens.Space.xLarge)
            .accessibilityElement(children: .contain)
            .accessibilityAddTraits(.isModal)
            .accessibilityAction(.escape) { confirmsDecline = false }
            .accessibilityIdentifier("tripInvitationDeclineDialog")
        }
    }

    @MainActor private func sendResponse(accept: Bool) async throws {
        guard !responding else { throw CancellationError() }
        responding = true
        defer { responding = false }
        if let store {
            if accept { store.accept(invitation, locationConsent: true) }
            else { store.decline(invitation) }
        } else if let onRespond {
            do {
                try await onRespond(accept, accept)
                if accept { liveChoice = true }
            } catch {
                if let tripError = error as? IPhoneTripRequestError, case .routeConflict("TRIP_STATE_CONFLICT") = tripError {
                    invitationUnavailable = true
                    self.error = "이 여행은 종료되었거나 취소되어 초대에 응답할 수 없어요."
                }
                throw error
            }
        }
    }

    private var invitationCard: some View {
        VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
            HStack {
                Text(invitation.ownerName)
                    .foregroundStyle(accepted == nil ? WegoTokens.Palette.onInk : WegoTokens.Palette.ink)
                    .frame(width: WegoTokens.Metrics.tripInvitationAvatarSize,
                           height: WegoTokens.Metrics.tripInvitationAvatarSize)
                    .background(accepted == nil ? WegoTokens.Palette.ink : WegoTokens.Palette.onInk, in: Circle())
                Spacer()
                Image(systemName: accepted == nil ? "envelope" : "checkmark")
                    .font(WegoTokens.Typography.action)
                    .foregroundStyle(accepted == nil ? WegoTokens.Palette.accent : WegoTokens.Palette.ink)
                    .frame(width: WegoTokens.Metrics.tripInvitationAvatarSize,
                           height: WegoTokens.Metrics.tripInvitationAvatarSize)
                    .background(accepted == nil ? WegoTokens.Palette.background : WegoTokens.Palette.routeHighlight,
                                in: Circle())
                Spacer()
                Text("나")
                    .foregroundStyle(accepted == nil ? WegoTokens.Palette.accent : WegoTokens.Palette.ink)
                    .frame(width: WegoTokens.Metrics.tripInvitationAvatarSize,
                           height: WegoTokens.Metrics.tripInvitationAvatarSize)
                    .background(accepted == nil ? WegoTokens.Palette.accentSoft : WegoTokens.Palette.background, in: Circle())
                    .overlay {
                        if accepted == nil {
                            Circle().strokeBorder(WegoTokens.Palette.accent,
                                                  style: StrokeStyle(lineWidth: WegoTokens.Metrics.hairlineWidth,
                                                                     dash: [WegoTokens.Metrics.hairlineWidth, WegoTokens.Metrics.timelineWidth]))
                        }
                    }
            }
            .font(WegoTokens.Typography.caption.weight(.semibold))
            .background {
                Canvas { context, size in
                    var line = Path()
                    line.move(to: CGPoint(x: 0, y: size.height / 2))
                    line.addLine(to: CGPoint(x: size.width, y: size.height / 2))
                    context.stroke(line, with: .color(accepted == nil ? WegoTokens.Palette.accent : WegoTokens.Palette.routeHighlight),
                                   style: StrokeStyle(lineWidth: WegoTokens.Metrics.hairlineWidth,
                                                      dash: accepted == nil ? [WegoTokens.Metrics.hairlineWidth, WegoTokens.Metrics.timelineWidth] : []))
                }
            }
            .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                Text(invitationUnavailable ? "만료된 여행 초대" : accepted == nil ? "받은 여행 초대" : "초대를 수락했어요")
                    .font(WegoTokens.Typography.caption.weight(.semibold))
                    .foregroundStyle(accepted == nil ? WegoTokens.Palette.accent : WegoTokens.Palette.routeHighlight)
                    .accessibilityIdentifier("tripInvitationStatus")
                Text(invitation.title)
                    .font(WegoTokens.Typography.title)
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityAddTraits(.isHeader)
                    .accessibilityIdentifier("inviteDetailTitle")
                Text("\(invitation.ownerName)님의 초대")
                    .font(WegoTokens.Typography.label)
                    .foregroundStyle(accepted == nil ? WegoTokens.Palette.secondary : WegoTokens.Palette.onInkSecondary)
            }
        }
        .padding(WegoTokens.Space.screen)
        .foregroundStyle(accepted == nil ? WegoTokens.Palette.text : WegoTokens.Palette.onInk)
        .background(accepted == nil ? WegoTokens.Palette.accentSoft : WegoTokens.Palette.ink,
                    in: RoundedRectangle(cornerRadius: WegoTokens.Radius.hero))
    }

    private var details: some View {
        VStack(spacing: WegoTokens.Space.medium) {
            LabeledContent("만든 사람", value: invitation.ownerName)

        }
        .font(WegoTokens.Typography.label)
        .padding(WegoTokens.Space.medium)
        .background(WegoTokens.Palette.surface, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.card))
    }
}

private func invitationActionLabel(_ title: String, isLoading: Bool = false, onAccent: Bool = true) -> some View {
    Group {
        if isLoading { WegoButtonLoadingLabel("참여 확인 중…", onAccent: onAccent) }
        else { Text(title) }
    }
        .font(WegoTokens.Typography.action)
        .frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.primaryButtonHeight)
        .contentShape(Rectangle())
}

private var invitationSampleNotice: some View {
    Text("샘플 초대예요. 실제 초대 응답이나 위치 공유는 전송되지 않아요.")
        .font(WegoTokens.Typography.caption)
        .foregroundStyle(WegoTokens.Palette.secondary)
        .fixedSize(horizontal: false, vertical: true)
}
