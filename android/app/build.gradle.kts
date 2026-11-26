import java.security.MessageDigest
import java.security.SecureRandom

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("org.jetbrains.kotlin.plugin.serialization")
}

// Версия из тега релиза (v1.3.0 → 1.3.0, код 10300); без тега — dev.
val tag = (System.getenv("SONAR_VERSION") ?: "").removePrefix("v")
val parts = tag.split(".").mapNotNull { it.toIntOrNull() }
val verName = if (parts.isNotEmpty()) tag else "dev"
val verCode = if (parts.isNotEmpty()) parts.getOrElse(0) { 0 } * 10000 + parts.getOrElse(1) { 0 } * 100 + parts.getOrElse(2) { 0 } else 1

// Общий сервер Navidrome: тот же секрет SHARED_NAVIDROME, что у ПК-версии. Пароль в APK не попадает —
// только токен (md5(пароль + соль)), как велит Subsonic API.
fun q(s: String) = "\"" + s.replace("\\", "\\\\").replace("\"", "\\\"") + "\""
val shared: Map<*, *> = System.getenv("SHARED_NAVIDROME")?.takeIf { it.isNotBlank() }?.let {
    groovy.json.JsonSlurper().parseText(it) as Map<*, *>
} ?: emptyMap<String, String>()
val sharedSalt = ByteArray(8).also { SecureRandom().nextBytes(it) }.joinToString("") { "%02x".format(it) }
val sharedToken = (shared["password"] as String?)?.let { pw ->
    MessageDigest.getInstance("MD5").digest((pw + sharedSalt).toByteArray()).joinToString("") { "%02x".format(it) }
} ?: (shared["token"] as String? ?: "")
val sharedSaltFinal = if (shared["password"] != null) sharedSalt else (shared["salt"] as String? ?: "")

android {
    namespace = "app.sonar"
    compileSdk = 35

    defaultConfig {
        applicationId = "app.sonar"
        minSdk = 26
        targetSdk = 35
        versionCode = verCode
        versionName = verName
        buildConfigField("String", "GITHUB_REPO", q(System.getenv("SONAR_REPO") ?: "unvisited594/sonarr"))
        buildConfigField("String", "SHARED_URL", q((shared["url"] as String?) ?: ""))
        buildConfigField("String", "SHARED_USER", q((shared["user"] as String?) ?: ""))
        buildConfigField("String", "SHARED_TOKEN", q(sharedToken))
        buildConfigField("String", "SHARED_SALT", q(sharedSaltFinal))
        buildConfigField("String", "SHARED_NAME", q((shared["name"] as String?) ?: "Общий сервер"))
    }

    // Подпись: один и тот же ключ для всех версий, иначе Android не даст обновиться поверх.
    val ks = System.getenv("ANDROID_KEYSTORE_FILE")
    signingConfigs {
        if (ks != null && file(ks).exists()) {
            create("release") {
                storeFile = file(ks)
                storePassword = System.getenv("ANDROID_KEYSTORE_PASSWORD")
                keyAlias = System.getenv("ANDROID_KEY_ALIAS") ?: "sonar"
                keyPassword = System.getenv("ANDROID_KEYSTORE_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.findByName("release") ?: signingConfigs.getByName("debug")
        }
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
        isCoreLibraryDesugaringEnabled = true   // NewPipeExtractor использует java.time и nio
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    lint {
        abortOnError = false        // предупреждения линтера не должны ронять сборку релиза
        checkReleaseBuilds = false
    }

    packaging {
        resources {
            excludes += setOf("/META-INF/{AL2.0,LGPL2.1}", "META-INF/DEPENDENCIES", "META-INF/INDEX.LIST",
                "META-INF/*.kotlin_module", "META-INF/versions/9/previous-compilation-data.bin")
        }
    }
}

dependencies {
    coreLibraryDesugaring("com.android.tools:desugar_jdk_libs_nio:2.1.5")

    val composeBom = platform("androidx.compose:compose-bom:2024.12.01")
    implementation(composeBom)
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.7")
    implementation("androidx.core:core-ktx:1.15.0")

    implementation("androidx.media3:media3-exoplayer:1.5.1")
    implementation("androidx.media3:media3-exoplayer-hls:1.5.1")
    implementation("androidx.media3:media3-session:1.5.1")

    implementation("io.coil-kt:coil-compose:2.7.0")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")

    implementation("com.github.TeamNewPipe:NewPipeExtractor:v0.27.1")
}
