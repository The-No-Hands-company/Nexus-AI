# Release Signing And Notarization

This repository now supports secret-driven release signing for desktop and mobile builds.

## Electron release secrets

- `MACOS_CERTIFICATE_P12_BASE64`: Base64-encoded Developer ID Application certificate.
- `MACOS_CERTIFICATE_PASSWORD`: Password for the macOS signing certificate.
- `APPLE_ID`: Apple ID used for notarization.
- `APPLE_APP_SPECIFIC_PASSWORD`: App-specific password for notarization.
- `APPLE_TEAM_ID`: Apple team ID used by electron-builder notarization.
- `WINDOWS_CERTIFICATE_P12_BASE64`: Base64-encoded Authenticode certificate.
- `WINDOWS_CERTIFICATE_PASSWORD`: Password for the Windows signing certificate.

## Android signing secrets

- `ANDROID_KEYSTORE_BASE64`: Base64-encoded Android release keystore.
- `ANDROID_KEYSTORE_PASSWORD`: Keystore password.
- `ANDROID_KEY_ALIAS`: Alias inside the keystore.
- `ANDROID_KEY_PASSWORD`: Alias key password.

## iOS signing secrets

- `IOS_BUILD_CERTIFICATE_BASE64`: Base64-encoded iOS distribution certificate in P12 format.
- `IOS_P12_PASSWORD`: Password for the iOS P12 certificate.
- `IOS_KEYCHAIN_PASSWORD`: Temporary keychain password for GitHub Actions.
- `IOS_PROVISIONING_PROFILE_BASE64`: Base64-encoded provisioning profile.
- `IOS_TEAM_ID`: Apple Developer team ID.
- `IOS_CODE_SIGN_IDENTITY`: Code signing identity, for example `Apple Distribution: Example, Inc.`
- `IOS_PROVISIONING_PROFILE_SPECIFIER`: Provisioning profile specifier name.

## Release gate and tagging

- Workflow: `Release Tag Gate`
- Required upstream workflows on the release branch SHA:
  - `Electron Build and Release`
  - `Mobile Capacitor CI`

Use the `Release Tag Gate` workflow dispatch to create tags. It refuses to create a tag unless both upstream workflows succeeded on the current release branch head SHA.

## Branch protection

GitHub branch protection is not stored natively in this repository. Configure it in repository settings for the `release` branch and require these checks:

- `Electron Build and Release`
- `Mobile Capacitor CI`
- `Release Tag Gate`

This makes the branch green only when desktop build verification, mobile build verification, and the aggregate gate have all passed.