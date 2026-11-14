# Private Android and iOS testing

This project is configured for private pre-release testing, not a public store launch.

## What is configured

- Android package: `com.csingh1s.habitatinspector`
- iOS bundle identifier: `com.csingh1s.habitatinspector`
- `device-preview`: a direct-install Android APK for device checks outside Google Play.
- `store-test`: store-signed Android AAB and iOS archive for Google Play Internal Testing and
  Apple TestFlight.

The Android package and iOS bundle identifier are permanent store identities. Do not change
them after the first Google Play or App Store Connect upload.

## One-time account prerequisites

1. Create or use an Expo account and create an Expo project for this app.
2. Enroll the organization or individual developer account in:
   - Google Play Console (one-time registration fee).
   - Apple Developer Program (annual membership).
3. Create the app record in both consoles using the identifiers above:
   - Google Play: `com.csingh1s.habitatinspector`
   - App Store Connect: `com.csingh1s.habitatinspector`
4. Configure an Android upload key and an Apple distribution certificate/provisioning profile
   through EAS. Do not commit any keys, certificates, provisioning profiles, API keys, or
   service-account files to this repository.

## Build a private testing release

Authenticate interactively from the `mobile` folder:

```powershell
npx eas-cli login
npx eas-cli build:configure
```

The second command links this local project to the Expo project and adds the non-secret
project reference needed by EAS. Review that change before committing it.

Create store-ready test builds:

```powershell
npm run build:android:test
npm run build:ios:test
```

These cloud builds use the `store-test` profile. EAS increments remote store build numbers.

## Distribute to testers

### Android: Google Play Internal Testing

1. Upload the generated Android AAB to the **Internal testing** track in Google Play Console.
2. Add tester email addresses or a Google Group.
3. Share only the Play testing opt-in link with approved testers.
4. Verify installation, camera permission, photo-library permission, upload retry, and
   human-review behavior on physical Android devices.

### iOS: Apple TestFlight

1. Upload the generated iOS build to App Store Connect, or use the EAS submit workflow after
   Apple credentials are configured.
2. Wait for Apple processing to complete.
3. Add internal testers first. Use external testers only after Apple Beta App Review if needed.
4. Share the TestFlight invitation only with approved testers.

## Required testing gates

Before inviting external users, verify:

- A user cannot access another tenant's evidence.
- A failed upload does not create a report finding.
- A Qwen result is always labeled as a review candidate with source evidence and uncertainty.
- A user cannot publish or send an AI-generated result without qualified human approval.
- Camera/photo permissions and privacy language are correct on both platforms.
- No development identity headers, endpoints, tokens, or secrets exist in a production build.

Do not upload real client photos to external test services until consent, retention, and
privacy controls are approved.
