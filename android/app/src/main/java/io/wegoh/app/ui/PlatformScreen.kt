package io.wegoh.app.ui

import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import io.wegoh.app.WegoState

@Suppress("UNUSED_PARAMETER")
@Composable
fun PlatformScreen(state: WegoState,initialRoute: String="trips",onRootBack: ()->Unit={},onVehicleConnection: ()->Unit={},
    vehicleConnection: @Composable ()->Unit={},onProfileLoad: ()->Unit={},onProfileRefresh: ()->Unit=onProfileLoad,
    journeys: @Composable (onExit: ()->Unit)->Unit) {
    val route=when(initialRoute){"journeys","courses"->"home";"friends"->"profile";else->initialRoute}
    CompositionLocalProvider(LocalVehicleLandingPage provides route) {journeys(onRootBack)}
}
