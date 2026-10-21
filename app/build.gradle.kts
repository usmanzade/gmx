plugins {
    alias(libs.plugins.android.application)
}

val keystorePath: String? = providers.environmentVariable("KEYSTORE_PATH").orNull

android {
    namespace = "com.usmanzade.gmx"
    compileSdk = 37

    defaultConfig {
        applicationId = "com.usmanzade.gmx"
        minSdk = 28
        targetSdk = 37
        versionCode = providers.gradleProperty("GMX_VERSION_CODE").get().toInt()
        versionName = providers.gradleProperty("GMX_VERSION_NAME").get()
    }

    signingConfigs {
        if (keystorePath != null) {
            create("release") {
                storeFile = file(keystorePath)
                storePassword = providers.environmentVariable("KEYSTORE_PASSWORD").get()
                keyAlias = providers.environmentVariable("KEY_ALIAS").get()
                keyPassword = providers.environmentVariable("KEY_PASSWORD").get()
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
            if (keystorePath != null) {
                signingConfig = signingConfigs.getByName("release")
            }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    lint {
        abortOnError = false
    }
}

dependencies {
    compileOnly(libs.libxposed.api)
}
