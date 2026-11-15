import SwiftUI

struct WegoStatusColumn<Content: View>: View {
    let spacing: CGFloat
    @ViewBuilder let content: () -> Content

    var body: some View {
        VStack(alignment: .center, spacing: spacing, content: content)
            .multilineTextAlignment(.center)
            .frame(maxWidth: .infinity, alignment: .center)
    }
}

struct WegoEmptyListCard: View {
    let systemImage: String
    let title: String
    let message: String
    let actionTitle: String
    var actionSystemImage = "plus"
    var actionIconAtEnd = false
    var actionIdentifier: String?
    var contentIdentifier: String?
    var showsAction = true
    let action: () -> Void

    var body: some View {
        WegoCard(.surface, padding: WegoTokens.Space.large, radius: WegoTokens.Radius.hero) {
            WegoStatusColumn(spacing: WegoTokens.Space.medium) {
                WegoEmptyListArtwork(systemImage: systemImage)
                VStack(spacing: WegoTokens.Space.small) {
                    Text(title).font(WegoTokens.Typography.section.weight(.bold))
                        .accessibilityAddTraits(.isHeader)
                        .accessibilityIdentifier(contentIdentifier ?? "emptyListTitle")
                    Text(message).font(WegoTokens.Typography.label)
                        .foregroundStyle(WegoTokens.Palette.secondary)
                }
                .fixedSize(horizontal: false, vertical: true)
                if showsAction {
                Button(action: action) {
                    HStack(spacing: WegoTokens.Space.small) {
                        if !actionIconAtEnd { Image(systemName: actionSystemImage).accessibilityHidden(true) }
                        Text(actionTitle)
                        if actionIconAtEnd { Image(systemName: actionSystemImage).accessibilityHidden(true) }
                    }
                }
                .buttonStyle(.wego(.primary))
                .accessibilityIdentifier(actionIdentifier ?? "emptyListAction")
                }
            }
        }
    }
}

private struct WegoEmptyListArtwork: View {
    let systemImage: String

    var body: some View {
        ZStack {
            Canvas { context, size in
                let dot = WegoTokens.Metrics.emptyRouteDotSize
                let inset = WegoTokens.Metrics.hairlineWidth / 2
                let bounds = CGRect(origin: .zero, size: size).insetBy(dx: inset, dy: inset)
                let y = bounds.midY
                var route = Path()
                route.move(to: CGPoint(x: bounds.minX + dot, y: y))
                route.addLine(to: CGPoint(x: bounds.maxX - dot, y: y))
                context.stroke(route, with: .color(WegoTokens.Palette.accent.opacity(WegoTokens.Opacity.pastRouteSegment)),
                               style: StrokeStyle(lineWidth: WegoTokens.Metrics.hairlineWidth,
                                                  dash: [WegoTokens.Metrics.timelineWidth, WegoTokens.Space.xSmall]))
                let start = Path(ellipseIn: CGRect(x: bounds.minX, y: y - dot / 2, width: dot, height: dot))
                let end = Path(CGRect(x: bounds.maxX - dot, y: y - dot / 2, width: dot, height: dot))
                context.fill(start, with: .color(WegoTokens.Palette.background))
                context.fill(end, with: .color(WegoTokens.Palette.background))
                context.stroke(start, with: .color(WegoTokens.Palette.accent), lineWidth: WegoTokens.Metrics.hairlineWidth)
                context.stroke(end, with: .color(WegoTokens.Palette.accent), lineWidth: WegoTokens.Metrics.hairlineWidth)
            }
            Image(systemName: systemImage)
                .font(WegoTokens.Typography.title)
                .foregroundStyle(WegoTokens.Palette.accent)
                .frame(width: WegoTokens.Metrics.emptyIconSize, height: WegoTokens.Metrics.emptyIconSize)
                .background(WegoTokens.Palette.background, in: Circle())
                .overlay {
                    Circle().strokeBorder(WegoTokens.Palette.accent.opacity(WegoTokens.Opacity.pastRouteSegment),
                                          style: StrokeStyle(lineWidth: WegoTokens.Metrics.hairlineWidth,
                                                             dash: [WegoTokens.Metrics.timelineWidth, WegoTokens.Space.xSmall]))
                }
        }
        .frame(height: WegoTokens.Metrics.emptyArtworkHeight)
        .accessibilityHidden(true)
    }
}

struct WegoEmptyRequestRow: View {
    let systemImage: String
    let message: String

    var body: some View {
        HStack(spacing: WegoTokens.Space.compact) {
            Image(systemName: systemImage).font(WegoTokens.Typography.label)
                .frame(width: WegoTokens.Metrics.emptyRequestIconSize, height: WegoTokens.Metrics.emptyRequestIconSize)
                .background(WegoTokens.Palette.surface, in: Circle())
                .accessibilityHidden(true)
            Text(message).font(WegoTokens.Typography.label)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(WegoTokens.Space.medium)
        .foregroundStyle(WegoTokens.Palette.secondary)
        .overlay {
            RoundedRectangle(cornerRadius: WegoTokens.Radius.card)
                .strokeBorder(WegoTokens.Palette.divider,
                              style: StrokeStyle(lineWidth: WegoTokens.Metrics.hairlineWidth,
                                                 dash: [WegoTokens.Space.xSmall, WegoTokens.Metrics.timelineWidth]))
        }
    }
}
