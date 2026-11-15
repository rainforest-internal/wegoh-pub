package io.wegoh.app

/** Real debug-loopback report journey; storage is isolated and no GPS is injected. */
@Suppress("DEPRECATION")
class CourseReportingTests: android.test.InstrumentationTestCase() {
    fun testVerifiedDownloadReportsAndQuarantinesWithoutLocation() {
        PublishedJourneyTests().also {it.injectInstrumentation(instrumentation)}.runPublishedJourney(reportOnly=true)
    }
}
