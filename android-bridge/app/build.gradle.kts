plugins {
    id("com.android.application") // AGP 9+ compiles Kotlin natively (built-in)
}

android {
    namespace = "com.splits.healthspike"
    compileSdk = 36

    defaultConfig {
        // applicationId is the app's permanent identity (Play-compatible name,
        // decided 2026-07-16 before first family install); the code namespace
        // deliberately stays com.splits.healthspike — renaming it would only
        // churn source paths.
        applicationId = "com.splits.bridge"
        minSdk = 26
        targetSdk = 36
        versionCode = 2
        versionName = "0.2" // 0.2: schedule-after-rejections fix + status-bar insets
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

dependencies {
    // Health Connect Jetpack client (latest stable).
    implementation("androidx.health.connect:connect-client:1.1.0")

    // Minimal AndroidX surface for a themed Activity + coroutine scope.
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.7")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")

    // Recurring background sync (healthconnect-bridge set-and-forget requirement).
    implementation("androidx.work:work-runtime-ktx:2.11.2")
}
