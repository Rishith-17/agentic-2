const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('jarvis', {
  getBackendUrl:  () => ipcRenderer.invoke('get-backend-url'),
  getApiToken:    () => ipcRenderer.invoke('get-api-token'),
  openExternal:   (url) => ipcRenderer.send('open-external', url),
  minimize: () => ipcRenderer.send('minimize-window'),
  maximize: () => ipcRenderer.send('maximize-window'),
  close:    () => ipcRenderer.send('close-window'),
});
