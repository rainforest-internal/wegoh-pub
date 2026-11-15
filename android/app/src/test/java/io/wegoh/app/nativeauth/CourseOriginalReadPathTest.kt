package io.wegoh.app.nativeauth

import org.junit.Assert.*
import org.junit.Test

class CourseOriginalReadPathTest {
    @Test fun originalsUseExactOwnerPathAndPublicDownloadRemainsSeparate() {
        assertEquals("/v1/studio/packs/coast_1/versions/2147483647",
            NativeApiClient.packVersionPath("coast_1",Int.MAX_VALUE,original=true))
        assertEquals("/v1/packs/coast_1/versions/1",NativeApiClient.packVersionPath("coast_1",1))
        NativeApiClient.requireReadPath("/v1/studio/packs/"+"a".repeat(80)+"/versions/1")
    }

    @Test fun originalPathsRejectInvalidIdsVersionsAndManagementActions() {
        val base="/v1/studio/packs/a/versions/1"
        val denied=listOf(base+"/",base+"/reuse-permission",base+"/remix-source",base+"?all=1",base+"#fragment",
            "/v1/studio/packs/A/versions/1","/v1/studio/packs/_a/versions/1",
            "/v1/studio/packs/"+"a".repeat(81)+"/versions/1",
            "/v1/studio/packs/a%2fb/versions/1","/v1/studio/packs/a/../b/versions/1")+
            listOf("0","01","-1","1.0","2147483648","9999999999").map {"/v1/studio/packs/a/versions/$it"}
        for(path in denied) {
            try {NativeApiClient.requireReadPath(path);fail("Unregistered original path accepted")}
            catch(expected: IllegalArgumentException) {assertEquals("NATIVE_READ_PATH_NOT_ALLOWED",expected.message)}
        }
    }
}
