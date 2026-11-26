package app.sonar.update

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.core.content.FileProvider
import app.sonar.BuildConfig
import app.sonar.net.Http
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.File

data class Release(val version: String, val notes: String, val apkUrl: String?, val pageUrl: String)

/** Обновления из релизов на GitHub: тот же репозиторий, что и у ПК-версии. */
object Updater {
    private val json = Json { ignoreUnknownKeys = true }

    val current: String get() = BuildConfig.VERSION_NAME

    private fun parse(v: String): List<Int>? =
        Regex("""^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?""").find(v.trim())?.groupValues?.drop(1)?.map { it.toIntOrNull() ?: 0 }

    fun isNewer(remote: String, local: String = current): Boolean {
        val r = parse(remote) ?: return false
        val l = parse(local) ?: return false
        for (i in 0 until 3) if (r[i] != l[i]) return r[i] > l[i]
        return false
    }

    /** Блокирующий вызов. */
    fun latest(): Release? {
        val body = Http.get("https://api.github.com/repos/${BuildConfig.GITHUB_REPO}/releases/latest")
        val o = json.parseToJsonElement(body).jsonObject
        val tag = o["tag_name"]?.jsonPrimitive?.content ?: return null
        val apk = o["assets"]?.jsonArray?.map { it.jsonObject }?.firstOrNull {
            it["name"]?.jsonPrimitive?.content?.lowercase()?.endsWith(".apk") == true
        }?.get("browser_download_url")?.jsonPrimitive?.content
        val notes = o["body"]?.takeIf { it.toString() != "null" }?.jsonPrimitive?.content ?: ""
        return Release(tag.removePrefix("v"), notes, apk,
            o["html_url"]?.jsonPrimitive?.content ?: "https://github.com/${BuildConfig.GITHUB_REPO}/releases")
    }

    /** Блокирующий вызов: скачать APK во временную папку. progress(0..1). */
    fun download(context: Context, url: String, progress: (Float) -> Unit): File {
        val dir = File(context.cacheDir, "updates").apply { mkdirs() }
        val out = File(dir, "sonar-update.apk")
        val req = okhttp3.Request.Builder().url(url).header("User-Agent", "Sonar Android").build()
        Http.client.newCall(req).execute().use { resp ->
            if (!resp.isSuccessful) throw java.io.IOException("HTTP ${resp.code}")
            val body = resp.body ?: throw java.io.IOException("пустой ответ")
            val total = body.contentLength().coerceAtLeast(1)
            var done = 0L
            body.byteStream().use { input ->
                out.outputStream().use { output ->
                    val buf = ByteArray(64 * 1024)
                    while (true) {
                        val n = input.read(buf)
                        if (n < 0) break
                        output.write(buf, 0, n)
                        done += n
                        progress((done.toFloat() / total).coerceAtMost(1f))
                    }
                }
            }
        }
        return out
    }

    /** Открыть установщик Android. Если нет разрешения ставить приложения — сначала отправить в настройки. */
    fun install(context: Context, apk: File): Boolean {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && !context.packageManager.canRequestPackageInstalls()) {
            context.startActivity(Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                Uri.parse("package:${context.packageName}")).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            return false
        }
        val uri = FileProvider.getUriForFile(context, "${context.packageName}.files", apk)
        context.startActivity(Intent(Intent.ACTION_VIEW).setDataAndType(uri, "application/vnd.android.package-archive")
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK))
        return true
    }
}
