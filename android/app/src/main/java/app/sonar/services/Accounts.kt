package app.sonar.services

import app.sonar.data.Store
import app.sonar.model.Resolved
import app.sonar.model.Track
import app.sonar.net.Http
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.longOrNull
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonObject
import okhttp3.FormBody
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.net.URLEncoder
import java.security.MessageDigest

private val json = Json { ignoreUnknownKeys = true }

private fun enc(s: String) = URLEncoder.encode(s, "UTF-8")
private fun hexOf(b: ByteArray) = b.joinToString("") { "%02x".format(it) }
private fun JsonElement?.str(): String? = (this as? JsonPrimitive)?.takeIf { it.isString }?.content
private fun JsonObject.obj(k: String) = this[k] as? JsonObject
private fun JsonObject.arr(k: String) = this[k] as? JsonArray

private fun call(req: Request): String = Http.client.newCall(req).execute().use { r ->
    val body = r.body?.string() ?: ""
    if (r.code == 401 || r.code == 403) throw IllegalStateException("Вход устарел — войдите в аккаунт ещё раз")
    if (!r.isSuccessful) throw IllegalStateException("HTTP ${r.code}")
    body
}

/** Ключи аккаунтов в настройках. */
object AccountKeys {
    const val YANDEX = "yandex_token"
    const val SOUNDCLOUD = "soundcloud_token"
    const val YOUTUBE = "ytmusic_cookie"
    const val DEEZER = "deezer_profile"

    fun get(key: String): String? = Store.settings.value.accounts[key]?.takeIf { it.isNotBlank() }
    fun set(key: String, value: String?) = Store.updateSettings {
        it.copy(accounts = if (value.isNullOrBlank()) it.accounts - key else it.accounts + (key to value))
    }
}

// ---------------- Яндекс Музыка ----------------

/** Яндекс Музыка: тот же API, что у официального приложения (вход — OAuth-токен, как на ПК). */
class YandexMusic(private val token: String) : MusicService {
    override val id = "yandex"
    override val name = "Яндекс Музыка"
    private val api = "https://api.music.yandex.net"

    companion object {
        /** Тот же client_id, что у ПК-версии: так токен получают все сторонние клиенты. */
        const val LOGIN_URL = "https://oauth.yandex.ru/authorize?response_type=token&client_id=23cabbbdc6cd418abb4b39c32c41195d"
        const val REDIRECT_PREFIX = "https://music.yandex.ru/#access_token"
        private const val SIGN_SALT = "XGRlBW9FXlekgbPrRHuSiA"
    }

    private fun req(path: String) = Request.Builder().url(api + path)
        .header("Authorization", "OAuth $token").header("X-Yandex-Music-Client", "YandexMusicAndroid/24023621")

    private fun get(path: String): JsonObject =
        json.parseToJsonElement(call(req(path).build())).jsonObject

    private fun cover(o: JsonObject): String? =
        (o["coverUri"].str() ?: o.obj("album")?.get("coverUri").str() ?: o.arr("albums")?.firstOrNull()?.jsonObject?.get("coverUri").str())
            ?.let { "https://" + it.replace("%%", "400x400") }

    private fun track(o: JsonObject): Track? {
        val tid = (o["id"] as? JsonPrimitive)?.content ?: return null
        if (o["available"]?.jsonPrimitive?.content == "false") return null
        return Track(
            id = tid,
            title = o["title"].str() ?: return null,
            artist = o.arr("artists")?.mapNotNull { it.jsonObject["name"].str() }?.joinToString(", ") ?: "",
            durationMs = o["durationMs"]?.jsonPrimitive?.longOrNull ?: 0L,
            artworkUrl = cover(o),
            serviceId = id,
        )
    }

    fun uid(): String = get("/account/status").obj("result")?.obj("account")?.get("uid")?.jsonPrimitive?.content
        ?: throw IllegalStateException("Яндекс не узнал аккаунт — войдите ещё раз")

    override fun search(query: String): List<Track> =
        get("/search?text=${enc(query)}&type=track&page=0").obj("result")?.obj("tracks")?.arr("results")
            ?.mapNotNull { track(it.jsonObject) } ?: emptyList()

    /** «Мне нравится» Яндекса. */
    fun likes(): List<Track> {
        val ids = get("/users/${uid()}/likes/tracks").obj("result")?.obj("library")?.arr("tracks")
            ?.mapNotNull { it.jsonObject["id"]?.jsonPrimitive?.content }?.take(300) ?: return emptyList()
        val out = mutableListOf<Track>()
        for (chunk in ids.chunked(100)) {
            val body = FormBody.Builder().add("track-ids", chunk.joinToString(",")).build()
            val r = json.parseToJsonElement(call(req("/tracks").post(body).build())).jsonObject
            out += r.arr("result")?.mapNotNull { track(it.jsonObject) } ?: emptyList()
        }
        return out
    }

