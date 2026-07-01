# Capacitor Configuration for Nexus AI Mobile Application
# Enhanced with essential plugins for actual functionality

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
  webDir: 'dist',
  bundledWebRuntime: false,
  server: resolveServerConfig(),
  backgroundColor: '#0a0f1a',
  plugins: {
    // Essential plugins for actual functionality
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
    // Core functionality plugins
    Camera: {
      quality: 85,
      allowEditing: true,
      resultType: 0, // FILE_URI
      saveToGallery: true,
      correctOrientation: true,
      preserveAspectRatio: true,
    },
    Filesystem: {
      // Default to app's documents directory for user files
      directory: 'Documents',
      encoding: 'utf-8',
    },
    LocalNotifications: {
      // Small icon for notification tray
      smallIcon: "ic_stat_icon_sample",
      // Icon color (Android only)
      iconColor: "#488AFF",
      // Sound to play
      sound: "res://platform_default",
      // Channel configuration
      channelId: "nexus_agents",
      channelName: "Nexus AI Agents",
      channelDescription: "Notifications from Nexus AI proactive agents",
    },
    Share: {
      // Optional: configure share dialog title
      dialogTitle: "Share with Nexus AI",
    },
    Preferences: {
      // No special configuration needed
    }
  }
};

export default config;