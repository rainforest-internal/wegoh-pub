import SwiftUI

struct WegoFloatingAction: View {
    let title: String
    let identifier: String
    let action: () -> Void

    var body: some View {
        Button(action: action) { Label(title, systemImage: "plus") }
            .buttonStyle(.wego(.primary))
            .accessibilityIdentifier(identifier)
            .padding(.horizontal, WegoTokens.Space.screen)
            .padding(.vertical, WegoTokens.Space.small)
    }
}

struct WegoButtonStyle: ButtonStyle {
    enum Tone { case primary, soft, plain }

    let tone: Tone
    @Environment(\.isEnabled) private var isEnabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(WegoTokens.Typography.action)
            .foregroundStyle(foreground)
            .padding(.horizontal, WegoTokens.Space.medium)
            .padding(.vertical, WegoTokens.Space.compact)
            .frame(maxWidth: tone == .plain ? nil : .infinity,
                   minHeight: tone == .plain ? WegoTokens.Metrics.touchTarget : WegoTokens.Metrics.primaryButtonHeight)
            .background(background(pressed: configuration.isPressed),
                        in: RoundedRectangle(cornerRadius: WegoTokens.Radius.control))
            .opacity(configuration.isPressed ? WegoTokens.Opacity.controlPressed : 1)
            .contentShape(RoundedRectangle(cornerRadius: WegoTokens.Radius.control))
    }

    private var foreground: Color {
        guard isEnabled else { return WegoTokens.Palette.secondary }
        switch tone {
        case .primary: return WegoTokens.Palette.onAccent
        case .soft: return WegoTokens.Palette.accent
        case .plain: return WegoTokens.Palette.secondary
        }
    }

    private func background(pressed: Bool) -> Color {
        guard isEnabled else { return tone == .plain ? .clear : WegoTokens.Palette.divider }
        switch tone {
        case .primary: return pressed ? WegoTokens.Palette.ink : WegoTokens.Palette.accent
        case .soft: return pressed ? WegoTokens.Palette.divider : WegoTokens.Palette.accentSoft
        case .plain: return pressed ? WegoTokens.Palette.surface : .clear
        }
    }
}

extension ButtonStyle where Self == WegoButtonStyle {
    static func wego(_ tone: WegoButtonStyle.Tone = .primary) -> WegoButtonStyle {
        WegoButtonStyle(tone: tone)
    }
}

struct WegoCard<Content: View>: View {
    enum Tone { case ink, soft, surface, outlined }

    let tone: Tone
    let padding: CGFloat
    let radius: CGFloat?
    let content: Content

    init(_ tone: Tone = .surface, padding: CGFloat = WegoTokens.Space.medium, radius: CGFloat? = nil,
         @ViewBuilder content: () -> Content) {
        self.tone = tone
        self.padding = padding
        self.radius = radius
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: WegoTokens.Space.medium) { content }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(padding)
            .foregroundStyle(tone == .ink ? WegoTokens.Palette.onInk : WegoTokens.Palette.text)
            .background(background, in: shape)
            .overlay { shape.strokeBorder(tone == .outlined ? WegoTokens.Palette.divider : .clear,
                                          lineWidth: WegoTokens.Metrics.hairlineWidth) }
    }

    private var shape: RoundedRectangle {
        RoundedRectangle(cornerRadius: radius ?? (tone == .ink ? WegoTokens.Radius.hero : WegoTokens.Radius.card))
    }

    private var background: Color {
        switch tone {
        case .ink: WegoTokens.Palette.ink
        case .soft: WegoTokens.Palette.accentSoft
        case .surface: WegoTokens.Palette.surface
        case .outlined: WegoTokens.Palette.background
        }
    }
}

struct RouteStrip: View {
    /// 진행 바 위에 놓는 다른 차. position은 장소 칸 기준 소수 위치(0=첫 장소).
    struct Marker: Equatable, Identifiable {
        var id: String
        var label: String
        var position: Double
        var accessibilityText: String
    }

    let stops: [String]
    var progress: Int? = nil
    var onInk = false
    /// 내 차의 '지금 여기' 위치. 장소 칸 기준 소수 위치이며 nil이면 그리지 않는다.
    var position: Double? = nil
    var companions: [Marker] = []

