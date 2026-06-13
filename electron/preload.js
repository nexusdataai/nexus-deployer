/**
 * Electron Preload Script
 * This script runs in the renderer process before the web page loads
 * It has access to Node.js APIs and can expose safe APIs to the renderer
 * 
 * Feature: startup-health-check
 * Exposes startup status IPC for frontend loading screen
 */

const { contextBridge, ipcRenderer } = require('electron');

// Expose protected methods that allow the renderer process to use
// the ipcRenderer without exposing the entire object
contextBridge.exposeInMainWorld('electronAPI', {
  // Platform information
  platform: process.platform,
  
  // Example: expose a method to open external links
  openExternal: (url) => {
    require('electron').shell.openExternal(url);
  },
  
  // Check if running in Electron
  isElectron: true,
  
  // Startup status APIs
  getStartupStatus: () => ipcRenderer.invoke('get-startup-status'),
  retryStartup: () => ipcRenderer.invoke('retry-startup'),
  onStartupStatus: (callback) => {
    const handler = (event, status) => callback(status);
    ipcRenderer.on('startup-status', handler);
    // Return cleanup function
    return () => ipcRenderer.removeListener('startup-status', handler);
  },
});

// Log that preload script has loaded
console.log('Nexus AI Installer - Preload script loaded successfully');

// You can also expose Node.js APIs safely
contextBridge.exposeInMainWorld('nodeAPI', {
  platform: process.platform,
  arch: process.arch,
  versions: process.versions
});
