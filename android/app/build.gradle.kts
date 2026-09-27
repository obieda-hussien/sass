plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.plugin.compose")
}

val configuredApiBaseUrl = providers.gradleProperty("FULFILLOS_API_BASE_URL")
    .orElse(providers.environmentVariable("FULFILLOS_API_BASE_URL"))

android {
    namespace = "com.obieda.fulfillos"
    compileSdk = 37

    defaultConfig {
        applicationId = "com.obieda.fulfillos"
        minSdk = 26
        targetSdk = 36
        versionCode = 4
        versionName = "0.2.2"
    }

    buildTypes {
        getByName("debug") {
            applicationIdSuffix = ".debug"
            versionNameSuffix = "-debug"
            val debugUrl = configuredApiBaseUrl.orElse("http://10.0.2.2:8080").get()
            buildConfigField("String", "API_BASE_URL", "\"$debugUrl\"")
        }
        getByName("release") {
            isDebuggable = false
            isMinifyEnabled = false
            val releaseUrl = configuredApiBaseUrl.orNull
                ?: error("FULFILLOS_API_BASE_URL must be set for release builds")
            require(releaseUrl.startsWith("https://")) {
                "Release API URL must use HTTPS: $releaseUrl"
            }
            buildConfigField("String", "API_BASE_URL", "\"$releaseUrl\"")
            signingConfig = signingConfigs.getByName("debug")
        }
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }
    packaging {
        resources.excludes += "/META-INF/{AL2.0,LGPL2.1}"
    }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2026.09.00")
    implementation(composeBom)
    implementation("androidx.activity:activity-compose:1.12.0")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.11.0")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.11.0")
    implementation("androidx.work:work-runtime-ktx:2.12.0")
    debugImplementation("androidx.compose.ui:ui-tooling")
}
