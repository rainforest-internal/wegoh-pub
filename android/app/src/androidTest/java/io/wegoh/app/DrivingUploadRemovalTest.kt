package io.wegoh.app

import android.content.pm.PackageManager
import android.test.InstrumentationTestCase
import io.wegoh.app.nativeauth.NativeApiClient
import io.wegoh.app.nativeauth.VehicleConnection

@Suppress("DEPRECATION")
class DrivingUploadRemovalTest: InstrumentationTestCase() {
    fun testInstalledAppCannotStartTheRetiredUploadService() {
        val context=instrumentation.targetContext
        val services=context.packageManager.getPackageInfo(context.packageName,PackageManager.GET_SERVICES).services.orEmpty()
        assertFalse(services.any {it.name.endsWith(".DrivingDataService")})
        val activities=context.packageManager.getPackageInfo(context.packageName,PackageManager.GET_ACTIVITIES).activities.orEmpty()
        assertFalse(activities.any {it.name.endsWith(".DrivingDataActivity")})
        assertFalse(VehicleConnection::class.java.declaredMethods.any {it.name.startsWith("readDrivingData")})
        assertFalse(VehicleConnection::class.java.declaredClasses.any {it.simpleName=="DrivingUpload"})
        assertFalse(NativeApiClient::class.java.declaredMethods.any {it.name.startsWith("drivingPost")})
    }
}
