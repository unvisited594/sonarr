package app.sonar.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.FavoriteBorder
import androidx.compose.material.icons.filled.GraphicEq
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.MusicNote
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.sonar.data.Store
import app.sonar.model.Track
import app.sonar.player.Hub
import coil.compose.AsyncImage

val serviceNames = mapOf("ytmusic" to "YouTube Music", "soundcloud" to "SoundCloud", "navidrome" to "Navidrome")

/** Обложка трека; если картинки нет — цветная заглушка с нотой (как на ПК). */
@Composable
fun Cover(url: String?, size: Dp?, radius: Dp, modifier: Modifier = Modifier, seed: String = "") {
    val m = (if (size != null) modifier.size(size) else modifier.fillMaxWidth().aspectRatio(1f))
        .clip(RoundedCornerShape(radius))
    if (url.isNullOrBlank()) {
        val h = (seed.hashCode() and 0xFFFFFF)
        val a = Color(0xFF000000 or (h.toLong() and 0xFFFFFF)).copy(alpha = 1f)
        Box(m.background(Brush.linearGradient(listOf(a, SonarColors.accent))), contentAlignment = Alignment.Center) {
            Icon(Icons.Filled.MusicNote, contentDescription = null, tint = Color.White.copy(alpha = 0.8f))
        }
    } else {
        AsyncImage(model = url, contentDescription = null, contentScale = ContentScale.Crop,
            modifier = m.background(SonarColors.surface))
    }
}

@Composable
fun PageTitle(text: String, sub: String? = null) {
    Column(Modifier.padding(start = 20.dp, end = 20.dp, top = 18.dp, bottom = 6.dp)) {
        Text(text, fontSize = 32.sp, fontWeight = FontWeight.Black, color = SonarColors.text, lineHeight = 36.sp)
        if (sub != null) Text(sub, color = SonarColors.muted, fontSize = 14.sp)
    }
}

@Composable
fun SectionHead(text: String, action: String? = null, onAction: () -> Unit = {}) {
    Row(Modifier.fillMaxWidth().padding(start = 20.dp, end = 12.dp, top = 22.dp, bottom = 10.dp),
        verticalAlignment = Alignment.CenterVertically) {
        Text(text, fontSize = 21.sp, fontWeight = FontWeight.ExtraBold, color = SonarColors.text, modifier = Modifier.weight(1f))
        if (action != null) Text(action, color = SonarColors.muted, fontSize = 13.sp, fontWeight = FontWeight.SemiBold,
            modifier = Modifier.clip(RoundedCornerShape(8.dp)).clickable(onClick = onAction).padding(8.dp))
    }
}

/** Карточка трека в горизонтальном ряду (как карточки на главной ПК-версии). */
@Composable
fun TrackCard(track: Track, onClick: () -> Unit) {
    Column(Modifier.width(148.dp).clip(RoundedCornerShape(14.dp)).clickable(onClick = onClick).padding(6.dp)) {
        Box {
            Cover(track.artworkUrl, null, 12.dp, seed = track.key)
            Box(Modifier.align(Alignment.BottomEnd).padding(8.dp).size(34.dp).shadow(6.dp, CircleShape)
                .clip(CircleShape).background(SonarColors.text), contentAlignment = Alignment.Center) {
                Icon(Icons.Filled.PlayArrow, contentDescription = null, tint = SonarColors.bg, modifier = Modifier.size(20.dp))
            }
        }
        Spacer(Modifier.height(8.dp))
        Text(track.title, fontWeight = FontWeight.Bold, fontSize = 14.sp, maxLines = 1, overflow = TextOverflow.Ellipsis,
            color = SonarColors.text)
        Text(track.artist, color = SonarColors.muted, fontSize = 12.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

@Composable
fun TrackShelf(tracks: List<Track>) {
    LazyRow(contentPadding = PaddingValues(horizontal = 14.dp), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
        itemsIndexed(tracks, key = { i, t -> "$i:${t.key}" }) { i, t -> TrackCard(t) { Hub.playQueue(tracks, i) } }
    }
}

/** Строка трека: обложка, название, исполнитель · сервис · длительность, лайк и меню «⋮». */
@Composable
fun TrackRow(track: Track, index: Int? = null, playing: Boolean = false, onClick: () -> Unit) {
    val likes by Store.likes.collectAsState()
    val liked = likes.any { it.key == track.key }
    var menu by remember { mutableStateOf(false) }
    Row(
        Modifier.fillMaxWidth().padding(horizontal = 10.dp).clip(RoundedCornerShape(12.dp))
            .background(if (playing) SonarColors.surface else Color.Transparent)
            .clickable(onClick = onClick).padding(horizontal = 10.dp, vertical = 7.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (index != null) {
            Box(Modifier.width(26.dp), contentAlignment = Alignment.Center) {
                if (playing) Icon(Icons.Filled.GraphicEq, contentDescription = null, tint = SonarColors.accent, modifier = Modifier.size(18.dp))
                else Text("${index + 1}", color = SonarColors.muted, fontSize = 13.sp)
            }
            Spacer(Modifier.width(6.dp))
        }
        Cover(track.artworkUrl, 50.dp, 9.dp, seed = track.key)
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(track.title, fontWeight = FontWeight.SemiBold, fontSize = 15.sp, maxLines = 1, overflow = TextOverflow.Ellipsis,
                color = if (playing) SonarColors.accent else SonarColors.text)
            val extra = listOfNotNull(track.artist.takeIf { it.isNotBlank() }, serviceNames[track.serviceId],
                track.durationMs.takeIf { it > 0 }?.let { fmt(it) }).joinToString(" · ")
            Text(extra, color = SonarColors.muted, fontSize = 12.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        IconButton(onClick = { Store.toggleLike(track) }) {
            Icon(if (liked) Icons.Filled.Favorite else Icons.Filled.FavoriteBorder, contentDescription = "Лайк",
                tint = if (liked) SonarColors.like else SonarColors.muted, modifier = Modifier.size(20.dp))
        }
        Box {
            IconButton(onClick = { menu = true }) {
                Icon(Icons.Filled.MoreVert, contentDescription = "Ещё", tint = SonarColors.muted, modifier = Modifier.size(20.dp))
            }
            DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                DropdownMenuItem(text = { Text("Играть следующим") }, onClick = { Hub.playNext(track); menu = false })
                DropdownMenuItem(text = { Text("Добавить в очередь") }, onClick = { Hub.enqueue(track); menu = false })
                DropdownMenuItem(text = { Text("Волна по треку") }, onClick = { Hub.waveFrom(track); menu = false })
                DropdownMenuItem(text = { Text(if (liked) "Убрать из лайков" else "В мои лайки") },
                    onClick = { Store.toggleLike(track); menu = false })
            }
        }
    }
}

/** Полупрозрачная «таблетка»-переключатель (как чипы на ПК). */
@Composable
fun Pill(text: String, selected: Boolean, onClick: () -> Unit) {
    Text(text, fontSize = 14.sp, fontWeight = FontWeight.SemiBold,
        color = if (selected) SonarColors.bg else SonarColors.text,
        modifier = Modifier.clip(RoundedCornerShape(50)).background(if (selected) SonarColors.text else SonarColors.surface)
            .clickable(onClick = onClick).padding(horizontal = 16.dp, vertical = 9.dp))
}

/** Карточка-группа настроек (как serviceCard на ПК). */
@Composable
fun Card(content: @Composable () -> Unit) {
    Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp).clip(RoundedCornerShape(18.dp))
        .background(SonarColors.panel).padding(18.dp)) { content() }
}