    /** «Моя волна» Яндекса. */
    override fun wave(): List<Track> =
        get("/rotor/station/user:onyourwave/tracks").obj("result")?.arr("sequence")
            ?.mapNotNull { it.jsonObject.obj("track")?.let { t -> track(t) } } ?: emptyList()

    override fun resolve(track: Track): Resolved {
        val infos = get("/tracks/${track.id}/download-info").arr("result")?.map { it.jsonObject } ?: emptyList()
        val best = infos.filter { it["codec"].str() == "mp3" }.maxByOrNull { it["bitrateInKbps"]?.jsonPrimitive?.content?.toIntOrNull() ?: 0 }
            ?: throw IllegalStateException("Трек недоступен в Яндекс Музыке")
        val xml = call(Request.Builder().url(best["downloadInfoUrl"].str()!!).build())
        fun tag(n: String) = Regex("<$n>([^<]*)</$n>").find(xml)?.groupValues?.get(1) ?: ""
        val host = tag("host"); val path = tag("path"); val ts = tag("ts"); val s = tag("s")
        val sign = hexOf(MessageDigest.getInstance("MD5").digest((SIGN_SALT + path.drop(1) + s).toByteArray()))
        return Resolved("https://$host/get-mp3/$sign/$ts$path")
    }
}

// ---------------- SoundCloud: лайки аккаунта ----------------

/** Лайки SoundCloud по токену из входа (cookie oauth_token). Играют через обычный SoundCloud. */
class SoundCloudAccount(private val token: String) {
    companion object {
        const val LOGIN_URL = "https://soundcloud.com/signin"
        private var clientId: String? = null
    }