    var body: some View {
        VStack(spacing: WegoTokens.Space.small) {
            Canvas { context, size in
                let diameter = WegoTokens.Metrics.courseSummaryDotSize
                let border = WegoTokens.Metrics.timelineWidth
                let top = (size.height - diameter - border) / 2
                let inset = (diameter + border) / 2
                let step = stops.count > 1 ? (size.width - diameter - border) / CGFloat(stops.count - 1) : 0
                for index in stops.indices.dropLast() {
                    var rail = Path()
                    rail.move(to: CGPoint(x: inset + CGFloat(index) * step, y: top + inset))
                    rail.addLine(to: CGPoint(x: inset + CGFloat(index + 1) * step, y: top + inset))
                    let completed = progress.map { index < $0 } ?? false
                    context.stroke(rail, with: .color(routeColor),
                                   style: StrokeStyle(lineWidth: WegoTokens.Metrics.timelineWidth,
                                                      lineCap: .round,
                                                      dash: completed ? [] : [WegoTokens.Metrics.timelineWidth, WegoTokens.Space.xSmall]))
                }
                for index in stops.indices {
                    let rect = CGRect(x: border / 2 + CGFloat(index) * step, y: top + border / 2, width: diameter, height: diameter)
                    let point = index == stops.count - 1 && stops.count > 1
                        ? RoundedRectangle(cornerRadius: WegoTokens.Metrics.courseSummaryDestinationRadius).path(in: rect)
                        : Path(ellipseIn: rect)
                    let completed = index == 0 || progress.map { index <= $0 } == true
                    context.fill(point, with: .color(completed ? routeColor : cardColor))
                    context.stroke(point, with: .color(routeColor), lineWidth: WegoTokens.Metrics.timelineWidth)
                }
                let marker = WegoTokens.Metrics.routeCurrentMarkerSize
                func markerRect(_ value: Double) -> CGRect {
                    CGRect(x: inset + CGFloat(value) * step - marker / 2, y: top + inset - marker / 2, width: marker, height: marker)
                }
                for companion in visibleCompanions {
                    let circle = Path(ellipseIn: markerRect(companion.position))
                    context.fill(circle, with: .color(cardColor))
                    context.stroke(circle, with: .color(textColor), lineWidth: WegoTokens.Metrics.timelineWidth)
                    context.draw(Text(companion.label).font(WegoTokens.Typography.caption.weight(.semibold)).foregroundStyle(textColor),
                                 at: CGPoint(x: markerRect(companion.position).midX, y: markerRect(companion.position).midY))
                }
                if let current = visiblePosition {
                    let circle = Path(ellipseIn: markerRect(current))
                    context.fill(circle, with: .color(routeColor))
                    context.stroke(circle, with: .color(cardColor), lineWidth: WegoTokens.Metrics.timelineWidth)
                }
            }
            .frame(height: (hasMarkers ? max(WegoTokens.Metrics.courseSummaryDotSize, WegoTokens.Metrics.routeCurrentMarkerSize)
                                        : WegoTokens.Metrics.courseSummaryDotSize) + WegoTokens.Metrics.timelineWidth)
            HStack(alignment: .top, spacing: WegoTokens.Space.small) {
                ForEach(stops.indices, id: \.self) { index in
                    Text(stops[index])
                        .font(WegoTokens.Typography.caption)
                        .fixedSize(horizontal: false, vertical: true)
                        .frame(maxWidth: .infinity, alignment: index == 0 ? .leading : index == stops.count - 1 ? .trailing : .center)
                        .multilineTextAlignment(index == 0 ? .leading : index == stops.count - 1 ? .trailing : .center)
                }
            }
            .foregroundStyle(textColor)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(accessibilitySummary)
    }

    private var routeColor: Color { onInk ? WegoTokens.Palette.routeHighlight : WegoTokens.Palette.accent }
    private var cardColor: Color { onInk ? WegoTokens.Palette.ink : WegoTokens.Palette.background }
    private var textColor: Color { onInk ? WegoTokens.Palette.onInk : WegoTokens.Palette.text }
    private var lastIndex: Double { Double(max(stops.count - 1, 0)) }
    private var visiblePosition: Double? { position.flatMap { stops.count > 1 && (0...lastIndex).contains($0) ? $0 : nil } }
    private var visibleCompanions: [Marker] { stops.count > 1 ? companions.filter { (0...lastIndex).contains($0.position) } : [] }
    private var hasMarkers: Bool { visiblePosition != nil || !visibleCompanions.isEmpty }

    private var accessibilitySummary: String {
        guard let first = stops.first else { return "아직 정한 경로가 없어요" }
        guard stops.count > 1, let last = stops.last else { return "장소 \(first)" }
        let middle = stops.dropFirst().dropLast()
        var summary = middle.isEmpty ? "출발지 \(first), 도착지 \(last)"
            : "출발지 \(first), 경유지 \(middle.joined(separator: ", ")), 도착지 \(last)"
        if let current = visiblePosition {
            let from = Int(current.rounded(.down)), to = min(from + 1, stops.count - 1)
            summary += from == to ? ", 지금 \(stops[from]) 근처" : ", 지금 \(stops[from])에서 \(stops[to]) 가는 중"
        }
        for companion in visibleCompanions { summary += ", " + companion.accessibilityText }
        return summary
    }
}

struct RouteStop: Identifiable, Equatable {
    enum State: String { case arrived = "도착", next = "다음", planned = "예정" }

