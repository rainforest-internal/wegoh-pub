protocol APIKeyConfiguration {
    static var mapAPIKey: String? { get }
}

extension APIKeyConfiguration {
    static var mapAPIKey: String? { nil }
}

enum APIKeys: APIKeyConfiguration {}
