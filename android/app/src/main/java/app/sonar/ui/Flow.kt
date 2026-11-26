package app.sonar.ui

import android.graphics.drawable.BitmapDrawable
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import app.sonar.data.LookData
import app.sonar.data.Store
import coil.imageLoader
import coil.request.ImageRequest
import kotlin.math.cos
import kotlin.math.sin

fun hex(s: String, fallback: Color = Color.White): Color =
    runCatching { Color(android.graphics.Color.parseColor(s)) }.getOrDefault(fallback)

/** Цвета обложки (как «Из обложки» на ПК). */
@Composable
fun rememberCoverColors(url: String?): List<Color>? {
    val context = LocalContext.current
    var colors by remember(url) { mutableStateOf<List<Color>?>(null) }
    LaunchedEffect(url) {
        if (url == null) return@LaunchedEffect
        val req = ImageRequest.Builder(context).data(url).allowHardware(false).size(160).build()
        val bmp = (context.imageLoader.execute(req).drawable as? BitmapDrawable)?.bitmap ?: return@LaunchedEffect
        colors = dominantColors(bmp).ifEmpty { null }
    }
    return colors
}

/** Самые заметные цвета картинки: уменьшаем до 24×24, группируем похожие, берём яркие и насыщенные. */
fun dominantColors(src: android.graphics.Bitmap): List<Color> {
    val bmp = android.graphics.Bitmap.createScaledBitmap(src, 24, 24, true)
    val counts = HashMap<Int, Int>()
    val hsv = FloatArray(3)
    for (y in 0 until 24) for (x in 0 until 24) {
        val c = bmp.getPixel(x, y)
        val key = ((c shr 20 and 0xF) shl 8) or ((c shr 12 and 0xF) shl 4) or (c shr 4 and 0xF)   // 4 бита на канал
        counts[key] = (counts[key] ?: 0) + 1
    }
    return counts.entries.map { (key, n) ->
        val r = ((key shr 8) and 0xF) * 17
        val g = ((key shr 4) and 0xF) * 17
        val b = (key and 0xF) * 17
        android.graphics.Color.RGBToHSV(r, g, b, hsv)
        Triple(android.graphics.Color.rgb(r, g, b), n * (0.3f + hsv[1]) * (0.3f + hsv[2]), hsv[0])
    }.sortedByDescending { it.second }
        .fold(mutableListOf<Triple<Int, Float, Float>>()) { acc, t ->   // разные оттенки, а не четыре почти одинаковых
            if (acc.none { kotlin.math.abs(it.third - t.third) < 25f }) acc += t
            acc
        }.take(4).map { Color(it.first) }
}

/** Живой фон большого плеера: цветные пятна плывут и перетекают. */
@Composable
fun FlowBackground(coverUrl: String?, modifier: Modifier = Modifier) {
    val look by Store.look.collectAsState()
    val cover = rememberCoverColors(coverUrl)
    val preset = LookData.flowPresets.firstOrNull { it.id == look.flowSource }
    val colors: List<Color> = when {
        preset != null -> preset.colors.map { hex(it) }
        look.flowSource == "custom" -> look.flowCustom.map { hex(it) }
        else -> cover ?: listOf(Color(0xFF7C4DFF), Color(0xFF00B8D4), Color(0xFF3B2A6E))
    }
    val base = preset?.let { hex(it.base) } ?: Color(0xFF070707)
    val speed = 0.4f + look.flowSpeed / 50f
    val t by rememberInfiniteTransition(label = "flow").animateFloat(
        initialValue = 0f, targetValue = 1000f,
        animationSpec = infiniteRepeatable(tween(1_000_000, easing = LinearEasing), RepeatMode.Restart), label = "t")
    Canvas(modifier.fillMaxSize()) {
        drawRect(base)
        val time = t * speed * 0.6f
        colors.forEachIndexed { i, c ->
            val ph = i * 1.9f
            val cx = size.width * (0.5f + 0.32f * cos(time * (0.11f + i * 0.03f) + ph))
            val cy = size.height * (0.45f + 0.3f * sin(time * (0.09f + i * 0.025f) + ph * 1.3f))
            val r = size.maxDimension * (0.42f + 0.06f * sin(time * 0.2f + ph))
            drawCircle(Brush.radialGradient(listOf(c.copy(alpha = 0.85f), c.copy(alpha = 0.35f), Color.Transparent),
                center = Offset(cx, cy), radius = r), radius = r, center = Offset(cx, cy))
        }
        drawRect(Brush.verticalGradient(listOf(Color.Black.copy(alpha = 0.15f), Color.Black.copy(alpha = 0.55f))))
    }
}