    let id: String
    let title: String
    var subtitle: String? = nil
    var state: State = .planned
}

struct RouteList: View {
    let stops: [RouteStop]
    var onInk = false
    var numbered = false
    @ScaledMetric(relativeTo: .footnote) private var badgeSize = WegoTokens.Metrics.courseStopBadgeSize

    init(stops: [RouteStop], onInk: Bool = false, numbered: Bool = false) {
        self.stops = stops
        self.onInk = onInk
        self.numbered = numbered
    }

    var body: some View {
        VStack(spacing: 0) {
            ForEach(Array(stops.enumerated()), id: \.element.id) { index, stop in
                HStack(alignment: .top, spacing: WegoTokens.Space.compact) {
                    Color.clear.frame(width: columnWidth)
                    VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                        HStack(alignment: .firstTextBaseline, spacing: WegoTokens.Space.small) {
                            Text(stop.title)
                                .font(numbered || stop.state == .next ? WegoTokens.Typography.section : WegoTokens.Typography.body)
                                .frame(maxWidth: .infinity, alignment: .leading)
                            if !numbered {
                                Text(stop.state.rawValue).font(WegoTokens.Typography.caption)
                                    .foregroundStyle(secondaryColor)
                            }
                        }
                        if let subtitle = stop.subtitle, !subtitle.isEmpty {
                            Text(subtitle).font(WegoTokens.Typography.label).foregroundStyle(secondaryColor)
                        }
                    }
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.bottom, index == stops.count - 1 ? 0 : WegoTokens.Space.medium)
                }
                .frame(minHeight: numbered ? max(WegoTokens.Metrics.permissionIconSize, badgeSize + WegoTokens.Space.medium)
                       : WegoTokens.Metrics.permissionIconSize, alignment: .topLeading)
                .overlay(alignment: .leading) {
                    Canvas { context, size in
                        let diameter = numbered ? badgeSize
                            : stop.state == .next ? WegoTokens.Metrics.courseSummaryDotSize : WegoTokens.Metrics.tripRouteDotSize
                        let center = columnWidth / 2
                        let top = numbered ? 0 : WegoTokens.Space.small
                        if index < stops.count - 1 {
                            var rail = Path()
                            rail.move(to: CGPoint(x: center, y: top + diameter / 2))
                            rail.addLine(to: CGPoint(x: center, y: size.height + top + diameter / 2))
                            context.stroke(rail, with: .color(routeColor),
                                           style: StrokeStyle(lineWidth: WegoTokens.Metrics.hairlineWidth,
                                                              dash: !numbered && stop.state == .arrived ? [] : [WegoTokens.Metrics.timelineWidth, WegoTokens.Space.xSmall]))
                        }
                        let rect = CGRect(x: center - diameter / 2, y: top, width: diameter, height: diameter)
                        let point = index == stops.count - 1
                            ? RoundedRectangle(cornerRadius: WegoTokens.Metrics.courseSummaryDestinationRadius).path(in: rect)
                            : Path(ellipseIn: rect)
                        let badgeColor = numbered && index == stops.count - 1 && !onInk ? WegoTokens.Palette.ink : routeColor
                        context.fill(point, with: .color(numbered || stop.state == .arrived ? badgeColor : cardColor))
                        context.stroke(point, with: .color(badgeColor), lineWidth: WegoTokens.Metrics.timelineWidth)
                    }
                    .frame(width: columnWidth)
                    .overlay(alignment: .top) {
                        if numbered {
                            Text("\(index + 1)")
                                .font(WegoTokens.Typography.caption.weight(.bold))
                                .foregroundStyle(onInk ? WegoTokens.Palette.ink : WegoTokens.Palette.onAccent)
                                .frame(width: columnWidth, height: badgeSize)
                        }
                    }
                    .accessibilityHidden(true)
                }
                .foregroundStyle(onInk ? WegoTokens.Palette.onInk : WegoTokens.Palette.text)
                .accessibilityElement(children: .combine)
            }
        }
    }

    private var columnWidth: CGFloat { numbered ? badgeSize : WegoTokens.Metrics.courseStopNumberWidth }
    private var routeColor: Color { onInk ? WegoTokens.Palette.routeHighlight : WegoTokens.Palette.accent }
    private var cardColor: Color { onInk ? WegoTokens.Palette.ink : WegoTokens.Palette.background }
    private var secondaryColor: Color { onInk ? WegoTokens.Palette.onInkSecondary : WegoTokens.Palette.secondary }
}

