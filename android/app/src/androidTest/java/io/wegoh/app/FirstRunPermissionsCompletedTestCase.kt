package io.wegoh.app

import android.content.Context
import android.content.SharedPreferences
import android.test.InstrumentationTestCase

@Suppress("DEPRECATION")
abstract class FirstRunPermissionsCompletedTestCase: InstrumentationTestCase() {
    private var preferences: SharedPreferences?=null
    private var hadCompletion=false
    private var completion=false

    override fun setUp() {
        super.setUp()
        val store=instrumentation.targetContext.getSharedPreferences("first_run_permissions",Context.MODE_PRIVATE)
        hadCompletion=store.contains("completed")
        completion=store.getBoolean("completed",false)
        preferences=store
        assertTrue(store.edit().putBoolean("completed",true).commit())
    }

    override fun tearDown() {
        try {
            preferences?.let {store->
                val restore=store.edit()
                if(hadCompletion)restore.putBoolean("completed",completion) else restore.remove("completed")
                assertTrue(restore.commit())
            }
        } finally {super.tearDown()}
    }
}
