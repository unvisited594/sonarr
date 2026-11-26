package app.sonar.ui

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.gestures.detectVerticalDragGestures
import androidx.compose.material.icons.automirrored.filled.QueueMusic
import androidx.compose.material.icons.filled.Repeat
import androidx.compose.material.icons.filled.RepeatOne
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.lerp
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
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
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.FavoriteBorder
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.MusicNote
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.SkipNext
import androidx.compose.material.icons.filled.SkipPrevious
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Shadow
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.sonar.data.Store
import app.sonar.lyrics.LyricLine
import app.sonar.lyrics.Lyrics
import app.sonar.player.Hub
import coil.compose.AsyncImage
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext

fun fmt(ms: Long): String {
    val s = (ms / 1000).coerceAtLeast(0)
    return "${s / 60}:${(s % 60).toString().padStart(2, '0')}"
}

/** Позиция и длительность, обновляются пару раз в секунду. */
@Composable
fun rememberProgress(): Pair<Long, Long> {
    var pos by remember { mutableLongStateOf(0L) }
    var dur by remember { mutableLongStateOf(0L) }
    LaunchedEffect(Unit) {
        while (true) {
            pos = Hub.exo.currentPosition
            dur = Hub.exo.duration.takeIf { it > 0 } ?: (Hub.state.value.current?.durationMs ?: 0L)
            delay(400)
        }
    }
    return pos to dur
}

