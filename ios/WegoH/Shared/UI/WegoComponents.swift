import SwiftUI

struct BrandHeader: View {
    var markSize: CGFloat = WegoTokens.Metrics.loginStepBadgeSize

    var body: some View {
        HStack(spacing: markSize * 0.14) {
            Image("BrandMark")
                .resizable()
                .frame(width: markSize, height: markSize)
            Image("BrandWordmark")
                .resizable()
                .scaledToFit()
                .frame(width: markSize * 2.45)
                .foregroundStyle(WegoTokens.Palette.text)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("WegoH")
    }
}

struct ActionButton: View {
    let title: String
    var icon: String? = nil
    var isLoading = false
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            if isLoading {
                WegoButtonLoadingLabel(title, onAccent: true)
            } else {
                HStack(spacing: WegoTokens.Space.small) {
                    if let icon { Image(systemName: icon).accessibilityHidden(true) }
                    Text(title)
                }
            }
        }
        .buttonStyle(.wego(.primary))
        .disabled(isLoading)
        .padding(.horizontal, WegoTokens.Space.large)
        .padding(.vertical, WegoTokens.Space.small)
    }
}

struct WegoPrimaryButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var isEnabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .frame(minWidth: WegoTokens.Metrics.touchTarget, minHeight: WegoTokens.Metrics.touchTarget)
            .contentShape(Rectangle())
            .foregroundStyle(WegoTokens.Palette.onAccent)
            .background(WegoTokens.Palette.accent,
                        in: RoundedRectangle(cornerRadius: WegoTokens.Radius.control))
            .opacity(isEnabled ? (configuration.isPressed ? WegoTokens.Opacity.controlPressed : 1) : WegoTokens.Opacity.controlDisabled)
    }
}
