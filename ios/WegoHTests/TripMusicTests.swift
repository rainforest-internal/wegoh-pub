import Foundation
import XCTest
@testable import WegoH

private final class TripMusicHTTPStub: URLProtocol {
    static var respond: ((URLRequest) throws -> (Int, Data))?
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func stopLoading() { }
    override func startLoading() {
        do {
            let (status, data) = try Self.respond!(request)
            let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: ["Content-Type": "application/json"])!
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data); client?.urlProtocolDidFinishLoading(self)
        } catch { client?.urlProtocol(self, didFailWithError: error) }
    }
}

@MainActor
final class TripMusicTests: XCTestCase {
    private let trip = String(repeating: "a", count: 32)
    private let actor = "team-" + String(repeating: "1", count: 40)
    private var page: IPhoneTripMusicPage { .init(tripId: trip, musicSharing: true, items: [], limit: 200, canAdd: true, canReorder: true, nowPlaying: []) }
    private func item(_ id: Character, by owner: String? = nil) -> IPhoneTripMusicPage.Item {
        .init(id: String(repeating: id, count: 32), title: "곡 \(id)", url: "https://open.spotify.com/playlist/sample",
              addedBy: .init(id: owner ?? actor, name: "샘플"), reviewState: "approved")
    }
    private var draft: TripMusicDraft { .init(title: " 합성 음악 ", url: "https://open.spotify.com/playlist/sample", platform: .spotify, rightsConfirmed: true, reviewConsent: false) }
    private var selection: TripMusicSavedSelection {
        .init(playlistId: String(repeating: "c", count: 32), playlistRevision: 3, trackId: String(repeating: "d", count: 32))
    }
    private var api: IPhoneTripMusicAPI {
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [TripMusicHTTPStub.self]
        return .init(configuration: config)
    }
    override func tearDown() { TripMusicHTTPStub.respond = nil; super.tearDown() }

    func testDraftRequiresRightsValidHTTPSAndMatchingPlatform() {
        XCTAssertFalse(TripMusicDraft().rightsConfirmed)
        XCTAssertFalse(TripMusicDraft().reviewConsent)
        XCTAssertTrue(draft.isValid)
        for invalid in [TripMusicDraft(title: "음악", url: "http://example.invalid", rightsConfirmed: true),
                        TripMusicDraft(title: "음악", url: draft.url, platform: .melon, rightsConfirmed: true),
                        TripMusicDraft(title: "음악", url: draft.url, rightsConfirmed: false)] { XCTAssertFalse(invalid.isValid) }
    }

    func testExactTripPOSTHasExplicitRightsAndReviewWithoutPlatformOrArtistFields() async throws {
        let expected = try JSONEncoder().encode(page)
        var calls = 0
        TripMusicHTTPStub.respond = { request in
            calls += 1
            XCTAssertEqual(request.url?.path, "/v1/iphone/trips/" + self.trip + "/music/playlist")
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer " + String(repeating: "F", count: 43))
            var data = request.httpBody ?? Data()
            if data.isEmpty {
                let stream = try XCTUnwrap(request.httpBodyStream); stream.open(); defer { stream.close() }
                var buffer = [UInt8](repeating: 0, count: 1024)
                while stream.hasBytesAvailable { let n = stream.read(&buffer, maxLength: buffer.count); if n <= 0 { break }; data.append(contentsOf: buffer.prefix(n)) }
            }
            let body = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
            XCTAssertEqual(Set(body.keys), ["title", "url", "rightsConfirmed", "reviewConsent"])
            XCTAssertEqual(body["title"] as? String, "합성 음악")
            XCTAssertEqual(body["reviewConsent"] as? Bool, false)
            return (201, expected)
        }
        let result = try await api.add(trip, draft: draft, token: String(repeating: "F", count: 43))
        XCTAssertEqual(result, page); XCTAssertEqual(calls, 1)
    }

