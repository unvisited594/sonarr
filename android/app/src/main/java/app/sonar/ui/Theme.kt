package app.sonar.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.graphics.Color
import app.sonar.data.Store

/** Цвета Sonar. Меняются вместе с темой из «Оформления» — всё, что их читает, перерисуется. */
object SonarColors {
    var bg by mutableStateOf(Color(0xFF070707))
    var panel by mutableStateOf(Color(0xFF121212))
    var surface by mutableStateOf(Color(0xFF1A1A1A))
    var text by mutableStateOf(Color(0xFFF2F2F2))
    var muted by mutableStateOf(Color(0xFF8C8C8C))
    var accent by mutableStateOf(Color(0xFF7C4DFF))
    val like = Color(0xFFFF4D6D)
    var light by mutableStateOf(false)
}

@Composable
fun SonarTheme(content: @Composable () -> Unit) {
    val look by Store.look.collectAsState()
    val c = SonarColors
    SideEffect { applyLook(look.theme, look.accent) }   // после композиции: без «обратной записи» состояния
    MaterialThemeFor(c, content)
}

fun applyLook(theme: String, accent: String) {
    val c = SonarColors
    when (theme) {
        "light" -> { c.bg = Color(0xFFF2F2F5); c.panel = Color(0xFFFFFFFF); c.surface = Color(0xFFE6E6EB)
            c.text = Color(0xFF141416); c.muted = Color(0xFF6B6B72); c.light = true }
        "amoled" -> { c.bg = Color(0xFF000000); c.panel = Color(0xFF0A0A0A); c.surface = Color(0xFF141414)
            c.text = Color(0xFFF2F2F2); c.muted = Color(0xFF8C8C8C); c.light = false }
        else -> { c.bg = Color(0xFF070707); c.panel = Color(0xFF121212); c.surface = Color(0xFF1A1A1A)
            c.text = Color(0xFFF2F2F2); c.muted = Color(0xFF8C8C8C); c.light = false }
    }
    c.accent = hex(accent, Color(0xFF7C4DFF))
}

@Composable
private fun MaterialThemeFor(c: SonarColors, content: @Composable () -> Unit) {
    val scheme = if (c.light) lightColorScheme(
        primary = c.text, onPrimary = Color.White, secondary = c.accent, background = c.bg, onBackground = c.text,
        surface = c.panel, onSurface = c.text, surfaceVariant = c.surface, onSurfaceVariant = c.muted, surfaceContainer = c.panel,
    ) else darkColorScheme(
        primary = c.text, onPrimary = Color(0xFF0D0D0D), secondary = c.accent, background = c.bg, onBackground = c.text,
        surface = c.panel, onSurface = c.text, surfaceVariant = c.surface, onSurfaceVariant = c.muted, surfaceContainer = c.panel,
    )
    MaterialTheme(colorScheme = scheme, content = content)
}
