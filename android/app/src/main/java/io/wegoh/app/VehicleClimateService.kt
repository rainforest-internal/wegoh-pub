package io.wegoh.app

import io.wegoh.app.nativeauth.WegoLog
import android.app.*
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Handler
import android.os.Binder
import android.os.IBinder
import android.os.Looper
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue

class VehicleClimateService: Service() {
    private val handler=Handler(Looper.getMainLooper())
    private var host: VehicleClimateHost?=null
    private var safety: ClimateCarSafety?=null
    private var foregroundObservation: java.io.Closeable?=null
    private var supportReporter: VehicleControlSupportReporter?=null
    private var connectionObservation: java.io.Closeable?=null
    private var boundaryObservation: java.io.Closeable?=null
    private var lifetime: VehicleReceiverLifetime?=null
    private fun refreshSupport() {
        val app=application as WegoApplication
        val status=connection.status().stage
        supportReporter?.setActive(active && !closed && app.receiverSettings.enabled &&
            status in setOf(io.wegoh.app.nativeauth.VehicleConnection.Stage.CONNECTED,io.wegoh.app.nativeauth.VehicleConnection.Stage.CHECKING) &&
            connection.climateBaseCurrent(connection.dataEpoch()))
    }
    private var power: SessionPowerMonitor?=null
    private var receiverLease: java.io.Closeable?=null
    private lateinit var connection: io.wegoh.app.nativeauth.VehicleConnection
    private var currentReceiverRevision: ()->Long?={connection.currentDataBoundary()?.revision}
    private var busy=false
    private var closed=false
    private val poll=object: Runnable {
        override fun run() {
            handler.removeCallbacks(this)
            if(closed)return
            if(lifetime?.check()!=true)return
            if(busy)return
            if(safety?.snapshot()?.permitsReceiver()==true) {
                val receiver=host
                if(receiver==null) {handler.postDelayed(this,2_000);return}
                busy=true
                receiver.checkPending({_,apply->apply(true)}) {result->
                    if(closed)return@checkPending
                    busy=false
                    val wasReceiving=receiving
                    ready=result in setOf(VehicleClimateHostResult.NO_SUPPORTED_REQUEST,VehicleClimateHostResult.CONFIRMED)
                    message=when(result) {
                        VehicleClimateHostResult.CONFIRMED->"차량 설정 변경 완료"
                        VehicleClimateHostResult.NO_SUPPORTED_REQUEST->if(wasReceiving)message else "리모컨 요청 대기 중"
                        VehicleClimateHostResult.BLOCKED->"지원하지 않거나 허용이 끝난 요청이에요"
                        VehicleClimateHostResult.UNKNOWN->"설정 변경 여부를 확인하지 못했어요"
                        VehicleClimateHostResult.UNAVAILABLE->"차량 연결과 리모컨 수신을 확인해 주세요"
                    }
                    val delay=vehicleClimatePollDelay(result,receiver.hasPendingRequests)
                    WegoLog.i("WegoClimate","climate.receiver: poll scheduled result=${result.name.lowercase()} delay_ms=$delay more_queued=${receiver.hasPendingRequests}")
                    handler.postDelayed(this,delay)
                }
            } else {
                ready=false
                message="차량 상태 확인 중"
                handler.postDelayed(this,2_000)
            }
        }
    }
    internal class ReceiverBinder(val service: VehicleClimateService): Binder()
    override fun onBind(intent: Intent?): IBinder=ReceiverBinder(this)
    override fun onCreate() {
        super.onCreate()
        initializeReceiver()
    }
    private fun initializeReceiver() {
        closed=false;busy=false;lifetime=null
        val app=application as WegoApplication
        safety=ClimateCarSafety(this) {host?.authorityChanged()}
        connection=app.controller.vehicleAccountConnection ?: app.vehicleConnection
        host=VehicleClimateHost(this,connection,app.controller.remoteHistoryFor(connection),
            safety={safety?.snapshot()?.takeIf {app.receiverSettings.enabled} ?: VehicleClimateSafety(false,false,false,false,true)},
            senderName={id->app.controller.socialRepository.state.overview?.friends?.firstOrNull {it.id==id}?.name})
        supportReporter=VehicleControlSupportReporter({VehicleHardwareSdkAdapter(this)},
            {VehicleControlSupportNativeTransport(connection)})
        foregroundObservation=app.controller.observeClimateForeground {safety?.setForeground(it)}
        connectionObservation=connection.observe {refreshSupport()}
        boundaryObservation=connection.observeDataBoundary {
            // Boundary observers also run on the connection worker. Keep service shutdown
            // serialized with SDK callbacks and polling on the main thread.
            handler.post {if(!closed)lifetime?.check()}
        }
        power=SessionPowerMonitor(this) {safety?.setReceiverActive(false);stopSelf()}
    }
    override fun onStartCommand(intent: Intent?,flags: Int,startId: Int): Int {
        val app=application as WegoApplication
        if(intent?.action=="STOP") {
            safety?.setReceiverActive(false)
            app.receiverSettings.stopFromNotification(connection.reserveClimateReceiver())
            stopSelf()
            return START_NOT_STICKY
        }
        if(!app.receiverSettings.enabled) {stopSelf();return START_NOT_STICKY}
        if(closed) {
            // stopSelf does not destroy a service while a client remains bound. A new
            // authenticated start must recreate that instance's released resources.
            if(currentReceiverRevision()==null) {stopSelf();return START_NOT_STICKY}
            initializeReceiver()
        }
        if(lifetime==null)lifetime=VehicleReceiverLifetime(
            currentRevision=currentReceiverRevision,
            ended={
                message="차량 연결이 종료되어 리모컨 수신을 중지했습니다"
                releaseReceiver()
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
            })
        if(lifetime?.check()!=true)return START_NOT_STICKY
        val notifications=getSystemService(NotificationManager::class.java)
        notifications.createNotificationChannel(NotificationChannel("climate-remote","내 차 리모컨",NotificationManager.IMPORTANCE_LOW))
        val stop=PendingIntent.getService(this,0,Intent(this,VehicleClimateService::class.java).setAction("STOP"),PendingIntent.FLAG_IMMUTABLE)
        val open=PendingIntent.getActivity(this,0,Intent(this,VehicleClimateActivity::class.java),PendingIntent.FLAG_IMMUTABLE)
        val notification=Notification.Builder(this,"climate-remote").setSmallIcon(R.drawable.ic_wegoh).setContentTitle("내 차 리모컨")
            .setContentText("허용한 동승자의 조작을 받아요. 시트·실내등 조작은 정차 중에만 가능해요").setContentIntent(open).setOngoing(true)
            .addAction(Notification.Action.Builder(null,"수신 중지",stop).build()).build()
        try {
            if(android.os.Build.VERSION.SDK_INT>=29)startForeground(12,notification,ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
            else startForeground(12,notification)
        }
        catch(_: Exception) {message="리모컨 수신을 시작하지 못했어요";stopSelf();return START_NOT_STICKY}
        if(!active) {
            receiverLease=connection.reserveClimateReceiver()
            ready=false;active=true;message="리모컨 연결 확인 중"
            safety?.setReceiverActive(true);refreshSupport();handler.post(poll)
        }
        return START_NOT_STICKY
    }
    override fun onTimeout(startId: Int,fgsType: Int) {safety?.setReceiverActive(false);message="리모컨 수신 시간이 끝났어요";stopSelf()}
    private fun releaseReceiver() {
        if(closed)return
        closed=true;ready=false;active=false;handler.removeCallbacks(poll)
        supportReporter?.close();supportReporter=null
        connectionObservation?.close();connectionObservation=null
        boundaryObservation?.close();boundaryObservation=null
        foregroundObservation?.close();foregroundObservation=null
        safety?.setForeground(false);safety?.setReceiverActive(false)
        receiverLease?.close();receiverLease=null;host?.close();host=null;safety?.close();safety=null;power?.close();power=null
    }
    override fun onDestroy() {
        releaseReceiver()
        stopForeground(STOP_FOREGROUND_REMOVE);super.onDestroy()
    }
    companion object {
        internal fun runReceiver(context: android.content.Context, enabled: Boolean) {
            val intent=Intent(context,VehicleClimateService::class.java)
            if(!enabled) {
                message="리모컨 수신 꺼짐"
                context.stopService(intent)
            } else if(!active) {
                runCatching {context.startForegroundService(intent)}
                    .onFailure {message="리모컨 수신을 시작하지 못했어요"}
            }
        }

        var active by mutableStateOf(false);private set
        private var ready by mutableStateOf(false)
        val receiving: Boolean get()=active && ready
        var message by mutableStateOf("여행에서 허용한 동승자의 조작을 받아요");private set
    }
}

/** A receiver belongs to one authenticated account boundary, including while in the background.
 * A network interruption does not end reception while that boundary remains valid. Revocation,
 * expiry, or account replacement does; a later foreground refresh starts a new service owner.
 */
internal class VehicleReceiverLifetime(private val currentRevision: ()->Long?,private val ended: ()->Unit) {
    private val revision=currentRevision()
    private var closed=false
    fun check(): Boolean {
        if(!closed && (revision==null || currentRevision()!=revision)) {
            closed=true
            ended()
        }
        return !closed
    }
}
