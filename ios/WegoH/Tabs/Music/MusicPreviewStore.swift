import Foundation
import Observation

enum MusicPlatform: String, CaseIterable, Identifiable {
    case melon, spotify, youtubeMusic, youtube, other

    var id: Self { self }

    var label: String {
        switch self {
        case .melon: "멜론"
        case .spotify: "스포티파이"
        case .youtubeMusic: "유튜브 뮤직"
        case .youtube: "유튜브"
        case .other: "기타"
        }
    }

    static func detected(for url: URL) -> Self {
        switch url.host?.lowercased() {
        case "melon.com", "www.melon.com", "m.melon.com", "m2.melon.com", "kko.to", "kko.kakao.com": .melon
        case "open.spotify.com", "spotify.link": .spotify
        case "music.youtube.com": .youtubeMusic
        case "www.youtube.com", "youtube.com", "m.youtube.com", "youtu.be": .youtube
        default: .other
        }
    }
}

struct MusicPreviewItem: Identifiable {
    let id: String
    let title: String
    let platform: MusicPlatform
    let url: URL?
}

@MainActor
@Observable
final class MusicPreviewStore {
    private(set) var documents: [AccountMusicPlaylist] = []
    private(set) var hasLoaded = false
    private(set) var isLoading = false
    private(set) var isMutating = false
    private(set) var needsReload = false
    private(set) var error: String?
    private let api: any IPhoneMusicServing
    private var operation: UUID?

    init(api: any IPhoneMusicServing = IPhoneMusicAPI()) { self.api = api }

    var items: [MusicPreviewItem] {
        documents.flatMap { list in list.tracks.compactMap { track -> MusicPreviewItem? in
            guard let url = Self.validatedURL(track.url) else { return nil }
            return MusicPreviewItem(id: list.id + ":" + track.id, title: track.title,
                                    platform: MusicPlatform.detected(for: url), url: url)
        } }
    }

    func load(session: SessionManager, account: AccountSession, force: Bool = false) async {
        guard !isLoading, !isMutating, force || !hasLoaded, session.current == account else { return }
        let stamp = UUID(); operation = stamp; isLoading = true; error = nil
        defer { if operation == stamp { isLoading = false } }
        do {
            let value = try await session.withToken(for: account) { try await api.list(token: $0) }
            guard operation == stamp else { return }
            documents = value; hasLoaded = true; needsReload = false
        } catch is CancellationError { }
        catch { if operation == stamp, session.current == account { self.error = Self.message(error) } }
    }

    func save(id: String? = nil, title: String, platform: MusicPlatform, rawURL: String,
              session: SessionManager, account: AccountSession) async -> String? {
        guard !isMutating, !isLoading, hasLoaded, !needsReload else { return "먼저 목록을 새로고침해 주세요." }
        let title = title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !title.isEmpty, title.count <= 80, !title.unicodeScalars.contains(where: { $0.value < 32 }) else {
            return "플레이리스트 이름을 80자 이내로 입력해 주세요."
        }
        guard let url = Self.validatedURL(rawURL) else { return "https://로 시작하는 올바른 링크를 입력해 주세요." }
        let detected = MusicPlatform.detected(for: url)
        guard platform == .other || platform == detected else { return "\(platform.label) 링크가 아니에요. 플랫폼을 다시 골라 주세요." }
        guard !items.contains(where: { $0.url == url && $0.id != id }) else { return "이미 추가한 플레이리스트 링크예요." }
        isMutating = true; error = nil
        defer { isMutating = false }
        do {
            let value: AccountMusicPlaylist
            if let id {
                guard var list = documents.first(where: { list in list.tracks.contains { list.id + ":" + $0.id == id } }),
                      let index = list.tracks.firstIndex(where: { list.id + ":" + $0.id == id }) else {
                    return "목록이 바뀌었어요. 새로고침한 뒤 다시 수정해 주세요."
                }
                list.tracks[index].title = title; list.tracks[index].url = url.absoluteString
                if list.tracks.count == 1 { list.name = title }
                let updated = list
                value = try await session.withToken(for: account) { try await api.update(updated, token: $0) }
            } else {
                value = try await session.withToken(for: account) { try await api.create(title: title, url: url.absoluteString, token: $0) }
            }
            documents.removeAll { $0.id == value.id }; documents.insert(value, at: 0)
            return nil
        } catch is CancellationError { return "계정 상태가 바뀌었어요. 다시 열어 주세요." }
        catch {
            if session.current == account {
                needsReload = true
                self.error = Self.message(error)
                return self.error
            }
            return "계정 상태가 바뀌었어요. 다시 열어 주세요."
        }
    }

    func remove(id: String, session: SessionManager, account: AccountSession) async -> String? {
        guard !isMutating, !isLoading, !needsReload,
              var list = documents.first(where: { list in list.tracks.contains { list.id + ":" + $0.id == id } }) else {
            return "먼저 목록을 새로고침해 주세요."
        }
        isMutating = true; error = nil
        defer { isMutating = false }
        list.tracks.removeAll { list.id + ":" + $0.id == id }
        do {
            if list.tracks.isEmpty {
                let removed = list
                try await session.withToken(for: account) { try await api.delete(removed, token: $0) }
                documents.removeAll { $0.id == removed.id }
            } else {
                let updated = list
                let value = try await session.withToken(for: account) { try await api.update(updated, token: $0) }
                documents.removeAll { $0.id == value.id }; documents.insert(value, at: 0)
            }
            return nil
        } catch is CancellationError { return "계정 상태가 바뀌었어요. 다시 열어 주세요." }
        catch {
            if session.current == account { needsReload = true; self.error = Self.message(error) }
            return self.error ?? "계정 상태가 바뀌었어요. 다시 열어 주세요."
        }
    }

    private static func message(_ error: Error) -> String {
        switch error {
        case IPhoneResourceError.conflict: "목록이 다른 곳에서 바뀌었어요. 새로고침한 뒤 다시 확인해 주세요."
        case IPhoneResourceError.missing: "목록을 찾을 수 없어요. 새로고침해 주세요."
        case IPhoneSessionError.forbidden: "계정의 음악 목록을 변경할 수 없어요. 로그인 권한을 확인해 주세요."
        case IPhoneSessionError.invalidSession: "로그인 시간이 끝났어요. 다시 로그인해 주세요."
        default: "서버 응답을 확인하지 못했어요. 목록을 새로고침해 저장 여부를 확인해 주세요."
        }
    }

    nonisolated static func validatedURL(_ raw: String) -> URL? {
        let value = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard value.rangeOfCharacter(from: .whitespacesAndNewlines.union(.controlCharacters)) == nil,
              let parts = URLComponents(string: value), parts.scheme?.lowercased() == "https",
              let host = parts.host, !host.isEmpty, parts.user == nil, parts.password == nil,
              parts.port == nil || parts.port == 443 else { return nil }
        return parts.url
    }
}
