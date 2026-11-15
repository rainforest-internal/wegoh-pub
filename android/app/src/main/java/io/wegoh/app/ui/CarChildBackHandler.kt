package io.wegoh.app.ui

import androidx.activity.compose.BackHandler
import androidx.compose.runtime.*

internal class CarChildBackState {
    var action by mutableStateOf<(() -> Unit)?>(null)
}

internal val LocalCarChildBackState=staticCompositionLocalOf<CarChildBackState?> {null}

@Composable
fun CarChildBackHandler(enabled: Boolean,onBack: ()->Unit) {
    val owner=LocalCarChildBackState.current
    val current by rememberUpdatedState(onBack)
    DisposableEffect(owner,enabled) {
        val action={current()}
        if(enabled && owner!=null)owner.action=action
        onDispose {if(owner?.action===action)owner.action=null}
    }
    BackHandler(enabled=enabled && owner==null) {current()}
}
