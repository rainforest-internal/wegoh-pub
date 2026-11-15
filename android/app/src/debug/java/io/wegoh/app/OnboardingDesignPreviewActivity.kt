package io.wegoh.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import io.wegoh.app.ui.WegoCarTheme

class OnboardingDesignPreviewActivity: ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            var permissions by rememberSaveable {mutableStateOf(false)}
            WegoCarTheme {
                ConnectionEntry(fullScreen=true) {
                    if(!permissions)FirstRunWalkthrough(true,{hasWindowFocus()}) {permissions=true}
                    else FirstRunPermissionScreen(true,false,onRequest={finish()},onLater={finish()})
                }
            }
        }
    }
}
