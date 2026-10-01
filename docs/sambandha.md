# sambandha
> Repository portfolio profile for sambandha (C Header, Dart / Flutter, Flutter / Dart, HTML, Java, JavaScript)

---

## 📋 Overview

**sambandha** is a software project developed by Dibij.

According to the project documentation:

> A feature-rich, cross-platform Flutter dating and matrimony application built for Android and iOS. Sambandha blends modern dating flows (interactive swiping, video reels, and real-time audio/video calling) with cultural matchmaking features like Kundli (astrological chart) matching.

---


**Sambandha** is a mobile application developed using Flutter that provides a unified platform for dating and matrimonial matchmaking. It serves as a modern bridge for relationships, featuring localized interfaces, high-quality WebRTC calls, profile verification, and astrological compatibility checking.

The codebase is built primarily using **C Header, Dart / Flutter, Flutter / Dart, HTML, Java, JavaScript**, comprising 259 total files across the repository structure.

## 🗓️ Timeline

| Field | Value |
|-------|-------|
| **Started** | April 2026 |
| **Last Active** | July 2026 |
| **Duration** | ~3 months |

## 🔗 Repository

| Field | Value |
|-------|-------|
| **GitHub** | https://github.com/Dibij/sambandha |
| **Created on GitHub** | April 26, 2026 |
| **Last pushed** | July 12, 2026 |

## 🛠️ Tech Stack

- **C Header**
- **Dart / Flutter**
- **Flutter / Dart**
- **HTML**
- **Java**
- **JavaScript**

## 📁 Project Structure

