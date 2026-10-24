plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.atamisfilho.aircrosscockpit"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.atamisfilho.aircrosscockpit"
        minSdk = 29          // Android 10+ (seu S25 Ultra está muito acima disso)
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"
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

    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    // Android Auto (Car App Library) — telas + Surface p/ vídeo
    implementation("androidx.car.app:car-app:1.4.0")

    // Media3 / ExoPlayer — reprodução de áudio e vídeo
    implementation("androidx.media3:media3-exoplayer:1.4.1")
    implementation("androidx.media3:media3-session:1.4.1")
    implementation("androidx.media3:media3-ui:1.4.1")

    // ListenableFuture (usado pelas APIs do Car App e media3)
    implementation("com.google.guava:guava:33.3.1-android")

    // Android básico
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.activity:activity-ktx:1.9.2")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.4")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")
}
