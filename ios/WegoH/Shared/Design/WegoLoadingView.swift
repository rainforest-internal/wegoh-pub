import SwiftUI

enum WegoLoadingLayout { case inline, row, list, detail, launch }

struct WegoRouteLoader: View {
    var onInk = false
    var failed = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        TimelineView(.animation(minimumInterval: WegoTokens.Motion.loadingFrameInterval,
                                paused: reduceMotion || failed)) { timeline in
            Canvas { context, size in
                let dot = WegoTokens.Metrics.loadingDotSize
                let end = WegoTokens.Metrics.loadingDestinationSize
                let left = end / 2
                let right = size.width - end / 2
                let middle = size.width / 2
                let y = size.height / 2
                let accent = onInk ? WegoTokens.Palette.routeHighlight : WegoTokens.Palette.accent
                let background = onInk ? WegoTokens.Palette.ink : WegoTokens.Palette.background
                let progress = reduceMotion || failed ? 0.5 : timeline.date.timeIntervalSinceReferenceDate
                    .truncatingRemainder(dividingBy: WegoTokens.Motion.routeLoaderDuration) / WegoTokens.Motion.routeLoaderDuration
                var line = Path()
                line.move(to: CGPoint(x: left, y: y))
                line.addLine(to: CGPoint(x: right, y: y))
                context.stroke(line, with: .color(accent), style: StrokeStyle(lineWidth: WegoTokens.Metrics.timelineWidth,
                               lineCap: .round, dash: [WegoTokens.Space.xSmall, WegoTokens.Space.xSmall]))
                context.fill(Path(ellipseIn: CGRect(x: left - dot / 2, y: y - dot / 2, width: dot, height: dot)),
                             with: .color(onInk ? WegoTokens.Palette.onInk : WegoTokens.Palette.text))
                let station = CGRect(x: middle - dot / 2, y: y - dot / 2, width: dot, height: dot)
                context.fill(Path(ellipseIn: station), with: .color(progress >= 0.5 && !failed ? accent : background))
                context.stroke(Path(ellipseIn: station), with: .color(accent), lineWidth: WegoTokens.Metrics.timelineWidth)
                let destination = RoundedRectangle(cornerRadius: WegoTokens.Metrics.courseSummaryDestinationRadius)
                    .path(in: CGRect(x: right - end / 2, y: y - end / 2, width: end, height: end))
                context.fill(destination, with: .color(background))
                context.stroke(destination, with: .color(accent), lineWidth: WegoTokens.Metrics.timelineWidth)
                if failed {
                    let gap = WegoTokens.Metrics.loadingDestinationSize
                    context.fill(Path(ellipseIn: CGRect(x: middle - gap, y: y - gap, width: gap * 2, height: gap * 2)), with: .color(background))
                    var cross = Path()
                    cross.move(to: CGPoint(x: middle - dot / 2, y: y - dot / 2))
                    cross.addLine(to: CGPoint(x: middle + dot / 2, y: y + dot / 2))
                    cross.move(to: CGPoint(x: middle + dot / 2, y: y - dot / 2))
                    cross.addLine(to: CGPoint(x: middle - dot / 2, y: y + dot / 2))
                    context.stroke(cross, with: .color(WegoTokens.Palette.danger), style: StrokeStyle(lineWidth: WegoTokens.Metrics.timelineWidth, lineCap: .round))
                } else {
                    let x = left + (right - left) * progress
                    context.fill(Path(ellipseIn: CGRect(x: x - end / 2, y: y - end / 2, width: end, height: end)), with: .color(background))
                    context.fill(Path(ellipseIn: CGRect(x: x - dot / 2, y: y - dot / 2, width: dot, height: dot)), with: .color(accent))
                }
            }
        }
        .frame(width: WegoTokens.Metrics.loadingRouteWidth, height: WegoTokens.Metrics.loadingRouteHeight)
        .accessibilityHidden(true)
    }
}

struct WegoLoadingSpinner: View {
    var onInk = false
    var onAccent = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        TimelineView(.animation(minimumInterval: WegoTokens.Motion.loadingFrameInterval, paused: reduceMotion)) { timeline in
            Circle().trim(from: 0, to: 0.75)
                .stroke(onAccent ? WegoTokens.Palette.onAccent : onInk ? WegoTokens.Palette.onInk : WegoTokens.Palette.accent,
                        style: StrokeStyle(lineWidth: WegoTokens.Metrics.timelineWidth, lineCap: .round))
                .rotationEffect(.degrees(reduceMotion ? 0 : timeline.date.timeIntervalSinceReferenceDate
                    .truncatingRemainder(dividingBy: WegoTokens.Motion.skeletonDuration) / WegoTokens.Motion.skeletonDuration * 360))
        }
        .frame(width: WegoTokens.Metrics.loadingSpinnerSize, height: WegoTokens.Metrics.loadingSpinnerSize)
        .accessibilityHidden(true)
    }
}

