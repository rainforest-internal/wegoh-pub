import Foundation

struct AccountMusicTrack: Codable, Equatable {
    let id: String
    var title: String
    var url: String
}

struct AccountMusicPlaylist: Codable, Equatable {
    let id: String
    var name: String
    var tracks: [AccountMusicTrack]
    let revision: Int
}

protocol IPhoneMusicServing {
    func list(token: String) async throws -> [AccountMusicPlaylist]
    func create(title: String, url: String, token: String) async throws -> AccountMusicPlaylist
    func update(_ value: AccountMusicPlaylist, token: String) async throws -> AccountMusicPlaylist
    func delete(_ value: AccountMusicPlaylist, token: String) async throws
}

final class IPhoneMusicAPI: IPhoneMusicServing {
    private let http: IPhoneSessionAPI
    init(configuration: URLSessionConfiguration? = nil) { http = IPhoneSessionAPI(configuration: configuration) }
    func list(token: String) async throws -> [AccountMusicPlaylist] {
        struct Page: Decodable { let playlists: [AccountMusicPlaylist] }
        let page = try JSONDecoder().decode(Page.self, from: await http.resource("playlists", token: token))
        guard page.playlists.count <= 100, Set(page.playlists.map(\.id)).count == page.playlists.count else { throw IPhoneSessionError.invalidResponse }
        return try page.playlists.map(validate)
    }
    func create(title: String, url: String, token: String) async throws -> AccountMusicPlaylist {
        let body: [String: Any] = ["name": title, "tracks": [["title": title, "url": url]]]
        return try validate(JSONDecoder().decode(AccountMusicPlaylist.self, from: await http.resource("playlists", method: "POST",
            payload: JSONSerialization.data(withJSONObject: body), token: token, status: 201)))
    }
    func update(_ value: AccountMusicPlaylist, token: String) async throws -> AccountMusicPlaylist {
        _ = try validate(value)
        struct Body: Encodable { let name: String; let tracks: [AccountMusicTrack]; let revision: Int }
        let body = Body(name: value.name, tracks: value.tracks, revision: value.revision)
        let saved = try validate(JSONDecoder().decode(AccountMusicPlaylist.self, from: await http.resource("playlists/" + value.id,
            method: "PUT", payload: JSONEncoder().encode(body), token: token)))
        guard saved.id == value.id, saved.revision > value.revision else { throw IPhoneSessionError.invalidResponse }
        return saved
    }
    func delete(_ value: AccountMusicPlaylist, token: String) async throws {
        _ = try validate(value)
        let data = try await http.resource("playlists/" + value.id, method: "DELETE",
            payload: JSONEncoder().encode(["revision": value.revision]), token: token)
        struct Result: Decodable { let status: String }
        guard try JSONDecoder().decode(Result.self, from: data).status == "deleted" else { throw IPhoneSessionError.invalidResponse }
    }
    private func validate(_ value: AccountMusicPlaylist) throws -> AccountMusicPlaylist {
        func id(_ value: String) -> Bool { value.range(of: #"\A[a-f0-9]{32}\z"#, options: .regularExpression) != nil }
        guard id(value.id), (1...Int(Int32.max)).contains(value.revision), !value.name.isEmpty, value.name.count <= 80,
              value.tracks.count <= 100, Set(value.tracks.map(\.id)).count == value.tracks.count,
              value.tracks.allSatisfy({ id($0.id) && !$0.title.isEmpty && $0.title.count <= 120 && MusicPreviewStore.validatedURL($0.url) != nil }) else {
            throw IPhoneSessionError.invalidResponse
        }
        return value
    }
}