struct StatusPill: View {
    enum Tone { case live, soft, neutral }

    let title: String
    var tone: Tone
    var onInk: Bool

    init(_ title: String, tone: Tone = .neutral, onInk: Bool = false) {
        self.title = title
        self.tone = tone
        self.onInk = onInk
    }

    var body: some View {
        HStack(spacing: WegoTokens.Space.xSmall) {
            if tone == .live {
                Circle().fill(onInk ? WegoTokens.Palette.routeHighlight : WegoTokens.Palette.accent)
                    .frame(width: WegoTokens.Metrics.settingsStatusDotSize, height: WegoTokens.Metrics.settingsStatusDotSize)
                    .accessibilityHidden(true)
            }
            Text(title).font(WegoTokens.Typography.caption.weight(.semibold))
        }
        .padding(.horizontal, WegoTokens.Space.small)
        .padding(.vertical, WegoTokens.Space.xSmall)
        .foregroundStyle(onInk ? WegoTokens.Palette.onInk : tone == .neutral ? WegoTokens.Palette.secondary : WegoTokens.Palette.accent)
        .background(onInk ? WegoTokens.Palette.ink : tone == .neutral ? WegoTokens.Palette.surface : WegoTokens.Palette.accentSoft, in: Capsule())
        .overlay {
            Capsule().strokeBorder(onInk ? WegoTokens.Palette.onInkSecondary : .clear,
                                   lineWidth: WegoTokens.Metrics.hairlineWidth)
        }
        .fixedSize(horizontal: false, vertical: true)
        .accessibilityElement(children: .combine)
    }
}

struct AvatarBadge: View {
    enum Tone { case ink, soft, accent, neutral }

    let name: String
    var tone: Tone = .soft
    private let baseSize: CGFloat
    @ScaledMetric private var scaledSize: CGFloat

    init(name: String, tone: Tone = .soft, size: CGFloat = WegoTokens.Metrics.friendAvatarSize) {
        self.name = name
        self.tone = tone
        baseSize = size
        _scaledSize = ScaledMetric(wrappedValue: size, relativeTo: .caption)
    }

    var body: some View {
        Text(String(name.prefix(2)))
            .font(baseSize >= WegoTokens.Metrics.friendProfileAvatarSize ? WegoTokens.Typography.title : WegoTokens.Typography.label.weight(.semibold))
            .lineLimit(1)
            .frame(width: scaledSize, height: scaledSize)
            .foregroundStyle(tone == .ink ? WegoTokens.Palette.onInk : tone == .accent ? WegoTokens.Palette.onAccent : tone == .neutral ? WegoTokens.Palette.text : WegoTokens.Palette.accent)
            .background(tone == .ink ? WegoTokens.Palette.ink : tone == .accent ? WegoTokens.Palette.accent : tone == .neutral ? WegoTokens.Palette.background : WegoTokens.Palette.accentSoft, in: Circle())
            .accessibilityLabel(name)
    }
}

