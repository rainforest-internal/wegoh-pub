import SwiftUI

struct TripsHomeView: View {
    var notification: IPhonePushNotification? = nil
    var returnFromBackground: UUID? = nil
    var isSelected = true

    var body: some View {
        #if DEBUG
        if CourseUIFixture.requested && ProcessInfo.processInfo.arguments.contains("-trip-car-ui-missing-plate") {
            TripCarCreateUIFixture()
        } else if ProcessInfo.processInfo.arguments.contains("-trips-ui-create") {
            TripCreateView { _ in throw TripPreparationError.previewUnsupported }
        } else if ProcessInfo.processInfo.arguments.contains("-trips-ui-preview") || ProcessInfo.processInfo.arguments.contains("-trips-ui-empty") {
            TripsPreviewHomeView(isRootPreview: true)
        } else { TripsAccountHomeView(notification: notification, returnFromBackground: returnFromBackground, isSelected: isSelected) }
        #else
        TripsAccountHomeView(notification: notification, returnFromBackground: returnFromBackground, isSelected: isSelected)
        #endif
    }
}

struct TripsAccountHomeView: View {
    @Environment(SessionManager.self) private var session
    @State private var push = IPhonePushManager.shared
    @State private var visible = false
    let notification: IPhonePushNotification?
    let returnFromBackground: UUID?
    let isSelected: Bool
    @State private var handledNotificationID: String?
    @State private var notificationNotice: String?
    @State private var notifiedInvitation: IPhoneTripInvitation?
    @State private var retry = 0
    @State private var store: TripsAccountStore?
    @State private var showingCreate = false
    @State private var showingLogin = false
    @State private var confirmsRelogin = false
    @State private var createdTripID: String?
    private let api: any IPhoneTripServing

    init(api: (any IPhoneTripServing)? = nil, notification: IPhonePushNotification? = nil,
         returnFromBackground: UUID? = nil, isSelected: Bool = true) {
        self.notification = notification
        self.returnFromBackground = returnFromBackground
        self.isSelected = isSelected
        #if DEBUG
        self.api = api ?? IPhoneTripAPI(configuration: CourseDiscoveryUIFixture.configuration)
        #else
        self.api = api ?? IPhoneTripAPI()
        #endif
    }

