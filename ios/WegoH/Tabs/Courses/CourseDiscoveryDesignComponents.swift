import SwiftUI

struct CourseCreatorRankPill: View {
    let rank: Int?

    var body: some View {
        if let rank, (1...3).contains(rank) {
            StatusPill("드라이브 셀럽", tone: .soft)
                .accessibilityLabel("드라이브 셀럽 · 공개 경로 별표 기준 \(rank)위")
        }
    }
}

struct CourseDiscoveryCardMap: View {
    let item: CourseDiscoveryItem
    let store: CourseDiscoveryStore
    var height = WegoTokens.Metrics.courseDetailMapHeight

    var body: some View {
        CourseCardMap(height: height, stops: item.stops) { points in
            try await store.previewRoute(for: item, points: points)
        }
        .id(CourseCardRevision(item))
    }
}

struct CourseLiveCompactCard: View {
    let item: CourseDiscoveryItem
    let store: CourseDiscoveryStore
    var eventID: String? = nil
    var isUnread = false
    var publishedAt: String? = nil
    var showsFollow = false

    var body: some View {
        WegoCard(.outlined) {
          VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
            HStack(alignment: .top, spacing: WegoTokens.Space.compact) {
                NavigationLink(value: CourseLiveRoute.course(item, eventID: eventID)) {
                    HStack(alignment: .top, spacing: WegoTokens.Space.compact) {
                        CourseDiscoveryCardMap(item: item, store: store, height: WegoTokens.Metrics.profileAvatarSize)
                            .frame(width: WegoTokens.Metrics.profileAvatarSize)
                        VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                            HStack(spacing: WegoTokens.Space.small) {
                                Text(item.author).font(WegoTokens.Typography.caption)
                                if let date = publishedAt.flatMap(coursePublicationDate) {
                                    Text(date, style: .relative).font(WegoTokens.Typography.caption)
                                }
                                if isUnread { StatusPill("새 소식", tone: .soft) }
                            }.foregroundStyle(WegoTokens.Palette.secondary)
                            Text(item.title).font(WegoTokens.Typography.section)
                            CourseCardStopNames(names: item.stopNames)
                            Text(item.tags.map { "#" + $0 }.joined(separator: " "))
                                .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.accent)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier(eventID.map { "courseNews-" + $0 } ?? "courseDiscovery-" + item.id)
                CourseLiveStarButton(item: item, store: store)
            }
            if showsFollow { CourseLiveFollowButton(item: item, store: store) }
          }
        }
    }
}

struct CourseLiveFollowButton: View {
    let item: CourseDiscoveryItem
    let store: CourseDiscoveryStore
    @State private var error: String?

    var body: some View {
        if item.canFollow {
            VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                Button {
                    error = nil
                    Task {
                        do {
                            if let id = item.followId { try await store.unfollowCreator(followID: id) }
                            else { try await store.followCreator(item) }
                        } catch is CancellationError { } catch { self.error = courseErrorMessage(error) }
                    }
                } label: {
                    if item.followId != nil {
                        StatusPill("구독 중", tone: .neutral)
                            .frame(minHeight: WegoTokens.Metrics.touchTarget)
                    } else {
                        Text("구독").font(WegoTokens.Typography.caption.weight(.semibold))
                            .padding(.horizontal, WegoTokens.Space.compact)
                            .padding(.vertical, WegoTokens.Space.small)
                            .frame(minHeight: WegoTokens.Metrics.touchTarget)
                            .foregroundStyle(WegoTokens.Palette.accent)
                            .background(WegoTokens.Palette.accentSoft, in: Capsule())
                    }
                }
                .buttonStyle(.plain).disabled(store.busy)
                .opacity(store.busy ? WegoTokens.Opacity.controlDisabled : 1)
                .accessibilityLabel(item.followId == nil ? "\(item.author) 창작자 구독" : "\(item.author) 구독 중 · 구독 해제")
                .accessibilityValue(item.followId == nil ? "구독 안 함" : "구독 중")
                .accessibilityIdentifier("courseFollow-\(item.id)")
                if let error { Text(error).font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.danger) }
            }
        }
    }
}

struct CourseSubscribedCreatorTile: View {
    let creator: CourseLibraryCreator
    let store: CourseDiscoveryStore
    let hasNews: Bool
    @State private var error: String?
    @ScaledMetric(relativeTo: .caption) private var tileWidth = WegoTokens.Metrics.friendProfileAvatarSize

    var body: some View {
        VStack(spacing: WegoTokens.Space.small) {
            if let id = creator.creatorId, let name = creator.name {
                NavigationLink(value: CourseLiveRoute.creatorID(id)) { identity(name) }
                    .buttonStyle(.plain).accessibilityIdentifier("courseFollowedCreator-\(id)")
            } else {
                identity("현재 공개할 수 없는 창작자")
            }
            if creator.creatorId == nil || creator.name == nil {
                Button("구독 해제") {
                    error = nil
                    Task { do { try await store.unfollowCreator(followID: creator.id) }
                           catch is CancellationError { } catch { self.error = courseErrorMessage(error) } }
                }.buttonStyle(.wego(.plain)).disabled(store.busy).accessibilityIdentifier("courseUnfollow-\(creator.id)")
            }
            if let error { Text(error).font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.danger) }
        }.frame(width: tileWidth)
    }

    private func identity(_ name: String) -> some View {
        VStack(spacing: WegoTokens.Space.small) {
            AvatarBadge(name: name, tone: .ink, size: WegoTokens.Metrics.profileAvatarSize)
                .overlay { Circle().strokeBorder(hasNews ? WegoTokens.Palette.accent : .clear,
                                                lineWidth: WegoTokens.Metrics.selectedBorderWidth) }
            Text(name).font(WegoTokens.Typography.label).multilineTextAlignment(.center)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(name)
        .accessibilityValue(hasNews ? "새 경로 있음" : "")
    }
}

struct CourseLiveSavedCard: View {
    let item: CourseDiscoveryItem
    let store: CourseDiscoveryStore

    var body: some View {
        NavigationLink(value: CourseLiveRoute.course(item)) {
            WegoCard(.outlined) {
                VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
                    CourseDiscoveryCardMap(item: item, store: store, height: WegoTokens.Metrics.emptyArtworkHeight)
                    CourseCardStopNames(names: item.stopNames)
                    Text(item.title).font(WegoTokens.Typography.section)
                    Text("\(item.author) · 장소 \(item.stopCount)곳")
                        .font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                }
            }
        }.buttonStyle(.plain).accessibilityIdentifier("courseSaved-\(item.id)")
    }
}

private func coursePublicationDate(_ raw: String) -> Date? {
    let formatter = ISO8601DateFormatter()
    if let date = formatter.date(from: raw) { return date }
    formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    return formatter.date(from: raw)
}
