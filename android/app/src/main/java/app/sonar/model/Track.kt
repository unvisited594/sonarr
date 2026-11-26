package app.sonar.model

import kotlinx.serialization.Serializable

/** Трек из любого сервиса. id уникален внутри сервиса, url — страница трека (для YouTube/SoundCloud). */
@Serializable
data class Track(
    val id: String,
    val title: String,
    val artist: String,
    val durationMs: Long = 0,
    val artworkUrl: String? = null,
    val serviceId: String,
    val url: String? = null,
) {
    val key: String get() = "$serviceId:$id"
}

/** Готовый к воспроизведению адрес потока и похожие треки (для бесконечной волны). */
data class Resolved(
    val streamUrl: String,
    val hls: Boolean = false,
    val related: List<Track> = emptyList(),
)
