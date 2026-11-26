package app.sonar.data

import android.content.Context
import app.sonar.model.Track
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.serialization.Serializable
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json
import java.io.File

@Serializable
data class NavidromeLogin(val url: String, val user: String, val token: String, val salt: String)

@Serializable
data class Settings(
    val navidrome: NavidromeLogin? = null,
    val autoUpdate: Boolean = true,
    val skipVersion: String = "",
)

/** Лайки, история и настройки — JSON-файлы в памяти приложения. */
object Store {
    private val json = Json { ignoreUnknownKeys = true; encodeDefaults = true }
    private lateinit var dir: File

    private val _likes = MutableStateFlow<List<Track>>(emptyList())
    val likes: StateFlow<List<Track>> = _likes
    private val _history = MutableStateFlow<List<Track>>(emptyList())
    val history: StateFlow<List<Track>> = _history
    private val _settings = MutableStateFlow(Settings())
    val settings: StateFlow<Settings> = _settings

    fun init(context: Context) {
        dir = context.filesDir
        _likes.value = readList("likes.json")
        _history.value = readList("history.json")
        _settings.value = runCatching { json.decodeFromString(Settings.serializer(), File(dir, "settings.json").readText()) }
            .getOrDefault(Settings())
    }

    private fun readList(name: String): List<Track> = runCatching {
        json.decodeFromString(ListSerializer(Track.serializer()), File(dir, name).readText())
    }.getOrDefault(emptyList())

    private fun writeList(name: String, list: List<Track>) {
        runCatching { File(dir, name).writeText(json.encodeToString(ListSerializer(Track.serializer()), list)) }
    }

    fun isLiked(track: Track) = _likes.value.any { it.key == track.key }

    fun toggleLike(track: Track) {
        val now = _likes.value
        _likes.value = if (isLiked(track)) now.filterNot { it.key == track.key } else listOf(track) + now
        writeList("likes.json", _likes.value)
    }

    fun addHistory(track: Track) {
        _history.value = (listOf(track) + _history.value.filterNot { it.key == track.key }).take(200)
        writeList("history.json", _history.value)
    }

    fun updateSettings(change: (Settings) -> Settings) {
        _settings.value = change(_settings.value)
        runCatching { File(dir, "settings.json").writeText(json.encodeToString(Settings.serializer(), _settings.value)) }
    }
}