    func testUnknownTransportAndMalformedSuccessNeverRetryAndDefinitiveRejectionsStayDistinct() async {
        for (status, data, definitive) in [(400, Data("{}".utf8), true), (403, Data("{}".utf8), true),
                                         (409, Data("{}".utf8), true), (503, Data("{}".utf8), false),
                                         (201, Data("{}".utf8), false)] {
            var calls = 0
            TripMusicHTTPStub.respond = { _ in calls += 1; return (status, data) }
            do { _ = try await api.add(trip, draft: draft, token: String(repeating: "F", count: 43)); XCTFail("Expected error") }
            catch { XCTAssertEqual(tripMusicFailureIsDefinitive(error), definitive) }
            XCTAssertEqual(calls, 1)
        }
        var calls = 0
        TripMusicHTTPStub.respond = { _ in calls += 1; throw URLError(.networkConnectionLost) }
        do { _ = try await api.add(trip, draft: draft, token: String(repeating: "F", count: 43)); XCTFail("Expected transport error") }
        catch { XCTAssertFalse(tripMusicFailureIsDefinitive(error)) }
        XCTAssertEqual(calls, 1)
        XCTAssertFalse(tripMusicFailureIsDefinitive(CancellationError()))
    }

    func testNowPlayingMustPointAtAVisibleItemOncePerMember() {
        var value = page
        value.items = [item("b"), item("c")]
        let driver = IPhoneTripMusicPage.Item.Person(id: "team-" + String(repeating: "2", count: 40), name: "운전자")
        value.nowPlaying = [.init(itemId: item("c").id, startedBy: driver, startedAt: "2026-11-14T03:00:00+00:00")]
        XCTAssertTrue(value.isValid); XCTAssertTrue(value.isPlaying(item("c"))); XCTAssertFalse(value.isPlaying(item("b")))
        value.nowPlaying[0].itemId = String(repeating: "f", count: 32)
        XCTAssertFalse(value.isValid)
        value.nowPlaying = Array(repeating: .init(itemId: item("b").id, startedBy: driver, startedAt: "2026-11-14T03:00:00+00:00"), count: 2)
        XCTAssertFalse(value.isValid)
    }

    func testMovePATCHAlwaysSendsAfterIdIncludingNull() async throws {
        let expected = try JSONEncoder().encode(page)
        var bodies: [[String: Any]] = []
        TripMusicHTTPStub.respond = { request in
            XCTAssertEqual(request.httpMethod, "PATCH")
            XCTAssertEqual(request.url?.path, "/v1/iphone/trips/" + self.trip + "/music/playlist/" + String(repeating: "b", count: 32) + "/position")
            var data = request.httpBody ?? Data()
            if data.isEmpty {
                let stream = try XCTUnwrap(request.httpBodyStream); stream.open(); defer { stream.close() }
                var buffer = [UInt8](repeating: 0, count: 1024)
                while stream.hasBytesAvailable { let n = stream.read(&buffer, maxLength: buffer.count); if n <= 0 { break }; data.append(contentsOf: buffer.prefix(n)) }
            }
            bodies.append(try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any]))
            return (200, expected)
        }
        let token = String(repeating: "F", count: 43), moved = String(repeating: "b", count: 32)
        _ = try await api.move(trip, itemID: moved, after: nil, token: token)
        _ = try await api.move(trip, itemID: moved, after: String(repeating: "c", count: 32), token: token)
        XCTAssertEqual(bodies.map { Set($0.keys) }, [["afterId"], ["afterId"]])
        XCTAssertTrue(bodies[0]["afterId"] is NSNull)
        XCTAssertEqual(bodies[1]["afterId"] as? String, String(repeating: "c", count: 32))
        do { _ = try await api.move(trip, itemID: moved, after: moved, token: token); XCTFail("Expected invalid input") }
        catch { if case .invalidInput? = error as? IPhoneResourceError {} else { XCTFail("Expected invalid input, got \(error)") } }
        XCTAssertEqual(bodies.count, 2)
    }

    func testSavedTrackPOSTSendsOnlySourceIdentifiersWithRightsAndReview() async throws {
        let expected = try JSONEncoder().encode(page)
        var calls = 0
        TripMusicHTTPStub.respond = { request in
            calls += 1
            XCTAssertEqual(request.url?.path, "/v1/iphone/trips/" + self.trip + "/music/saved-playlists")
            XCTAssertEqual(request.httpMethod, "POST")
            var data = request.httpBody ?? Data()
            if data.isEmpty {
                let stream = try XCTUnwrap(request.httpBodyStream); stream.open(); defer { stream.close() }
                var buffer = [UInt8](repeating: 0, count: 1024)
                while stream.hasBytesAvailable { let n = stream.read(&buffer, maxLength: buffer.count); if n <= 0 { break }; data.append(contentsOf: buffer.prefix(n)) }
            }
            let body = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
            XCTAssertEqual(Set(body.keys), ["playlistId", "playlistRevision", "trackId", "rightsConfirmed", "reviewConsent"])
            XCTAssertEqual(body["playlistRevision"] as? Int, 3)
            XCTAssertEqual(body["rightsConfirmed"] as? Bool, true); XCTAssertEqual(body["reviewConsent"] as? Bool, true)
            return (200, expected)
        }
        let token = String(repeating: "F", count: 43)
        let result = try await api.addSaved(trip, selection: selection, rightsConfirmed: true, token: token)
        XCTAssertEqual(result, page); XCTAssertEqual(calls, 1)
        for (value, rights) in [(selection, false), (TripMusicSavedSelection(playlistId: "x", playlistRevision: 3, trackId: selection.trackId), true),
                                (TripMusicSavedSelection(playlistId: selection.playlistId, playlistRevision: 0, trackId: selection.trackId), true)] {
            do { _ = try await api.addSaved(trip, selection: value, rightsConfirmed: rights, token: token); XCTFail("Expected invalid input") }
            catch { XCTAssertTrue(tripMusicFailureIsDefinitive(error)) }
        }
        XCTAssertEqual(calls, 1)
    }

    func testPrivateItemsFromOtherAccountsCannotBeDisplayed() {
        var value = page
        value.items = [.init(id: String(repeating: "b", count: 32), title: "음악", url: draft.url,
                             addedBy: .init(id: actor, name: "샘플"), reviewState: "private")]
        XCTAssertTrue(value.isValid); XCTAssertTrue(value.permitsDisplay(to: actor))
        XCTAssertFalse(value.permitsDisplay(to: "team-" + String(repeating: "2", count: 40)))
        value.items[0].reviewState = "approved"
        XCTAssertTrue(value.permitsDisplay(to: "team-" + String(repeating: "2", count: 40)))
    }
}

