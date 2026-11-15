package io.wegoh.app

import android.content.Context
import android.content.ContextWrapper
import android.content.Intent
import android.graphics.Rect
import android.os.Bundle
import android.test.InstrumentationTestRunner
import android.view.accessibility.AccessibilityNodeInfo
import com.google.zxing.BinaryBitmap
import com.google.zxing.MultiFormatReader
import com.google.zxing.RGBLuminanceSource
import com.google.zxing.common.HybridBinarizer
import io.wegoh.app.nativeauth.NativeDeviceIdentity
import io.wegoh.app.nativeauth.VehicleConnection
import java.io.File
import org.json.JSONObject

class ConnectionOnboardingTest: FirstRunPermissionsCompletedTestCase() {
    private fun onMain(action: ()->Unit)=instrumentation.runOnMainSync(action)
    private fun await(label: String,condition: ()->Boolean) {
        val end=android.os.SystemClock.elapsedRealtime()+25000
        while(android.os.SystemClock.elapsedRealtime()<end) {if(condition())return;Thread.sleep(80)}
        fail("Connection entry timeout: $label")
    }
    private fun node(label: String): AccessibilityNodeInfo? {
        instrumentation.uiAutomation.clearCache()
        fun find(n: AccessibilityNodeInfo?): AccessibilityNodeInfo? {
            if(n==null)return null
            if(n.isVisibleToUser && (n.text?.toString()==label || n.contentDescription?.toString()==label))return n
            for(i in 0 until n.childCount)find(n.getChild(i))?.let {return it}
            return null
        }
        return find(instrumentation.uiAutomation.rootInActiveWindow)
    }
    private fun click(label: String) {
        await(label) {node(label)!=null}
        var n=node(label)
        repeat(6) {if(n?.performAction(AccessibilityNodeInfo.ACTION_CLICK)==true)return;n=n?.parent}
        fail("Connection entry action: $label")
    }
    private fun focus(host: MainActivity) {
        await("Main window laid out") {host.window.decorView.isShown && host.window.decorView.width>0}
        repeat(3) {
            if(host.hasWindowFocus())return
            val frames=java.util.concurrent.CountDownLatch(1)
            onMain {host.window.decorView.postOnAnimation {host.window.decorView.postOnAnimation {frames.countDown()}}}
            assertTrue(frames.await(3,java.util.concurrent.TimeUnit.SECONDS))
            val origin=IntArray(2);onMain {host.window.decorView.getLocationOnScreen(origin)}
            android.os.ParcelFileDescriptor.AutoCloseInputStream(instrumentation.uiAutomation.executeShellCommand(
                "input tap ${origin[0]+host.window.decorView.width/2} ${origin[1]+host.window.decorView.height/4}")).use {it.readBytes()}
            val end=android.os.SystemClock.uptimeMillis()+500
            while(!host.hasWindowFocus() && android.os.SystemClock.uptimeMillis()<end)Thread.sleep(40)
        }
        assertTrue("Rendered Main window focused",host.hasWindowFocus())
    }
    private fun absentNavigation() {
        for(label in listOf("뒤로","홈","전체 메뉴","발견","프로필"))assertNull(label,node(label))
    }
    private fun capture(name: String) {
        instrumentation.waitForIdleSync()
        File(instrumentation.targetContext.cacheDir,name+".png").outputStream().use {out ->
            instrumentation.uiAutomation.takeScreenshot().apply {compress(android.graphics.Bitmap.CompressFormat.PNG,100,out);recycle()}
        }
    }
    fun testActualMainEntryQrConnectionAndDisconnect() {
        val args=(instrumentation as InstrumentationTestRunner).arguments
        val base=instrumentation.targetContext
        val id="onboarding_"+java.util.UUID.randomUUID().toString().replace("-","").take(24)
        val directory=File(base.cacheDir,id).apply {mkdirs()}
        val isolated=object: ContextWrapper(base) {
            override fun getApplicationContext(): Context=this
            override fun getFilesDir()=File(directory,"files").apply {mkdirs()}
            override fun getNoBackupFilesDir()=File(directory,"private").apply {mkdirs()}
            override fun getSharedPreferences(name: String,mode: Int)=base.getSharedPreferences(id+name,mode)
        }
        val ca=NativeDeviceIdentity.parseCertificates(String(android.util.Base64.decode(args.getString("ca"),android.util.Base64.DEFAULT),Charsets.US_ASCII)).single()
        val connection=VehicleConnection.synthetic(base,id,args.getString("port")!!.toInt(),ca,args.getString("eventsPort")!!.toInt())
        val app=base.applicationContext as WegoApplication
        val delegate=app.javaClass.getDeclaredField("controller\$delegate").apply {isAccessible=true}
        val original=delegate.get(app) as Lazy<*>;val initialized=original.isInitialized()
        lateinit var controller: WegoController
        onMain {controller=WegoController(isolated,base.applicationContext);controller.connectAccount(connection);controller.setAppForeground(true);delegate.set(app,lazyOf(controller))}
        var activity: MainActivity?=null
        val marker=File(base.cacheDir,"onboarding-approve")
        try {
            activity=instrumentation.startActivitySync(Intent(base,MainActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)) as MainActivity
            var host=requireNotNull(activity)
            await("actual parked permission") {controller.state.setupAllowed}
            focus(host)
            await("walkthrough first page") {controller.state.setupAllowed && host.hasWindowFocus() && node("경로를 차에서 시작해요")!=null}
            absentNavigation();assertNull(node("차량 연결"));assertFalse(controller.firstRunGuide.completed)
            capture("walkthrough-course")
            click("다음");await("playlist introduction") {node("내 음악을 차에서")!=null}
            capture("walkthrough-playlist")
            click("이전");await("previous introduction") {node("경로를 차에서 시작해요")!=null}
            click("다음");click("다음");await("connection introduction") {node("휴대전화로 차량 연결")!=null}
            assertNull(node("차량 연결 QR 코드"));capture("walkthrough-connect")
            click("계속");await("parked entry") {node("차량을 연결해 주세요")!=null}
            assertNull("device courses removed",node("기기 경로"))
            assertTrue(controller.firstRunGuide.completed);assertTrue(FirstRunGuide(isolated).completed)
            onMain {host.finish()};await("first Main destroyed") {host.isDestroyed}
            activity=instrumentation.startActivitySync(Intent(base,MainActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)) as MainActivity
            host=requireNotNull(activity)
            focus(host)
            await("seen walkthrough does not recur") {
                if(!host.hasWindowFocus())focus(host)
                host.hasWindowFocus() && node("차량을 연결해 주세요")!=null
            }
            assertNull(node("경로를 차에서 시작해요"))
            await("connection entry fully rendered") {node("차량을 연결해 주세요")!=null && node("차량 연결")!=null}
            absentNavigation()
            capture("account-overview-onboarding-entry")
            val button=node("차량 연결")!!
            click("차량 연결");button.performAction(AccessibilityNodeInfo.ACTION_CLICK)
            await("inline real pending QR") {node("차량 연결 QR 코드")!=null && node("ABCD2345")!=null}
            absentNavigation();assertFalse(host.isFinishing);assertNull("device courses hidden during QR",node("기기 경로"))
            assertTrue("QR stays in Main",instrumentation.uiAutomation.rootInActiveWindow.packageName.toString()==base.packageName)
            val qr=Rect();node("차량 연결 QR 코드")!!.getBoundsInScreen(qr)
            val screen=instrumentation.uiAutomation.takeScreenshot();val pixels=IntArray(qr.width()*qr.height())
            screen.getPixels(pixels,0,qr.width(),qr.left,qr.top,qr.width(),qr.height());screen.recycle()
            assertEquals("https://wegoh.devforest.io/enroll.html?user_code=ABCD2345",
                MultiFormatReader().decode(BinaryBitmap(HybridBinarizer(RGBLuminanceSource(qr.width(),qr.height(),pixels)))).text)
            capture("account-overview-onboarding-qr")
            assertNotNull(node("연결 코드 유효 시간"))
            await("expired QR removed") {node("연결이 만료됐어요")!=null && node("차량 연결 QR 코드")==null}
            capture("qr-countdown-expired")
            click("다시 시도")
            await("single retry fresh QR") {node("EFGH2345")!=null && node("차량 연결 QR 코드")!=null}
            assertNull(node("ABCD2345"));assertTrue(connection.status().expiresAtMillis!!>System.currentTimeMillis()+250000)
            capture("qr-countdown-retried")
            marker.writeText(args.getString("gpsNonce")!!)
            await("actual connected discovery") {connection.status().stage==VehicleConnection.Stage.CONNECTED && node("공개 경로")!=null}
            assertNull(node("차량을 연결해 주세요"));assertNotNull(node("홈"));assertNotNull(node("전체 메뉴"))
            val epoch=connection.dataEpoch()
            click("전체 메뉴");await("owned menu") {node("여행방")!=null}
            assertEquals("Owned menu keeps account epoch",epoch,connection.dataEpoch())
            assertEquals(VehicleConnection.Stage.CONNECTED,connection.status().stage)
            click("발견");await("menu returns to discovery") {node("공개 경로")!=null}
            capture("account-overview-onboarding-connected")
            connection.disconnect()
            await("terminal connection returns to entry") {connection.status().stage==VehicleConnection.Stage.LOCKED && node("차량을 연결해 주세요")!=null}
            absentNavigation();assertNull(node("공개 경로"))
            File(base.cacheDir,"account-overview-onboarding-runtime.json").writeText(JSONObject()
                .put("synthetic",true).put("actualMainRenderer",true).put("inlineQrDecoded",true)
                .put("ownedMenuPreservesConnection",true).put("terminalLockClosesContent",true)
                .put("limits","Isolated TLS/mTLS phone approval fixture; no live owner approval, car/GPS injection or release result.").toString(2))
        } catch(failure: Throwable) {
            File(base.cacheDir,"account-overview-onboarding-failure-runtime.json").writeText(JSONObject()
                .put("setupAllowed",controller.state.setupAllowed).put("hasWindowFocus",activity?.hasWindowFocus())
                .put("stage",connection.status().stage.name).put("lifecycle",activity?.lifecycle?.currentState?.name).toString(2))
            runCatching {capture("account-overview-onboarding-failure")};throw failure
        } finally {
            if(marker.exists() && marker.readText()==args.getString("gpsNonce"))marker.delete()
            try {onMain {controller.close();activity?.finish()};if(activity!=null)await("Main destroyed") {activity!!.isDestroyed}}
            finally {onMain {delegate.set(app,original)};connection.close()}
            assertEquals("Real controller lazy unchanged",initialized,original.isInitialized())
        }
    }
}