struct WegoButtonLoadingLabel: View {
    let title: String
    var onAccent = false

    init(_ title: String, onAccent: Bool = false) { self.title = title; self.onAccent = onAccent }

    var body: some View {
        HStack(spacing: WegoTokens.Space.small) {
            WegoLoadingSpinner(onAccent: onAccent)
            Text(title).font(WegoTokens.Typography.action)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(title)
    }
}

struct WegoLoadingView: View {
    let title: String
    var layout: WegoLoadingLayout
    var onRetry: (() -> Void)?
    @State private var visible = false
    @State private var slow = false
    @State private var retryGeneration = 0

    init(_ title: String, layout: WegoLoadingLayout = .inline, onRetry: (() -> Void)? = nil) {
        self.title = title; self.layout = layout; self.onRetry = onRetry
        _visible = State(initialValue: layout == .launch || layout == .list || layout == .detail)
    }

    var body: some View {
        Group {
            if visible {
                Group {
                    if layout == .launch {
                        GeometryReader { bounds in
                            ScrollView {
                                VStack(spacing: WegoTokens.Space.medium) {
                                    if slow { slowNotice }
                                    launch
                                }
                                .frame(minHeight: bounds.size.height)
                            }
                            .scrollBounceBehavior(.basedOnSize)
                        }
                    } else {
                        VStack(spacing: WegoTokens.Space.medium) {
                            if slow { slowNotice }
                            switch layout {
                            case .list: skeletonList
                            case .detail: skeletonDetail
                            case .row: row
                            case .inline: status
                            case .launch: EmptyView()
                            }
                        }
                    }
                }
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier("wegoLoading")
            } else {
                Color.clear.accessibilityHidden(true)
                    .frame(height: layout == .row ? 0 : WegoTokens.Metrics.loadingMinimumHeight)
            }
        }
        .frame(maxWidth: .infinity)
        .task(id: retryGeneration) {
            do {
                let revealDelay = visible ? 0 : WegoTokens.Motion.loadingRevealDelay
                if revealDelay > 0 {
                    try await Task.sleep(for: .seconds(revealDelay))
                    visible = true
                }
                try await Task.sleep(for: .seconds(WegoTokens.Motion.loadingSlowDelay - revealDelay))
                slow = true
            } catch { }
        }
    }

    private var status: some View {
        WegoStatusColumn(spacing: WegoTokens.Space.medium) {
            WegoRouteLoader()
            Text(title).font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.secondary)
                .fixedSize(horizontal: false, vertical: true).multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.loadingMinimumHeight)
        .accessibilityElement(children: .ignore).accessibilityLabel(title)
    }

