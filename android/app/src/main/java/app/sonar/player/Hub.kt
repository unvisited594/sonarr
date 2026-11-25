package app.sonar.player

import android.content.Context
import android.net.Uri
import android.util.Log
import androidx.media3.common.AudioAttributes
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.common.MimeTypes
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.exoplayer.ExoPlayer
import app.sonar.data.Store
import app.sonar.model.Track
import app.sonar.services.Services
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

data class PlayerState(
    val queue: List<Track> = emptyList(),
    val index: Int = -1,
    val playing: Boolean = false,
    val loading: Boolean = false,
    val error: String? = null,
) {
    val current: Track? get() = queue.getOrNull(index)
}

/**
 * Плеер всего приложения: очередь, получение адреса потока и ExoPlayer.
 * Один на процесс; уведомление и экран блокировки — через PlaybackService (MediaSession).
 * Очередь заканчивается — дописываем похожие треки (бесконечная волна).
 */
@androidx.annotation.OptIn(UnstableApi::class)
object Hub {
    private const val TAG = "SonarHub"
    lateinit var exo: ExoPlayer
        private set
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private var job: Job? = null
    private var related: List<Track> = emptyList()
    private var failures = 0

    private val _state = MutableStateFlow(PlayerState())
    val state: StateFlow<PlayerState> = _state

    fun init(context: Context) {
        if (::exo.isInitialized) return
        exo = ExoPlayer.Builder(context.applicationContext)
            .setAudioAttributes(AudioAttributes.Builder().setUsage(C.USAGE_MEDIA)
                .setContentType(C.AUDIO_CONTENT_TYPE_MUSIC).build(), true)
            .setHandleAudioBecomingNoisy(true)
            .setWakeMode(C.WAKE_MODE_NETWORK)
            .build()
        Eq.attach(exo.audioSessionId)
        scope.launch { Store.look.collect { Eq.apply(it) } }
        exo.addListener(object : Player.Listener {
            override fun onIsPlayingChanged(isPlaying: Boolean) {
                _state.value = _state.value.copy(playing = isPlaying)
            }

            override fun onPlaybackStateChanged(playbackState: Int) {
                if (playbackState == Player.STATE_ENDED) next()
                if (playbackState == Player.STATE_READY) {
                    failures = 0
                    _state.value = _state.value.copy(loading = false)
                }
            }

            override fun onAudioSessionIdChanged(audioSessionId: Int) {
                Eq.attach(audioSessionId)   // эквалайзер цепляется к звуку плеера
            }

            override fun onPlayerError(error: PlaybackException) {
                Log.w(TAG, "ошибка воспроизведения", error)
                skipAfterError("Трек не играет: ${error.errorCodeName}")
            }
        })
    }

    fun playQueue(tracks: List<Track>, index: Int) {
        if (tracks.isEmpty()) return
        related = emptyList()
        _state.value = PlayerState(queue = tracks, index = index.coerceIn(0, tracks.size - 1))
        start()
    }

    private fun start() {
        val track = _state.value.current ?: return
        job?.cancel()
        exo.stop()
        _state.value = _state.value.copy(loading = true, error = null)
        job = scope.launch {
            try {
                val service = Services.get(track.serviceId) ?: throw IllegalStateException("Сервис трека не подключён")
                val resolved = withContext(Dispatchers.IO) { service.resolve(track) }
                related = resolved.related
                val meta = MediaMetadata.Builder()
                    .setTitle(track.title)
                    .setArtist(track.artist)
                    .setArtworkUri(track.artworkUrl?.let { Uri.parse(it) })
                    .build()
                val item = MediaItem.Builder()
                    .setMediaId(track.key)
                    .setUri(resolved.streamUrl)
                    .setMediaMetadata(meta)
                    .apply { if (resolved.hls) setMimeType(MimeTypes.APPLICATION_M3U8) }
                    .build()
                exo.setMediaItem(item)
                exo.prepare()
                exo.play()
                Store.addHistory(track)
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e
            } catch (e: Exception) {
                Log.w(TAG, "не получилось включить ${track.title}", e)
                skipAfterError("«${track.title}»: ${e.message ?: "не удалось включить"}")
            }
        }
    }

    private fun skipAfterError(message: String) {
        failures++
        _state.value = _state.value.copy(loading = false, error = message)
        if (failures < 4) next() else failures = 0   // много ошибок подряд — останавливаемся
    }

    fun toggle() {
        if (_state.value.current == null) return
        if (exo.isPlaying) exo.pause() else {
            if (exo.playbackState == Player.STATE_IDLE) start() else exo.play()
        }
    }

    fun next() {
        val s = _state.value
        if (s.index + 1 < s.queue.size) {
            _state.value = s.copy(index = s.index + 1)
            start()
            return
        }
        // очередь кончилась — бесконечная волна из похожих
        val known = s.queue.map { it.key }.toSet()
        val more = related.filter { it.key !in known }.take(20)
        if (more.isNotEmpty()) {
            _state.value = s.copy(queue = s.queue + more, index = s.index + 1)
            start()
        } else {
            exo.pause()
        }
    }

    fun prev() {
        val s = _state.value
        if (exo.currentPosition > 3000 || s.index <= 0) {
            exo.seekTo(0)
        } else {
            _state.value = s.copy(index = s.index - 1)
            start()
        }
    }

    fun seek(ms: Long) = exo.seekTo(ms)

    fun playAt(index: Int) {
        val s = _state.value
        if (index in s.queue.indices) {
            _state.value = s.copy(index = index)
            start()
        }
    }
}
