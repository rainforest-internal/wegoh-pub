import Foundation
import ImageIO

protocol CourseDiscoveryServing {
    func library(query: String, tags: [String], token: String) async throws -> CourseDiscoveryLibrary
    func detail(_ item: CourseDiscoveryItem, token: String) async throws -> CourseDiscoveryDetail
    func creator(_ creatorID: String, token: String) async throws -> CourseDiscoveryPublicCreator
    func setStarred(_ item: CourseDiscoveryItem, starred: Bool, token: String) async throws
    func followCreator(_ item: CourseDiscoveryItem, token: String) async throws
    func unfollowCreator(_ followID: String, token: String) async throws
    func setTagFollowed(_ tag: String, followed: Bool, token: String) async throws
    func markRead(_ eventID: String, token: String) async throws
    func notInterested(_ item: CourseDiscoveryItem, token: String) async throws
    func report(_ item: CourseDiscoveryItem, reason: String, token: String) async throws
    func copy(_ item: CourseDiscoveryItem, token: String) async throws -> CourseDetail
}

protocol CourseDiscoveryCoverServing {
    func cover(_ item: CourseDiscoveryItem, token: String) async throws -> Data
}

enum CourseDiscoveryCopyError: Error, LocalizedError {
    case permissionRequired
    var errorDescription: String? {
        "이 경로를 가져올 수 없어요. 원본 창작자의 재사용 허용과 내 경로 만들기 권한을 확인해 주세요."
    }
}

final class CourseDiscoveryAPI: CourseDiscoveryServing, CourseDiscoveryCoverServing {
    private let http: IPhoneSessionAPI
    init(configuration: URLSessionConfiguration? = nil) { http = IPhoneSessionAPI(configuration: configuration) }

    func library(query: String, tags: [String], token: String) async throws -> CourseDiscoveryLibrary {
        let clean = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard clean.unicodeScalars.count <= 100, clean.unicodeScalars.allSatisfy({ $0.value >= 32 }), validDiscoveryTags(tags) else { throw CourseRequestError.invalidInput }
        var components = URLComponents()
        components.queryItems = (clean.isEmpty ? [] : [URLQueryItem(name: "q", value: clean)])
            + tags.map { URLQueryItem(name: "tag", value: $0) }
        let query = components.percentEncodedQuery.map { $0.isEmpty ? "" : "?" + $0.replacingOccurrences(of: "+", with: "%2B") } ?? ""
        let value: CourseDiscoveryLibrary = try await request("courses/library" + query, token: token)
        guard value.isValid else { throw IPhoneSessionError.invalidResponse }
        return value
    }

    func detail(_ item: CourseDiscoveryItem, token: String) async throws -> CourseDiscoveryDetail {
        let value: CourseDiscoveryDetail = try await request(publicPath(item), token: token)
        guard value.isValid, value.pack.id == item.id, value.pack.version == item.version,
              value.checksum == item.checksum, value.pack.stops.count == item.stopCount,
              value.pack.title == item.title, value.pack.author == item.author,
              value.pack.description == item.description else { throw IPhoneSessionError.invalidResponse }
        return value
    }

    func creator(_ creatorID: String, token: String) async throws -> CourseDiscoveryPublicCreator {
        guard validDiscoveryAccountID(creatorID) else { throw CourseRequestError.invalidInput }
        let value: CourseDiscoveryPublicCreator = try await request("courses/creators/" + creatorID, token: token)
        guard value.isValid, value.creator.id == creatorID else { throw IPhoneSessionError.invalidResponse }
        return value
    }

    func cover(_ item: CourseDiscoveryItem, token: String) async throws -> Data {
        guard item.isValid, item.hasCover else { throw CourseRequestError.invalidInput }
        let data = try await http.courseCover(item.id, version: item.version, token: token)
        guard data.starts(with: [0xFF, 0xD8, 0xFF]),
              let image = CGImageSourceCreateWithData(data as CFData, nil),
              CGImageSourceGetCount(image) == 1,
              let properties = CGImageSourceCopyPropertiesAtIndex(image, 0, nil) as? [CFString: Any],
              let width = properties[kCGImagePropertyPixelWidth] as? Int,
              let height = properties[kCGImagePropertyPixelHeight] as? Int,
              (1...960).contains(width), (1...960).contains(height) else { throw IPhoneSessionError.invalidResponse }
        return data
    }

    func setStarred(_ item: CourseDiscoveryItem, starred: Bool, token: String) async throws {
        struct Receipt: Decodable { let starred: Bool }
        let value: Receipt = try await request(versionPath("stars", item), method: starred ? "PUT" : "DELETE", payload: Data("{}".utf8), token: token)
        guard value.starred == starred else { throw IPhoneSessionError.invalidResponse }
    }