    private var row: some View {
        HStack(spacing: WegoTokens.Space.small) {
            WegoLoadingSpinner()
            Text(title).font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .multilineTextAlignment(.center)
        .frame(maxWidth: .infinity, alignment: .center)
        .padding(.vertical, WegoTokens.Space.small)
        .accessibilityElement(children: .ignore).accessibilityLabel(title)
    }

    private var launch: some View {
        VStack(spacing: WegoTokens.Space.large) {
            Spacer(minLength: WegoTokens.Space.large)
            VStack(spacing: WegoTokens.Space.medium) {
                Image("BrandMark").resizable().scaledToFit()
                    .frame(width: WegoTokens.Metrics.loadingLaunchMarkSize, height: WegoTokens.Metrics.loadingLaunchMarkSize)
                    .accessibilityHidden(true)
                Text("WegoH").font(WegoTokens.Typography.title).foregroundStyle(WegoTokens.Palette.text)
                Text("함께 가는 드라이브").font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.secondary)
                    .multilineTextAlignment(.center).fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: WegoTokens.Space.large)
            VStack(spacing: WegoTokens.Space.small) {
                WegoRouteLoader()
                Text(title).font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.secondary)
                    .multilineTextAlignment(.center).fixedSize(horizontal: false, vertical: true)
            }
            .padding(.bottom, WegoTokens.Space.xLarge)
        }
        .padding(WegoTokens.Space.screen)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .accessibilityElement(children: .combine)
    }

    private var skeletonList: some View {
        VStack(alignment: .leading, spacing: WegoTokens.Space.large) {
            row
            skeletonCard(onInk: true)
            WegoSkeleton(width: WegoTokens.Metrics.loadingRouteWidth, height: WegoTokens.Metrics.loadingSkeletonTitleHeight)
            ForEach(0..<3) { _ in skeletonCard(onInk: false) }
        }
        .accessibilityElement(children: .ignore).accessibilityLabel(title)
    }

    private var skeletonDetail: some View {
        VStack(alignment: .leading, spacing: WegoTokens.Space.large) {
            VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
                WegoSkeleton(width: WegoTokens.Metrics.loadingRouteWidth, height: WegoTokens.Metrics.loadingSkeletonTitleHeight, onInk: true)
                WegoRouteLoader(onInk: true).frame(maxWidth: .infinity)
                WegoSkeleton(height: WegoTokens.Metrics.loadingSkeletonLineHeight, onInk: true)
            }
            .padding(WegoTokens.Space.screen)
            .frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.loadingSkeletonCardHeight, alignment: .leading)
            .background(WegoTokens.Palette.ink, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.hero))
            row
            ForEach(0..<2) { _ in skeletonCard(onInk: false) }
        }
        .accessibilityElement(children: .ignore).accessibilityLabel(title)
    }

    private func skeletonCard(onInk: Bool) -> some View {
        VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
            WegoSkeleton(width: WegoTokens.Metrics.loadingRouteWidth, height: WegoTokens.Metrics.loadingSkeletonTitleHeight, onInk: onInk)
            WegoSkeleton(height: WegoTokens.Metrics.loadingSkeletonLineHeight, onInk: onInk)
            WegoSkeleton(width: WegoTokens.Metrics.loadingRouteWidth, height: WegoTokens.Metrics.loadingSkeletonLineHeight, onInk: onInk)
        }
        .padding(WegoTokens.Space.screen)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(onInk ? WegoTokens.Palette.ink : WegoTokens.Palette.surface,
                    in: RoundedRectangle(cornerRadius: WegoTokens.Radius.card))
    }

    private var slowNotice: some View {
        WegoStatusColumn(spacing: WegoTokens.Space.small) {
            Text("시간이 조금 걸리고 있어요").font(WegoTokens.Typography.section)
                .foregroundStyle(WegoTokens.Palette.text).multilineTextAlignment(.center)
                .accessibilityIdentifier("wegoLoadingSlow")
            ViewThatFits(in: .horizontal) {
                HStack(spacing: WegoTokens.Space.small) { slowActions }.fixedSize(horizontal: true, vertical: false)
                VStack(spacing: WegoTokens.Space.small) { slowActions }
            }
        }
        .padding(WegoTokens.Space.medium)
    }

    @ViewBuilder private var slowActions: some View {
        if let onRetry {
            Button("다시 시도") { slow = false; retryGeneration += 1; onRetry() }
                .buttonStyle(.wego(.soft)).accessibilityIdentifier("wegoLoadingRetry")
        }
        Button("계속 기다리기") { slow = false }
            .buttonStyle(.wego(.plain)).accessibilityIdentifier("wegoLoadingWait")
    }
}

private struct WegoSkeleton: View {
    var width: CGFloat?
    let height: CGFloat
    var onInk = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        RoundedRectangle(cornerRadius: WegoTokens.Radius.routeSegment)
            .fill(onInk ? WegoTokens.Palette.skeletonOnInk : WegoTokens.Palette.skeleton)
            .overlay {
                if !reduceMotion {
                    RoundedRectangle(cornerRadius: WegoTokens.Radius.routeSegment)
                        .fill(onInk ? WegoTokens.Palette.skeletonOnInkHighlight : WegoTokens.Palette.surface)
                        .phaseAnimator([false, true]) { view, phase in view.opacity(phase ? 1 : 0) }
                        animation: { _ in .easeInOut(duration: WegoTokens.Motion.skeletonDuration) }
                }
            }
            .frame(width: width, height: height)
            .accessibilityHidden(true)
    }
}

struct WegoLoadingFailureView: View {
    let message: String
    var messageIdentifier: String? = nil
    let retry: () -> Void

    var body: some View {
        WegoStatusColumn(spacing: WegoTokens.Space.medium) {
            WegoRouteLoader(failed: true)
            Text("불러오지 못했어요").font(WegoTokens.Typography.cardTitle).accessibilityAddTraits(.isHeader)
            Text(message).font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.secondary)
                .multilineTextAlignment(.center).fixedSize(horizontal: false, vertical: true)
                .accessibilityIdentifier(messageIdentifier ?? "wegoLoadingFailureMessage")
            Button("다시 시도", action: retry).buttonStyle(.wego(.soft)).accessibilityIdentifier("wegoLoadingFailureRetry")
        }
        .padding(WegoTokens.Space.screen)
        .frame(maxWidth: .infinity, minHeight: WegoTokens.Metrics.loadingMinimumHeight)
        .foregroundStyle(WegoTokens.Palette.text)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("wegoLoadingFailure")
    }
}
