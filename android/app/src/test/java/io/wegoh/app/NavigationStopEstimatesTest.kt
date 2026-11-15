package io.wegoh.app

import org.junit.Assert.assertEquals
import org.junit.Test

class NavigationStopEstimatesTest {
    private val overview=NavigationOverview("pack@1",listOf(NavigationLeg("a",60,1000),NavigationLeg("b",180,3000)),0,
        listOf(NavigationTraffic(1500.0,2500.0,"HEAVY")),0)

    @Test fun beforeGuidanceThereIsNoPerStopPlaceholder() {
        assertEquals(emptyList<String>(),(null as NavigationOverview?).stopEstimates("a",1000))
    }

    @Test fun onlyKnownValuesAreShown() {
        assertEquals(listOf("약 1분"),overview.stopEstimates("a",1000))
        assertEquals(listOf("약 2분","정체 포함"),overview.stopEstimates("b",1000))
        assertEquals(emptyList<String>(),overview.stopEstimates("missing",1000))
        assertEquals(emptyList<String>(),overview.stopEstimates("b",92000))
    }
}
