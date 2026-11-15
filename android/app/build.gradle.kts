import java.net.URI
import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}
val localMapProperties = Properties().apply {
    rootProject.file("local.properties").takeIf { it.isFile }?.inputStream()?.use { load(it) }
}
val kakaoNativeAppKey = providers.environmentVariable("WEGOH_KAKAO_NATIVE_APP_KEY")
    .orElse(providers.gradleProperty("wegohKakaoNativeAppKey"))
    .orElse(localMapProperties.getProperty("wegohKakaoNativeAppKey", "")).get()
    .replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n").replace("\r", "\\r")

android {
    namespace = "io.wegoh.app"
    compileSdk = 35
    defaultConfig {
        applicationId = "io.wegoh.app"
        buildConfigField("String", "KAKAO_NATIVE_APP_KEY", "\"$kakaoNativeAppKey\"")
        minSdk = 28
        targetSdk = 35
        versionCode = 4
        versionName = "0.4.0"
        testInstrumentationRunner = "android.test.InstrumentationTestRunner"
    }
    useLibrary("android.car", false)
    useLibrary("android.test.runner", false)
    useLibrary("android.test.base", false)
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    buildFeatures { compose = true; buildConfig = true }
    val releaseStore = providers.environmentVariable("WEGOH_RELEASE_STORE_FILE").orNull
    if(releaseStore!=null)signingConfigs.create("release") {
        storeFile=file(releaseStore)
        storePassword=providers.environmentVariable("WEGOH_RELEASE_STORE_PASSWORD").orNull
        keyAlias=providers.environmentVariable("WEGOH_RELEASE_KEY_ALIAS").orNull
        keyPassword=providers.environmentVariable("WEGOH_RELEASE_KEY_PASSWORD").orNull
    }
    buildTypes {
        debug {
            buildConfigField("String", "PACK_API_BASE_URL", "\"http://127.0.0.1:18081\"")
            buildConfigField("String", "PRIVACY_URL", "\"\"")
            buildConfigField("String", "LOCATION_TERMS_URL", "\"\"")
        }
        release {
            isMinifyEnabled = false
            signingConfig=signingConfigs.findByName("release")
            val api=providers.gradleProperty("wegohApiUrl").orElse("").get()
                .replace("\\","\\\\").replace("\"","\\\"").replace("\n","\\n").replace("\r","\\r")
            buildConfigField("String", "PACK_API_BASE_URL", "\"$api\"")
            for((property,field) in listOf("wegohPrivacyUrl" to "PRIVACY_URL","wegohLocationTermsUrl" to "LOCATION_TERMS_URL")) {
                val url=providers.gradleProperty(property).orElse("").get()
                    .replace("\\","\\\\").replace("\"","\\\"").replace("\n","\\n").replace("\r","\\r")
                buildConfigField("String",field,"\"$url\"")
            }
        }
    }
}

// Local debug is not an accidentally shippable release. No fake legal URLs/signing.
// Legal URLs are optional: when absent the vehicle UI hides their links.
tasks.configureEach {
    if(name=="preReleaseBuild")doFirst {
        providers.gradleProperty("wegohApiUrl").orNull ?: error("Release blocked: wegohApiUrl is required")
        for(field in listOf("wegohApiUrl","wegohPrivacyUrl","wegohLocationTermsUrl")) {
            val value=providers.gradleProperty(field).orNull ?: continue
            val uri=URI(value)
            check(uri.scheme=="https" && !uri.host.isNullOrBlank() && uri.userInfo==null && uri.fragment==null && uri.query==null) {"Release requires approved HTTPS URLs"}
            check(uri.host !in setOf("localhost","127.0.0.1") && !uri.host.endsWith(".invalid") && !uri.host.endsWith(".example")) {"Release requires real service URLs"}
        }
        check(android.signingConfigs.findByName("release")?.storeFile?.isFile==true) {"Release blocked: private release signing configuration is required"}
    }
}
dependencies {
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
    implementation("com.kakao.maps.open:android:2.15.2")
    implementation("androidx.core:core-ktx:1.16.0")
    implementation("androidx.activity:activity-compose:1.10.1")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.9.0")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.9.0")
    implementation("androidx.lifecycle:lifecycle-viewmodel-ktx:2.9.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
    implementation(platform("androidx.compose:compose-bom:2024.04.01"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material3:material3")
    implementation("ai.pleos.playground:NaviHelper:3.0.5")
    implementation("ai.pleos.playground:FusedLocation:1.1.3")
    implementation(project(":vehicle-hardware"))
    implementation("com.google.zxing:core:3.5.4")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("androidx.media3:media3-exoplayer:1.4.1")
}

tasks.matching { it.name=="assembleDebugAndroidTest" }.configureEach {
    dependsOn("assembleDebug")
}

apply(from = rootProject.file("gradle/native-access-build-type.gradle"))
