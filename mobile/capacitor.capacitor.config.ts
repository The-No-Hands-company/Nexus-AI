// Capacitor configuration for Nexus AI Mobile Application
// Enhanced with native plugins for improved functionality

import type { CapacitorConfig } from '@capacitor/cli';

function resolveServerConfig() {
  const raw = process.env.NEXUS_MOBILE_SERVER_URL?.trim();
  if (!raw) {
    return {
      androidScheme: 'https',
      iosScheme: 'https',
    };
  }
  try {
    const parsed = new URL(raw);
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
      return {
        androidScheme: 'https',
        iosScheme: 'https',
      };
    }
    return {
      url: parsed.toString(),
      cleartext: parsed.protocol === 'http:',
      allowNavigation: [parsed.host],
      androidScheme: parsed.protocol === 'http:' ? 'http' : 'https',
      iosScheme: parsed.protocol === 'http:' ? 'http' : 'https',
    };
  } catch {
    return {
      androidScheme: 'https',
      iosScheme: 'https',
    };
  }
}

const config: CapacitorConfig = {
  appId: 'ai.nexus.mobile',
  appName: 'Nexus AI',
  webDir: '../../static',
  bundledWebRuntime: false,
  server: resolveServerConfig(),
  backgroundColor: '#0a0f1a',
  plugins: {
    // Configure commonly used Capacitor plugins
    SplashScreen: {
      launchShowDuration: 3000,
      launchAutoHide: true,
      backgroundColor: "#0a0f1a",
      androidScaleType: "CENTER_CROP",
      showSpinner: true,
      spinnerColor: "#7c6af7",
      iosSpinnerStyle: "large",
      androidSpinnerStyle: "large",
    },
    Keyboard: {
      resize: 'body',
      style: 'DARK',
    },
    StatusBar: {
      overlaysWebView: true,
      style: 'LIGHT',
      backgroundColor: '#0a0f1a',
    },
    // Camera configuration for image input
    Camera: {
      quality: 80,
      allowEditing: false,
      resultType: 0, // FILE_URI
      saveToGallery: true,
      correctOrientation: true,
    },
    // Filesystem for saving generated images
    Filesystem: {
      // Default to app's documents directory
      directory: 'Documents',
      encoding: 'utf-8',
    },
    // Local notifications for reminders from proactive agents
    LocalNotifications: {
      // Small icon for notification tray
      smallIcon: "ic_stat_icon_sample",
      // Icon color (Android only)
      iconColor: "#488AFF",
      // Sound to play
      sound: "res://platform_default",
    }
  }
};

export default config;