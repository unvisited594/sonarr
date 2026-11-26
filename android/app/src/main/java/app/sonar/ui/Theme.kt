package app.sonar.ui

import android.app.Activity
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
import androidx.compose.ui.platform.LocalView
import androidx.core.view.WindowCompat
import app.sonar.data.Store

/** Цвета Sonar. Меняются вместе с темой из «Оформления» — всё, что их читает, перерисуется. */
object SonarColors {
    var bg by mutableStateOf(Color(0xFF0F0F12))
    var panel by mutableStateOf(Color(0xFF1A1A1F))
    var surface by mutableStateOf(Color(0xFF26262D))
    var text by mutableStateOf(Color(0xFFF2F2F2))
    var muted by mutableStateOf(Color(0xFF9A9AA3))
    var accent by mutableStateOf(Color(0xFF7C4DFF))
    var onAccent by mutableStateOf(Color.White)
    var outline by mutableStateOf(Color.Transparent)
    val like = Color(0xFFFF4D6D)
    var light by mutableStateOf(false)
}

/** Тёмная — мягкий графит; AMOLED — чистый чёрный (экран не светится); светлая — как светлая тема на ПК. */
fun applyLook(theme: String, accent: String) {
    val c = SonarColors
    when (theme) {
        "light" -> { c.bg = Color(0xFFF2F2F5); c.panel = Color(0xFFFFFFFF); c.surface = Color(0xFFE4E4EA)
            c.text = Color(0xFF141416); c.muted = Color(0xFF6B6B72); c.outline = Color.Transparent; c.light = true }
        "amoled" -> { c.bg = Color(0xFF000000); c.panel = Color(0xFF000000); c.surface = Color(0xFF0D0D0D)
            c.text = Color(0xFFFFFFFF); c.muted = Color(0xFF8C8C8C); c.outline = Color(0xFF262626); c.light = false }
        else -> { c.bg = Color(0xFF0F0F12); c.panel = Color(0xFF1A1A1F); c.surface = Color(0xFF26262D)
            c.text = Color(0xFFF2F2F2); c.muted = Color(0xFF9A9AA3); c.outline = Color.Transparent; c.light = false }
    }
    val a = hex(accent, Color(0xFF7C4DFF))
    c.accent = a
    c.onAccent = if (a.red * 0.299f + a.green * 0.587f + a.blue * 0.114f > 0.62f) Color.Black else Color.White
}

@Composable
fun SonarTheme(content: @Composable () -> Unit) {
    val look by Store.look.collectAsState()
    applyLook(look.theme, look.accent)   // до содержимого: всё ниже сразу рисуется в новых цветах
    val c = SonarColors
    val view = LocalView.current
    SideEffect {   // значки статус-бара: тёмные на светлой теме, светлые на тёмной
        (view.context as? Activity)?.window?.let { w ->
            WindowCompat.getInsetsController(w, view).apply {
                isAppearanceLightStatusBars = c.light
                isAppearanceLightNavigationBars = c.light
            }
        }
    }
    val scheme = if (c.light) lightColorScheme(
        primary = c.accent, onPrimary = c.onAccent, secondary = c.accent, background = c.bg, onBackground = c.text,
        surface = c.panel, onSurface = c.text, surfaceVariant = c.surface, onSurfaceVariant = c.muted,
        surfaceContainer = c.panel, surfaceContainerHigh = c.surface,
    ) else darkColorScheme(
        primary = c.accent, onPrimary = c.onAccent, secondary = c.accent, background = c.bg, onBackground = c.text,
        surface = c.panel, onSurface = c.text, surfaceVariant = c.surface, onSurfaceVariant = c.muted,
        surfaceContainer = c.panel, surfaceContainerHigh = c.surface,
    )
    MaterialTheme(colorScheme = scheme, content = content)
}
