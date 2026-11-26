package app.sonar.ui

import android.Manifest
import android.content.ComponentName
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.LibraryMusic
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.media3.session.MediaController
import androidx.media3.session.SessionToken
import app.sonar.data.NavidromeLogin
import app.sonar.data.Store
import app.sonar.model.Track
import app.sonar.player.Hub
import app.sonar.player.PlaybackService
import app.sonar.services.AccountKeys
import app.sonar.services.DeezerProfile
import app.sonar.services.MusicService
import app.sonar.services.SoundCloudAccount
import app.sonar.services.YandexMusic
import app.sonar.services.YouTubeAccount
import app.sonar.services.Navidrome
import app.sonar.services.Services
import app.sonar.update.Release
import app.sonar.update.Updater
import com.google.common.util.concurrent.ListenableFuture
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.security.SecureRandom
import java.util.Calendar

class MainActivity : ComponentActivity() {
    private var controller: ListenableFuture<MediaController>? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        if (Build.VERSION.SDK_INT >= 33) requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)
        // подключаемся к сервису — он держит музыку в фоне и показывает уведомление
        controller = MediaController.Builder(this, SessionToken(this, ComponentName(this, PlaybackService::class.java))).buildAsync()
        setContent { SonarTheme { SonarApp() } }
    }

    override fun onDestroy() {
        controller?.let { MediaController.releaseFuture(it) }
        super.onDestroy()
    }
}

// ---------------- корень ----------------

@Composable
fun SonarApp() {
    var tab by remember { mutableIntStateOf(0) }
    var full by remember { mutableStateOf(false) }
    var lookOpen by remember { mutableStateOf(false) }
    var release by remember { mutableStateOf<Release?>(null) }
    var login by remember { mutableStateOf<Pair<WebLoginSpec, String>?>(null) }
    val state by Hub.state.collectAsState()
    val settings by Store.settings.collectAsState()

    LaunchedEffect(Unit) {   // проверка обновлений при запуске
        if (settings.autoUpdate) {
            val r = runCatching { withContext(Dispatchers.IO) { Updater.latest() } }.getOrNull()
            if (r != null && Updater.isNewer(r.version) && r.version != settings.skipVersion) release = r
        }
    }
    BackHandler(enabled = full) { full = false }

    Box(Modifier.fillMaxSize().background(SonarColors.bg)) {
        Column(Modifier.fillMaxSize()) {
            Box(Modifier.weight(1f).fillMaxWidth().statusBarsPadding()) {
                when (tab) {
                    0 -> HomeScreen()
                    1 -> SearchScreen()
                    2 -> LibraryScreen()
                    else -> SettingsScreen(onRelease = { release = it }, onLook = { lookOpen = true },
                        onLogin = { spec, key -> login = spec to key })
                }
            }
            if (state.current != null) MiniPlayer(onOpen = { full = true })
            BottomBar(tab) { tab = it }
        }
        AnimatedVisibility(visible = full && state.current != null,
            enter = slideInVertically { it }, exit = slideOutVertically { it }) {
            FullPlayer(onClose = { full = false })
        }
        if (lookOpen) LookScreen(onClose = { lookOpen = false })
        login?.let { (spec, key) ->
            WebLogin(spec, onResult = { value -> AccountKeys.set(key, value); login = null }, onClose = { login = null })
        }
    }
    release?.let { r -> UpdateDialog(r, onDismiss = { release = null }) }
}

/** Нижнее меню: тонкое, без подложек, выбранный пункт — акцентом (как левое меню на ПК). */
@Composable
fun BottomBar(tab: Int, onTab: (Int) -> Unit) {
    val items = listOf<Triple<String, ImageVector, Int>>(
        Triple("Главная", Icons.Filled.Home, 0), Triple("Поиск", Icons.Filled.Search, 1),
        Triple("Медиатека", Icons.Filled.LibraryMusic, 2), Triple("Настройки", Icons.Filled.Settings, 3),
    )
    Row(Modifier.fillMaxWidth().background(SonarColors.bg).navigationBarsPadding().padding(top = 6.dp, bottom = 4.dp),
        horizontalArrangement = Arrangement.SpaceEvenly) {
        for ((label, icon, i) in items) {
            val on = tab == i
            Column(Modifier.weight(1f).clip(RoundedCornerShape(12.dp)).clickable { onTab(i) }.padding(vertical = 6.dp),
                horizontalAlignment = Alignment.CenterHorizontally) {
                Icon(icon, contentDescription = label, tint = if (on) SonarColors.accent else SonarColors.muted, modifier = Modifier.size(24.dp))
                Text(label, fontSize = 11.sp, fontWeight = if (on) FontWeight.Bold else FontWeight.Medium,
                    color = if (on) SonarColors.accent else SonarColors.muted)
                Box(Modifier.padding(top = 3.dp).size(width = 16.dp, height = 3.dp).clip(RoundedCornerShape(2.dp))
                    .background(if (on) SonarColors.accent else Color.Transparent))
            }
        }
    }
}

