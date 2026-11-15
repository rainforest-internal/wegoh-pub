plugins {
    id("com.android.library")
    id("org.jetbrains.kotlin.android")
}
android {
    namespace = "io.wegoh.nativeaccess"
    compileSdk = 35
    defaultConfig { minSdk = 29 }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
    kotlinOptions { jvmTarget = "17" }
    sourceSets.getByName("main") {
        // Same maintained core files as the product; no manual SDK source copy.
        java.setSrcDirs(listOf("../app/src/main/java/io/wegoh/app/nativeauth"))
        assets.srcDir(layout.buildDirectory.dir("generated/native-access-assets"))
    }
}
val nativeWireAsset by tasks.registering(Sync::class) {
    from(rootProject.file("../server/native_access_wire.json"))
    into(layout.buildDirectory.dir("generated/native-access-assets"))
}
tasks.named("preBuild").configure {
    dependsOn(nativeWireAsset)
}
apply(from = rootProject.file("gradle/native-access-build-type.gradle"))

dependencies { implementation("com.squareup.okhttp3:okhttp:4.12.0") }
