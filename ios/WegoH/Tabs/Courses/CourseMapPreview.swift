import KakaoMapsSDK
import OSLog
import SwiftUI

struct CourseMapPreview: View {
    let stops: [CourseStop]
    var path: [CourseCoordinate] = []
    var isThumbnail = false

    var body: some View {
        WegoMapPreview(markers: stops.map { .init(id: $0.id, name: $0.name, latitude: $0.latitude, longitude: $0.longitude) },
                       path: path, accessibilityTitle: "경로 장소 지도", isThumbnail: isThumbnail)
    }
}

struct WegoMapMarker: Hashable, Identifiable {
    var id: String
    var name: String
    var latitude: Double
    var longitude: Double
    var sequenceLabel: String? = nil
    /// 다른 차 현재 위치 표식. 위치가 갱신돼도 지도 시점을 다시 맞추지 않고, 장소 번호와 다른 색으로 그린다.
    var isVehicle = false
}

struct WegoMapPreview: View {
    private enum MapState { case preparing, ready, failed }
    let markers: [WegoMapMarker]
    var path: [CourseCoordinate] = []
    var accessibilityTitle = "장소 지도"
    var isThumbnail = false
    @Environment(\.scenePhase) private var scenePhase
    @State private var visible = false
    @State private var mapState: MapState = .preparing

    private var hasMapKey: Bool {
        APIKeys.mapAPIKey?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty == false
    }

    var body: some View {
        Group {
            if isThumbnail && (mapState == .failed || !hasMapKey) {
                Image(systemName: "mappin.slash").foregroundStyle(WegoTokens.Palette.secondary)
            } else if markers.isEmpty && path.isEmpty {
                ContentUnavailableView("표시할 위치가 없어요", systemImage: "map")
            } else if !hasMapKey {
                ContentUnavailableView("지도를 표시할 수 없어요", systemImage: "map",
                                       description: Text("위치 정보는 아래 목록에서 확인해 주세요."))
            } else if mapState == .failed {
                ContentUnavailableView {
                    Label("지도를 불러오지 못했어요", systemImage: "map")
                } actions: {
                    Button("다시 시도") { mapState = .preparing }
                }
            } else {
                CourseMapSurface(stops: markers, path: path, showsNames: !isThumbnail, active: visible && scenePhase == .active,
                                 onReady: { mapState = .ready }, onFailure: { mapState = .failed })
                    .accessibilityLabel(accessibilityTitle)
                    .overlay {
                        if mapState == .preparing {
                            if isThumbnail { ProgressView() }
                            else { WegoLoadingView("지도를 준비하고 있어요", layout: .inline) }
                        }
                    }
            }
        }
        .onAppear { visible = true }
        .onDisappear { visible = false }
        .onChange(of: markers.isEmpty && path.isEmpty) { _, empty in
            if empty { mapState = .preparing }
        }
    }
}

private struct CourseMapSurface: UIViewRepresentable {
    let stops: [WegoMapMarker]
    let path: [CourseCoordinate]
    /// 장소 번호 표식 아래에 장소 이름을 쓴다. 작은 썸네일은 번호만 둔다.
    let showsNames: Bool
    let active: Bool
    let onReady: () -> Void
    let onFailure: () -> Void

    func makeUIView(context: Context) -> KMViewContainer {
        let view = KMViewContainer()
        context.coordinator.container = view
        context.coordinator.controller = KMController(viewContainer: view)
        context.coordinator.controller?.delegate = context.coordinator
        return view
    }

    func updateUIView(_ uiView: KMViewContainer, context: Context) {
        context.coordinator.update(stops: stops, path: path)
        context.coordinator.setActive(active)
    }

    func makeCoordinator() -> Coordinator { Coordinator(stops: stops, path: path, showsNames: showsNames, onReady: onReady, onFailure: onFailure) }

    static func dismantleUIView(_ uiView: KMViewContainer, coordinator: Coordinator) {
        coordinator.controller?.delegate = nil
        coordinator.controller?.pauseEngine()
        coordinator.controller?.resetEngine()
        coordinator.controller = nil
    }

    final class Coordinator: NSObject, MapControllerDelegate {
        private var stops: [WegoMapMarker]
        let onReady: () -> Void
        let onFailure: () -> Void
        private var path: [CourseCoordinate]
        private let showsNames: Bool
        private var renderedStops: [WegoMapMarker]?
        private var renderedPath: [CourseCoordinate]?
        private var renderedAnchors: [WegoMapMarker]?
        private var styles: Set<String> = []
        private var active = false
        var controller: KMController?
        weak var container: KMViewContainer?
        init(stops: [WegoMapMarker], path: [CourseCoordinate], showsNames: Bool, onReady: @escaping () -> Void, onFailure: @escaping () -> Void) {
            self.stops = stops
            self.path = path
            self.showsNames = showsNames
            self.onReady = onReady
            self.onFailure = onFailure
        }
        func setActive(_ shouldActivate: Bool) {
            guard let controller, active != shouldActivate else { return }
            active = shouldActivate
            if active {
                if !controller.isEnginePrepared && !controller.prepareEngine() {
                    fail()
                    return
                }
                controller.activateEngine()
            } else {
                controller.pauseEngine()
            }
        }

