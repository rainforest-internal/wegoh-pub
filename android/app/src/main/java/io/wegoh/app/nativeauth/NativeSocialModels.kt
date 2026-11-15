package io.wegoh.app.nativeauth

import java.time.Instant
import java.util.Collections

/** Current server projections; none of these values is an authority or a credential. */
class SocialPerson internal constructor(val id: String, val name: String?) {
    override fun toString() = "SocialPerson(redacted)"
}
class SocialFriendRequest internal constructor(val person: SocialPerson,val direction: Direction) {
    enum class Direction { INCOMING, OUTGOING }
    override fun toString() = "SocialFriendRequest(redacted)"
}
class SocialBlock internal constructor(val person: SocialPerson,val available: Boolean) {
    override fun toString() = "SocialBlock(redacted)"
}
class SocialReview internal constructor(val kind: String,val state: State,val requested: Boolean) {
    enum class State { PRIVATE, QUARANTINED, APPROVED, REJECTED }
    override fun toString() = "SocialReview(redacted)"
}
class SocialCourse internal constructor(val id: String,val version: Int,val title: String) {
    override fun toString() = "SocialCourse(redacted)"
}
class SocialRoomSummary internal constructor(val id: String,val name: String,val ownerId: String,
    val courseId: String?,val courseVersion: Int?,val expiresAt: Instant,val memberCount: Int,val review: SocialReview) {
    override fun toString() = "SocialRoomSummary(redacted)"
}
class SocialOverview internal constructor(people: List<SocialPerson>,friends: List<SocialPerson>,
    requests: List<SocialFriendRequest>,blocks: List<SocialBlock>,rooms: List<SocialRoomSummary>,
    val friendsAvailable: Boolean,val roomsAvailable: Boolean,val historyAvailable: Boolean,val friendsReadOnly: Boolean) {
    val people=immutableSocialList(people)
    val friends=immutableSocialList(friends)
    val requests=immutableSocialList(requests)
    val blocks=immutableSocialList(blocks)
    val rooms=immutableSocialList(rooms)
    override fun toString() = "SocialOverview(redacted)"
}
enum class SocialRole { MEMBER, DJ, REST, FOOD }
enum class SocialPreference { BALANCED, COUNTRY_ROADS, SHORT_DISTANCE, SHORT_TIME }
enum class SocialSignalKind(internal val wire: String) {
    RESTROOM("restroom"), SMOKING("smoking"), NURSING("nursing"), DROWSY("drowsy"),
    REST("rest"), ARRIVED("arrived"), JOIN("join")
}
class SocialMember internal constructor(val person: SocialPerson,val role: SocialRole) {
    override fun toString() = "SocialMember(redacted)"
}
/** A manually selected place in a shared signal, never an automatic vehicle location. */
class SocialSelectedPlace internal constructor(val name: String,val latitude: Double,val longitude: Double) {
    override fun toString() = "SocialSelectedPlace(redacted)"
}
class SocialSignal internal constructor(val id: String,val kind: SocialSignalKind,val accountId: String,
    val createdAt: Instant,val destination: SocialSelectedPlace?,val review: SocialReview?,
    val agree: Int,val pass: Int,val myVote: Vote?) {
    enum class Vote { AGREE, PASS }
    override fun toString() = "SocialSignal(redacted)"
}
class SocialRoom internal constructor(val id: String,val name: String,val ownerId: String,
    val courseId: String?,val courseVersion: Int?,val preference: SocialPreference,val role: SocialRole,
    val expiresAt: Instant,val serverNow: Instant,val expiresInSeconds: Double,val course: SocialCourse?,
    val review: SocialReview,val readOnly: Boolean,members: List<SocialMember>,signals: List<SocialSignal>) {
    val members=immutableSocialList(members)
    val signals=immutableSocialList(signals)
    override fun toString() = "SocialRoom(redacted)"
}
class SocialHistorySummary internal constructor(val id: String,val title: String,val ownerId: String,
    val ownerName: String?,val own: Boolean,val createdAt: Instant,val updatedAt: Instant,
    val startedAt: Instant,val endedAt: Instant?,val courseId: String?,val courseVersion: Int?,
    val revision: Int,val review: SocialReview,val visitCount: Int,val tracePointCount: Int) {
    override fun toString() = "SocialHistorySummary(redacted)"
}
/** Only a validated server cursor. Never a path, token or caller-provided query. */
class SocialHistoryCursor internal constructor(internal val encoded: String) {
    override fun toString() = "SocialHistoryCursor(redacted)"
}
class SocialMusicTrack internal constructor(val id: String,val title: String,val url: String) {
    override fun toString() = "SocialMusicTrack(redacted)"
}
class SocialMusicSelection internal constructor(val id: String,val name: String,val currentTrackId: String,
    tracks: List<SocialMusicTrack>,val review: SocialReview) {
    val tracks=immutableSocialList(tracks)
    override fun toString() = "SocialMusicSelection(redacted)"
}
class SocialRoomMusic internal constructor(val revision: Int,val selection: SocialMusicSelection?) {
    override fun toString() = "SocialRoomMusic(redacted)"
}
class SocialHistorySource internal constructor(val kind: String,val actorId: String,val receivedAt: Instant) {
    override fun toString() = "SocialHistorySource(redacted)"
}
class SocialHistoryVisit internal constructor(val id: String,val place: SocialSelectedPlace,val visitedAt: Instant,
    val review: String,val rating: Int?,val source: SocialHistorySource) {
    override fun toString() = "SocialHistoryVisit(redacted)"
}
class SocialHistoryPoint internal constructor(val latitude: Double,val longitude: Double,val capturedAt: Instant,val accuracyMeters: Double?) {
    override fun toString() = "SocialHistoryPoint(redacted)"
}
class SocialHistoryTrace internal constructor(val id: String,val streamId: String,val label: String,
    points: List<SocialHistoryPoint>,val source: SocialHistorySource) {
    val points=immutableSocialList(points)
    override fun toString() = "SocialHistoryTrace(redacted)"
}
class SocialHistoryDetail internal constructor(val summary: SocialHistorySummary,visits: List<SocialHistoryVisit>,
    traces: List<SocialHistoryTrace>,val source: SocialHistorySource,val course: SocialCourse?) {
    val visits=immutableSocialList(visits)
    val traces=immutableSocialList(traces)
    override fun toString() = "SocialHistoryDetail(redacted)"
}
class SocialHistoryPage internal constructor(history: List<SocialHistorySummary>,val nextCursor: SocialHistoryCursor?,
    val readOnly: Boolean,val traceIngestAvailable: Boolean) {
    val history=immutableSocialList(history)
    override fun toString() = "SocialHistoryPage(redacted)"
}
/** A server accepted state signal; not a physical arrival or vehicle-action ACK. */
class SocialSignalReceipt internal constructor(val id: String) {
    override fun toString() = "SocialSignalReceipt(redacted)"
}
class NativeSocialFailure internal constructor(val kind: Kind,val httpStatus: Int?=null,
    val reason: Reason?=null,val mayHaveExecuted: Boolean=false,val retryAfterSeconds: Int?=null,
    val serverErrorCode: String?=null,
    /** Method and path template of the failing exchange, identifiers masked; diagnostics only. */
    internal val requestTemplate: String?=null):
    IllegalStateException("NATIVE_SOCIAL_"+kind.name) {
    enum class Kind { CONSENT_REQUIRED, AUTHORIZATION_REQUIRED, FORBIDDEN, NOT_FOUND, CONFLICT,
        TOO_LARGE, RATE_LIMITED, UNAVAILABLE, INVALID_RESPONSE, STALE, CLOSED }
    enum class Reason { REVISION_CHANGED }
    override fun toString() = "NativeSocialFailure("+kind.name+")"
}
internal fun <T> immutableSocialList(values: List<T>): List<T> = Collections.unmodifiableList(values.toList())
