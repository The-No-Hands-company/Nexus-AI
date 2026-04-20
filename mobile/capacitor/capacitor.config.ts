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
};

export default config;
