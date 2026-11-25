package app.sonar.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

/** Цвета тёмной темы Sonar (как в версии для ПК). */
object SonarColors {
    val bg = Color(0xFF070707)
    val panel = Color(0xFF121212)
    val surface = Color(0xFF1A1A1A)
    val text = Color(0xFFF2F2F2)
    val muted = Color(0xFF8C8C8C)
    val accent = Color(0xFF7C4DFF)
    val like = Color(0xFFFF4D6D)
}

@Composable
fun SonarTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = darkColorScheme(
            primary = SonarColors.text,
            onPrimary = Color(0xFF0D0D0D),
            secondary = SonarColors.accent,
            background = SonarColors.bg,
            onBackground = SonarColors.text,
            surface = SonarColors.panel,
            onSurface = SonarColors.text,
            surfaceVariant = SonarColors.surface,
            onSurfaceVariant = SonarColors.muted,
            surfaceContainer = SonarColors.panel,
        ),
        content = content,
    )
}