extension TripMusicTests {
    private func preparedStore() async throws -> (TripMusicStore, MusicStoreAPI, SessionManager) {
        let session = SessionManager(api: MusicAuth(), credentials: MusicCredential())
        await session.restore()
        let actor = self.actor, trip = self.trip
        let detail: [String: Any] = ["id": trip, "title": "합성 여행", "description": "합성", "state": "active", "revision": 1,
            "isOwner": true, "ownerId": actor, "myPermissions": ["invite": true, "edit": true],
            "members": [["id": actor, "name": "샘플", "state": "accepted", "isMe": true, "isOwner": true, "hasVehicle": false, "carId": NSNull(), "readiness": "needsCar"]],
            "cars": [], "unassigned": [["id": actor, "name": "샘플"]], "courses": [], "locationConsent": true]
        let data = try JSONSerialization.data(withJSONObject: detail)
        TripMusicHTTPStub.respond = { _ in (200, data) }
        let config = URLSessionConfiguration.ephemeral; config.protocolClasses = [TripMusicHTTPStub.self]
        let preparation = TripPreparationStore(tripID: trip, session: session, api: IPhoneTripAPI(configuration: config))
        await preparation.load()
        XCTAssertNotNil(preparation.detail)
        let api = MusicStoreAPI(page: page)
        return (TripMusicStore(preparation: preparation, api: api), api, session)
    }

    func testMoveDirectionsSendTheNeighborAndRespectReorderPermission() async throws {
        let (store, api, _) = try await preparedStore()
        api.value.items = [item("b"), item("c"), item("d")]
        await store.load()
        await store.move(item("d"), .up)
        await store.move(item("b"), .down)
        await store.move(item("c"), .top)
        await store.move(item("b"), .top)
        await store.move(item("d"), .down)
        XCTAssertEqual(api.moves.map(\.0), [item("d").id, item("b").id, item("c").id])
        XCTAssertEqual(api.moves.map(\.1), [item("b").id, item("c").id, nil])
        api.value.canReorder = false
        await store.load(); await store.move(item("d"), .top)
        XCTAssertEqual(api.moves.count, 3)
        api.value.canReorder = true; await store.load()
        api.moveFailure = IPhoneSessionError.forbidden
        await store.move(item("d"), .top)
        XCTAssertEqual(store.message, "DJ나 여행 만든 사람만 순서를 바꿀 수 있어요.")
        api.moveFailure = IPhoneSessionError.unavailable
        let loads = api.loads
        await store.move(item("d"), .top)
        XCTAssertEqual(api.loads, loads + 1)
        XCTAssertEqual(store.message, "순서를 바꾸지 못했어요. 지금 순서를 확인해 주세요.")
        XCTAssertNotNil(store.visiblePage)
    }