    private var canRead: Bool { session.phase == .signedIn && session.current?.scopes.contains("trips:read") == true }
    private var boundStore: TripsAccountStore? {
        guard let account = session.current, store?.belongsToAccount(account) == true else { return nil }
        return store
    }
    private var list: IPhoneTripList? { boundStore?.value }
    private var loading: Bool { boundStore?.loading == true }
    private var error: String? { boundStore?.errorMessage }
    private var hasLoadedEmptyCurrentTrips: Bool {
        list.map { value in
            !value.trips.contains { $0.state == .planned || $0.state == .active }
        } == true
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: WegoTokens.Space.large) {
                HStack {
                    Text("여행").font(WegoTokens.Typography.hero).accessibilityAddTraits(.isHeader)
                    Spacer()

                }
                .frame(minHeight: WegoTokens.Metrics.settingsHeaderHeight)
                if canRead, let notificationNotice {
                    VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                        Text(notificationNotice).font(WegoTokens.Typography.label)
                            .accessibilityIdentifier("tripPushNotice")
                        Button("다시 확인") {
                            handledNotificationID = nil
                            retry += 1
                        }
                        .buttonStyle(.wego(.soft)).disabled(loading)
                        .accessibilityIdentifier("tripPushRetry")
                    }
                }
                if session.phase == .checkingSession || session.phase == .signingOut {
                    WegoLoadingView(session.phase == .signingOut ? "로그아웃 중…" : "로그인 확인 중…", layout: .list)
                } else if !canRead {
                    accountGate
                } else if let list {
                    if loading { WegoLoadingView("여행을 새로 확인하고 있어요.", layout: .row) }
                    invitationList(list.invitations)
                    let current = list.trips.filter { $0.state == .planned || $0.state == .active }
                    let past = list.trips.filter { $0.state == .completed || $0.state == .cancelled }
                    Text("내 여행").font(WegoTokens.Typography.section).accessibilityAddTraits(.isHeader)
                    if current.isEmpty {
                        WegoEmptyListCard(systemImage: "map", title: "아직 참여 중인 여행이 없어요",
                                          message: "새 여행을 만들거나 초대를 수락하면 여기에 보여요.", actionTitle: "여행 만들기",
                                          actionIdentifier: "tripCreateEmpty", contentIdentifier: "tripsEmpty", showsAction: false) { showingCreate = true }
                    }
                    ForEach(current) { trip in tripLink(trip) }
                    if !past.isEmpty {
                        Text("지난 여행").font(WegoTokens.Typography.section).accessibilityAddTraits(.isHeader)
                        ForEach(past) { trip in tripLink(trip) }
                    }
                } else if error == nil || loading { WegoLoadingView("여행을 불러오는 중", layout: .list) }
                if notificationNotice == nil, canRead, let error, !loading, list == nil {
                    WegoLoadingFailureView(message: error) { Task { await refresh() } }
                } else if notificationNotice == nil, let error, list != nil {
                    VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                        Text(error).font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.danger)
                            .accessibilityIdentifier("tripsRefreshError")
                        Button("다시 불러오기") { Task { await refresh() } }
                            .buttonStyle(.wego(.soft)).disabled(loading)
                            .accessibilityIdentifier("tripsRefresh")
                    }
                }
                #if DEBUG
                NavigationLink("디자인 미리보기") { TripsPreviewHomeView().toolbar(.hidden, for: .tabBar) }
                    .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                #endif
            }
            .padding(.horizontal, WegoTokens.Space.screen).padding(.bottom, WegoTokens.Space.medium)
        }
        .foregroundStyle(WegoTokens.Palette.text).background(WegoTokens.Palette.background).buttonStyle(.plain)
        .toolbar(.hidden, for: .navigationBar)
        .safeAreaInset(edge: .bottom) {
            if canRead && list != nil {
                WegoFloatingAction(title: "여행 만들기", identifier: hasLoadedEmptyCurrentTrips ? "tripCreateEmpty" : "tripCreate") { showingCreate = true }
            }
        }
        .scrollBounceBehavior(.always, axes: .vertical)
        .refreshable { await refresh() }
        .onAppear {
            visible = true
            refreshIfInvalidated()
        }
        .onDisappear { visible = false }
        .onChange(of: push.foregroundTripInvitation) { _, _ in refreshIfInvalidated() }
        .onChange(of: returnFromBackground) { _, _ in refreshIfInvalidated() }
        .task(id: TripListRequest(account: session.current.map(TripsSessionIdentity.init), retry: retry, isSelected: isSelected)) {
            guard isSelected else { return }
            guard canRead, let account = session.current else { store = nil; return }
            if store?.belongsToAccount(account) != true {
                store = TripsAccountStore(session: session, api: api)
            }
            guard let boundStore else { return }
            let invalidated = boundStore.noteInvalidation(invitation: push.foregroundTripInvitation, foregroundReturn: returnFromBackground)
            if let notification, notification.accountID == account.accountID,
               handledNotificationID != notification.eventID, let tripID = notification.tripID {
                notificationNotice = nil
                if notification.kind == .tripInvitation {
                    let destination = await boundStore.invitationDestination(for: tripID)
                    guard !Task.isCancelled, boundStore.isCurrent, boundStore.belongsToAccount(account),
                          self.boundStore === boundStore else { return }
                    switch destination {
                    case .review(let invitation): notifiedInvitation = invitation
                    case .member(let id): createdTripID = id
                    case .unavailable: notificationNotice = "이미 처리됐거나 만료된 여행 초대예요."
                    case nil: notificationNotice = boundStore.errorMessage ?? "여행 초대를 확인하지 못했어요."
                    }
                    handledNotificationID = notification.eventID
                } else {
                    handledNotificationID = notification.eventID
                    createdTripID = tripID
                    if boundStore.value == nil && boundStore.errorMessage == nil { await boundStore.load() }
                }
            } else {
                await boundStore.reloadOnSelection(invalidated: invalidated)
            }
        }
        .navigationDestination(isPresented: Binding(get: { notifiedInvitation != nil }, set: { if !$0 { notifiedInvitation = nil } })) {
            if let invitation = notifiedInvitation { invitationReview(invitation) }
        }
        .sheet(isPresented: $showingCreate) {
            NavigationStack {
                TripCreateView { draft in
                    guard let account = session.current else { throw IPhoneSessionError.invalidSession }
                    let id = try await session.withToken(for: account) { try await api.create(draft, token: $0) }
                    await refresh()
                    createdTripID = id
                }
            }
        }
        .sheet(isPresented: $showingLogin) { LoginView(secondaryTitle: "닫기") { showingLogin = false } }
        .navigationDestination(isPresented: Binding(get: { createdTripID != nil && !showingCreate }, set: { if !$0 { createdTripID = nil } })) {
            if let id = createdTripID { TripPreparationView(tripID: id, session: session, onMutation: refresh) }
        }
        .alert("여행 기능을 위해 다시 로그인할까요?", isPresented: $confirmsRelogin) {
            Button("다시 로그인") {
                Task {
                    await session.signOut()
                    if session.phase == .signedOut { showingLogin = true }
                }
            }
            Button("취소", role: .cancel) { }
        } message: { Text("이 iPhone에서 로그아웃한 뒤 다시 로그인해 여행·차량·경로 기능을 승인해 주세요.") }
    }

    private var accountGate: some View {
        VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
            Image(systemName: "map").font(WegoTokens.Typography.title).foregroundStyle(WegoTokens.Palette.accent).accessibilityHidden(true)
            Text(session.current == nil ? "내 여행을 함께 준비해요" : "여행 기능이 추가됐어요").font(WegoTokens.Typography.cardTitle)
            Text(session.current == nil ? "로그인하면 내 여행과 받은 초대를 확인할 수 있어요." : "기존 로그인에는 여행 권한이 없어요. 다시 로그인해 새 기능의 계정 연결을 승인해 주세요.")
                .font(WegoTokens.Typography.body).foregroundStyle(WegoTokens.Palette.secondary)
            Button {
                if session.phase == .signedIn { confirmsRelogin = true }
                else { showingLogin = true }
            } label: {
                Text(session.phase == .signedIn ? "다시 로그인" : "로그인")
                    .font(WegoTokens.Typography.action).frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.primaryButtonHeight)
            }
            .buttonStyle(WegoPrimaryButtonStyle()).accessibilityIdentifier("tripsLogin")
            .disabled([.checkingSession, .signingIn, .signingOut].contains(session.phase))
        }
        .padding(WegoTokens.Space.screen)
        .background(WegoTokens.Palette.surface, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.hero))
    }

    private func invitationList(_ invitations: [IPhoneTripInvitation]) -> some View {
        VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
            Text("받은 초대").font(WegoTokens.Typography.section).accessibilityAddTraits(.isHeader)
            if invitations.isEmpty { WegoEmptyRequestRow(systemImage: "envelope", message: "받은 초대가 없어요.") }
            ForEach(invitations) { invitation in
                NavigationLink {
                    invitationReview(invitation)
                } label: {
                    HStack(spacing: WegoTokens.Space.medium) {
                        Image(systemName: "envelope").font(WegoTokens.Typography.section)
                            .foregroundStyle(WegoTokens.Palette.onAccent)
                            .frame(width: WegoTokens.Metrics.touchTarget, height: WegoTokens.Metrics.touchTarget)
                            .background(WegoTokens.Palette.accent, in: Circle()).accessibilityHidden(true)
                        VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                            Text(invitation.title).font(WegoTokens.Typography.section)
                            Text("\(invitation.ownerName)님의 초대").font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                        }
                        Spacer()
                        Image(systemName: "chevron.right").foregroundStyle(WegoTokens.Palette.accent)
                    }
                    .padding(WegoTokens.Space.medium)
                    .background(WegoTokens.Palette.accentSoft, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.card))
                    .contentShape(Rectangle())
                }
                .accessibilityIdentifier("accountTripInvite-" + invitation.id)
            }
        }
    }

    private func invitationReview(_ invitation: IPhoneTripInvitation) -> some View {
        TripInvitationPreview(invitation: TripPreviewInvitation(id: invitation.id, title: invitation.title, ownerName: invitation.ownerName)) { accept, location in
            guard let boundStore else { throw IPhoneSessionError.invalidSession }
            try await boundStore.respond(invitation, accept: accept, locationConsent: location)
        }
    }

    private func tripLink(_ trip: IPhoneTripSummary) -> some View {
        NavigationLink { TripPreparationView(tripID: trip.id, session: session, onMutation: refresh) } label: {
            if trip.state == .completed || trip.state == .cancelled {
                VStack(spacing: WegoTokens.Space.medium) {
                    HStack(alignment: .top, spacing: WegoTokens.Space.small) {
                        VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                            Text(trip.title).font(WegoTokens.Typography.section)
                            Text("\(tripDateLabel(start: trip.startDate, end: trip.endDate)) · 일행 \(trip.memberCount)명 · 차량 \(trip.carCount)대")
                                .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                        }
                        Spacer(minLength: WegoTokens.Space.small)
                        Text(trip.state.label).font(WegoTokens.Typography.caption)
                            .foregroundStyle(WegoTokens.Palette.secondary)
                    }
                    .frame(minHeight: WegoTokens.Metrics.touchTarget)
                    Divider().overlay(WegoTokens.Palette.divider)
                }
                .foregroundStyle(WegoTokens.Palette.text)
                .padding(.vertical, WegoTokens.Space.small)
                .contentShape(Rectangle())
            } else {
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                        Text(trip.title).font(trip.state == .active ? WegoTokens.Typography.cardTitle : WegoTokens.Typography.section)
                        Text("\(tripDateLabel(start: trip.startDate, end: trip.endDate)) · 만든 사람 \(trip.ownerName)").font(WegoTokens.Typography.caption)
                        Text("일행 \(trip.memberCount)명 · 차량 \(trip.carCount)대").font(WegoTokens.Typography.caption)
                        if trip.state == .active, let route = trip.routePreview, !route.isEmpty {
                            RouteStrip(stops: route.map(\.name), onInk: true)
                        }
                    }
                    Spacer(minLength: WegoTokens.Space.small)
                    Text(trip.state.label).font(WegoTokens.Typography.caption.weight(.semibold))
                        .padding(WegoTokens.Space.small)
                        .foregroundStyle(trip.state == .active ? WegoTokens.Palette.ink : WegoTokens.Palette.secondary)
                        .background(WegoTokens.Palette.background, in: Capsule())
                }
                .foregroundStyle(trip.state == .active ? WegoTokens.Palette.onInk : WegoTokens.Palette.text)
                .padding(WegoTokens.Space.medium)
                .background(trip.state == .active ? WegoTokens.Palette.ink : WegoTokens.Palette.surface,
                            in: RoundedRectangle(cornerRadius: WegoTokens.Radius.card))
                .contentShape(Rectangle())
            }
        }
        .accessibilityIdentifier("accountTrip-" + trip.id)
    }

    private func refreshIfInvalidated() {
        guard visible, isSelected, canRead, let boundStore,
              boundStore.noteInvalidation(invitation: push.foregroundTripInvitation, foregroundReturn: returnFromBackground) else { return }
        Task { await boundStore.refreshAfterInvalidation() }
    }

    private func refresh() async {
        guard canRead else { return }
        await boundStore?.load()
    }
}

private struct TripListRequest: Hashable {
    let account: TripsSessionIdentity?
    let retry: Int
    let isSelected: Bool
}

private struct TripsSessionIdentity: Hashable {
    let accountID: String
    let expiresAt: Date
    let scopes: Set<String>

    init(account: AccountSession) {
        accountID = account.accountID; expiresAt = account.expiresAt; scopes = account.scopes
    }
}
