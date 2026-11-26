package app.sonar.services

import app.sonar.model.Resolved
import app.sonar.model.Track
import app.sonar.net.Http
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.longOrNull
import java.net.URLEncoder
import java.security.MessageDigest

/** Navidrome (Subsonic API): поиск, поток, случайные треки как «волна». */
class Navidrome(
    baseUrl: String,
    private val user: String,
    private val token: String,
    private val salt: String,
    val label: String,
) : MusicService {
    override val id = "navidrome"
    override val name = "Navidrome"
    private val base = baseUrl.trimEnd('/').let { if (it.startsWith("http")) it else "https://$it" }

    companion object {
        fun tokenFor(password: String, salt: String): String =
            MessageDigest.getInstance("MD5").digest((password + salt).toByteArray()).joinToString("") { "%02x".format(it) }

        private val json = Json { ignoreUnknownKeys = true }
    }

    private fun enc(s: String) = URLEncoder.encode(s, "UTF-8")

    private fun url(method: String, params: Map<String, String> = emptyMap()): String {
        val all = mapOf("u" to user, "t" to token, "s" to salt, "v" to "1.16.1", "c" to "sonar-android", "f" to "json") + params
        return "$base/rest/$method.view?" + all.entries.joinToString("&") { "${enc(it.key)}=${enc(it.value)}" }
    }

    private fun call(method: String, params: Map<String, String> = emptyMap()): JsonObject {
        val root = json.parseToJsonElement(Http.get(url(method, params))).jsonObject["subsonic-response"]?.jsonObject
            ?: throw IllegalStateException("Сервер ответил не как Navidrome")
        if (root["status"]?.jsonPrimitive?.content != "ok") {
            val msg = root["error"]?.jsonObject?.get("message")?.jsonPrimitive?.content ?: "ошибка сервера"
            throw IllegalStateException(msg)
        }
        return root
    }

    private fun songs(el: JsonElement?): List<Track> = (el as? JsonArray ?: JsonArray(emptyList())).map { s ->
        val o = s.jsonObject
        fun str(k: String) = o[k]?.jsonPrimitive?.content ?: ""
        Track(
            id = str("id"),
            title = str("title"),
            artist = str("artist"),
            durationMs = (o["duration"]?.jsonPrimitive?.longOrNull ?: 0L) * 1000,
            artworkUrl = o["coverArt"]?.jsonPrimitive?.content?.let { url("getCoverArt", mapOf("id" to it, "size" to "512")) },
            serviceId = id,
        )
    }

    fun ping() {
        call("ping")
    }

    override fun search(query: String): List<Track> =
        songs(call("search3", mapOf("query" to query, "songCount" to "60", "albumCount" to "0", "artistCount" to "0"))
            ["searchResult3"]?.jsonObject?.get("song"))

    override fun resolve(track: Track) = Resolved(url("stream", mapOf("id" to track.id)))

    override fun wave(): List<Track> =
        songs(call("getRandomSongs", mapOf("size" to "60"))["randomSongs"]?.jsonObject?.get("song"))
}
