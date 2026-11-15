package io.wegoh.app.nativeauth

import org.junit.Assert.*
import org.junit.Test

class CourseDiscoveryReadPathTest {
    @Test fun nativeLibraryAndPublicDetailsUseOnlyTheirReadOnlyPaths() {
        NativeApiClient.requireReadPath("/v1/native/courses/library")
        assertEquals("/v1/native/courses/public/coast_1/versions/2147483647",
            NativeApiClient.publicCoursePath("coast_1",Int.MAX_VALUE))
    }
    @Test fun catalogueReadsDoNotExposeManagementOrCredentialBearingQueries() {
        val invalid=listOf("/v1/studio/course-library","/v1/native/courses/library?token=secret",
            "/v1/native/courses/library?tag=바다","/v1/native/courses/library/",
            "/v1/native/courses/follows","/v1/native/courses/public/A/versions/1",
            "/v1/native/courses/public/a/versions/0","/v1/native/courses/public/a/versions/01",
            "/v1/native/courses/public/a/versions/2147483648","/v1/native/courses/public/a/versions/1/stars")
        invalid.forEach {path->assertTrue("Rejected $path",runCatching {NativeApiClient.requireReadPath(path)}.isFailure)}
    }
}
