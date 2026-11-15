enum VehicleQR {
    static func inputCode(_ input: String) -> String? {
        guard input.utf8.count <= 64 else { return nil }
        let value = input.uppercased().filter { !$0.isWhitespace && $0 != "-" }
        let alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789".utf8
        guard value.utf8.count == 8, value.utf8.allSatisfy(alphabet.contains) else { return nil }
        return value
    }

    static func comparisonCode(in payload: String) -> String? {
        let prefix = "https://wegoh.devforest.io/enroll.html?user_code="
        guard payload.utf8.count == prefix.utf8.count + 8, payload.hasPrefix(prefix) else { return nil }
        let code = payload.suffix(8)
        let alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789".utf8
        guard code.utf8.allSatisfy(alphabet.contains) else { return nil }
        return String(code)
    }
}
