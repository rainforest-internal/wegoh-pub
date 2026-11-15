// Generated file. Do not edit by hand.
import SwiftUI
import UIKit

enum WegoTokens {
    enum Palette {
        static let accent = Color.accentColor
        static let background = adaptive(light: 0xFFFFFF, dark: 0x131417)
        static let surface = adaptive(light: 0xF7F8FA, dark: 0x1D1E21)
        static let text = adaptive(light: 0x131417, dark: 0xF7F8FA)
        static let secondary = adaptive(light: 0x44464E, dark: 0xC7C9CE)
        static let divider = adaptive(light: 0xE0E1E6, dark: 0x44464E)
        static let onAccent = adaptive(light: 0xFFFFFF, dark: 0x131417)
        static let accentSoft = adaptive(light: 0xE8EFFC, dark: 0x1D2A42)
        static let personalRouteBorder = adaptive(light: 0xC7C9CE, dark: 0x44464E)
        static let ink = adaptive(light: 0x14243D, dark: 0x263A5E)
        static let onInk = adaptive(light: 0xFFFFFF, dark: 0xF7F8FA)
        static let routeHighlight = adaptive(light: 0x6C9CF0, dark: 0x7AA6F2)
        static let onInkSecondary = adaptive(light: 0xC7C9CE, dark: 0xC7C9CE)
        static let inkDivider = adaptive(light: 0x44464E, dark: 0x44464E)
        static let danger = adaptive(light: 0xC7290A, dark: 0xFF4C28)
        static let skeleton = adaptive(light: 0xEDEEF1, dark: 0x2C2D33)
        static let skeletonOnInk = adaptive(light: 0x22324D, dark: 0x30476F)
        static let skeletonOnInkHighlight = adaptive(light: 0x2C3D5B, dark: 0x3A5380)
        static let selectionIndicator = adaptive(light: 0x14243D, dark: 0x6C9CF0)
        static let inkBorder = adaptive(light: 0x14243D, dark: 0xA4A8AE)
        static let softBorder = adaptive(light: 0xE8EFFC, dark: 0x686A72)
        static let mapLabelText = adaptive(light: 0x131417, dark: 0x131417)
        static let mapLabelHalo = adaptive(light: 0xFFFFFF, dark: 0xFFFFFF)

        private static func adaptive(light: UInt32, dark: UInt32) -> Color {
            Color(uiColor: UIColor { traits in
                let rgb = traits.userInterfaceStyle == .dark ? dark : light
                return UIColor(red: CGFloat((rgb >> 16) & 255) / 255,
                               green: CGFloat((rgb >> 8) & 255) / 255,
                               blue: CGFloat(rgb & 255) / 255, alpha: 1)
            })
        }
    }

    enum Space {
        static let small: CGFloat = 8
        static let medium: CGFloat = 16
        static let large: CGFloat = 24
        static let xLarge: CGFloat = 32
        static let xSmall: CGFloat = 4
        static let compact: CGFloat = 12
        static let screen: CGFloat = 20
    }

    enum Radius {
        static let field: CGFloat = 12
        static let control: CGFloat = 16
        static let card: CGFloat = 20
        static let hero: CGFloat = 24
        static let sheet: CGFloat = 28
        static let routeSegment: CGFloat = 10
    }

    enum Opacity {
        static let pastRouteSegment: Double = 0.45
        static let controlPressed: Double = 0.8
        static let controlDisabled: Double = 0.45
        static let modalScrim: Double = 0.4
    }

    enum Motion {
        static let toastDuration: Double = 3.5
        static let loadingRevealDelay: Double = 0.3
        static let loadingSlowDelay: Double = 8
        static let routeLoaderDuration: Double = 1.6
        static let skeletonDuration: Double = 1.4
        static let loadingFrameInterval: Double = 0.03333333333333333
    }

    enum Typography {
        static let hero = Font.system(.largeTitle, weight: .bold)
        static let title = Font.system(.title, weight: .bold)
        static let section = Font.headline
        static let body = Font.system(.body, weight: .regular)
        static let label = Font.system(.subheadline, weight: .regular)
        static let caption = Font.system(.footnote, weight: .regular)
        static let action = Font.headline
        static let cardTitle = Font.system(.title3, weight: .bold)
    }

