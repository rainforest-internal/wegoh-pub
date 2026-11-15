package io.wegoh.app

import android.content.Context
import android.content.SharedPreferences
import androidx.compose.runtime.*
import io.wegoh.app.nativeauth.CommandReceiver
import io.wegoh.app.nativeauth.VehicleConnection
import java.io.Closeable

internal class VehicleReceiverSettings(
    private val preferences: SharedPreferences,
    private val session: () -> Long?,
    private val read: ((Result<CommandReceiver>) -> Unit) -> Unit,
    private val write: (CommandReceiver, Boolean, (Result<CommandReceiver>) -> Unit) -> Unit,
    private val runReceiver: (Boolean) -> Unit
) {
    private var epoch: Long? = null
    private var generation = 0L
    private var remote by mutableStateOf<CommandReceiver?>(null)
    private var local by mutableStateOf(preferences.getBoolean("enabled", true))
    var busy by mutableStateOf(false)
        private set
    var notice by mutableStateOf<String?>(null)
        private set
    var retry by mutableStateOf(false)
        private set
    val deviceId get() = remote?.deviceId?.takeIf { epoch != null && epoch == session() }
    val enabled get() = local && remote?.enabled == true
    val canToggle get() = remote != null && !busy

    fun connectionChanged() {
        if (epoch != session()) refresh()
    }

    fun refresh() {
        val current = session()
        if (epoch != current) {
            generation++
            epoch = current
            remote = null
            busy = false
            retry = false
            runReceiver(false)
        }
        if (busy) return
        if (current == null) {
            notice = "차량 연결 후 리모컨 수신을 설정하세요"
            return
        }
        load(++generation, reconcileStop = true)
    }

    private fun load(token: Long, reconcileStop: Boolean, failedEnable: Boolean = false, done: () -> Unit = {}) {
        busy = true
        retry = false
        notice = "리모컨 수신 확인 중"
        read { result ->
            if (!current(token)) { done(); return@read }
            result.fold(onSuccess = { state ->
                // 수신 선택은 연결(grant)마다 따로다. 다른 grant로 새로 연결되면 이전 연결(로그아웃 포함)의
                // 끔을 물려받지 않고 기본값(켜짐)으로 되돌린다. 같은 grant(앱 재시작 등)는 고른 값을 지킨다.
                val known = preferences.getString(GRANT_KEY, null)
                val newConnection = known != null && known != state.grantId
                if (known != state.grantId) preferences.edit().putString(GRANT_KEY, state.grantId).apply()
                if (newConnection) persistLocalEnabled(true)
                remote = state
                if (newConnection && !state.enabled) {
                    save(token, state, true, done)
                } else if (!local && state.enabled && reconcileStop) {
                    save(token, state, false, done)
                } else {
                    busy = false
                    retry = !local && state.enabled
                    notice = when {
                        failedEnable -> "리모컨 수신을 켜지 못했어요. 다시 켜 주세요"
                        retry -> "수신은 꺼졌지만 설정을 저장하지 못했어요"
                        else -> null
                    }
                    runReceiver(enabled)
                    done()
                }
            }, onFailure = { failed(); done() })
        }
    }

    fun setEnabled(value: Boolean) {
        if (busy || epoch == null || epoch != session()) return
        val state = remote ?: return
        if (value == enabled) return
        persistLocalEnabled(false)
        if (!value) runReceiver(false)
        save(++generation, state, value)
    }

    private fun save(token: Long, previous: CommandReceiver, value: Boolean, done: () -> Unit = {}) {
        busy = true
        retry = false
        notice = "리모컨 수신 설정 저장 중"
        write(previous, value) { result ->
            if (!current(token)) { done(); return@write }
            val saved = result.getOrNull()
            if (saved == null) {
                load(token, reconcileStop = false, failedEnable = value, done = done)
                return@write
            }
            remote = saved
            persistLocalEnabled(value)
            busy = false
            notice = null
            runReceiver(enabled)
            done()
        }
    }

    fun stopFromNotification(lease: Closeable) {
        stopLocally()
        epoch = session()
        remote = null
        if (epoch == null) {
            lease.close()
        } else {
            load(generation, reconcileStop = true, done = lease::close)
        }
    }

    fun stopLocally() {
        generation++
        busy = false
        persistLocalEnabled(false)
        runReceiver(false)
    }

    private fun current(token: Long) = generation == token && epoch != null && epoch == session()

    private fun persistLocalEnabled(value: Boolean) {
        local = value
        preferences.edit().putBoolean("enabled", value).apply()
    }

    private fun failed() {
        busy = false
        retry = true
        notice = if (local) "리모컨 수신 상태를 확인하지 못했어요" else "수신이 중지됐어요. 차량 연결을 확인해 주세요"
    }

    companion object {
        private const val GRANT_KEY = "grantId"
        fun forVehicle(app: WegoApplication): VehicleReceiverSettings {
            val connection = app.controller.vehicleAccountConnection ?: app.vehicleConnection
            return VehicleReceiverSettings(
                app.getSharedPreferences(VehicleAppDependencies.preferenceName("climate_receiver"), Context.MODE_PRIVATE),
                { connection.dataEpoch().takeIf {
                    connection.status().stage == VehicleConnection.Stage.CONNECTED ||
                        connection.status().stage == VehicleConnection.Stage.CHECKING && connection.verifiedDataBoundary() != null
                } },
                connection::readCommandReceiver,
                connection::setCommandReceiver,
                { enabled -> VehicleClimateService.runReceiver(app, enabled) }
            )
        }
    }
}

@Composable
internal fun rememberVehicleReceiverSettings(context: Context): VehicleReceiverSettings {
    val app = context.applicationContext as WegoApplication
    val connection = app.controller.vehicleAccountConnection ?: app.vehicleConnection
    val settings = app.receiverSettings
    DisposableEffect(settings, connection) {
        settings.refresh()
        val observation = connection.observe { settings.connectionChanged() }
        onDispose { observation.close() }
    }
    return settings
}