struct WegoRow: View {
    let systemImage: String
    let title: String
    var subtitle: String? = nil
    var accessorySystemImage: String = "chevron.right"

    var body: some View {
        HStack(spacing: WegoTokens.Space.compact) {
            Image(systemName: systemImage)
                .font(WegoTokens.Typography.section)
                .foregroundStyle(WegoTokens.Palette.accent)
                .frame(width: WegoTokens.Metrics.touchTarget, height: WegoTokens.Metrics.touchTarget)
                .background(WegoTokens.Palette.accentSoft, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.field))
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: WegoTokens.Space.xSmall) {
                Text(title).font(WegoTokens.Typography.section)
                if let subtitle { Text(subtitle).font(WegoTokens.Typography.label).foregroundStyle(WegoTokens.Palette.secondary) }
            }
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
            Image(systemName: accessorySystemImage).font(WegoTokens.Typography.caption.weight(.semibold))
                .foregroundStyle(WegoTokens.Palette.secondary).accessibilityHidden(true)
        }
        .foregroundStyle(WegoTokens.Palette.text)
        .frame(minHeight: WegoTokens.Metrics.touchTarget)
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
    }
}

struct SectionHeader: View {
    let title: String

    init(_ title: String) { self.title = title }

    var body: some View {
        Text(title).font(WegoTokens.Typography.label.weight(.semibold))
            .foregroundStyle(WegoTokens.Palette.secondary)
            .accessibilityAddTraits(.isHeader)
    }
}

struct WegoField: View {
    let title: String
    @Binding var text: String
    var error: String? = nil
    var focus: FocusState<Bool>.Binding? = nil
    var axis: Axis = .horizontal
    var prompt: String? = nil
    var identifier: String? = nil
    var showsTitle = true
    @FocusState private var focused: Bool

    init(_ title: String, text: Binding<String>, error: String? = nil,
         focus: FocusState<Bool>.Binding? = nil, axis: Axis = .horizontal,
         prompt: String? = nil, identifier: String? = nil, showsTitle: Bool = true) {
        self.title = title
        _text = text
        self.error = error
        self.focus = focus
        self.axis = axis
        self.prompt = prompt
        self.identifier = identifier
        self.showsTitle = showsTitle
    }

    var body: some View {
        VStack(alignment: .leading, spacing: WegoTokens.Space.small) {
            if showsTitle { Text(title).font(WegoTokens.Typography.label.weight(.semibold)) }
            TextField(title, text: $text, prompt: prompt.map { Text($0) }, axis: axis)
                .lineLimit(axis == .vertical ? 2...6 : 1...1)
                .font(WegoTokens.Typography.body)
                .padding(.horizontal, WegoTokens.Space.medium)
                .padding(.vertical, WegoTokens.Space.compact)
                .frame(minHeight: WegoTokens.Metrics.primaryButtonHeight)
                .background(WegoTokens.Palette.surface, in: RoundedRectangle(cornerRadius: WegoTokens.Radius.control))
                .overlay {
                    RoundedRectangle(cornerRadius: WegoTokens.Radius.control)
                        .strokeBorder(error == nil ? isFocused ? WegoTokens.Palette.accent : WegoTokens.Palette.divider : WegoTokens.Palette.danger,
                                      lineWidth: isFocused || error != nil ? WegoTokens.Metrics.selectedBorderWidth : WegoTokens.Metrics.hairlineWidth)
                }
                .focused(focus ?? $focused)
                .accessibilityLabel(title)
                .accessibilityIdentifier(identifier ?? title)
                .accessibilityHint(error ?? "")
            if let error {
                Text(error).font(WegoTokens.Typography.caption).foregroundStyle(WegoTokens.Palette.danger)
            }
        }
        .foregroundStyle(WegoTokens.Palette.text)
    }

    private var isFocused: Bool { focus?.wrappedValue ?? focused }
}

struct ChoiceChips: View {
    let options: [String]
    @Binding var selection: Set<String>
    var allowsMultipleSelection = true