    func testUnknownAddRequiresSuccessfulExplicitReloadWithoutReplayingPOST() async throws {
        let (store, api, _) = try await preparedStore()
        await store.load(); store.draft = draft
        api.addFailure = IPhoneSessionError.invalidResponse
        await store.add(); await store.add()
        XCTAssertTrue(store.resultUnknown); XCTAssertEqual(api.adds, 1)
        XCTAssertEqual(store.draft, draft); XCTAssertNotNil(store.visiblePage)
        api.loadFailure = IPhoneResourceError.unavailable
        await store.load(); await store.add()
        XCTAssertTrue(store.resultUnknown); XCTAssertEqual(api.adds, 1)
        api.loadFailure = nil
        await store.load()
        XCTAssertFalse(store.resultUnknown); XCTAssertEqual(api.adds, 1)
        XCTAssertTrue(store.canAdd)
    }

    func testSavedTrackNeedsSelectionAndRightsAndMarksTracksIAlreadyAdded() async throws {
        let (store, api, _) = try await preparedStore()
        api.library = [.init(id: selection.playlistId, name: "드라이브 모음", tracks: [
            .init(id: selection.trackId, title: "저장 곡", url: "https://open.spotify.com/track/sample"),
            .init(id: String(repeating: "e", count: 32), title: "추가한 곡", url: draft.url)], revision: 3)]
        api.value.items = [.init(id: String(repeating: "b", count: 32), title: "추가한 곡", url: draft.url,
                                 addedBy: .init(id: actor, name: "샘플"), reviewState: "approved")]
        await store.load(); await store.loadLibrary()
        XCTAssertEqual(store.savedChoices.map(\.alreadyAdded), [false, true])
        XCTAssertEqual(store.savedChoices.first?.platform, .spotify)
        XCTAssertFalse(store.canAddSaved)
        store.savedSelection = store.savedChoices[1].selection; store.savedRightsConfirmed = true
        XCTAssertFalse(store.canAddSaved)
        store.savedSelection = selection
        XCTAssertTrue(store.canAddSaved)
        await store.addSaved()
        XCTAssertEqual(api.savedAdds, [selection]); XCTAssertNil(store.savedSelection); XCTAssertFalse(store.savedRightsConfirmed)
        XCTAssertTrue(store.message?.contains("공유 검토") == true)
    }

    func testLostSavedTrackResponseStaysRetryableBecauseServerKeepsOneItem() async throws {
        let (store, api, _) = try await preparedStore()
        api.library = [.init(id: selection.playlistId, name: "저장 곡", tracks: [
            .init(id: selection.trackId, title: "저장 곡", url: "https://open.spotify.com/track/sample")], revision: 3)]
        await store.load(); await store.loadLibrary()
        store.savedSelection = selection; store.savedRightsConfirmed = true
        api.addFailure = IPhoneSessionError.invalidResponse
        await store.addSaved()
        XCTAssertFalse(store.resultUnknown); XCTAssertTrue(store.canAddSaved)
        api.addFailure = IPhoneResourceError.conflict
        await store.addSaved()
        XCTAssertNil(store.savedSelection); XCTAssertEqual(api.libraryReads, 2)
        XCTAssertEqual(api.savedAdds.count, 2)
    }

