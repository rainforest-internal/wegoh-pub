package io.wegoh.app

import io.wegoh.app.ui.CarSection
import org.junit.Assert.*
import org.junit.Test

class CarSectionTest {
    @Test fun remotePageHasOnlyOverviewAndInlineRequests() {
        assertEquals(listOf("리모컨","차량 요청"),CarSection.entries.map {it.title})
    }

    @Test fun removedAndUnknownSavedSectionsOpenOverview() {
        for(name in listOf(null,"RECOMMENDATIONS","CAUTIONS","unknown",""))
            assertEquals(CarSection.OVERVIEW,CarSection.fromSaved(name))
    }

    @Test fun remainingSavedSectionsKeepTheirSelection() {
        assertEquals(CarSection.OVERVIEW,CarSection.fromSaved("OVERVIEW"))
        assertEquals(CarSection.COMMANDS,CarSection.fromSaved("COMMANDS"))
    }
}