// ---------------- главная ----------------

fun greeting(): String = when (Calendar.getInstance().get(Calendar.HOUR_OF_DAY)) {
    in 5..11 -> "Доброе утро"
    in 12..17 -> "Добрый день"
    in 18..22 -> "Добрый вечер"
    else -> "Доброй ночи"
}

/** Волна: лайки вперемешку + случайное с Navidrome; если пусто — подборка YouTube Music. */
fun buildWave(likes: List<Track>): List<Track> {
    val out = mutableListOf<Track>()
    out += likes.shuffled().take(25)
    Services.navidrome?.let { nd -> runCatching { out += nd.wave().take(25) } }
    Services.yandex?.let { ya -> runCatching { out += ya.wave().take(25) } }
    if (out.isEmpty()) runCatching { out += Services.youtube.wave().take(30) }
    return out.distinctBy { it.key }.shuffled()
}

@Composable
fun HomeScreen() {
    val likes by Store.likes.collectAsState()
    val history by Store.history.collectAsState()
    val scope = rememberCoroutineScope()
    var waveBusy by remember { mutableStateOf(false) }
    var waveError by remember { mutableStateOf<String?>(null) }
    var navidrome by remember { mutableStateOf<List<Track>>(emptyList()) }
    var popular by remember { mutableStateOf<List<Track>>(emptyList()) }
    var yaWave by remember { mutableStateOf<List<Track>>(emptyList()) }
    LaunchedEffect(Unit) {
        yaWave = runCatching { withContext(Dispatchers.IO) { Services.yandex?.wave()?.take(20) ?: emptyList() } }.getOrDefault(emptyList())
        navidrome = runCatching { withContext(Dispatchers.IO) { Services.navidrome?.wave()?.take(20) ?: emptyList() } }.getOrDefault(emptyList())
        popular = runCatching { withContext(Dispatchers.IO) { Services.youtube.wave().take(20) } }.getOrDefault(emptyList())
    }

    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 20.dp)) {
        item { PageTitle(greeting(), "Вся музыка в одном плеере") }
        item {
            // «Моя волна» — живой фон и белая кнопка, как герой главной на ПК
            Box(Modifier.padding(horizontal = 16.dp, vertical = 8.dp).fillMaxWidth().height(190.dp).clip(RoundedCornerShape(26.dp))
                .clickable(enabled = !waveBusy) {
                    waveBusy = true
                    waveError = null
                    scope.launch {
                        val wave = withContext(Dispatchers.IO) { buildWave(likes) }
                        waveBusy = false
                        if (wave.isEmpty()) waveError = "Не из чего собрать волну — проверьте интернет" else Hub.playQueue(wave, 0)
                    }
                }) {
                FlowBackground(null)
                Column(Modifier.align(Alignment.BottomStart).padding(22.dp)) {
                    Text("Моя волна", fontSize = 34.sp, fontWeight = FontWeight.Black, color = Color.White)
                    Text("Лайки и похожая музыка — без остановки", color = Color.White.copy(alpha = 0.85f), fontSize = 14.sp)
                }
                Box(Modifier.align(Alignment.BottomEnd).padding(20.dp).size(60.dp).clip(CircleShape).background(Color.White),
                    contentAlignment = Alignment.Center) {
                    if (waveBusy) CircularProgressIndicator(color = Color.Black, strokeWidth = 3.dp, modifier = Modifier.size(28.dp))
                    else Icon(Icons.Filled.PlayArrow, contentDescription = "Играть", tint = Color.Black, modifier = Modifier.size(34.dp))
                }
            }
            waveError?.let { Text(it, color = SonarColors.like, modifier = Modifier.padding(horizontal = 20.dp)) }
        }
        if (yaWave.isNotEmpty()) {
            item { SectionHead("Моя волна Яндекса", "Играть") { Hub.playQueue(yaWave, 0) } }
            item { TrackShelf(yaWave) }
        }
        if (history.isNotEmpty()) {
            item { SectionHead("Недавно") }
            item { TrackShelf(history.take(20)) }
        }
        if (likes.isNotEmpty()) {
            item { SectionHead("Мои лайки", "Играть все") { Hub.playQueue(likes, 0) } }
            item { TrackShelf(likes.take(20)) }
        }
        if (navidrome.isNotEmpty()) {
            item { SectionHead(Services.navidrome?.label ?: "Navidrome") }
            item { TrackShelf(navidrome) }
        }
        if (popular.isNotEmpty()) {
            item { SectionHead("Популярное в YouTube Music") }
            item { TrackShelf(popular) }
        }
        if (history.isEmpty() && likes.isEmpty()) item {
            Text("Найдите музыку во вкладке «Поиск» — ставьте ♥, и здесь появятся ваши подборки.",
                color = SonarColors.muted, modifier = Modifier.padding(20.dp))
        }
    }
}

