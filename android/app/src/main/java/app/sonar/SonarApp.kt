package app.sonar

import android.app.Application
import app.sonar.data.Store
import app.sonar.net.NewPipeDownloader
import app.sonar.player.Hub
import org.schabi.newpipe.extractor.NewPipe
import org.schabi.newpipe.extractor.localization.ContentCountry
import org.schabi.newpipe.extractor.localization.Localization

class SonarApp : Application() {
    override fun onCreate() {
        super.onCreate()
        Store.init(this)
        NewPipe.init(NewPipeDownloader(), Localization("ru", "RU"), ContentCountry("RU"))
        Hub.init(this)
    }
}
