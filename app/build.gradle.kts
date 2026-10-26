plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.atamisfilho.aircrosscockpit"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.atamisfilho.aircrosscockpit"
        // Android 9+ — necessário porque os celulares que ainda têm servidor
        // MirrorLink (Galaxy S8/S9/Note8/Note9) rodam no máximo o Android 9.
        // (O S25 Ultra continua 100% suportado; minSdk baixo só amplia.)
        minSdk = 28
        targetSdk = 34
        versionCode = 2
        versionName = "1.1"
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
    implementation("androidx.car.app:app:1.4.0")
    // Implementação "projected" (espelhada no carro via Android Auto) —
    // necessária para CarHardwareManager/sensores funcionarem no modo Android Auto
    implementation("androidx.car.app:app-projected:1.4.0")

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
