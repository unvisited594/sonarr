package app.sonar.ui

import androidx.compose.animation.core.animateFloatAsState
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

@Composable
fun MiniPlayer(onOpen: () -> Unit) {
    val state by Hub.state.collectAsState()
    val track = state.current ?: return
    val (pos, dur) = rememberProgress()
    Column(Modifier.background(SonarColors.panel)) {
        LinearProgressIndicator(progress = { if (dur > 0) pos.toFloat() / dur else 0f },
            modifier = Modifier.fillMaxWidth().height(2.dp), color = SonarColors.text, trackColor = SonarColors.surface)
        Row(Modifier.fillMaxWidth().clickable(onClick = onOpen).padding(horizontal = 12.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically) {
            AsyncImage(model = track.artworkUrl, contentDescription = null, contentScale = ContentScale.Crop,
                modifier = Modifier.size(46.dp).clip(RoundedCornerShape(8.dp)).background(SonarColors.surface))
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(track.title, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text(state.error ?: track.artist, color = if (state.error != null) SonarColors.like else SonarColors.muted,
                    fontSize = 13.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            if (state.loading) {
                CircularProgressIndicator(Modifier.size(26.dp).padding(2.dp), strokeWidth = 2.dp)
            } else {
                IconButton(onClick = { Hub.toggle() }) {
                    Icon(if (state.playing) Icons.Filled.Pause else Icons.Filled.PlayArrow, contentDescription = "Пауза")
                }
            }
            IconButton(onClick = { Hub.next() }) { Icon(Icons.Filled.SkipNext, contentDescription = "Дальше") }
        }
    }
}

@Composable
fun FullPlayer(onClose: () -> Unit) {
    val state by Hub.state.collectAsState()
    val track = state.current ?: return
    val likes by Store.likes.collectAsState()
    val liked = likes.any { it.key == track.key }
    val (pos, dur) = rememberProgress()
    var showLyrics by remember { mutableStateOf(false) }
    var dragging by remember { mutableStateOf(false) }
    var dragValue by remember { mutableFloatStateOf(0f) }

    val look by Store.look.collectAsState()
    Box(Modifier.fillMaxSize().background(SonarColors.bg).clickable(enabled = false) {}) {   // клики не проходят под плеер
      if (look.flowOn) FlowBackground(track.artworkUrl)
      else Box(Modifier.fillMaxSize().background(Brush.verticalGradient(listOf(Color(0xFF2A2340), SonarColors.bg, SonarColors.bg))))
      Box(Modifier.fillMaxSize().statusBarsPadding().navigationBarsPadding()) {
        Column(Modifier.fillMaxSize().padding(horizontal = 24.dp)) {
            Row(Modifier.fillMaxWidth().padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                IconButton(onClick = onClose) { Icon(Icons.Filled.KeyboardArrowDown, contentDescription = "Свернуть") }
                Spacer(Modifier.weight(1f))
                IconButton(onClick = { showLyrics = !showLyrics }) {
                    Icon(Icons.Filled.MusicNote, contentDescription = "Текст песни",
                        tint = if (showLyrics) SonarColors.text else SonarColors.muted)
                }
            }
            Box(Modifier.fillMaxWidth().weight(1f), contentAlignment = Alignment.Center) {
                if (showLyrics) {
                    LyricsPane(pos)
                } else if (look.vinyl) {
                    Vinyl(track.artworkUrl, state.playing)
                } else {
                    AsyncImage(model = track.artworkUrl, contentDescription = null, contentScale = ContentScale.Crop,
                        modifier = Modifier.fillMaxWidth().aspectRatio(1f).clip(RoundedCornerShape(22.dp))
                            .background(SonarColors.surface))
                }
            }
            Spacer(Modifier.height(18.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(track.title, fontSize = 22.sp, fontWeight = FontWeight.Black, maxLines = 2, overflow = TextOverflow.Ellipsis)
                    Text(track.artist, color = SonarColors.muted, fontSize = 15.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
                IconButton(onClick = { Store.toggleLike(track) }) {
                    Icon(if (liked) Icons.Filled.Favorite else Icons.Filled.FavoriteBorder, contentDescription = "Лайк",
                        tint = if (liked) SonarColors.like else SonarColors.muted)
                }
            }
            Slider(
                value = if (dragging) dragValue else if (dur > 0) pos.toFloat() / dur else 0f,
                onValueChange = { dragging = true; dragValue = it },
                onValueChangeFinished = { Hub.seek((dragValue * dur).toLong()); dragging = false },
                colors = SliderDefaults.colors(thumbColor = SonarColors.text, activeTrackColor = SonarColors.text,
                    inactiveTrackColor = SonarColors.surface),
            )
            Row(Modifier.fillMaxWidth()) {
                Text(fmt(if (dragging) (dragValue * dur).toLong() else pos), color = SonarColors.muted, fontSize = 12.sp)
                Spacer(Modifier.weight(1f))
                Text(fmt(dur), color = SonarColors.muted, fontSize = 12.sp)
            }
            Row(Modifier.fillMaxWidth().padding(vertical = 18.dp), horizontalArrangement = Arrangement.SpaceEvenly,
                verticalAlignment = Alignment.CenterVertically) {
                IconButton(onClick = { Hub.prev() }, modifier = Modifier.size(56.dp)) {
                    Icon(Icons.Filled.SkipPrevious, contentDescription = "Назад", modifier = Modifier.size(36.dp))
                }
                Box(Modifier.size(78.dp).clip(CircleShape).background(SonarColors.text).clickable { Hub.toggle() },
                    contentAlignment = Alignment.Center) {
                    if (state.loading) CircularProgressIndicator(color = SonarColors.bg, strokeWidth = 3.dp, modifier = Modifier.size(34.dp))
                    else Icon(if (state.playing) Icons.Filled.Pause else Icons.Filled.PlayArrow, contentDescription = "Пауза",
                        tint = SonarColors.bg, modifier = Modifier.size(40.dp))
                }
                IconButton(onClick = { Hub.next() }, modifier = Modifier.size(56.dp)) {
                    Icon(Icons.Filled.SkipNext, contentDescription = "Дальше", modifier = Modifier.size(36.dp))
                }
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
