package app.sonar.services

import app.sonar.BuildConfig
import app.sonar.data.Store
import app.sonar.model.Resolved
import app.sonar.model.Track

/** Музыкальный сервис: поиск, адрес потока, «волна». Все методы — из фонового потока. */
interface MusicService {
    val id: String
    val name: String
    fun search(query: String): List<Track>
    fun resolve(track: Track): Resolved
    fun wave(): List<Track> = emptyList()
}

object Services {
    val youtube = NewPipeService.youtubeMusic()
    val soundcloud = NewPipeService.soundcloud()

    /** Navidrome: свой (из настроек) или общий, вшитый в сборку. */
    val navidrome: Navidrome?
        get() {
            val own = Store.settings.value.navidrome
            if (own != null) return Navidrome(own.url, own.user, own.token, own.salt, own.user)
            if (BuildConfig.SHARED_URL.isNotBlank() && BuildConfig.SHARED_TOKEN.isNotBlank()) {
                return Navidrome(BuildConfig.SHARED_URL, BuildConfig.SHARED_USER, BuildConfig.SHARED_TOKEN,
                    BuildConfig.SHARED_SALT, BuildConfig.SHARED_NAME)
            }
            return null
        }

    val yandex: YandexMusic? get() = AccountKeys.get(AccountKeys.YANDEX)?.let { YandexMusic(it) }
    val deezer: DeezerProfile? get() = AccountKeys.get(AccountKeys.DEEZER)?.let { DeezerProfile(it) }

    fun all(): List<MusicService> = listOfNotNull(navidrome, youtube, soundcloud, yandex, deezer)

    fun get(id: String): MusicService? = all().firstOrNull { it.id == id }
}