```
sambandha/
├── .github/
│   └── workflows/
│       ├── flutter_ci.yml
│       └── release.yml
├── .sambandha/
│   └── procedures.md
├── android/
│   ├── app/
│   │   ├── src/
│   │   │   ├── debug/
│   │   │   ├── main/
│   │   │   └── profile/
│   │   ├── build.gradle.kts
│   │   └── google-services.json
│   ├── gradle/
│   │   └── wrapper/
│   │       └── gradle-wrapper.properties
│   ├── .gitignore
│   ├── build.gradle.kts
│   ├── gradle.properties
│   └── settings.gradle.kts
├── assets/
│   ├── images/
│   │   ├── logo.png
│   │   ├── logos.png
│   │   └── profile.png
│   └── translations/
│       ├── en.json
│       └── ne.json
├── functions/
│   ├── index.js
│   ├── package-lock.json
│   └── package.json
├── ios/
│   ├── Flutter/
│   │   ├── AppFrameworkInfo.plist
│   │   ├── Debug.xcconfig
│   │   └── Release.xcconfig
│   ├── Runner/
│   │   ├── Assets.xcassets/
│   │   │   ├── AppIcon.appiconset/
│   │   │   └── LaunchImage.imageset/
│   │   ├── Base.lproj/
│   │   │   ├── LaunchScreen.storyboard.xml
│   │   │   └── Main.storyboard.xml
│   │   ├── AppDelegate.swift
│   │   ├── Info.plist
│   │   ├── Runner-Bridging-Header.h
│   │   └── SceneDelegate.swift
│   ├── Runner.xcodeproj/
│   │   ├── project.xcworkspace/
│   │   │   ├── xcshareddata/
│   │   │   └── contents.xcworkspacedata.xml
│   │   ├── xcshareddata/
│   │   │   └── xcschemes/
│   │   └── project.pbxproj
│   ├── Runner.xcworkspace/
│   │   ├── xcshareddata/
│   │   │   ├── IDEWorkspaceChecks.plist
│   │   │   └── WorkspaceSettings.xcsettings.xml
│   │   └── contents.xcworkspacedata.xml
│   ├── RunnerTests/
│   │   └── RunnerTests.swift
│   └── .gitignore
├── lib/
│   ├── constants/
│   │   ├── api_constants.dart
│   │   ├── firestore_constants.dart
│   │   └── secrets.dart
│   ├── core/
│   │   └── di/
│   │       └── injection.dart
│   ├── models/
│   │   ├── astrology_models.dart
│   │   ├── conversation_model.dart
│   │   ├── date_model.dart
│   │   ├── event_model.dart
│   │   ├── language_selector.dart
│   │   ├── match_model.dart
│   │   ├── message_model.dart
│   │   ├── notification_model.dart
│   │   ├── panic_alert_model.dart
│   │   ├── payment_model.dart
│   │   ├── profile_model.dart
│   │   ├── reel_model.dart
│   │   ├── user_model.dart
│   │   ├── user_profile_model.dart
│   │   └── verification_model.dart
│   ├── repositories/
│   │   ├── astrology_repository.dart
│   │   ├── auth_repository.dart
│   │   ├── bookmark_repository.dart
│   │   ├── chat_repository.dart
│   │   ├── database_seeder_repository.dart
│   │   ├── date_repository.dart
│   │   ├── discovery_repository.dart
│   │   ├── explore_repository.dart
│   │   ├── location_repository.dart
│   │   ├── panic_repository.dart
│   │   ├── profile_repository.dart
│   │   ├── reel_repository.dart
│   │   └── verification_repository.dart
│   ├── routes/
│   │   └── app_routes.dart
│   ├── screens/
│   │   ├── call_screen.dart
│   │   └── panic_screen.dart
│   ├── services/
│   │   ├── account_deletion_service.dart
│   │   ├── astrology_interpretation_service.dart
│   │   ├── astrology_service.dart
│   │   ├── auth_service.dart
│   │   ├── base64_conversion_service.dart
│   │   ├── bookmark_service.dart
│   │   ├── chat_service.dart
│   │   ├── data_takeout_service.dart
│   │   ├── database_seeder_service.dart
│   │   ├── date_service.dart
│   │   ├── deep_link_service.dart
│   │   ├── encryption_service.dart
│   │   ├── external_app_service.dart
│   │   ├── geospatial_service.dart
│   │   ├── image_picker_service.dart
│   │   ├── language_service.dart
│   │   ├── livekit_config_service.dart
│   │   ├── location_service.dart
│   │   ├── match_service.dart
│   │   ├── matchingengine_service.dart
│   │   ├── notification_service.dart
│   │   ├── panic_listener.dart
│   │   ├── panic_service.dart
│   │   ├── payment_service.dart
│   │   ├── profile_discovery_service.dart
│   │   ├── profile_service.dart
│   │   ├── storage_service.dart
│   │   ├── swipe_service.dart
│   │   ├── user_action_service.dart
│   │   └── video_service.dart
│   ├── theme/
│   │   └── app_theme.dart
│   ├── utils/
│   │   └── input_sanitizer.dart
│   ├── viewmodels/
│   │   ├── auth_viewmodel.dart
│   │   ├── bookmark_viewmodel.dart
│   │   ├── chat_viewmodel.dart
│   │   ├── compatibility_viewmodel.dart
│   │   ├── conversations_viewmodel.dart
│   │   ├── dashboard_viewmodel.dart
│   │   ├── database_seeder_viewmodel.dart
│   │   ├── date_viewmodel.dart
│   │   ├── discovery_viewmodel.dart
│   │   ├── edit_profile_viewmodel.dart
│   │   ├── events_viewmodel.dart
│   │   ├── kundli_viewmodel.dart
│   │   ├── profile_detail_viewmodel.dart
│   │   ├── profile_viewmodel.dart
│   │   ├── reel_viewmodel.dart
│   │   ├── settings_viewmodel.dart
│   │   └── verification_viewmodel.dart
│   ├── views/
│   │   ├── admin/
│   │   │   └── database_seeder_view.dart
│   │   ├── admin_dashboard_screen.dart
│   │   ├── birth_details_form_screen.dart
│   │   ├── bookmarks_screen.dart
│   │   ├── chat_screen.dart
│   │   ├── compatibility_check_screen.dart
│   │   ├── compatibility_screen.dart
│   │   ├── conversations_screen.dart
│   │   ├── create_new_password_screen.dart
│   │   ├── dashboard_screen.dart
│   │   ├── date_request_card.dart
│   │   ├── editprofile_screen.dart
│   │   ├── event_detail_screen.dart
│   │   ├── events_screen.dart
│   │   ├── forgot_password_otp_screen.dart
│   │   ├── forgot_password_screen.dart
│   │   ├── gallery_viewer_screen.dart
│   │   ├── help_support_screen.dart
│   │   ├── kundli_screen.dart
│   │   ├── login_screen.dart
│   │   ├── menu_screen.dart
│   │   ├── messages_screen.dart
│   │   ├── my_profile_screen.dart
│   │   ├── notifications_screen.dart
│   │   ├── otp_screen.dart
│   │   ├── phone_auth_screen.dart
│   │   ├── preference_selector.dart
│   │   ├── premium_screen.dart
│   │   ├── profile_detail_view.dart
│   │   ├── profile_reel_widget.dart
│   │   ├── reel_player_view.dart
│   │   ├── reshedule_date_sheet.dart
│   │   ├── schedule_date_sheet.dart
│   │   ├── settings_screen.dart
│   │   ├── signup_screen.dart
│   │   ├── splash_screen.dart
│   │   └── verification_view.dart
│   ├── widgets/
│   │   ├── kundli_chart.dart
│   │   ├── live_verification_overlay.dart
│   │   ├── premium_swipe_widget.dart
│   │   ├── sambandha_input_field.dart
│   │   ├── sambandha_primary_button.dart
│   │   ├── social_login_button.dart
│   │   └── upcoming_timer_card.dart
│   ├── firebase_options.dart
│   └── main.dart
├── test/
│   ├── week2/
│   │   └── widget_test.dart
│   ├── week3/
│   │   ├── bookmarked_profile_test.dart
│   │   ├── e_kyc_test.dart
│   │   ├── language_selector_test.dart
│   │   ├── panic_button_test.dart
│   │   └── phone_otp_test.dart
│   ├── week4/
│   │   ├── chat_engine_test.dart
│   │   ├── encryption_test.dart
│   │   ├── home_widget_test.dart
│   │   ├── multimedia_sharing_test.dart
│   │   └── voice_recorder_ui_test.dart
│   ├── week5/
│   │   ├── connection_notification_test.dart
│   │   ├── interest_matching_test.dart
│   │   ├── ride_sharing_location_test.dart
│   │   ├── search_filter_test.dart
│   │   └── weighted_matching_test.dart
│   ├── week6/
│   │   ├── chino_generation_test.dart
│   │   ├── date_completion_pin_test.dart
│   │   ├── emergency_heartbeat_test.dart
│   │   ├── gun_milap_api_test.dart
│   │   ├── push_notification_engine_test.dart
│   │   └── schedule_physical_date_workflow_test.dart
│   ├── week8/
│   │   ├── connection_requests_notification_test.dart
│   │   ├── geospatial_search_test.dart
│   │   ├── interest_based_matching_engine_test.dart
│   │   ├── ride_sharing_pathao_test.dart
│   │   ├── search_filter_algorithm_test.dart
│   │   └── weighted_matching_algorithm_test.dart
│   ├── img.png
│   ├── samandha_Sprint4_QA_Test_Report.md
│   ├── samandha_Week3_QA_Test_Report.md
│   ├── Sambandha_Sprint2_QA_Test_Report.md
│   ├── Sambandha_Week5_QA_Test_Report.md
│   └── sambandha_Week6_QA_Test_Report.md
├── web/
│   ├── icons/
│   │   ├── Icon-192.png
│   │   ├── Icon-512.png
│   │   ├── Icon-maskable-192.png
│   │   └── Icon-maskable-512.png
│   ├── favicon.png
│   ├── index.html
│   └── manifest.json
├── .gitignore
├── .metadata
├── analysis.txt
├── analysis_options.yaml
├── audit-report.md
├── devtools_options.yaml
├── extracted_strings.txt
├── firebase.json
├── firestore.rules
├── pubspec.lock
├── pubspec.yaml
├── README.md
└── sa
```

## 🚀 Key Features / Key Files

- `bin\create_test_date.dart`: Implements core functionality starting with `// ignore_for_file: avoid_print`
- `bin\monitor.dart`: Implements core functionality starting with `// bin/monitor.dart`
- `bin\seed_profiles.dart`: Implements core functionality starting with `import 'dart:convert';`
- `bin\update_profile_locations.dart`: Implements core functionality starting with `// ignore_for_file: avoid_print`
- `functions\index.js`: Implements core functionality starting with `const functions = require('firebase-functions');`

## 📝 Notes

- An existing `README.md` was present in the repository and integrated into this profile.
- A total of **1** git commit(s) were recorded for this project.