// ---------------- поиск ----------------

@Composable
fun SearchScreen() {
    var query by remember { mutableStateOf("") }
    var serviceId by remember { mutableStateOf("ytmusic") }
    var results by remember { mutableStateOf<List<Track>>(emptyList()) }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()
    val services = Services.all()
    val state by Hub.state.collectAsState()

    fun run(q0: String) {
        val q = q0.trim()
        val svc: MusicService = services.firstOrNull { it.id == serviceId } ?: return
        if (q.isEmpty()) return
        busy = true
        error = null
        scope.launch {
            val r = runCatching { withContext(Dispatchers.IO) { svc.search(q) } }
            busy = false
            results = r.getOrDefault(emptyList())
            error = r.exceptionOrNull()?.let { "Поиск не удался: ${it.message}" } ?: if (results.isEmpty()) "Ничего не нашлось" else null
        }
    }

    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 20.dp)) {
        item { PageTitle("Поиск") }
        item {
            Row(Modifier.padding(horizontal = 16.dp).fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(SonarColors.surface)
                .padding(horizontal = 14.dp, vertical = 13.dp), verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Filled.Search, contentDescription = null, tint = SonarColors.muted)
                Spacer(Modifier.width(10.dp))
                Box(Modifier.weight(1f)) {
                    if (query.isEmpty()) Text("Трек, исполнитель, альбом", color = SonarColors.muted, fontSize = 16.sp)
                    BasicTextField(value = query, onValueChange = { query = it }, singleLine = true,
                        textStyle = TextStyle(color = SonarColors.text, fontSize = 16.sp), cursorBrush = SolidColor(SonarColors.accent),
                        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
                        keyboardActions = KeyboardActions(onSearch = { run(query) }), modifier = Modifier.fillMaxWidth())
                }
            }
        }
        item {
            Row(Modifier.padding(horizontal = 16.dp, vertical = 12.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                for (s in services) Pill(s.name, s.id == serviceId) { serviceId = s.id; run(query) }
            }
        }
        if (busy) item { LinearProgressIndicator(Modifier.fillMaxWidth().padding(horizontal = 16.dp), color = SonarColors.accent) }
        error?.let { e -> item { Text(e, color = SonarColors.muted, modifier = Modifier.padding(20.dp, 8.dp)) } }
        if (results.isEmpty() && !busy && query.isBlank()) {
            item { SectionHead("Попробуйте") }
            item {
                Column(Modifier.padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    for (row in listOf(listOf("Хиты", "Лоу-фай", "Рок"), listOf("Рэп", "Джаз", "Электроника"))) {
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            for (q in row) Pill(q, false) { query = q; run(q) }
                        }
                    }
                }
            }
        }
        itemsIndexed(results, key = { i, t -> "$i:${t.key}" }) { i, t ->
            TrackRow(t, playing = state.current?.key == t.key) { Hub.playQueue(results, i) }
        }
    }
}

// ---------------- медиатека ----------------

