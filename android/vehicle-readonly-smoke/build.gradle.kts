plugins {
    id("com.android.application") version "8.8.2"
    id("org.jetbrains.kotlin.android") version "2.0.0"
}
val repositoryRoot = projectDir.parentFile.parentFile
val generatedAdapter = layout.buildDirectory.dir("generated/accepted-adapter")
val copyAcceptedAdapter by tasks.registering(Sync::class) {
    from(repositoryRoot.resolve("android/vehicle-hardware/src/main/java")) {
        include("io/wegoh/app/VehicleHardwarePort.kt", "io/wegoh/app/VehicleHardwareSdkAdapter.kt", "io/wegoh/app/VehicleTelemetryReader.kt")
    }
    into(generatedAdapter)
}

android {
    namespace = "io.wegoh.vehiclesmoke"
    compileSdk = 35
    useLibrary("android.car", false)
    useLibrary("android.test.runner", false)
    useLibrary("android.test.base", false)
    defaultConfig {
        applicationId = "io.wegoh.vehiclesmoke"
        minSdk = 28
        targetSdk = 35
        versionCode = 1
        versionName = "1"
        testInstrumentationRunner = "android.test.InstrumentationTestRunner"
    }
    flavorDimensions += "permission"
    productFlavors {
        create("readOnly") { dimension = "permission"; buildConfigField("boolean", "EXPECT_READ_PERMISSIONS", "true") }
        create("denied") { dimension = "permission"; buildConfigField("boolean", "EXPECT_READ_PERMISSIONS", "false") }
    }
    buildFeatures { buildConfig = true }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
    kotlinOptions { jvmTarget = "17" }
    sourceSets.getByName("main").java.srcDir(generatedAdapter)
}
dependencies { implementation("ai.pleos.playground:Vehicle:2.3.2") }
tasks.named("preBuild").configure { dependsOn(copyAcceptedAdapter) }
tasks.matching { it.name.endsWith("Kotlin") }.configureEach { dependsOn(copyAcceptedAdapter) }
tasks.matching { it.name.contains("Release") }.configureEach {
    doFirst { error("Vehicle read-only diagnostic is debug-only; never a product/submission release.") }
}