        func addViews() {
            let center = stops.first.map { MapPoint(longitude: $0.longitude, latitude: $0.latitude) }
                ?? path.first.map { MapPoint(longitude: $0.lng, latitude: $0.lat) }
            guard let center else { return }
            controller?.addView(MapviewInfo(viewName: "course", viewInfoName: "map",
                                            defaultPosition: center, defaultLevel: 14))
        }
        func addViewSucceeded(_ viewName: String, viewInfoName: String) {
            guard let map = controller?.getView("course") as? KakaoMap else { return }
            map.viewRect = CGRect(origin: .zero, size: container?.bounds.size ?? .zero)
            let labels = map.getLabelManager()
            // 장소 표식이 같은 자리의 기본 지도 이름(예: 서울역)을 반쯤 가리지 않게, 아래 우선순위 레이어와 경쟁해 겹친 기본 이름을 숨긴다.
            _ = labels.addLabelLayer(option: LabelLayerOptions(layerID: "stops", competitionType: .lower,
                competitionUnit: .poi, orderType: .rank, zOrder: Int(WegoTokens.Metrics.mapMarkerLayerOrder)))
            let routes = map.getRouteManager()
            routes.addRouteStyleSet(RouteStyleSet(styleID: "course-road", styles: [RouteStyle(styles: [
                PerLevelRouteStyle(width: UInt(WegoTokens.Metrics.mapRouteWidth), color: UIColor(WegoTokens.Palette.accent), strokeWidth: UInt(WegoTokens.Metrics.mapRouteStrokeWidth),
                    strokeColor: UIColor(WegoTokens.Palette.onAccent), level: 0)
            ])]))
            _ = routes.addRouteLayer(layerID: "course-road", zOrder: 0)
            styles.removeAll()
            renderedStops = nil
            renderedPath = nil
            renderedAnchors = nil
            update(stops: stops, path: path)
            DispatchQueue.main.async { [weak self] in
                guard let self, controller != nil else { return }
                onReady()
            }
        }

        func update(stops: [WegoMapMarker], path: [CourseCoordinate]) {
            self.stops = stops
            self.path = path
            guard let map = controller?.getView("course") as? KakaoMap,
                  let labels = map.getLabelManager().getLabelLayer(layerID: "stops"),
                  let routes = map.getRouteManager().getRouteLayer(layerID: "course-road"),
                  renderedStops != stops || renderedPath != path else { return }
            // 다른 차 위치만 바뀌었을 때는 시점을 그대로 둔다. 주기적으로 지도가 움직이지 않게 한다.
            let anchors = stops.filter { !$0.isVehicle }
            let refit = renderedAnchors != anchors || renderedPath != path
            if renderedStops != stops {
                labels.clearAllItems()
                var number = 0
                for stop in stops {
                    if !stop.isVehicle { number += 1 }
                    let label = stop.sequenceLabel ?? (stop.isVehicle ? stop.name : String(number))
                    let style = (stop.isVehicle ? "car-" : "stop-") + label
                    if styles.insert(style).inserted {
                        addStyle(style, label: label, vehicle: stop.isVehicle, to: map.getLabelManager())
                    }
                    let point = MapPoint(longitude: stop.longitude, latitude: stop.latitude)
                    let option = PoiOptions(styleID: style, poiID: stop.id)
                    if stop.isVehicle { option.rank = 1 }
                    if showsNames && !stop.isVehicle { option.addText(PoiText(text: stop.name, styleIndex: 0)) }
                    labels.addPoi(option: option, at: point)?.show()
                }
                renderedStops = stops
            }
            if renderedPath != path {
                routes.clearAllRoutes()
                if path.count > 1 {
                    let options = RouteOptions(routeID: "course-road", styleID: "course-road", zOrder: 0)
                    options.segments = [RouteSegment(points: path.map { MapPoint(longitude: $0.lng, latitude: $0.lat) }, styleIndex: 0)]
                    routes.addRoute(option: options)?.show()
                }
                renderedPath = path
            }
            if refit {
                renderedAnchors = anchors
                fitStops(in: map)
            }
        }

