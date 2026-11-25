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
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.FavoriteBorder
import androidx.compose.material.icons.filled.GraphicEq
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.LibraryMusic
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Switch
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
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
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.media3.session.MediaController
import androidx.media3.session.SessionToken
import app.sonar.data.NavidromeLogin
import app.sonar.data.Store
import app.sonar.model.Track
import app.sonar.player.Hub
import app.sonar.player.PlaybackService
import app.sonar.services.MusicService
import app.sonar.services.Navidrome
import app.sonar.services.Services
import app.sonar.update.Release
import app.sonar.update.Updater
import coil.compose.AsyncImage
import com.google.common.util.concurrent.ListenableFuture
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.security.SecureRandom

class MainActivity : ComponentActivity() {
    private var controller: ListenableFuture<MediaController>? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        if (Build.VERSION.SDK_INT >= 33) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)
        }
        // подключаемся к сервису — он держит музыку в фоне и показывает уведомление
        controller = MediaController.Builder(this, SessionToken(this, ComponentName(this, PlaybackService::class.java)))
            .buildAsync()
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
    val state by Hub.state.collectAsState()
    var release by remember { mutableStateOf<Release?>(null) }
    var lookOpen by remember { mutableStateOf(false) }
    val settings by Store.settings.collectAsState()

    LaunchedEffect(Unit) {   // проверка обновлений при запуске
        if (settings.autoUpdate) {
            val r = runCatching { withContext(Dispatchers.IO) { Updater.latest() } }.getOrNull()
            if (r != null && Updater.isNewer(r.version) && r.version != settings.skipVersion) release = r
        }
    }

    BackHandler(enabled = full) { full = false }

    Box(Modifier.fillMaxSize().background(SonarColors.bg)) {
        Scaffold(
            containerColor = SonarColors.bg,
            bottomBar = {
                Column {
                    if (state.current != null) MiniPlayer(onOpen = { full = true })
                    NavigationBar(containerColor = SonarColors.bg) {
                        val items = listOf(
                            Triple("Главная", Icons.Filled.Home, 0),
                            Triple("Поиск", Icons.Filled.Search, 1),
                            Triple("Медиатека", Icons.Filled.LibraryMusic, 2),
                            Triple("Настройки", Icons.Filled.Settings, 3),
                        )
                        for ((label, icon, i) in items) {
                            NavigationBarItem(selected = tab == i, onClick = { tab = i },
                                icon = { Icon(icon, contentDescription = label) }, label = { Text(label) })
                        }
                    }
                }
            },
        ) { pad ->
            Box(Modifier.padding(pad).fillMaxSize()) {
                when (tab) {
                    0 -> HomeScreen()
                    1 -> SearchScreen()
                    2 -> LibraryScreen()
                    else -> SettingsScreen(onRelease = { release = it }, onLook = { lookOpen = true })
                }
            }
        }
        if (full && state.current != null) FullPlayer(onClose = { full = false })
        if (lookOpen) LookScreen(onClose = { lookOpen = false })
    }

    release?.let { r -> UpdateDialog(r, onDismiss = { release = null }) }
}

// ---------------- общие элементы ----------------

@Composable
fun Header(text: String) {
    Text(text, fontSize = 30.sp, fontWeight = FontWeight.Black, modifier = Modifier.padding(start = 20.dp, top = 16.dp, bottom = 8.dp))
}

@Composable
fun SectionTitle(text: String) {
    Text(text, fontSize = 19.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(start = 20.dp, top = 18.dp, bottom = 6.dp))
}

