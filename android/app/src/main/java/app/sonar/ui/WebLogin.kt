package app.sonar.ui

import android.annotation.SuppressLint
import android.graphics.Bitmap
import android.webkit.CookieManager
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import app.sonar.net.Http

/**
 * Вход в сервис во встроенном браузере (как на ПК): ждём cookie с данными входа
 * или переход на адрес OAuth-редиректа и отдаём результат.
 */
data class WebLoginSpec(
    val title: String,
    val url: String,
    val cookieHost: String? = null,      // где смотреть cookie
    val cookieName: String? = null,      // cookie, появление которой = вход выполнен
    val wholeCookie: Boolean = false,    // отдать все cookie строкой
    val redirectPrefix: String? = null,  // OAuth: отдать токен из адреса редиректа
    val desktopAgent: Boolean = false,   // Google не пускает «встроенные браузеры» — притворяемся Chrome
)

@SuppressLint("SetJavaScriptEnabled")
@Composable
fun WebLogin(spec: WebLoginSpec, onResult: (String) -> Unit, onClose: () -> Unit) {
    BackHandler(onBack = onClose)
    var done = false
    fun check(view: WebView?, url: String?) {
        if (done) return
        val u = url ?: ""
        if (spec.redirectPrefix != null && u.startsWith(spec.redirectPrefix)) {
            Regex("""access_token=([^&]+)""").find(u)?.groupValues?.get(1)?.let { done = true; onResult(it) }
            return
        }
        val host = spec.cookieHost ?: return
        val cookies = CookieManager.getInstance().getCookie("https://$host") ?: return
        val name = spec.cookieName ?: return
        val value = Regex("""(?:^|;\s*)${Regex.escape(name)}=([^;]+)""").find(cookies)?.groupValues?.get(1) ?: return
        done = true
        onResult(if (spec.wholeCookie) cookies else value)
        view?.stopLoading()
    }
    Box(Modifier.fillMaxSize().background(SonarColors.bg).statusBarsPadding().navigationBarsPadding()) {
        Column(Modifier.fillMaxSize()) {
            Row(Modifier.fillMaxWidth().padding(8.dp), verticalAlignment = Alignment.CenterVertically) {
                IconButton(onClick = onClose) { Icon(Icons.Filled.Close, contentDescription = "Закрыть", tint = SonarColors.text) }
                Text(spec.title, fontSize = 18.sp, fontWeight = FontWeight.Bold, color = SonarColors.text)
            }
            AndroidView(modifier = Modifier.fillMaxSize(), factory = { ctx ->
                CookieManager.getInstance().setAcceptCookie(true)
                WebView(ctx).apply {
                    settings.javaScriptEnabled = true
                    settings.domStorageEnabled = true
                    if (spec.desktopAgent) settings.userAgentString = Http.USER_AGENT
                    CookieManager.getInstance().setAcceptThirdPartyCookies(this, true)
                    webViewClient = object : WebViewClient() {
                        override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean {
                            check(view, request?.url?.toString())
                            return done
                        }
                        override fun onPageStarted(view: WebView?, url: String?, favicon: Bitmap?) = check(view, url)
                        override fun onPageFinished(view: WebView?, url: String?) = check(view, url)
                    }
                    loadUrl(spec.url)
                }
            })
        }
    }
}
