package io.wegoh.app.ui

import org.junit.Assert.assertEquals
import org.junit.Test

class CarPopupButtonRoleTest {
    @Test
    fun confirmationStylesUseTheDarkPopupFillAndOthersTheLightCancelFill() {
        listOf(CarButtonStyle.FILLED,CarButtonStyle.DARK,CarButtonStyle.ON_INK,CarButtonStyle.DANGER).forEach {
            assertEquals(it.name,CarPopupButtonRole.CONFIRM,carPopupButtonRole(it))
        }
        listOf(CarButtonStyle.OUTLINE,CarButtonStyle.SOFT,CarButtonStyle.INK_OUTLINE,CarButtonStyle.DASHED,CarButtonStyle.TEXT).forEach {
            assertEquals(it.name,CarPopupButtonRole.CANCEL,carPopupButtonRole(it))
        }
    }
}
