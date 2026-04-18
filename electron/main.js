const { app, BrowserWindow, globalShortcut, ipcMain, shell } = require('electron');
const path = require('path');
const fs = require('fs');
const os = require('os');

// Fix cache permission errors on Windows/OneDrive
app.commandLine.appendSwitch('disable-http-cache');
app.commandLine.appendSwitch('disable-gpu-shader-disk-cache');
app.commandLine.appendSwitch('disk-cache-size', '0');

const BACKEND_URL = process.env.JARVIS_BACKEND_URL || 'http://127.0.0.1:8765';

// Read the API token written by FastAPI on first run.
// Default data dir mirrors Python: ~/.jarvis-assistant/jarvis_api.token
function readApiToken() {
  const tokenPath = path.join(os.homedir(), '.jarvis-assistant', 'jarvis_api.token');
  try {
    return fs.readFileSync(tokenPath, 'utf8').trim();
  } catch {
    return '';  // auth may be disabled or backend not yet started
  }
}

let mainWindow = null;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1180,
    height: 720,
    minWidth: 1024,
    minHeight: 640,
    frame: false,
    transparent: true,
    alwaysOnTop: false,  // Changed: Don't stay on top by default
    skipTaskbar: false,
    resizable: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.loadFile(path.join(__dirname, 'ui', 'dist', 'index.html'));
  // Removed: setVisibleOnAllWorkspaces - let it behave like a normal window

  // Allow user to toggle always-on-top with a keyboard shortcut if needed
  mainWindow.on('focus', () => {
    // Window is focused, normal behavior
  });
}

function toggleWindow() {
  if (!mainWindow) return;
  if (mainWindow.isVisible()) {
    mainWindow.hide();
  } else {
    mainWindow.show();
    mainWindow.focus();
  }
}

app.whenReady().then(() => {
  createWindow();

  const ok = globalShortcut.register('CommandOrControl+Shift+J', () => {
    toggleWindow();
  });
  if (!ok) {
    console.error('Global shortcut registration failed');
  }

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('will-quit', () => {
  globalShortcut.unregisterAll();
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

ipcMain.handle('get-backend-url', () => BACKEND_URL);
ipcMain.handle('get-api-token', () => readApiToken());

ipcMain.on('minimize-window', () => {
  if (mainWindow) mainWindow.minimize();
});

ipcMain.on('maximize-window', () => {
  if (mainWindow) {
    if (mainWindow.isMaximized()) {
      mainWindow.unmaximize();
    } else {
      mainWindow.maximize();
    }
  }
});

ipcMain.on('close-window', () => {
  if (mainWindow) mainWindow.hide();
});

ipcMain.on('open-external', (event, url) => {
  // Validate it's a real http/https URL before opening
  if (url && /^https?:\/\//.test(url)) {
    shell.openExternal(url);
  }
});
