plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "toys.bobs.nms"
    compileSdk = 36

    defaultConfig {
        applicationId = "toys.bobs.nms"
        minSdk = 29
        targetSdk = 36
        versionCode = 1
        versionName = "0.1"
    }
    buildFeatures { buildConfig = true }
    buildTypes {
        release {
            isMinifyEnabled = false
            // a personal app: the debug key signs releases too, so `assembleRelease` installs straight away
            signingConfig = signingConfigs.getByName("debug")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

kotlin {
    compilerOptions { jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17) }
}

dependencies {
    implementation("androidx.core:core-ktx:1.17.0")
    implementation("androidx.appcompat:appcompat:1.7.1")
    implementation("androidx.activity:activity-ktx:1.11.0")
    implementation("androidx.window:window:1.4.0")
    implementation("androidx.webkit:webkit:1.14.0")
    implementation("com.google.android.material:material:1.13.0")
}