    enum Metrics {
        static let touchTarget: CGFloat = 44
        static let buttonCornerRadius: CGFloat = 14
        static let courseMapHeight: CGFloat = 220
        static let placeMapHeight: CGFloat = 200
        static let courseStopNumberWidth: CGFloat = 20
        static let mapMarkerCanvasWidth: CGFloat = 24
        static let mapMarkerCanvasHeight: CGFloat = 30
        static let mapMarkerInset: CGFloat = 2
        static let mapMarkerDiameter: CGFloat = 20
        static let mapMarkerFontSize: CGFloat = 12
        static let mapMarkerStrokeWidth: CGFloat = 2
        static let mapMarkerLayerOrder: CGFloat = 10001
        static let mapRouteWidth: CGFloat = 8
        static let mapRouteStrokeWidth: CGFloat = 2
        static let mapLabelHaloWidth: CGFloat = 2
        static let primaryButtonHeight: CGFloat = 54
        static let permissionIconSize: CGFloat = 48
        static let loginMarkSize: CGFloat = 64
        static let onboardingMarkSize: CGFloat = 30
        static let introductionBodySize: CGFloat = 18
        static let pageIndicatorSize: CGFloat = 6
        static let activePageIndicatorWidth: CGFloat = 22
        static let timelineWidth: CGFloat = 2
        static let loginTopSpace: CGFloat = 56
        static let loginStepsSpace: CGFloat = 40
        static let loginStepBadgeSize: CGFloat = 28
        static let settingsAvatarSize: CGFloat = 52
        static let settingsMenuHeight: CGFloat = 72
        static let settingsStatusDotSize: CGFloat = 7
        static let hairlineWidth: CGFloat = 1
        static let settingsHeaderHeight: CGFloat = 52
        static let profileAvatarSize: CGFloat = 72
        static let settingsDetailRowHeight: CGFloat = 56
        static let selectedBorderWidth: CGFloat = 1.5
        static let friendAvatarSize: CGFloat = 40
        static let friendProfileAvatarSize: CGFloat = 88
        static let friendRowHeight: CGFloat = 60
        static let friendSearchAvatarSize: CGFloat = 48
        static let musicArtworkSize: CGFloat = 48
        static let musicEqualizerWidth: CGFloat = 83
        static let musicEqualizerHeight: CGFloat = 44
        static let courseSummaryDotSize: CGFloat = 12
        static let courseSummaryDestinationRadius: CGFloat = 3
        static let routeCurrentMarkerSize: CGFloat = 18
        static let courseStopBadgeSize: CGFloat = 28
        static let courseDetailMapHeight: CGFloat = 150
        static let courseEditorMapHeight: CGFloat = 150
        static let coursePlaceSelectionSize: CGFloat = 26
        static let tripChecklistIconSize: CGFloat = 24
        static let tripMemberAvatarSize: CGFloat = 28
        static let tripRouteDotSize: CGFloat = 8
        static let tripChecklistRowHeight: CGFloat = 32
        static let emptyArtworkHeight: CGFloat = 96
        static let emptyIconSize: CGFloat = 72
        static let emptyCountBadgeSize: CGFloat = 56
        static let emptyRouteDotSize: CGFloat = 8
        static let emptyRequestIconSize: CGFloat = 40
        static let tripInvitationAvatarSize: CGFloat = 44
        static let tripInvitationSheetHeight: CGFloat = 600
        static let tripUnassignedChipMinimumWidth: CGFloat = 88
        static let tripSignalReasonTileHeight: CGFloat = 96
        static let tripSignalResponseButtonHeight: CGFloat = 60
        static let tripProgressActionHeight: CGFloat = 68
        static let tripRouteSegmentMinimumHeight: CGFloat = 36
        static let vehicleScannerHeight: CGFloat = 260
        static let loadingRouteWidth: CGFloat = 132
        static let loadingRouteHeight: CGFloat = 28
        static let loadingDotSize: CGFloat = 10
        static let loadingDestinationSize: CGFloat = 12
        static let loadingLaunchMarkSize: CGFloat = 88
        static let loadingSpinnerSize: CGFloat = 16
        static let loadingSkeletonLineHeight: CGFloat = 12
        static let loadingSkeletonTitleHeight: CGFloat = 20
        static let loadingSkeletonCardHeight: CGFloat = 152
        static let loadingMinimumHeight: CGFloat = 180
    }
}
