import Foundation
import Security

struct StoredIPhoneCredential: Equatable {
    let token: String
    let logoutPending: Bool
}

@MainActor
protocol IPhoneCredentialStoring: AnyObject {
    func load() throws -> StoredIPhoneCredential?
    func saveToken(_ token: String) throws
    func markLogoutPending() throws
    func clearToken() throws
}

@MainActor
final class IPhoneCredentialStore: IPhoneCredentialStoring {
    private let item: [CFString: Any]

    init(service: String = "io.wegoh.iphone.session", account: String = "accessToken") {
        item = [
            kSecClass: kSecClassGenericPassword,
            kSecAttrService: service,
            kSecAttrAccount: account,
            kSecAttrSynchronizable: false
        ]
    }

    func load() throws -> StoredIPhoneCredential? {
        var query = item
        query[kSecReturnData] = true
        query[kSecReturnAttributes] = true
        query[kSecMatchLimit] = kSecMatchLimitOne
        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess else { throw KeychainError.unavailable }
        guard let attributes = result as? [CFString: Any],
              let data = attributes[kSecValueData] as? Data,
              let token = String(data: data, encoding: .utf8), !token.isEmpty else {
            try clearToken()
            return nil
        }
        let marker = attributes[kSecAttrGeneric] as? Data ?? Data()
        return StoredIPhoneCredential(token: token, logoutPending: !marker.isEmpty && marker != Data([0]))
    }

    func saveToken(_ token: String) throws {
        let attributes: [CFString: Any] = [
            kSecValueData: Data(token.utf8),
            kSecAttrGeneric: Data([0]),
            kSecAttrAccessible: kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        ]
        let status = SecItemUpdate(item as CFDictionary, attributes as CFDictionary)
        if status == errSecItemNotFound {
            let newItem = item.merging(attributes) { _, new in new }
            guard SecItemAdd(newItem as CFDictionary, nil) == errSecSuccess else { throw KeychainError.unavailable }
        } else if status != errSecSuccess {
            throw KeychainError.unavailable
        }
    }

    func markLogoutPending() throws {
        let status = SecItemUpdate(item as CFDictionary, [kSecAttrGeneric: Data([1])] as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else { throw KeychainError.unavailable }
    }

    func clearToken() throws {
        let status = SecItemDelete(item as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else { throw KeychainError.unavailable }
    }

    private enum KeychainError: Error {
        case unavailable
    }
}