    func testLostSharingOffResponseBlocksAddingUntilServerStateIsRead() async throws {
        let (store, api, _) = try await preparedStore()
        await store.load(); store.draft = draft
        api.sharingFailure = IPhoneSessionError.unavailable
        await store.setSharing(false)
        XCTAssertTrue(store.resultUnknown); XCTAssertFalse(store.canAdd)
        XCTAssertTrue(store.message?.contains("결과를 확인하지 못했어요") == true)
        await store.add(); XCTAssertEqual(api.adds, 0)
        api.value.musicSharing = false
        await store.load()
        XCTAssertFalse(store.resultUnknown); XCTAssertFalse(store.canAdd)
        XCTAssertEqual(store.visiblePage?.musicSharing, false)
    }

    func testAccessRevocationClearsPageForAllOperationsAndLateLogoutReplyIsDiscarded() async throws {
        let (store, api, session) = try await preparedStore()
        await store.load(); store.draft = draft
        api.addFailure = IPhoneSessionError.forbidden
        await store.add(); XCTAssertNil(store.visiblePage)
        await store.load()
        api.sharingFailure = IPhoneResourceError.missing
        await store.setSharing(false); XCTAssertNil(store.visiblePage)
        await store.load()
        api.pauseRead = true
        let loading = Task { await store.load() }
        while api.readContinuation == nil { await Task.yield() }
        await session.signOut()
        api.readContinuation?.resume(returning: api.value)
        await loading.value
        XCTAssertNil(store.visiblePage)
        XCTAssertFalse(store.canAdd)
    }
}

@MainActor
private final class MusicStoreAPI: IPhoneTripMusicServing {
    var value: IPhoneTripMusicPage
    var addFailure: Error?, sharingFailure: Error?, loadFailure: Error?, moveFailure: Error?
    var adds = 0, loads = 0, pauseRead = false, libraryReads = 0
    var moves: [(String, String?)] = []
    var library: [AccountMusicPlaylist] = []
    var savedAdds: [TripMusicSavedSelection] = []
    var readContinuation: CheckedContinuation<IPhoneTripMusicPage, Never>?
    init(page: IPhoneTripMusicPage) { value = page }
    func load(_ tripID: String, token: String) async throws -> IPhoneTripMusicPage {
        loads += 1
        if let loadFailure { throw loadFailure }
        if pauseRead { return await withCheckedContinuation { readContinuation = $0 } }
        return value
    }
    func sharing(_ tripID: String, enabled: Bool, token: String) async throws -> IPhoneTripMusicPage {
        if let sharingFailure { throw sharingFailure }
        value.musicSharing = enabled; return value
    }
    func add(_ tripID: String, draft: TripMusicDraft, token: String) async throws -> IPhoneTripMusicPage {
        adds += 1
        if let addFailure { throw addFailure }
        return value
    }
    func move(_ tripID: String, itemID: String, after afterID: String?, token: String) async throws -> IPhoneTripMusicPage {
        if let moveFailure { throw moveFailure }
        moves.append((itemID, afterID)); return value
    }
    func library(token: String) async throws -> [AccountMusicPlaylist] { libraryReads += 1; return library }
    func addSaved(_ tripID: String, selection: TripMusicSavedSelection, rightsConfirmed: Bool, token: String) async throws -> IPhoneTripMusicPage {
        savedAdds.append(selection)
        if let addFailure { throw addFailure }
        return value
    }
}

private final class MusicAuth: IPhoneSessionServing {
    func restore(token: String) async throws -> AccountSession {
        .init(accountID: "team-" + String(repeating: "1", count: 40), displayName: "샘플", expiresAt: .now.addingTimeInterval(3600), scopes: ["account:read", "trips:read", "trips:manage"])
    }
    func logout(token: String) async throws { }
    func beginLogin() async throws -> IPhoneLoginAttempt { throw IPhoneSessionError.unavailable }
    func exchange(_ attempt: IPhoneLoginAttempt, callbackURL: URL) async throws -> IPhoneSessionReceipt { throw IPhoneSessionError.unavailable }
    func cancel(_ attempt: IPhoneLoginAttempt) async throws { }
}

@MainActor
private final class MusicCredential: IPhoneCredentialStoring {
    var value: StoredIPhoneCredential? = .init(token: String(repeating: "F", count: 43), logoutPending: false)
    func load() throws -> StoredIPhoneCredential? { value }
    func saveToken(_ token: String) throws { value = .init(token: token, logoutPending: false) }
    func markLogoutPending() throws { value = nil }
    func clearToken() throws { value = nil }
}
