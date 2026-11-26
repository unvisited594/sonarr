package app.sonar.services

import app.sonar.model.Resolved
import app.sonar.model.Track
import org.schabi.newpipe.extractor.InfoItem
import org.schabi.newpipe.extractor.ServiceList
import org.schabi.newpipe.extractor.StreamingService
import org.schabi.newpipe.extractor.stream.DeliveryMethod
import org.schabi.newpipe.extractor.stream.StreamInfo
import org.schabi.newpipe.extractor.stream.StreamInfoItem

/** YouTube Music и SoundCloud через NewPipeExtractor — без входа в аккаунт. */
class NewPipeService private constructor(
    private val service: StreamingService,
    override val id: String,
    override val name: String,
    private val filters: List<String>,
) : MusicService {

    companion object {
        fun youtubeMusic() = NewPipeService(ServiceList.YouTube, "ytmusic", "YouTube Music", listOf("music_songs"))
        fun soundcloud() = NewPipeService(ServiceList.SoundCloud, "soundcloud", "SoundCloud", listOf("tracks"))
    }

    private fun toTrack(item: StreamInfoItem): Track {
        val cover = item.thumbnails.maxByOrNull { it.height }?.url
        return Track(
            id = item.url,
            title = item.name ?: "",
            artist = item.uploaderName ?: "",
            durationMs = maxOf(0L, item.duration) * 1000,
            artworkUrl = cover,
            serviceId = id,
            url = item.url,
        )
    }

    private fun items(list: List<InfoItem>): List<Track> =
        list.filterIsInstance<StreamInfoItem>().map { toTrack(it) }.filter { it.title.isNotBlank() }

    override fun search(query: String): List<Track> {
        val ex = service.getSearchExtractor(query, filters, "")
        ex.fetchPage()
        return items(ex.initialPage.items)
    }

    override fun resolve(track: Track): Resolved {
        val info = StreamInfo.getInfo(service, track.url ?: track.id)
        val streams = info.audioStreams.filter { it.isUrl }
        val best = streams.filter { it.deliveryMethod == DeliveryMethod.PROGRESSIVE_HTTP }.maxByOrNull { it.averageBitrate }
            ?: streams.firstOrNull { it.deliveryMethod == DeliveryMethod.HLS }
            ?: throw IllegalStateException("У трека нет аудиопотока")
        return Resolved(best.content, best.deliveryMethod == DeliveryMethod.HLS, items(info.relatedItems))
    }

    override fun wave(): List<Track> = search(if (id == "ytmusic") "хиты" else "trending")
}