@Composable
fun LibraryScreen() {
    var tab by remember { mutableIntStateOf(0) }
    val likes by Store.likes.collectAsState()
    val history by Store.history.collectAsState()
    val state by Hub.state.collectAsState()
    val settings by Store.settings.collectAsState()
    // вкладки: свои лайки, история и лайки каждого подключённого аккаунта
    val sources = buildList<Pair<String, (() -> List<Track>)?>> {
        add("Лайки" to null); add("История" to null)
        AccountKeys.get(AccountKeys.YANDEX)?.let { t -> add("Яндекс" to { YandexMusic(t).likes() }) }
        AccountKeys.get(AccountKeys.SOUNDCLOUD)?.let { t -> add("SoundCloud" to { SoundCloudAccount(t).likes() }) }
        AccountKeys.get(AccountKeys.YOUTUBE)?.let { c -> add("YouTube Music" to { YouTubeAccount(c).likes() }) }
        AccountKeys.get(AccountKeys.DEEZER)?.let { p -> add("Deezer" to { DeezerProfile(p).likes() }) }
    }
    var remote by remember { mutableStateOf<List<Track>>(emptyList()) }
    var remoteStatus by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(tab, settings.accounts) {
        val loader = sources.getOrNull(tab)?.second ?: return@LaunchedEffect
        remote = emptyList(); remoteStatus = "Загружаю…"
        val r = runCatching { withContext(Dispatchers.IO) { loader() } }
        remote = r.getOrDefault(emptyList())
        remoteStatus = r.exceptionOrNull()?.let { "Не получилось: ${it.message}" } ?: if (remote.isEmpty()) "Тут пока пусто" else null
    }
    val list = when (tab) { 0 -> likes; 1 -> history; else -> remote }
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 20.dp)) {
        item { PageTitle("Медиатека") }
        item {
            // шапка «Мои лайки»: градиентная обложка с сердцем и кнопка «Играть»
            Row(Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(92.dp).clip(RoundedCornerShape(18.dp))
                    .background(Brush.linearGradient(listOf(SonarColors.accent, Color(0xFFFF4D6D)))),
                    contentAlignment = Alignment.Center) {
                    Icon(Icons.Filled.Favorite, contentDescription = null, tint = Color.White, modifier = Modifier.size(40.dp))
                }
                Spacer(Modifier.width(16.dp))
                Column(Modifier.weight(1f)) {
                    Text(when (tab) { 0 -> "Мои лайки"; 1 -> "Прослушанное"; else -> "Лайки: ${sources.getOrNull(tab)?.first ?: ""}" },
                        fontSize = 22.sp, fontWeight = FontWeight.Black, color = SonarColors.text)
                    Text("${list.size} треков", color = SonarColors.muted)
                }
                if (list.isNotEmpty()) Box(Modifier.size(54.dp).clip(CircleShape).background(SonarColors.accent)
                    .clickable { Hub.playQueue(list, 0) }, contentAlignment = Alignment.Center) {
                    Icon(Icons.Filled.PlayArrow, contentDescription = "Играть", tint = SonarColors.onAccent, modifier = Modifier.size(30.dp))
                }
            }
        }
        item {
            Row(Modifier.padding(horizontal = 16.dp).horizontalScroll(rememberScrollState()),
                horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                sources.forEachIndexed { i, (title, _) -> Pill(title, tab == i) { tab = i } }
            }
            Spacer(Modifier.height(8.dp))
            if (tab >= 2) remoteStatus?.let { Text(it, color = SonarColors.muted, modifier = Modifier.padding(horizontal = 20.dp)) }
        }
        if (list.isEmpty() && tab < 2) item {
            Text(if (tab == 0) "Здесь появятся треки, которым вы поставите ♥" else "Здесь будет то, что вы слушали",
                color = SonarColors.muted, modifier = Modifier.padding(20.dp))
        }
        itemsIndexed(list, key = { i, t -> "$i:${t.key}" }) { i, t ->
            TrackRow(t, index = i, playing = state.current?.key == t.key) { Hub.playQueue(list, i) }
        }
    }
}

// ---------------- настройки ----------------

@Composable
private fun CardTitle(t: String) = Text(t, fontSize = 18.sp, fontWeight = FontWeight.ExtraBold, color = SonarColors.text)

@Composable
private fun Muted(t: String) = Text(t, color = SonarColors.muted, fontSize = 13.sp, modifier = Modifier.padding(top = 4.dp))

