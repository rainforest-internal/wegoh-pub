package io.wegoh.app.ui

import org.junit.Assert.assertEquals
import org.junit.Test

class VehicleCourseFeedColumnsTest {
    private val card=CarTokens.CourseCardMinWidth
    private val gap=CarTokens.Gap

    @Test fun matchesAdaptiveGridColumnRule() {
        assertEquals(1,vehicleCourseFeedColumns(card,narrow=false))
        assertEquals(1,vehicleCourseFeedColumns(card*2+gap-CarTokens.BorderWidth,narrow=false))
        assertEquals(2,vehicleCourseFeedColumns(card*2+gap,narrow=false))
        assertEquals(3,vehicleCourseFeedColumns(card*3+gap*2,narrow=false))
    }

    @Test fun narrowAndTinyWidthsKeepOneColumn() {
        assertEquals(1,vehicleCourseFeedColumns(card*3+gap*2,narrow=true))
        assertEquals(1,vehicleCourseFeedColumns(CarTokens.Gap,narrow=false))
    }
}
