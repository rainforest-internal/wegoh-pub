#if DEBUG
import SwiftUI

struct WegoLoadingUIFixture: View {
    static var requested: Bool { ProcessInfo.processInfo.arguments.contains("-loading-ui-fixture") }
    private static var mode: String {
        let arguments = ProcessInfo.processInfo.arguments
        guard let index = arguments.firstIndex(of: "-loading-ui-fixture"), arguments.indices.contains(index + 1) else { return "list" }
        return arguments[index + 1]
    }
    @State private var finished = false
    @State private var retries = 0

    var body: some View {
        Group {
            if Self.mode == "launch" {
                WegoLoadingView("내 여행을 불러오는 중", layout: .launch)
            } else {
                NavigationStack {
                    ScrollView {
                        VStack(alignment: .leading, spacing: WegoTokens.Space.large) {
                            if Self.mode == "list" { Text("여행").font(WegoTokens.Typography.hero) }
                            if Self.mode == "detail" { Text("서해안 드라이브").font(WegoTokens.Typography.title) }
                            if finished {
                                Text("불러오기 완료").accessibilityIdentifier("loadingFixtureComplete")
                            } else if Self.mode == "failure" {
                                WegoLoadingFailureView(message: "연결 상태를 확인하고 다시 시도해 주세요.") { finished = true }
                            } else if Self.mode == "button" {
                                Text("여행 정보").font(WegoTokens.Typography.title)
                                Text("이미 입력한 내용은 그대로 보여요.")
                                ActionButton(title: "저장하는 중", isLoading: true) { }
                                    .accessibilityIdentifier("loadingFixtureSave")
                                WegoLoadingView("가까운 휴게소를 찾는 중", layout: .row)
                            } else {
                                WegoLoadingView("여행을 불러오는 중", layout: Self.mode == "list" ? .list : Self.mode == "detail" ? .detail : .inline) { retries += 1 }
                            }
                            if retries > 0 { Text("재시도 \(retries)").accessibilityIdentifier("loadingFixtureRetryCount") }
                        }
                        .padding(WegoTokens.Space.screen)
                    }
                    .navigationTitle(Self.mode == "detail" ? "여행" : "공통 로딩")
                    .navigationBarTitleDisplayMode(.inline)
                }
            }
        }
        .foregroundStyle(WegoTokens.Palette.text)
        .background(WegoTokens.Palette.background.ignoresSafeArea())
        .preferredColorScheme(ProcessInfo.processInfo.arguments.contains("-loading-ui-dark") ? .dark : .light)
        .environment(\.dynamicTypeSize, ProcessInfo.processInfo.arguments.contains("-loading-ui-large-text") ? .accessibility5 : .large)
        .task {
            if Self.mode == "fast" {
                try? await Task.sleep(for: .milliseconds(100))
                finished = true
            }
        }
    }
}
#endif