@Composable
fun SettingsScreen(onRelease: (Release) -> Unit, onLook: () -> Unit, onLogin: (WebLoginSpec, String) -> Unit) {
    val settings by Store.settings.collectAsState()
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var url by remember { mutableStateOf(settings.navidrome?.url ?: "") }
    var user by remember { mutableStateOf(settings.navidrome?.user ?: "") }
    var password by remember { mutableStateOf("") }
    var status by remember { mutableStateOf<String?>(null) }
    var updateStatus by remember { mutableStateOf<String?>(null) }

    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 30.dp)) {
        item { PageTitle("Настройки") }
        item {
            Card {
                Row(Modifier.fillMaxWidth().clickable(onClick = onLook), verticalAlignment = Alignment.CenterVertically) {
                    Box(Modifier.size(46.dp).clip(RoundedCornerShape(12.dp))
                        .background(Brush.linearGradient(listOf(SonarColors.accent, Color(0xFF00B8D4)))))
                    Spacer(Modifier.width(14.dp))
                    Column(Modifier.weight(1f)) {
                        CardTitle("Оформление")
                        Muted("Тема, фон плеера, текст песни, эквалайзер, наборы")
                    }
                    Text("›", fontSize = 28.sp, color = SonarColors.muted)
                }
            }
        }
        item { AccountsCard(onLogin) }
        item {
            Card {
                CardTitle("Navidrome")
                val shared = Services.navidrome
                Muted(when {
                    settings.navidrome != null -> "Подключён свой сервер: ${settings.navidrome?.url}"
                    shared != null -> "Подключён общий сервер «${shared.label}» — вход не нужен"
                    else -> "Не подключён. Впишите адрес своего сервера Navidrome."
                })
                Spacer(Modifier.height(10.dp))
                OutlinedTextField(url, { url = it }, label = { Text("Адрес сервера") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(user, { user = it }, label = { Text("Имя пользователя") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(password, { password = it }, label = { Text("Пароль") }, singleLine = true,
                    visualTransformation = PasswordVisualTransformation(), modifier = Modifier.fillMaxWidth())
                Spacer(Modifier.height(10.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = {
                        val salt = ByteArray(8).also { SecureRandom().nextBytes(it) }.joinToString("") { "%02x".format(it) }
                        val login = NavidromeLogin(url.trim(), user.trim(), Navidrome.tokenFor(password, salt), salt)
                        status = "Проверяю…"
                        scope.launch {
                            val ok = runCatching {
                                withContext(Dispatchers.IO) { Navidrome(login.url, login.user, login.token, login.salt, login.user).ping() }
                            }
                            if (ok.isSuccess) {
                                Store.updateSettings { it.copy(navidrome = login) }
                                password = ""
                                status = "Готово, сервер подключён"
                            } else status = "Не получилось: ${ok.exceptionOrNull()?.message}"
                        }
                    }, enabled = url.isNotBlank() && user.isNotBlank() && password.isNotBlank()) { Text("Подключить") }
                    if (settings.navidrome != null) {
                        OutlinedButton(onClick = { Store.updateSettings { it.copy(navidrome = null) }; status = "Свой сервер отключён" }) {
                            Text("Отключить свой")
                        }
                    }
                }
                status?.let { Muted(it) }
            }
        }
        item {
            Card {
                CardTitle("Обновления")
                Muted("Версия ${Updater.current}")
                Row(Modifier.fillMaxWidth().padding(top = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text("Проверять при запуске", Modifier.weight(1f), color = SonarColors.text)
                    Switch(checked = settings.autoUpdate, onCheckedChange = { on -> Store.updateSettings { it.copy(autoUpdate = on) } })
                }
                TextButton(onClick = {
                    updateStatus = "Проверяю…"
                    scope.launch {
                        val r = runCatching { withContext(Dispatchers.IO) { Updater.latest() } }
                        val rel = r.getOrNull()
                        updateStatus = when {
                            r.isFailure -> "Не получилось проверить: ${r.exceptionOrNull()?.message}"
                            rel == null -> "Релизов пока нет"
                            Updater.isNewer(rel.version) -> { onRelease(rel); "Доступна версия ${rel.version}" }
                            else -> "У вас последняя версия"
                        }
                    }
                }) { Text("Проверить сейчас") }
                updateStatus?.let { Muted(it) }
            }
        }
        item {
            Card {
                CardTitle("Sonar")
                Muted("Новости, версии для ПК и Linux — в Telegram-канале @sonar081.")
                TextButton(onClick = { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("https://t.me/sonar081"))) }) {
                    Text("Открыть канал")
                }
            }
        }
    }
}

/** Аккаунты, как на ПК: вход во встроенном браузере (Яндекс, SoundCloud, YouTube Music) или ссылка (Deezer). */
@Composable
fun AccountsCard(onLogin: (WebLoginSpec, String) -> Unit) {
    val settings by Store.settings.collectAsState()
    var deezer by remember { mutableStateOf(settings.accounts[AccountKeys.DEEZER] ?: "") }
    Card {
        CardTitle("Аккаунты")
        Muted("Войдите, чтобы видеть свои лайки и волну. Логины хранятся только на этом телефоне.")
        val rows = listOf(
            Triple("Яндекс Музыка", AccountKeys.YANDEX,
                WebLoginSpec("Вход в Яндекс", YandexMusic.LOGIN_URL, redirectPrefix = YandexMusic.REDIRECT_PREFIX)),
            Triple("SoundCloud", AccountKeys.SOUNDCLOUD,
                WebLoginSpec("Вход в SoundCloud", SoundCloudAccount.LOGIN_URL, cookieHost = "soundcloud.com",
                    cookieName = "oauth_token", desktopAgent = true)),
            Triple("YouTube Music", AccountKeys.YOUTUBE,
                WebLoginSpec("Вход в YouTube Music", YouTubeAccount.LOGIN_URL, cookieHost = "music.youtube.com",
                    cookieName = "__Secure-3PAPISID", wholeCookie = true, desktopAgent = true)),
        )
        for ((title, key, spec) in rows) {
            val on = !settings.accounts[key].isNullOrBlank()
            Row(Modifier.fillMaxWidth().padding(top = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(title, fontWeight = FontWeight.SemiBold, color = SonarColors.text)
                    Text(if (on) "Подключено" else "Не подключено", color = if (on) SonarColors.accent else SonarColors.muted, fontSize = 13.sp)
                }
                if (on) OutlinedButton(onClick = { AccountKeys.set(key, null) }) { Text("Выйти") }
                else Button(onClick = { onLogin(spec, key) }) { Text("Войти") }
            }
        }
        Spacer(Modifier.height(14.dp))
        Text("Deezer", fontWeight = FontWeight.SemiBold, color = SonarColors.text)
        Muted("Вход не нужен: ссылка на ваш открытый профиль (deezer.com/ru/profile/…). Треки играют через YouTube.")
        OutlinedTextField(deezer, { deezer = it }, singleLine = true, label = { Text("Ссылка на профиль") },
            modifier = Modifier.fillMaxWidth().padding(top = 6.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.padding(top = 8.dp)) {
            Button(onClick = { AccountKeys.set(AccountKeys.DEEZER, deezer.trim()) }, enabled = deezer.isNotBlank()) { Text("Сохранить") }
            if (!settings.accounts[AccountKeys.DEEZER].isNullOrBlank()) {
                OutlinedButton(onClick = { AccountKeys.set(AccountKeys.DEEZER, null); deezer = "" }) { Text("Убрать") }
            }
        }
        Muted("Spotify пока только на ПК: ему нужно своё приложение разработчика.")
    }
}

@Composable
fun UpdateDialog(release: Release, onDismiss: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var progress by remember { mutableFloatStateOf(-1f) }
    var error by remember { mutableStateOf<String?>(null) }
    AlertDialog(
        onDismissRequest = { if (progress < 0) onDismiss() },
        title = { Text("Вышла версия ${release.version}") },
        text = {
            Column {
                if (release.notes.isNotBlank()) Text(release.notes.take(800), fontSize = 14.sp)
                if (progress >= 0) {
                    Spacer(Modifier.height(12.dp))
                    LinearProgressIndicator(progress = { progress }, modifier = Modifier.fillMaxWidth())
                }
                error?.let { Text(it, color = SonarColors.like) }
            }
        },
        confirmButton = {
            TextButton(enabled = progress < 0, onClick = {
                val apk = release.apkUrl
                if (apk == null) {
                    context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(release.pageUrl)))
                    onDismiss()
                    return@TextButton
                }
                progress = 0f
                scope.launch {
                    val file = runCatching { withContext(Dispatchers.IO) { Updater.download(context, apk) { p -> progress = p } } }
                    file.getOrNull()?.let { Updater.install(context, it); onDismiss() }
                        ?: run { error = "Не скачалось: ${file.exceptionOrNull()?.message}"; progress = -1f }
                }
            }) { Text(if (progress >= 0) "Скачиваю…" else "Обновить") }
        },
        dismissButton = {
            TextButton(enabled = progress < 0, onClick = {
                Store.updateSettings { it.copy(skipVersion = release.version) }
                onDismiss()
            }) { Text("Пропустить") }
        },
    )
}