    func followCreator(_ item: CourseDiscoveryItem, token: String) async throws {
        guard item.canFollow else { throw CourseRequestError.invalidInput }
        struct Receipt: Decodable { let followId: String }
        let value: Receipt = try await request(versionPath("follows", item), method: "PUT", payload: Data("{}".utf8), token: token)
        guard validCourseFollowID(value.followId) else { throw IPhoneSessionError.invalidResponse }
    }

    func unfollowCreator(_ followID: String, token: String) async throws {
        guard validCourseFollowID(followID) else { throw CourseRequestError.invalidInput }
        struct Receipt: Decodable { let following: Bool }
        let value: Receipt = try await request("courses/follows/" + followID, method: "DELETE", payload: Data("{}".utf8), token: token)
        guard !value.following else { throw IPhoneSessionError.invalidResponse }
    }

    func setTagFollowed(_ tag: String, followed: Bool, token: String) async throws {
        guard normalizedDiscoveryTag(tag) == tag else { throw CourseRequestError.invalidInput }
        var component = URLComponents()
        component.path = tag
        let encoded = component.percentEncodedPath
        struct Receipt: Decodable { let following: Bool; let tag: String }
        let value: Receipt = try await request("courses/tag-follows/" + encoded, method: followed ? "PUT" : "DELETE", payload: Data("{}".utf8), token: token)
        guard value.following == followed, normalizedDiscoveryTag(value.tag) == value.tag,
              courseTagKey(value.tag) == courseTagKey(tag) else { throw IPhoneSessionError.invalidResponse }
    }

    func markRead(_ eventID: String, token: String) async throws {
        guard validCourseEventID(eventID) else { throw CourseRequestError.invalidInput }
        struct Receipt: Decodable { let read: Bool }
        let value: Receipt = try await request("courses/news/" + eventID + "/read", method: "PUT", payload: Data("{}".utf8), token: token)
        guard value.read else { throw IPhoneSessionError.invalidResponse }
    }

    func notInterested(_ item: CourseDiscoveryItem, token: String) async throws {
        struct Receipt: Decodable { let hidden: Bool }
        let value: Receipt = try await request(versionPath("hidden", item), method: "PUT", payload: Data("{}".utf8), token: token)
        guard value.hidden else { throw IPhoneSessionError.invalidResponse }
    }

    func report(_ item: CourseDiscoveryItem, reason: String, token: String) async throws {
        guard ["harmful", "privacy", "rights", "other"].contains(reason) else { throw CourseRequestError.invalidInput }
        struct Receipt: Decodable { let reportId: String; let state: String }
        let value: Receipt = try await request(publicPath(item) + "/reports", method: "POST",
            payload: JSONEncoder().encode(["reason": reason]), token: token, status: 202)
        guard value.state == "quarantined", value.reportId.range(of: #"\A[a-f0-9]{32}\z"#, options: .regularExpression) != nil else {
            throw IPhoneSessionError.invalidResponse
        }
    }

    func copy(_ item: CourseDiscoveryItem, token: String) async throws -> CourseDetail {
        let value: CourseDetail
        do {
            value = try await request(publicPath(item) + "/copy", method: "POST", payload: Data("{}".utf8), token: token, status: 201)
        } catch IPhoneSessionError.forbidden {
            throw CourseDiscoveryCopyError.permissionRequired
        }
        guard value.pack.isValid, value.pack.id != item.id, value.pack.version == 1,
              let receipt = value.remixDraftId, receipt.range(of: #"\A[a-f0-9]{32}\z"#, options: .regularExpression) != nil,
              let tags = value.tags, validDiscoveryTags(tags), tags == item.tags,
              value.hasCover == item.hasCover else { throw IPhoneSessionError.invalidResponse }
        return value
    }

    private func publicPath(_ item: CourseDiscoveryItem) throws -> String { try versionPath("public", item) }
    private func versionPath(_ kind: String, _ item: CourseDiscoveryItem) throws -> String {
        guard item.isValid else { throw CourseRequestError.invalidInput }
        return "courses/\(kind)/\(item.id)/versions/\(item.version)"
    }
    private func request<T: Decodable>(_ path: String, method: String = "GET", payload: Data? = nil,
                                       token: String, status: Int = 200) async throws -> T {
        let data = try await http.resource(path, method: method, payload: payload, token: token, status: status)
        do { return try JSONDecoder().decode(T.self, from: data) }
        catch { throw IPhoneSessionError.invalidResponse }
    }
}
