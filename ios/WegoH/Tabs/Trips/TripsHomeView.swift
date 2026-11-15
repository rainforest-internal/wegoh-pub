import SwiftUI

struct TripsPreviewHomeView: View {
    var isRootPreview = false
    @State private var store: TripsPreviewStore = {
        #if DEBUG
        if ProcessInfo.processInfo.arguments.contains("-trips-ui-empty") {
            return TripsPreviewStore(invitations: [], myTrips: [], pastTrips: [])
        }
        #endif
        return TripsPreviewStore()
    }()
    @State private var showsInitialPreview = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: WegoTokens.Space.large) {
                HStack {
                    Text("여행")
                        .font(WegoTokens.Typography.hero)
                        .accessibilityAddTraits(.isHeader)
                    Spacer()
                    Text("샘플 여행")
                        .font(WegoTokens.Typography.caption.weight(.semibold))
                        .foregroundStyle(WegoTokens.Palette.accent)
                        .padding(.horizontal, WegoTokens.Space.compact)
                        .padding(.vertical, WegoTokens.Space.small)
                        .background(WegoTokens.Palette.accentSoft, in: Capsule())
                }
                .frame(minHeight: WegoTokens.Metrics.settingsHeaderHeight)
                if !store.invitations.isEmpty {
                    VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                        sectionTitle("받은 초대", count: store.invitations.count)
                        ForEach(store.invitations) { invitation in
                            NavigationLink(value: invitation) {
                                HStack(spacing: WegoTokens.Space.medium) {
                                    Image(systemName: "envelope")
                                        .font(WegoTokens.Typography.section)
                                        .foregroundStyle(WegoTokens.Palette.onAccent)
                                        .frame(width: WegoTokens.Metrics.touchTarget, height: WegoTokens.Metrics.touchTarget)
                                        .background(WegoTokens.Palette.accent, in: Circle())
                                        .accessibilityHidden(true)
                                    VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                                        Text(invitation.title).font(WegoTokens.Typography.section)
                                        Text("\(invitation.ownerName)님의 초대")
                                            .font(WegoTokens.Typography.label)
                                            .foregroundStyle(WegoTokens.Palette.secondary)
                                    }
                                    Spacer()
                                    chevron.foregroundStyle(WegoTokens.Palette.accent)
                                }
                                .padding(WegoTokens.Space.medium)
                                .background(WegoTokens.Palette.accentSoft, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.card))
                            }
                            .accessibilityIdentifier("tripInvite-\(invitation.id)")
                        }
                    }
                } else {
                    VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                        Text("받은 초대").font(WegoTokens.Typography.section).accessibilityAddTraits(.isHeader)
                        WegoEmptyRequestRow(systemImage: "envelope", message: "받은 초대가 없어요.")
                    }
                }
                if store.myTrips.isEmpty && store.accepted.isEmpty {
                    VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                        Text("내 여행").font(WegoTokens.Typography.section).accessibilityAddTraits(.isHeader)
                        WegoEmptyListCard(systemImage: "map", title: "아직 참여 중인 여행이 없어요",
                                          message: "함께 떠날 여행을 준비해 보세요.", actionTitle: "처음 상태 보기",
                                          actionSystemImage: "arrow.right", actionIconAtEnd: true,
                                          actionIdentifier: "tripsPreviewInitial", contentIdentifier: "tripsEmpty") {
                            showsInitialPreview = true
                        }

                        Text("샘플 목록이에요. 내 계정의 여행은 여행 탭에서 확인해 주세요.")
                            .font(WegoTokens.Typography.caption)
                            .foregroundStyle(WegoTokens.Palette.secondary)
                            .frame(maxWidth: .infinity)
                            .multilineTextAlignment(.center)
                    }
                } else {
                    tripSection("내 여행", trips: store.myTrips, accepted: store.accepted)
                }
                if !store.pastTrips.isEmpty {
                    tripSection("지난 여행", trips: store.pastTrips, past: true)
                }
            }
            .padding(.horizontal, WegoTokens.Space.screen)
            .padding(.bottom, WegoTokens.Space.medium)
        }
        .buttonStyle(.plain)
        .foregroundStyle(WegoTokens.Palette.text)
        .background(WegoTokens.Palette.background)
        .navigationTitle("디자인 미리보기")
        .toolbar(isRootPreview ? .hidden : .visible, for: .navigationBar)
        .navigationDestination(for: TripPreviewInvitation.self) { invitation in
            TripInvitationPreview(invitation: invitation, store: store)
        }
        .navigationDestination(isPresented: $showsInitialPreview) {
            if let trip = TripPreviewData.myTrips.first(where: { $0.id == "new-trip" }) {
                TripPreparationView(preview: trip)
            }
        }
    }

    private func sectionTitle(_ title: String, count: Int) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: WegoTokens.Space.small) {
            Text(title).font(WegoTokens.Typography.label.weight(.semibold))
            Text("\(count)")
                .font(WegoTokens.Typography.caption)
                .foregroundStyle(WegoTokens.Palette.secondary)
        }
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isHeader)
    }

    private func tripSection(_ title: String, trips: [TripPreview], accepted: [AcceptedTripPreview] = [], past: Bool = false) -> some View {
        VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
            sectionTitle(title, count: trips.count + accepted.count)
            ForEach(accepted) { value in
                NavigationLink(value: value.invitation) {
                    HStack(spacing: WegoTokens.Space.small) {
                        VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                            Text(value.invitation.title).font(WegoTokens.Typography.section)
                            Text("만든 사람 \(value.invitation.ownerName)")
                                .font(WegoTokens.Typography.label)
                                .foregroundStyle(WegoTokens.Palette.secondary)
                        }
                        Spacer(minLength: WegoTokens.Space.small)
                        VStack(alignment: .trailing, spacing: WegoTokens.Space.small) {
                            Text("초대 수락 완료")
                                .font(WegoTokens.Typography.caption.weight(.semibold))
                                .foregroundStyle(WegoTokens.Palette.accent)
                                .padding(.horizontal, WegoTokens.Space.small)
                                .padding(.vertical, WegoTokens.Space.xSmall)
                                .background(WegoTokens.Palette.background, in: Capsule())
                            chevron.foregroundStyle(WegoTokens.Palette.secondary)
                        }
                    }
                    .padding(WegoTokens.Space.medium)
                    .background(WegoTokens.Palette.surface, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.card))
                }
                .accessibilityIdentifier("tripAccepted-\(value.id)")
            }
            ForEach(trips) { trip in
                NavigationLink {
                    TripPreviewDetail(trip: trip)
                } label: {
                    if past {
                        pastTripRow(trip)
                    } else if trip.state == .active {
                        activeTripCard(trip)
                    } else {
                        plannedTripCard(trip)
                    }
                }
                .accessibilityIdentifier("trip-\(trip.id)")
            }
        }
    }

    private func activeTripCard(_ trip: TripPreview) -> some View {
        VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
            HStack(alignment: .top, spacing: WegoTokens.Space.small) {
                VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                    Text(trip.title)
                        .font(WegoTokens.Typography.cardTitle)
                        .foregroundStyle(WegoTokens.Palette.onInk)
                    Text("\(trip.dateLabel) · 만든 사람 \(trip.ownerName)")
                        .font(WegoTokens.Typography.label)
                        .foregroundStyle(WegoTokens.Palette.onInkSecondary)
                }
                Spacer(minLength: WegoTokens.Space.xSmall)
                HStack(spacing: WegoTokens.Space.xSmall) {
                    Circle().fill(WegoTokens.Palette.accent)
                        .frame(width: WegoTokens.Metrics.settingsStatusDotSize, height: WegoTokens.Metrics.settingsStatusDotSize)
                        .accessibilityHidden(true)
                    Text(trip.state.label).font(WegoTokens.Typography.caption.weight(.semibold))
                }
                .foregroundStyle(WegoTokens.Palette.ink)
                .padding(.horizontal, WegoTokens.Space.small)
                .padding(.vertical, WegoTokens.Space.xSmall)
                .background(WegoTokens.Palette.onInk, in: Capsule())
            }
            if !trip.stops.isEmpty {
                TripHomeRouteStrip(stops: trip.stops)
            }
            Divider().overlay(WegoTokens.Palette.inkDivider)
            Text("일행 \(trip.memberCount)명 · 차량 \(trip.carCount)대")
                .font(WegoTokens.Typography.caption)
                .foregroundStyle(WegoTokens.Palette.onInkSecondary)
        }
        .padding(WegoTokens.Space.medium)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(WegoTokens.Palette.ink, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.hero))
        .contentShape(RoundedRectangle(cornerRadius: WegoTokens.Radius.hero))
    }

    private func plannedTripCard(_ trip: TripPreview) -> some View {
        HStack(spacing: WegoTokens.Space.small) {
            VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                Text(trip.title).font(WegoTokens.Typography.section)
                Text("\(trip.dateLabel) · 만든 사람 \(trip.ownerName)")
                    .font(WegoTokens.Typography.label)
                    .foregroundStyle(WegoTokens.Palette.secondary)
                Text("일행 \(trip.memberCount)명 · 차량 \(trip.carCount)대")
                    .font(WegoTokens.Typography.caption)
                    .foregroundStyle(WegoTokens.Palette.secondary)
            }
            Spacer(minLength: WegoTokens.Space.small)
            Text(trip.state.label)
                .font(WegoTokens.Typography.caption)
                .padding(.horizontal, WegoTokens.Space.small)
                .padding(.vertical, WegoTokens.Space.xSmall)
                .background(WegoTokens.Palette.background, in: Capsule())
                .overlay { Capsule().strokeBorder(WegoTokens.Palette.divider) }
        }
        .padding(WegoTokens.Space.medium)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(WegoTokens.Palette.surface, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.card))
        .contentShape(RoundedRectangle(cornerRadius: WegoTokens.Radius.card))
    }

    private func pastTripRow(_ trip: TripPreview) -> some View {
        VStack(spacing: WegoTokens.Space.medium) {
            HStack(spacing: WegoTokens.Space.small) {
                VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                    Text(trip.title).font(WegoTokens.Typography.section)
                    Text("\(trip.dateLabel) · 만든 사람 \(trip.ownerName) · 일행 \(trip.memberCount)명 · 차량 \(trip.carCount)대")
                        .font(WegoTokens.Typography.caption)
                        .foregroundStyle(WegoTokens.Palette.secondary)
                }
                Spacer(minLength: WegoTokens.Space.small)
                Text(trip.state.label)
                    .font(WegoTokens.Typography.caption)
                    .foregroundStyle(WegoTokens.Palette.secondary)
            }
            .frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.touchTarget, alignment: .leading)
            Divider().overlay(WegoTokens.Palette.divider)
        }
        .contentShape(Rectangle())
    }

    private var chevron: some View {
        Image(systemName: "chevron.right")
            .font(WegoTokens.Typography.caption.weight(.semibold))
            .accessibilityHidden(true)
    }
}

