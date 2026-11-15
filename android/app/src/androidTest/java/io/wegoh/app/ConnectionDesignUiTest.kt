package io.wegoh.app

import android.content.Intent
import android.graphics.Bitmap
import androidx.compose.ui.semantics.*
import com.google.zxing.BinaryBitmap
import com.google.zxing.MultiFormatReader
import com.google.zxing.RGBLuminanceSource
import com.google.zxing.common.HybridBinarizer
import io.wegoh.app.nativeauth.VehicleConnection
import java.io.File

class ConnectionDesignUiTest: EntryDesignTestCase() {
    private fun textNode(label: String)=nodes().first {
        it.config.getOrNull(SemanticsProperties.ContentDescription)?.contains(label)==true ||
            it.config.getOrNull(SemanticsProperties.Text)?.any {text->text.text==label}==true
    }
    private fun reveal(label: String) {
        repeat(12) {
            val r=bounds(control(label))
            if(!r.isEmpty && frame.contains(r))return
            val action=nodes().firstNotNullOfOrNull {it.config.getOrNull(SemanticsActions.ScrollBy)?.action}
            assertNotNull("Scrollable narrow connection body",action)
            instrumentation.runOnMainSync {requireNotNull(action).invoke(0f,frame.height()/2f)}
            settle()
        }
        fail("Connection action remains outside viewport: $label")
    }
    fun testAccountQrAndActionsFitEveryPreset() {
        host=instrumentation.startActivitySync(Intent(instrumentation.targetContext,SafFrameworkHarnessActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_MULTIPLE_TASK)) as SafFrameworkHarnessActivity
        val uri="https://wegoh.devforest.io/enroll.html?user_code=ABCD2345"
        var cancelled=0
        try {
            for(night in listOf(false,true))for((width,height) in presets) {
                render(width,height,night,entry=false) {
                    ConnectionEntry {
                        ConnectionBody(VehicleConnection.Progress(VehicleConnection.Stage.APPROVAL_REQUIRED,"ABCD2345",uri,
                            System.currentTimeMillis()+300000),true,{},{},{cancelled++},{},{},onboarding=true)
                    }
                }
                val qr=bounds(textNode("차량 연결 QR 코드"))
                val code=bounds(textNode("ABCD2345"))
                assertTrue("QR visible at $width x $height",frame.contains(qr) && !qr.isEmpty)
                assertTrue("Code follows QR without overlap",code.top>=qr.bottom && frame.contains(code))
                var screen: Bitmap?=null
                var qrCrop: Bitmap?=null
                var decoded: String?=null
                val until=android.os.SystemClock.uptimeMillis()+5000
                while(decoded!=uri && android.os.SystemClock.uptimeMillis()<until) {
                    qrCrop?.recycle();screen?.recycle()
                    screen=requireNotNull(instrumentation.uiAutomation.takeScreenshot())
                    qrCrop=Bitmap.createBitmap(requireNotNull(screen),qr.left,qr.top,qr.width(),qr.height())
                    val image=requireNotNull(qrCrop)
                    val pixels=IntArray(image.width*image.height)
                    image.getPixels(pixels,0,image.width,0,0,image.width,image.height)
                    decoded=try {MultiFormatReader().decode(BinaryBitmap(HybridBinarizer(RGBLuminanceSource(image.width,image.height,pixels)))).text}
                        catch(_: com.google.zxing.ReaderException) {null}
                    if(decoded!=uri)Thread.sleep(50)
                }
                if(decoded!=uri)File(host.cacheDir,"connection-qr-diagnostic.png").outputStream().use {
                    requireNotNull(qrCrop).compress(Bitmap.CompressFormat.PNG,100,it)
                }
                assertEquals("connection.qr: validation failed width=$width height=$height night=$night bounds=$qr",uri,decoded)
                val shot=requireNotNull(screen)
                qrCrop?.recycle()
                if(width==1700 || width==628) {
                    val panel=Bitmap.createBitmap(shot,frame.left,frame.top,frame.width(),frame.height())
                    File(host.cacheDir,"connection-${width}x$height-${if(night)"night" else "day"}.png").outputStream().use {
                        panel.compress(Bitmap.CompressFormat.PNG,100,it)
                    }
                    panel.recycle()
                }
                shot.recycle()
                reveal("취소");checkButton("취소");tap("취소")
            }
            assertEquals("Each displayed cancel invokes exactly once",presets.size*2,cancelled)
        } finally {instrumentation.runOnMainSync {host.finish()}}
    }
}
