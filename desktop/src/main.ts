import { app, BrowserWindow } from 'electron'
import * as path from 'path'

app.whenReady().then(() => {
    const win = new BrowserWindow({
        width: 800,
        height: 600,
        titleBarStyle: 'hiddenInset',   // macOS: traffic lights float over content
        backgroundColor: '#0f172a',      // matches your gradient — no white flash on load
        vibrancy: 'under-window',        // macOS: real translucency behind the window
      })
  win.loadFile(path.join(__dirname, '../src/index.html'))
})