package io.wegoh.app

import android.app.*
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.content.BroadcastReceiver
import android.content.Context
import android.content.IntentFilter
import androidx.core.content.ContextCompat

class SessionService : Service() {
    private val journey get() = (application as WegoApplication).journeyExecution
    private var powerMonitor: SessionPowerMonitor? = null
    override fun onBind(intent: Intent?): IBinder? = null
    override fun onCreate() {
        super.onCreate()
        powerMonitor=SessionPowerMonitor(this) {
            journey.interrupt("화면이 꺼져 경로를 중단했어요");stopSelf()
        }
    }
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == "STOP") { stopSelf(); return START_NOT_STICKY }
        if (intent == null || journey.isActive) return START_NOT_STICKY
        try {
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(NotificationChannel("journey", "경로 진행", NotificationManager.IMPORTANCE_LOW))
            manager.cancel(11)
            val initialNotification = notification()
            if (Build.VERSION.SDK_INT >= 29) startForeground(10, initialNotification, ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION)
            else startForeground(10, initialNotification)
            journey.begin(intent.getStringExtra("pack") ?: error("선택한 경로가 없습니다"),onCompleted={
                // Nothing is left to observe: end location use now and leave a dismissible result.
                stopForeground(STOP_FOREGROUND_REMOVE)
                runCatching {manager.notify(11,completedNotification())}
                stopSelf()
            }) {
                if(intent.getBooleanExtra("navigate",false))journey.requestNavigation()
            }
        } catch (e: Exception) { journey.fail("경로를 시작할 수 없어요"); stopSelf() }
        return START_NOT_STICKY
    }
    private fun openApp()=PendingIntent.getActivity(this,0,Intent(this,MainActivity::class.java),PendingIntent.FLAG_IMMUTABLE)
    private fun notification(): Notification {
        val stop=PendingIntent.getService(this,1,Intent(this,SessionService::class.java).setAction("STOP"),PendingIntent.FLAG_IMMUTABLE)
        return Notification.Builder(this,"journey")
            .setContentTitle("경로 진행 중").setContentText("방문 장소 확인 중")
            .setSmallIcon(R.drawable.ic_wegoh).setContentIntent(openApp()).setOngoing(true)
            .addAction(Notification.Action.Builder(null,"경로 종료",stop).build()).build()
    }
    private fun completedNotification(): Notification=Notification.Builder(this,"journey")
        .setContentTitle("모든 장소 방문 완료")
        .setSmallIcon(R.drawable.ic_wegoh).setContentIntent(openApp()).setAutoCancel(true).build()
    override fun onDestroy() {
        powerMonitor?.close();powerMonitor=null
        // Completion already released the session; its final foreground chime may still be playing.
        if(journey.isActive)journey.stop()
        stopForeground(STOP_FOREGROUND_REMOVE);super.onDestroy()
    }
}

/** One receiver shared by the service and isolated emulator lifecycle tests. */
internal class SessionPowerMonitor(private val context: Context,private val inactive: ()->Unit): AutoCloseable {
    private var closed=false
    private val receiver=object: BroadcastReceiver() {
        override fun onReceive(context: Context?,intent: Intent?) {
            if(!closed && intent?.action in setOf(Intent.ACTION_SCREEN_OFF,Intent.ACTION_SHUTDOWN))inactive()
        }
    }
    init {
        ContextCompat.registerReceiver(context,receiver,IntentFilter().apply {
            addAction(Intent.ACTION_SCREEN_OFF);addAction(Intent.ACTION_SHUTDOWN)
        },ContextCompat.RECEIVER_NOT_EXPORTED)
    }
    override fun close() {if(!closed){closed=true;context.unregisterReceiver(receiver)}}
}
