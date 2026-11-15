plugins { id("com.android.application"); id("org.jetbrains.kotlin.android") }
android {
    namespace = "io.wegoh.nativeaccess.smoke"
    compileSdk = 35
    useLibrary("android.test.runner", false)
    useLibrary("android.test.base", false)
    defaultConfig { applicationId = "io.wegoh.nativeaccess.smoke"; minSdk = 29; targetSdk = 35; versionCode = 1; versionName = "1"; testInstrumentationRunner = "android.test.InstrumentationTestRunner" }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
    kotlinOptions { jvmTarget = "17" }
}
// Consume the actual AAR artifact, not project source/classpath by accident.
val nativeAar = project(":native-access").layout.buildDirectory.file("outputs/aar/native-access-debug.aar")
dependencies {
    implementation(files(nativeAar).builtBy(":native-access:bundleDebugAar"))
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("org.jetbrains.kotlin:kotlin-stdlib:2.0.0")
}

// This isolated diagnostic consumer is never a submission/release application.
tasks.matching { it.name == "preReleaseBuild" }.configureEach { doFirst { error("SDK smoke is debug-only") } }

// Bind the test-only JVM initialization bridge to the actual debug AAR classes.
// Public operations are always the real packaged library; no project-source dependency.
val aarFriendDirectory = layout.buildDirectory.dir("aar-test-friend")
val extractAarTestFriend by tasks.registering(Copy::class) {
    dependsOn(":native-access:bundleDebugAar")
    from({ zipTree(nativeAar.get().asFile) }) { include("classes.jar") }
    into(aarFriendDirectory)
}
tasks.matching { it.name == "preDebugAndroidTestBuild" }.configureEach { dependsOn(extractAarTestFriend) }
