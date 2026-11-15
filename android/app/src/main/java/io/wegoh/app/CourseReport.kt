package io.wegoh.app

/** Public content identity only; no vehicle/person/location identity is included. */
data class VerifiedPackOrigin(val id: String,val version: Int,val checksum: String) {
    val key get()="$id@$version"
}
enum class CourseReportReason(val wire: String,val label: String) {
    HARMFUL("harmful","유해 콘텐츠"),PRIVACY("privacy","개인정보"),RIGHTS("rights","권리 침해"),OTHER("other","기타")
}
enum class CourseReportOutcome { ACCEPTED, FAILED }