        private func addStyle(_ style: String, label: String, vehicle: Bool, to labels: LabelManager) {
            let fill = UIColor(vehicle ? WegoTokens.Palette.ink : WegoTokens.Palette.accent)
            let ink = UIColor(vehicle ? WegoTokens.Palette.onInk : WegoTokens.Palette.onAccent)
            let text = label as NSString
            let attributes: [NSAttributedString.Key: Any] = [.font: UIFont.boldSystemFont(ofSize: WegoTokens.Metrics.mapMarkerFontSize), .foregroundColor: ink]
            let textSize = text.size(withAttributes: attributes)
            let width = max(WegoTokens.Metrics.mapMarkerCanvasWidth, textSize.width + WegoTokens.Metrics.mapMarkerInset * 4)
            let centerY = WegoTokens.Metrics.mapMarkerInset + WegoTokens.Metrics.mapMarkerDiameter / 2
            let renderer = UIGraphicsImageRenderer(size: CGSize(width: width, height: WegoTokens.Metrics.mapMarkerCanvasHeight))
            let image = renderer.image { _ in
                fill.setFill()
                let outline = UIBezierPath(roundedRect: CGRect(x: WegoTokens.Metrics.mapMarkerInset, y: WegoTokens.Metrics.mapMarkerInset,
                                                               width: width - WegoTokens.Metrics.mapMarkerInset * 2, height: WegoTokens.Metrics.mapMarkerDiameter),
                                           cornerRadius: WegoTokens.Metrics.mapMarkerDiameter / 2)
                outline.fill()
                ink.setStroke()
                outline.lineWidth = WegoTokens.Metrics.mapMarkerStrokeWidth
                outline.stroke()
                text.draw(at: CGPoint(x: (width - textSize.width) / 2, y: centerY - textSize.height / 2), withAttributes: attributes)
            }
            let icon = PoiIconStyle(symbol: image, anchorPoint: CGPoint(x: 0.5, y: centerY / WegoTokens.Metrics.mapMarkerCanvasHeight))
            guard !vehicle else {
                labels.addPoiStyle(PoiStyle(styleID: style, styles: [PerLevelPoiStyle(iconStyle: icon, level: 0)]))
                return
            }
            // 장소 이름은 번호 표식 아래에 둔다. 지도 타일은 다크 모드에서도 밝아 글자·외곽선은 지도 기준 고정색을 쓴다.
            let name = PoiTextStyle(textLineStyles: [PoiTextLineStyle(textStyle: TextStyle(
                fontSize: UInt(WegoTokens.Metrics.mapMarkerFontSize), fontColor: UIColor(WegoTokens.Palette.mapLabelText),
                strokeThickness: UInt(WegoTokens.Metrics.mapLabelHaloWidth), strokeColor: UIColor(WegoTokens.Palette.mapLabelHalo)))])
            name.textLayouts = [.bottom]
            labels.addPoiStyle(PoiStyle(styleID: style, styles: [PerLevelPoiStyle(iconStyle: icon, textStyle: name, level: 0)]))
        }

        func addViewFailed(_ viewName: String, viewInfoName: String) { fail() }
        func authenticationFailed(_ errorCode: Int, desc: String) {
            Logger(subsystem: "io.wegoh.iphone", category: "course-map")
                .error("course.map: failed reason=authentication code=\(errorCode, privacy: .public)")
            fail()
        }
        func containerDidResized(_ size: CGSize) {
            guard let map = controller?.getView("course") as? KakaoMap else { return }
            map.viewRect = CGRect(origin: .zero, size: size)
            fitStops(in: map)
        }
        private func fitStops(in map: KakaoMap) {
            let size = map.viewRect.size
            guard size.width > 0, size.height > 0 else { return }
            let side = min(WegoTokens.Space.large, size.width / 6)
            map.setMargins(UIEdgeInsets(top: min(WegoTokens.Space.large * 2, size.height / 4), left: side,
                                        bottom: min(WegoTokens.Space.xLarge, size.height / 5), right: side))
            let anchors = stops.filter { !$0.isVehicle }
            let points = (anchors.isEmpty ? stops : anchors).map { CourseCoordinate(lat: $0.latitude, lng: $0.longitude) } + path
            guard let first = points.first else { return }
            if points.contains(where: { $0 != first }) {
                let bounds = AreaRect(points: points.map { MapPoint(longitude: $0.lng, latitude: $0.lat) })
                map.moveCamera(CameraUpdate.make(area: bounds, levelLimit: 15))
            } else {
                map.moveCamera(CameraUpdate.make(target: MapPoint(longitude: first.lng, latitude: first.lat),
                                                 zoomLevel: 15, mapView: map))
            }
        }
        private func fail() {
            DispatchQueue.main.async { [weak self] in
                guard let self, controller != nil else { return }
                onFailure()
            }
        }
    }
}