    private fun clientId(): String {
        clientId?.let { return it }
        val page = Http.get("https://soundcloud.com/")
        val scripts = Regex("""<script[^>]+src="(https://a-v2\.sndcdn\.com/assets/[^"]+\.js)"""").findAll(page)
            .map { it.groupValues[1] }.toList().reversed()
        for (src in scripts) {
            val m = Regex("""client_id\s*[:=]\s*"([A-Za-z0-9]{32})"""").find(runCatching { Http.get(src) }.getOrDefault(""))
            if (m != null) return m.groupValues[1].also { clientId = it }
        }
        throw IllegalStateException("Не удалось подготовить SoundCloud — попробуйте позже")
    }

    private fun get(path: String): JsonObject {
        val sep = if ('?' in path) '&' else '?'
        val r = Request.Builder().url("https://api-v2.soundcloud.com$path${sep}client_id=${clientId()}")
            .header("Authorization", "OAuth $token").build()
        return json.parseToJsonElement(call(r)).jsonObject
    }

    fun likes(): List<Track> {
        val me = get("/me")["id"]?.jsonPrimitive?.content ?: return emptyList()
        return get("/users/$me/track_likes?limit=200").arr("collection")?.mapNotNull { item ->
            val t = item.jsonObject.obj("track") ?: return@mapNotNull null
            val url = t["permalink_url"].str() ?: return@mapNotNull null
            Track(id = url, title = t["title"].str() ?: "", artist = t.obj("user")?.get("username").str() ?: "",
                durationMs = t["duration"]?.jsonPrimitive?.longOrNull ?: 0L,
                artworkUrl = t["artwork_url"].str()?.replace("-large", "-t500x500"), serviceId = "soundcloud", url = url)
        } ?: emptyList()
    }
}

// ---------------- YouTube Music: понравившиеся ----------------

/** «Понравившиеся» YouTube Music по cookie аккаунта Google (вход во встроенном браузере). */
class YouTubeAccount(private val cookie: String) {
    companion object {
        const val LOGIN_URL = "https://accounts.google.com/ServiceLogin?service=youtube&continue=https%3A%2F%2Fmusic.youtube.com%2F"
        const val ORIGIN = "https://music.youtube.com"
    }

    private fun auth(): String {
        val sapisid = Regex("""(?:^|;\s*)__Secure-3PAPISID=([^;]+)""").find(cookie)?.groupValues?.get(1)
            ?: Regex("""(?:^|;\s*)SAPISID=([^;]+)""").find(cookie)?.groupValues?.get(1)
            ?: throw IllegalStateException("Войдите в аккаунт Google ещё раз")
        val ts = System.currentTimeMillis() / 1000
        val hash = hexOf(MessageDigest.getInstance("SHA-1").digest("$ts $sapisid $ORIGIN".toByteArray()))
        return "SAPISIDHASH ${ts}_$hash"
    }

    private fun browse(browseId: String): JsonObject {
        val body = buildJsonObject {
            putJsonObject("context") { putJsonObject("client") { put("clientName", "WEB_REMIX"); put("clientVersion", "1.20241202.01.00"); put("hl", "ru") } }
            put("browseId", browseId)
        }.toString().toRequestBody("application/json".toMediaType())
        val r = Request.Builder().url("$ORIGIN/youtubei/v1/browse?prettyPrint=false").post(body)
            .header("cookie", cookie).header("authorization", auth()).header("x-origin", ORIGIN).header("origin", ORIGIN)
            .header("x-goog-authuser", "0").header("user-agent", Http.USER_AGENT).build()
        return json.parseToJsonElement(call(r)).jsonObject
    }

    /** Ищем строки треков где угодно в ответе — так переживём перестановки в разметке YouTube. */
    private fun collect(el: JsonElement, out: MutableList<JsonObject>) {
        when (el) {
            is JsonObject -> {
                el.obj("musicResponsiveListItemRenderer")?.let { out += it }
                for ((_, v) in el) collect(v, out)
            }
            is JsonArray -> el.forEach { collect(it, out) }
            else -> {}
        }
    }

    private fun runsText(col: JsonObject?): String =
        col?.obj("musicResponsiveListItemFlexColumnRenderer")?.obj("text")?.arr("runs")
            ?.mapNotNull { it.jsonObject["text"].str() }?.joinToString("") ?: ""

    fun likes(): List<Track> {
        val rows = mutableListOf<JsonObject>()
        collect(browse("VLLM"), rows)
        return rows.mapNotNull { r ->
            val vid = r.obj("playlistItemData")?.get("videoId").str()
                ?: Regex(""""videoId":"([\w-]{11})"""").find(r.toString())?.groupValues?.get(1) ?: return@mapNotNull null
            val cols = r.arr("flexColumns")?.map { it.jsonObject } ?: emptyList()
            val title = runsText(cols.getOrNull(0)).ifBlank { return@mapNotNull null }
            val artist = runsText(cols.getOrNull(1)).split(" • ").first()
            val thumb = r.obj("thumbnail")?.obj("musicThumbnailRenderer")?.obj("thumbnail")?.arr("thumbnails")
                ?.lastOrNull()?.jsonObject?.get("url").str()?.replace(Regex("""=w\d+-h\d+"""), "=w400-h400")
            val url = "https://music.youtube.com/watch?v=$vid"
            Track(id = url, title = title, artist = artist, artworkUrl = thumb, serviceId = "ytmusic", url = url)
        }.distinctBy { it.id }
    }
}

// ---------------- Deezer: избранное открытого профиля ----------------

/** Deezer: избранное открытого профиля; звук — тот же трек в YouTube Music (Deezer шифрует потоки). */
class DeezerProfile(private val profile: String) : MusicService {
    override val id = "deezer"
    override val name = "Deezer"
    private val userId = Regex("""(\d{3,})""").find(profile)?.groupValues?.get(1) ?: profile

    private fun track(o: JsonObject) = Track(
        id = (o["id"] as? JsonPrimitive)?.content ?: "",
        title = o["title"].str() ?: "",
        artist = o.obj("artist")?.get("name").str() ?: "",
        durationMs = (o["duration"]?.jsonPrimitive?.longOrNull ?: 0L) * 1000,
        artworkUrl = o.obj("album")?.get("cover_xl").str() ?: o.obj("album")?.get("cover_big").str(),
        serviceId = id,
    )

    fun likes(): List<Track> {
        val r = json.parseToJsonElement(Http.get("https://api.deezer.com/user/$userId/tracks?limit=300")).jsonObject
        if (r.obj("error") != null) throw IllegalStateException("Профиль Deezer закрыт или не найден")
        return r.arr("data")?.map { track(it.jsonObject) } ?: emptyList()
    }

    override fun search(query: String): List<Track> {
        val r = json.parseToJsonElement(Http.get("https://api.deezer.com/search?q=${enc(query)}&limit=50")).jsonObject
        return r.arr("data")?.map { track(it.jsonObject) } ?: emptyList()
    }

    /** Играем тот же трек из YouTube Music: ищем «исполнитель название», сверяем длительность. */
    override fun resolve(track: Track): Resolved {
        val found = Services.youtube.search("${track.artist} ${track.title}")
        val best = found.minByOrNull { kotlin.math.abs(it.durationMs - track.durationMs) }
            ?: throw IllegalStateException("Не нашёл этот трек в YouTube Music")
        return Services.youtube.resolve(best)
    }
}
