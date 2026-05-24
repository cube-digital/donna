import { app, BrowserWindow } from "electron";
import * as path from "path";

// Load the shared web/ build in production, or the Vite dev server when
// developing. Pass DONNA_WEB_URL to override (useful for staging builds).
const DEV_URL = process.env.DONNA_WEB_URL ?? "http://localhost:5173";
const PROD_INDEX = path.join(__dirname, "../../web/dist/index.html");

function createWindow(): BrowserWindow {
    const win = new BrowserWindow({
        width: 1440,
        height: 900,
        minWidth: 1100,
        minHeight: 680,
        titleBarStyle: "hiddenInset",
        backgroundColor: "#171719", // matches --bg-0 in dark theme so there's no white flash
        vibrancy: "under-window",
        webPreferences: {
            contextIsolation: true,
            nodeIntegration: false,
        },
    });

    const useDev = !app.isPackaged && process.env.DONNA_USE_DEV_SERVER !== "0";
    if (useDev) {
        win.loadURL(DEV_URL);
    } else {
        win.loadFile(PROD_INDEX);
    }

    return win;
}

app.whenReady().then(() => {
    createWindow();

    app.on("activate", () => {
        if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
});

app.on("window-all-closed", () => {
    if (process.platform !== "darwin") app.quit();
});
