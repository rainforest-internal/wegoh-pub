package io.wegoh.app

import androidx.compose.runtime.Composable
import io.wegoh.app.ui.WegoVehicleScreen

/** Unpaired device courses expose local execution only; account actions never call account APIs. */
@Composable
internal fun LocalCourseScreen(state: WegoState,onSelect: (String)->Unit,onImport: ()->Unit,
    onStart: ()->Unit,onStop: ()->Unit,onNavigate: ()->Unit,onReset: ()->Unit,
    onBack: ()->Unit,onSuspendConsent: ()->Unit,onWithdrawAndDelete: ()->Unit,
    onSystemSettings: ()->Unit,onLegalDocument: (String)->Unit) {
    WegoVehicleScreen(state,onSelect,onImport,onStart,onStop,onNavigate,onReset,
        onBrowse={},onDownload={},onShareVisits={},onRootBack=onBack,onVehicleConnection=onBack,
        accountFeatures=false,onSuspendConsent=onSuspendConsent,onWithdrawAndDelete=onWithdrawAndDelete,
        onSystemSettings=onSystemSettings,onLegalDocument=onLegalDocument)
}