@Composable
fun TrackRow(track: Track, onClick: () -> Unit) {
    val likes by Store.likes.collectAsState()
    val liked = likes.any { it.key == track.key }
    Row(
        Modifier.fillMaxWidth().clickable(onClick = onClick).padding(horizontal = 16.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        AsyncImage(model = track.artworkUrl, contentDescription = null, contentScale = ContentScale.Crop,
            modifier = Modifier.size(52.dp).clip(RoundedCornerShape(10.dp)).background(SonarColors.surface))
        Spacer(Modifier.width(14.dp))
        Column(Modifier.weight(1f)) {
            Text(track.title, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(track.artist, color = SonarColors.muted, fontSize = 13.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        IconButton(onClick = { Store.toggleLike(track) }) {
            Icon(if (liked) Icons.Filled.Favorite else Icons.Filled.FavoriteBorder, contentDescription = "Лайк",
                tint = if (liked) SonarColors.like else SonarColors.muted)
        }
    }
}

@Composable
fun TrackList(tracks: List<Track>, header: @Composable () -> Unit = {}) {
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 24.dp)) {
        item { header() }
        itemsIndexed(tracks, key = { i, t -> "$i:${t.key}" }) { i, t ->
            TrackRow(t) { Hub.playQueue(tracks, i) }
        }
    }
}

// ---------------- экраны ----------------

@Composable
fun HomeScreen() {
    val likes by Store.likes.collectAsState()
    val history by Store.history.collectAsState()
    val scope = rememberCoroutineScope()
    var waveBusy by remember { mutableStateOf(false) }
    var waveError by remember { mutableStateOf<String?>(null) }
    TrackList(history.take(30)) {
        Column {
            Header("Sonar")
            Box(
                Modifier.padding(horizontal = 16.dp).fillMaxWidth().height(150.dp).clip(RoundedCornerShape(24.dp))
                    .background(androidx.compose.ui.graphics.Brush.linearGradient(listOf(SonarColors.accent, Color2.cyan)))
                    .clickable(enabled = !waveBusy) {
                        waveBusy = true
                        waveError = null
                        scope.launch {
                            val wave = withContext(Dispatchers.IO) { buildWave(likes) }
                            waveBusy = false
                            if (wave.isEmpty()) waveError = "Не из чего собрать волну — проверьте интернет"
                            else Hub.playQueue(wave, 0)
                        }
                    }
                    .padding(20.dp),
            ) {
                Column(Modifier.align(Alignment.BottomStart)) {
                    Icon(Icons.Filled.GraphicEq, contentDescription = null, tint = SonarColors.text, modifier = Modifier.size(34.dp))
                    Text(if (waveBusy) "Собираю волну…" else "Моя волна", fontSize = 26.sp, fontWeight = FontWeight.Black)
                    Text("Ваши лайки и похожая музыка — без остановки", color = SonarColors.text.copy(alpha = 0.8f), fontSize = 13.sp)
                }
            }
            waveError?.let { Text(it, color = SonarColors.like, modifier = Modifier.padding(20.dp, 8.dp)) }
            if (likes.isNotEmpty()) {
                SectionTitle("Лайки")
                likes.take(5).forEachIndexed { i, t -> TrackRow(t) { Hub.playQueue(likes, i) } }
            }
            SectionTitle(if (history.isEmpty()) "Найдите музыку во вкладке «Поиск»" else "Недавно")
        }
    }
}

object Color2 {
    val cyan = androidx.compose.ui.graphics.Color(0xFF00B8D4)
}

/** Волна: лайки вперемешку + случайное с Navidrome; если пусто — подборка YouTube Music. */
fun buildWave(likes: List<Track>): List<Track> {
    val out = mutableListOf<Track>()
    out += likes.shuffled().take(25)
    Services.navidrome?.let { nd -> runCatching { out += nd.wave().take(25) } }
    if (out.isEmpty()) runCatching { out += Services.youtube.wave().take(30) }
    return out.distinctBy { it.key }.shuffled()
}

@Composable
fun SearchScreen() {
    var query by remember { mutableStateOf("") }
    var serviceId by remember { mutableStateOf("ytmusic") }
    var results by remember { mutableStateOf<List<Track>>(emptyList()) }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()
    val services = Services.all()

    fun run() {
        val q = query.trim()
        val svc: MusicService = services.firstOrNull { it.id == serviceId } ?: return
        if (q.isEmpty()) return
        busy = true
        error = null
        scope.launch {
            val r = runCatching { withContext(Dispatchers.IO) { svc.search(q) } }
            busy = false
            results = r.getOrDefault(emptyList())
            error = r.exceptionOrNull()?.let { "Поиск не удался: ${it.message}" }
                ?: if (results.isEmpty()) "Ничего не нашлось" else null
        }
    }

    TrackList(results) {
        Column {
            Header("Поиск")
            OutlinedTextField(
                value = query, onValueChange = { query = it }, singleLine = true,
                placeholder = { Text("Трек, исполнитель…") },
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
                keyboardActions = KeyboardActions(onSearch = { run() }),
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp),
            )
            Row(Modifier.padding(horizontal = 16.dp, vertical = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                for (s in services) {
                    FilterChip(selected = s.id == serviceId, onClick = { serviceId = s.id; run() }, label = { Text(s.name) })
                }
            }
            if (busy) LinearProgressIndicator(Modifier.fillMaxWidth().padding(horizontal = 16.dp))
            error?.let { Text(it, color = SonarColors.muted, modifier = Modifier.padding(20.dp, 8.dp)) }
        }
    }
}

@Composable
fun LibraryScreen() {
    var tab by remember { mutableIntStateOf(0) }
    val likes by Store.likes.collectAsState()
    val history by Store.history.collectAsState()
    Column(Modifier.fillMaxSize()) {
        Header("Медиатека")
        TabRow(selectedTabIndex = tab, containerColor = SonarColors.bg) {
            Tab(selected = tab == 0, onClick = { tab = 0 }, text = { Text("Лайки · ${likes.size}") })
            Tab(selected = tab == 1, onClick = { tab = 1 }, text = { Text("История") })
        }
        val list = if (tab == 0) likes else history
        if (list.isEmpty()) {
            Text(if (tab == 0) "Здесь появятся треки, которым вы поставите ♥" else "Здесь будет то, что вы слушали",
                color = SonarColors.muted, modifier = Modifier.padding(20.dp))
        } else {
            TrackList(list)
        }
    }
}

@Composable
fun SettingsScreen(onRelease: (Release) -> Unit, onLook: () -> Unit) {
    val settings by Store.settings.collectAsState()
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var url by remember { mutableStateOf(settings.navidrome?.url ?: "") }
    var user by remember { mutableStateOf(settings.navidrome?.user ?: "") }
    var password by remember { mutableStateOf("") }
    var status by remember { mutableStateOf<String?>(null) }
    var updateStatus by remember { mutableStateOf<String?>(null) }

    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 32.dp)) {
        item { Header("Настройки") }
        item { Column(Modifier.padding(horizontal = 16.dp)) {
            Button(onClick = onLook, modifier = Modifier.fillMaxWidth()) { Text("Оформление: тема, фон, текст, эквалайзер") }
        } }
        item { Column {
            SectionTitle("Navidrome")
            val shared = Services.navidrome
            Text(
                when {
                    settings.navidrome != null -> "Подключён свой сервер: ${settings.navidrome?.url}"
                    shared != null -> "Подключён общий сервер «${shared.label}» — вход не нужен"
                    else -> "Не подключён. Впишите адрес своего сервера Navidrome."
                },
                color = SonarColors.muted, modifier = Modifier.padding(horizontal = 20.dp),
            )
            Column(Modifier.padding(horizontal = 16.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(url, { url = it }, label = { Text("Адрес сервера") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(user, { user = it }, label = { Text("Имя пользователя") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(password, { password = it }, label = { Text("Пароль") }, singleLine = true,
                    visualTransformation = PasswordVisualTransformation(), modifier = Modifier.fillMaxWidth())
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
                status?.let { Text(it, color = SonarColors.muted) }
            }
        } }
        item { Column {
            SectionTitle("Обновления")
            Text("Версия ${Updater.current}", color = SonarColors.muted, modifier = Modifier.padding(horizontal = 20.dp))
            Row(Modifier.padding(horizontal = 20.dp, vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                Text("Проверять при запуске", Modifier.weight(1f))
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
            }, modifier = Modifier.padding(horizontal = 8.dp)) { Text("Проверить сейчас") }
            updateStatus?.let { Text(it, color = SonarColors.muted, modifier = Modifier.padding(horizontal = 20.dp)) }
        } }
        item { Column {
            SectionTitle("Sonar")
            Text("Новости и версии для ПК — в Telegram-канале @sonar081.", color = SonarColors.muted,
                modifier = Modifier.padding(horizontal = 20.dp))
            TextButton(onClick = {
                context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("https://t.me/sonar081")))
            }, modifier = Modifier.padding(horizontal = 8.dp)) { Text("Открыть канал") }
        } }
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
                    val file = runCatching {
                        withContext(Dispatchers.IO) { Updater.download(context, apk) { p -> progress = p } }
                    }
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