    var body: some View {
        WegoChipLayout {
            ForEach(Array(options.enumerated()), id: \.offset) { _, option in
                Button {
                    if selection.contains(option) { selection.remove(option) }
                    else if allowsMultipleSelection { selection.insert(option) }
                    else { selection = [option] }
                } label: {
                    Text(option).font(WegoTokens.Typography.label.weight(.semibold))
                        .padding(.horizontal, WegoTokens.Space.medium)
                        .padding(.vertical, WegoTokens.Space.small)
                        .frame(minHeight: WegoTokens.Metrics.touchTarget)
                        .foregroundStyle(selection.contains(option) ? WegoTokens.Palette.onInk : WegoTokens.Palette.text)
                        .background(selection.contains(option) ? WegoTokens.Palette.ink : WegoTokens.Palette.background, in: Capsule())
                        .overlay {
                            Capsule().strokeBorder(selection.contains(option) ? .clear : WegoTokens.Palette.divider,
                                                   lineWidth: WegoTokens.Metrics.hairlineWidth)
                        }
                }
                .buttonStyle(.plain)
                .accessibilityAddTraits(selection.contains(option) ? .isSelected : [])
            }
        }
    }
}

struct WegoChipLayout: Layout {
    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        arrange(width: proposal.width ?? .infinity, subviews: subviews).size
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let arrangement = arrange(width: bounds.width, subviews: subviews)
        for (index, origin) in arrangement.origins.enumerated() {
            subviews[index].place(at: CGPoint(x: bounds.minX + origin.x, y: bounds.minY + origin.y),
                                 proposal: ProposedViewSize(width: min(bounds.width, subviews[index].sizeThatFits(.unspecified).width), height: nil))
        }
    }

    private func arrange(width: CGFloat, subviews: Subviews) -> (size: CGSize, origins: [CGPoint]) {
        var origins: [CGPoint] = []
        var x: CGFloat = 0
        var y: CGFloat = 0
        var rowHeight: CGFloat = 0
        var measuredWidth: CGFloat = 0
        for view in subviews {
            let ideal = view.sizeThatFits(.unspecified)
            let size = view.sizeThatFits(ProposedViewSize(width: min(width, ideal.width), height: nil))
            if x > 0 && x + size.width > width {
                x = 0
                y += rowHeight + WegoTokens.Space.small
                rowHeight = 0
            }
            origins.append(CGPoint(x: x, y: y))
            measuredWidth = max(measuredWidth, x + size.width)
            x += size.width + WegoTokens.Space.small
            rowHeight = max(rowHeight, size.height)
        }
        return (CGSize(width: measuredWidth, height: y + rowHeight), origins)
    }
}

#if DEBUG
#Preview("공용 컴포넌트 · 밝게") {
    ScrollView {
        VStack(spacing: WegoTokens.Space.large) {
            WegoCard(.ink) {
                VStack(alignment: .leading, spacing: WegoTokens.Space.medium) {
                    Text("함께 달리는 경로").font(WegoTokens.Typography.cardTitle)
                    RouteStrip(stops: ["출발", "함께 갈 곳", "도착"], progress: 1, onInk: true)
                }
            }
            WegoCard(.outlined) {
                RouteList(stops: [.init(id: "start", title: "출발", state: .arrived),
                                  .init(id: "next", title: "다음 장소", subtitle: "주소", state: .next)])
            }
            WegoRow(systemImage: "car", title: "연결 차량", subtitle: "차량 연결을 확인해요")
            HStack { AvatarBadge(name: "사용자F", tone: .ink); StatusPill("진행 중", tone: .live) }
            Button("계속") {}.buttonStyle(.wego(.primary))
        }
        .padding(WegoTokens.Space.screen)
    }
    .background(WegoTokens.Palette.background)
    .preferredColorScheme(.light)
}

#Preview("공용 컴포넌트 · 어둡게") {
    VStack(spacing: WegoTokens.Space.medium) {
        WegoCard(.ink) { RouteStrip(stops: ["출발", "도착"], onInk: true) }
        WegoCard(.soft) { Text("함께 경로를 골라요").font(WegoTokens.Typography.body) }
        WegoRow(systemImage: "person.2", title: "일행", subtitle: "함께 가는 사람들")
        StatusPill("예정")
        Button("경로 보기") {}.buttonStyle(.wego(.soft))
    }
    .padding(WegoTokens.Space.screen)
    .background(WegoTokens.Palette.background)
    .preferredColorScheme(.dark)
}
#endif