private struct TripHomeRouteStrip: View {
    let stops: [String]

    var body: some View {
        VStack(spacing: WegoTokens.Space.small) {
            Canvas { context, size in
                let diameter = WegoTokens.Metrics.tripRouteDotSize
                let inset = diameter / 2
                if stops.count > 1 {
                    var line = Path()
                    line.move(to: CGPoint(x: inset, y: inset))
                    line.addLine(to: CGPoint(x: size.width - inset, y: inset))
                    context.stroke(line, with: .color(WegoTokens.Palette.routeHighlight),
                                   style: StrokeStyle(lineWidth: WegoTokens.Metrics.hairlineWidth,
                                                      dash: [WegoTokens.Metrics.hairlineWidth, WegoTokens.Space.xSmall]))
                }
                for index in stops.indices {
                    let x = stops.count > 1 ? CGFloat(index) * (size.width - diameter) / CGFloat(stops.count - 1) : 0
                    let rect = CGRect(x: x, y: 0, width: diameter, height: diameter)
                    let shape = index == stops.count - 1 ? Path(rect) : Path(ellipseIn: rect)
                    context.fill(shape, with: .color(index == 0 && stops.count > 1 ? WegoTokens.Palette.routeHighlight : WegoTokens.Palette.ink))
                    context.stroke(shape, with: .color(WegoTokens.Palette.routeHighlight), lineWidth: WegoTokens.Metrics.hairlineWidth)
                }
            }
            .frame(height: WegoTokens.Metrics.tripRouteDotSize)
            HStack(alignment: .top, spacing: WegoTokens.Space.small) {
                ForEach(stops.indices, id: \.self) { index in
                    Text(stops[index])
                        .font(WegoTokens.Typography.caption)
                        .lineLimit(1).truncationMode(.tail)
                        .frame(maxWidth: .infinity, alignment: index == 0 ? .leading : index == stops.count - 1 ? .trailing : .center)
                        .multilineTextAlignment(index == 0 ? .leading : index == stops.count - 1 ? .trailing : .center)
                }
            }
            .foregroundStyle(WegoTokens.Palette.onInk)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("경로 순서: \(stops.joined(separator: ", "))")
    }
}
