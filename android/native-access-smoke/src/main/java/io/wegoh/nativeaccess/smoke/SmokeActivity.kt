package io.wegoh.nativeaccess.smoke

import android.app.Activity
import android.os.Bundle
import android.widget.TextView
import io.wegoh.app.nativeauth.VehicleConnection
import io.wegoh.app.nativeauth.VehicleEventsListener
import io.wegoh.app.nativeauth.VehicleEvent

/** Isolated AAR consumer; no CarUx approval/network/real account is simulated. */
class SmokeActivity : Activity() {
    private lateinit var connection: VehicleConnection
    private var observation: java.io.Closeable? = null
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val text=TextView(this).apply { text="SDK loading";textSize=24f;setPadding(32,32,32,32) };setContentView(text)
        val isolatedDir=java.io.File(cacheDir,"sdk-smoke-"+java.util.UUID.randomUUID().toString()).apply {check(mkdirs())}
        val isolated=object: android.content.ContextWrapper(applicationContext) {
            override fun getApplicationContext(): android.content.Context=this
            override fun getNoBackupFilesDir()=isolatedDir
        }
        connection=VehicleConnection(isolated)
        // A real host must feed actual Pleos CarUx; unknown remains fail-closed.
        connection.setSetupAllowed(false)
        var blockedWss=false;var guardedReads=0
        fun render(){text.text="SDK "+connection.status().stage.name+(if(blockedWss)" / WSS guarded" else "")+(if(guardedReads==6)" / reads guarded" else "")}
        // Resolve actual AAR/default connector + documented runtime dependencies.
        Class.forName("io.wegoh.app.nativeauth.NativeEvents")
        Class.forName("okhttp3.OkHttpClient")
        Class.forName("kotlin.jvm.internal.Intrinsics")
        var attempted=false
        observation=connection.observe {state ->
            render()
            if(state.stage in setOf(VehicleConnection.Stage.SETUP_BLOCKED, VehicleConnection.Stage.LOCKED, VehicleConnection.Stage.RECOVERY_REQUIRED) && !attempted) {
                attempted=true
                connection.readPublicPacks {check(it.isFailure);guardedReads++;render()}
                connection.readPackVersion("sample",1) {check(it.isFailure);guardedReads++;render()}
                connection.readPlaylist("a".repeat(32)) {check(it.isFailure);guardedReads++;render()}
                connection.readAccountDisplayName {check(it.isFailure);guardedReads++;render()}
                connection.readPermissions {check(it.isFailure);guardedReads++;render()}
                connection.readFunctionalPermissions {check(it.isFailure);guardedReads++;render()}
                connection.connectEvents(object: VehicleEventsListener {
                    override fun onEvent(event: VehicleEvent){error("Unapproved smoke must never receive events")}
                }) {result->check(result.isFailure);blockedWss=true;render()}
            }
        }
        connection.setForeground(true)
    }
    override fun onPause() {connection.setForeground(false);super.onPause()}
    override fun onDestroy() {observation?.close();connection.close();super.onDestroy()}
}
