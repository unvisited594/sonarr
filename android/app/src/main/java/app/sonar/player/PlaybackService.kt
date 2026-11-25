package app.sonar.player

import android.app.PendingIntent
import android.content.Intent
import androidx.media3.common.ForwardingPlayer
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.session.MediaSession
import androidx.media3.session.MediaSessionService
import app.sonar.ui.MainActivity

/** Фоновое воспроизведение: уведомление, экран блокировки, наушники, Android Auto. */
@androidx.annotation.OptIn(UnstableApi::class)
class PlaybackService : MediaSessionService() {
    private var session: MediaSession? = null

    override fun onCreate() {
        super.onCreate()
        Hub.init(this)
        // кнопки «дальше/назад» в уведомлении ведут в нашу очередь, а не в плейлист ExoPlayer
        val player = object : ForwardingPlayer(Hub.exo) {
            private val extra = listOf(Player.COMMAND_SEEK_TO_NEXT, Player.COMMAND_SEEK_TO_PREVIOUS,
                Player.COMMAND_SEEK_TO_NEXT_MEDIA_ITEM, Player.COMMAND_SEEK_TO_PREVIOUS_MEDIA_ITEM)

            override fun getAvailableCommands(): Player.Commands =
                super.getAvailableCommands().buildUpon().apply { extra.forEach { add(it) } }.build()

            override fun isCommandAvailable(command: Int): Boolean = command in extra || super.isCommandAvailable(command)
            override fun hasNextMediaItem(): Boolean = true
            override fun hasPreviousMediaItem(): Boolean = true
            override fun seekToNext() = Hub.next()
            override fun seekToNextMediaItem() = Hub.next()
            override fun seekToPrevious() = Hub.prev()
            override fun seekToPreviousMediaItem() = Hub.prev()
        }
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        session = MediaSession.Builder(this, player).setSessionActivity(open).build()
    }

    override fun onGetSession(controllerInfo: MediaSession.ControllerInfo): MediaSession? = session

    override fun onTaskRemoved(rootIntent: Intent?) {
        if (!Hub.exo.playWhenReady) stopSelf()   // смахнули приложение на паузе — закрываемся
    }

    override fun onDestroy() {
        session?.release()
        session = null
        super.onDestroy()
    }
}
