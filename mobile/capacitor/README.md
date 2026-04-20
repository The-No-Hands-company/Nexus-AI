# Nexus AI Mobile Shell (Capacitor)

This package wraps the Nexus AI web app as native Android/iOS projects.

## Prerequisites

- Node.js 20+
- Android Studio + Android SDK (for Android builds)
- Xcode 15+ (for iOS builds)

## Run

1. Install dependencies:
   npm install
2. Generate and sync native projects:
    npm run android:sync
    npm run ios:sync
3. Open native projects:
    npm run android:open
    npm run ios:open

## Build

- Android debug APK:
   npm run android:build:debug
- Android release APK/AAB preparation:
   npm run android:build:release
- iOS simulator build:
   npm run ios:build:sim
- iOS archive (unsigned):
   npm run ios:archive

## CI parity

- Android CI command:
   npm run ci:android
- iOS CI command:
   npm run ci:ios

## Optional live backend URL

Set `NEXUS_MOBILE_SERVER_URL` before sync/build to load a remote backend URL instead of local packaged assets.

The shell hosts the existing Nexus AI web UI with native packaging hooks.