/** Мини-плеер: парящая плашка цвета обложки над меню, свайп вверх — большой плеер (как плеер-бар на ПК). */
@Composable
fun MiniPlayer(onOpen: () -> Unit) {
    val state by Hub.state.collectAsState()
    val track = state.current ?: return
    val (pos, dur) = rememberProgress()
    val tint = rememberCoverColors(track.artworkUrl)?.firstOrNull() ?: SonarColors.surface
    val bg = lerp(tint, Color.Black, 0.55f)
    Box(Modifier.padding(horizontal = 8.dp, vertical = 4.dp).fillMaxWidth().shadow(10.dp, RoundedCornerShape(16.dp))
        .clip(RoundedCornerShape(16.dp)).background(bg)
        .pointerInput(Unit) { detectVerticalDragGestures { _, drag -> if (drag < -12) onOpen() } }
        .clickable(onClick = onOpen)) {
        Row(Modifier.fillMaxWidth().padding(start = 8.dp, end = 4.dp, top = 8.dp, bottom = 10.dp),
            verticalAlignment = Alignment.CenterVertically) {
            Cover(track.artworkUrl, 44.dp, 9.dp, seed = track.key)
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(track.title, fontWeight = FontWeight.Bold, color = Color.White, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text(state.error ?: track.artist, color = if (state.error != null) SonarColors.like else Color.White.copy(alpha = 0.7f),
                    fontSize = 13.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            val likes by Store.likes.collectAsState()
            val liked = likes.any { it.key == track.key }
            IconButton(onClick = { Store.toggleLike(track) }) {
                Icon(if (liked) Icons.Filled.Favorite else Icons.Filled.FavoriteBorder, contentDescription = "Лайк",
                    tint = if (liked) SonarColors.like else Color.White)
            }
            if (state.loading) {
                CircularProgressIndicator(Modifier.size(26.dp).padding(2.dp), color = Color.White, strokeWidth = 2.dp)
            } else {
                IconButton(onClick = { Hub.toggle() }) {
                    Icon(if (state.playing) Icons.Filled.Pause else Icons.Filled.PlayArrow, contentDescription = "Пауза",
                        tint = Color.White, modifier = Modifier.size(30.dp))
                }
            }
        }
        Box(Modifier.align(Alignment.BottomStart).padding(horizontal = 12.dp).fillMaxWidth().height(2.dp)
            .clip(RoundedCornerShape(1.dp)).background(Color.White.copy(alpha = 0.2f))) {
            Box(Modifier.fillMaxWidth(if (dur > 0) (pos.toFloat() / dur).coerceIn(0f, 1f) else 0f).height(2.dp).background(Color.White))
        }
    }
}

/** Большой плеер, как на ПК: живой фон, сервис сверху, крупная обложка или текст, кнопки, очередь. Свайп вниз — свернуть. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun FullPlayer(onClose: () -> Unit) {
    val state by Hub.state.collectAsState()
    val track = state.current ?: return
    val likes by Store.likes.collectAsState()
    val liked = likes.any { it.key == track.key }
    val look by Store.look.collectAsState()
    val (pos, dur) = rememberProgress()
    var showLyrics by remember { mutableStateOf(false) }
    var showQueue by remember { mutableStateOf(false) }
    var dragging by remember { mutableStateOf(false) }
    var dragValue by remember { mutableFloatStateOf(0f) }
    var pull by remember { mutableFloatStateOf(0f) }

    Box(Modifier.fillMaxSize().graphicsLayer { translationY = pull.coerceAtLeast(0f) }.background(SonarColors.bg)
        .clickable(enabled = false) {}   // клики не проходят под плеер
        .pointerInput(Unit) {
            detectVerticalDragGestures(onDragEnd = { if (pull > 220f) onClose(); pull = 0f }, onDragCancel = { pull = 0f }) { _, d ->
                pull += d
            }
        }) {
        if (look.flowOn) FlowBackground(track.artworkUrl)
        else Box(Modifier.fillMaxSize().background(Brush.verticalGradient(listOf(Color(0xFF2A2340), SonarColors.bg, SonarColors.bg))))
        Column(Modifier.fillMaxSize().statusBarsPadding().navigationBarsPadding().padding(horizontal = 24.dp)) {
            Row(Modifier.fillMaxWidth().padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                IconButton(onClick = onClose) {
                    Icon(Icons.Filled.KeyboardArrowDown, contentDescription = "Свернуть", tint = Color.White, modifier = Modifier.size(30.dp))
                }
                Box(Modifier.weight(1f), contentAlignment = Alignment.Center) {
                    Text(serviceNames[track.serviceId] ?: "Sonar", color = Color.White.copy(alpha = 0.85f), fontSize = 13.sp,
                        fontWeight = FontWeight.Bold, modifier = Modifier.clip(RoundedCornerShape(50))
                            .background(Color.White.copy(alpha = 0.14f)).padding(horizontal = 12.dp, vertical = 5.dp))
                }
                IconButton(onClick = { showQueue = true }) {
                    Icon(Icons.AutoMirrored.Filled.QueueMusic, contentDescription = "Очередь", tint = Color.White)
                }
            }
            Box(Modifier.fillMaxWidth().weight(1f).padding(vertical = 12.dp), contentAlignment = Alignment.Center) {
                when {
                    showLyrics -> LyricsPane(pos)
                    look.vinyl -> Vinyl(track.artworkUrl, state.playing)
                    else -> Box(Modifier.fillMaxWidth().aspectRatio(1f).shadow(24.dp, RoundedCornerShape(22.dp))) {
                        Cover(track.artworkUrl, null, 22.dp, seed = track.key)
                    }
                }
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(track.title, fontSize = 24.sp, fontWeight = FontWeight.Black, color = Color.White, maxLines = 2,
                        overflow = TextOverflow.Ellipsis, lineHeight = 28.sp)
                    Text(track.artist, color = Color.White.copy(alpha = 0.72f), fontSize = 16.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
                IconButton(onClick = { Store.toggleLike(track) }) {
                    Icon(if (liked) Icons.Filled.Favorite else Icons.Filled.FavoriteBorder, contentDescription = "Лайк",
                        tint = if (liked) SonarColors.like else Color.White, modifier = Modifier.size(28.dp))
                }
            }
            Slider(
                value = if (dragging) dragValue else if (dur > 0) (pos.toFloat() / dur).coerceIn(0f, 1f) else 0f,
                onValueChange = { dragging = true; dragValue = it },
                onValueChangeFinished = { Hub.seek((dragValue * dur).toLong()); dragging = false },
                colors = SliderDefaults.colors(thumbColor = Color.White, activeTrackColor = Color.White,
                    inactiveTrackColor = Color.White.copy(alpha = 0.25f)),
            )
            Row(Modifier.fillMaxWidth()) {
                Text(fmt(if (dragging) (dragValue * dur).toLong() else pos), color = Color.White.copy(alpha = 0.7f), fontSize = 12.sp)
                Spacer(Modifier.weight(1f))
                Text(fmt(dur), color = Color.White.copy(alpha = 0.7f), fontSize = 12.sp)
            }
            Row(Modifier.fillMaxWidth().padding(vertical = 14.dp), horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically) {
                IconButton(onClick = { Hub.toggleRepeat() }) {
                    Icon(if (state.repeatOne) Icons.Filled.RepeatOne else Icons.Filled.Repeat, contentDescription = "Повтор",
                        tint = if (state.repeatOne) SonarColors.accent else Color.White.copy(alpha = 0.7f))
                }
                IconButton(onClick = { Hub.prev() }, modifier = Modifier.size(60.dp)) {
                    Icon(Icons.Filled.SkipPrevious, contentDescription = "Назад", tint = Color.White, modifier = Modifier.size(40.dp))
                }
                Box(Modifier.size(80.dp).shadow(12.dp, CircleShape).clip(CircleShape).background(Color.White).clickable { Hub.toggle() },
                    contentAlignment = Alignment.Center) {
                    if (state.loading) CircularProgressIndicator(color = Color.Black, strokeWidth = 3.dp, modifier = Modifier.size(34.dp))
                    else Icon(if (state.playing) Icons.Filled.Pause else Icons.Filled.PlayArrow, contentDescription = "Пауза",
                        tint = Color.Black, modifier = Modifier.size(42.dp))
                }
                IconButton(onClick = { Hub.next() }, modifier = Modifier.size(60.dp)) {
                    Icon(Icons.Filled.SkipNext, contentDescription = "Дальше", tint = Color.White, modifier = Modifier.size(40.dp))
                }
                IconButton(onClick = { showLyrics = !showLyrics }) {
                    Icon(Icons.Filled.MusicNote, contentDescription = "Текст песни",
                        tint = if (showLyrics) SonarColors.accent else Color.White.copy(alpha = 0.7f))
                }
            }
        }
    }
    if (showQueue) {
        ModalBottomSheet(onDismissRequest = { showQueue = false }, containerColor = SonarColors.panel) {
            Text("Очередь", fontSize = 22.sp, fontWeight = FontWeight.Black, color = SonarColors.text,
                modifier = Modifier.padding(start = 20.dp, bottom = 8.dp))
            LazyColumn(Modifier.fillMaxWidth().height(460.dp)) {
                itemsIndexed(state.queue, key = { i, t -> "$i:${t.key}" }) { i, t ->
                    TrackRow(t, index = i, playing = i == state.index) { Hub.playAt(i) }
                }
            }
        }
    }
}

/** Обложка-пластинка: крутится, пока играет музыка. */
@Composable
fun Vinyl(cover: String?, playing: Boolean) {
    var angle by remember { mutableFloatStateOf(0f) }
    LaunchedEffect(playing) {
        while (playing) {
            angle = (angle + 1.2f) % 360f
            delay(16)
        }
    }
    Box(Modifier.fillMaxWidth().aspectRatio(1f).graphicsLayer { rotationZ = angle }.clip(CircleShape)
        .background(Color(0xFF111114)), contentAlignment = Alignment.Center) {
        for (k in 1..5) Box(Modifier.fillMaxSize(1f - k * 0.08f).clip(CircleShape)
            .background(if (k % 2 == 0) Color(0xFF16161A) else Color(0xFF0E0E11)))
        AsyncImage(model = cover, contentDescription = null, contentScale = ContentScale.Crop,
            modifier = Modifier.fillMaxSize(0.42f).clip(CircleShape).background(SonarColors.surface))
        Box(Modifier.size(14.dp).clip(CircleShape).background(Color(0xFF111114)))
    }
}

/** Текст песни как в Dotify: текущая строка яркая, спетые и будущие — приглушены, автопрокрутка. */
@Composable
fun LyricsPane(pos: Long) {
    val state by Hub.state.collectAsState()
    val track = state.current ?: return
    var lines by remember(track.key) { mutableStateOf<List<LyricLine>?>(null) }
    var synced by remember(track.key) { mutableStateOf(false) }
    LaunchedEffect(track.key) {
        val (l, s) = runCatching { withContext(Dispatchers.IO) { Lyrics.load(track) } }.getOrDefault(emptyList<LyricLine>() to false)
        lines = l
        synced = s
    }
    val list = lines
    val look by Store.look.collectAsState()
    val now = pos + look.lyricsOffset
    val text = hex(look.lyricsColor)
    val sung = hex(look.lyricsSung, Color.Black)
    val halo = if (look.lyricsHalo) Shadow(if (sung.luminance() < 0.5f) Color.White.copy(alpha = 0.7f)
        else Color.Black.copy(alpha = 0.5f), blurRadius = 6f) else null
    val align = if (look.lyricsAlign == "center") TextAlign.Center else TextAlign.Start
    when {
        list == null -> Text("Ищу текст песни…", color = SonarColors.muted)
        list.isEmpty() -> Text("Текст этой песни не найден", color = SonarColors.muted)
        else -> {
            val current = if (synced) list.indexOfLast { it.timeMs <= now } else -1
            val listState = rememberLazyListState()
            LaunchedEffect(current) {
                if (current >= 0) listState.animateScrollToItem(maxOf(0, current - 2))
            }
            LazyColumn(state = listState, modifier = Modifier.fillMaxSize(), contentPadding = PaddingValues(vertical = 40.dp)) {
                itemsIndexed(list) { i, line ->
                    val far = if (current < 0) 0 else kotlin.math.abs(i - current)
                    val alpha by animateFloatAsState(
                        when {
                            !synced || far == 0 -> 1f
                            far == 1 -> 0.7f
                            else -> 0.45f
                        }, label = "lyric")
                    val karaoke = look.lyricsStyle == "karaoke" && synced
                    // как в Dotify: спетые строки — цветом «спетого», текущая — ярко, будущие — тише
                    val base = TextStyle(fontSize = look.lyricsSize.sp, fontWeight = FontWeight.ExtraBold,
                        lineHeight = (look.lyricsSize * 1.25f).sp, textAlign = align)
                    val style = when {
                        !synced -> base.copy(color = text)
                        karaoke && i == current -> {
                            // караоке: строка закрашивается слева направо по мере пения
                            val nextT = list.getOrNull(i + 1)?.timeMs ?: (line.timeMs + 6000)
                            val end = line.timeMs + minOf((nextT - line.timeMs) * 95 / 100, line.text.length * 110L + 900)
                            val f = ((now - line.timeMs).toFloat() / maxOf(1L, end - line.timeMs)).coerceIn(0f, 1f)
                            base.copy(brush = Brush.horizontalGradient(0f to sung, f to sung, f to text, 1f to text), shadow = halo)
                        }
                        i < current -> base.copy(color = sung.copy(alpha = alpha), shadow = halo)
                        else -> base.copy(color = text.copy(alpha = alpha))
                    }
                    Text(
                        line.text, style = style,
                        modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp)
                            .clickable(enabled = synced && line.timeMs >= 0) { Hub.seek(line.timeMs) },
                    )
                }
            }
        }
    }
}
