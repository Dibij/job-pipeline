# Real-Beginners
> Repository portfolio profile for Real-Beginners (CSS, Python, TypeScript)

---

## 📋 Overview

**Real-Beginners** is a software project developed by Dibij.

The codebase is built primarily using **CSS, Python, TypeScript**, comprising 79 total files across the repository structure.

## 🗓️ Timeline

| Field | Value |
|-------|-------|
| **Started** | January 2026 |
| **Last Active** | January 2026 |
| **Duration** | 1 day |

## 🔗 Repository

| Field | Value |
|-------|-------|
| **GitHub** | https://github.com/Dibij/Real-Beginners |
| **Created on GitHub** | January 19, 2026 |
| **Last pushed** | January 19, 2026 |

## 🛠️ Tech Stack

- **CSS**
- **Python**
- **TypeScript**

## 📁 Project Structure

```
Real-Beginners/
├── backend/
│   ├── api_app/
│   │   ├── migrations/
│   │   │   ├── 0001_initial.py
│   │   │   ├── 0002_note_audio_file.py
│   │   │   ├── 0003_remove_note_audio_file_noteaudio.py
│   │   │   ├── 0004_note_summary.py
│   │   │   ├── 0005_actionitem.py
│   │   │   ├── 0006_actionitemhistory.py
│   │   │   ├── 0007_actionitemhistory_note_actionitemhistory_reasoning.py
│   │   │   ├── 0008_add_search_result.py
│   │   │   ├── 0009_add_notification.py
│   │   │   ├── 0010_actionitem_due_date_alarm.py
│   │   │   ├── 0011_actionitem_linked_alarm.py
│   │   │   ├── 0012_actionitem_end_time_actionitem_location_and_more.py
│   │   │   ├── 0013_alter_actionitem_item_type.py
│   │   │   ├── 0014_document_documentchunk.py
│   │   │   ├── 0015_remove_documentchunk_document_actionitem_ai_feedback_and_more.py
│   │   │   └── __init__.py
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── ai_engine.py
│   │   │   ├── email_webhook.py
│   │   │   ├── google_calendar.py
│   │   │   ├── transcription.py
│   │   │   └── web_search.py
│   │   ├── __init__.py
│   │   ├── admin.py
│   │   ├── apps.py
│   │   ├── consumers.py
│   │   ├── middleware.py
│   │   ├── models.py
│   │   ├── routing.py
│   │   ├── serializers.py
│   │   ├── tests.py
│   │   ├── urls.py
│   │   ├── utils.py
│   │   └── views.py
│   ├── voice_notes_backend/
│   │   ├── __init__.py
│   │   ├── asgi.py
│   │   ├── settings.py
│   │   ├── urls.py
│   │   └── wsgi.py
│   └── manage.py
├── frontend/
│   ├── public/
│   │   ├── sounds/
│   │   │   └── alarm_default.mp3
│   │   ├── file.svg
│   │   ├── globe.svg
│   │   ├── next.svg
│   │   ├── vercel.svg
│   │   └── window.svg
│   ├── src/
│   │   ├── app/
│   │   │   ├── calendar/
│   │   │   ├── clock/
│   │   │   ├── dashboard/
│   │   │   ├── history/
│   │   │   ├── login/
│   │   │   ├── register/
│   │   │   ├── search/
│   │   │   ├── search-history/
│   │   │   ├── settings/
│   │   │   ├── favicon.ico
│   │   │   ├── globals.css
│   │   │   ├── layout.tsx
│   │   │   └── page.tsx
│   │   ├── components/
│   │   │   ├── AudioVisualizer.tsx
│   │   │   ├── CreateNoteModal.tsx
│   │   │   ├── NoteDetailModal.tsx
│   │   │   ├── SettingsModal.tsx
│   │   │   └── Sidebar.tsx
│   │   ├── context/
│   │   │   ├── AuthContext.tsx
│   │   │   └── ThemeContext.tsx
│   │   └── utils/
│   │       └── api.ts
│   ├── .gitignore
│   ├── eslint.config.mjs
│   ├── next.config.ts
│   ├── package-lock.json
│   ├── package.json
│   ├── postcss.config.mjs
│   ├── README.md
│   └── tsconfig.json
├── .gitignore
├── requirements.txt
├── test_search_intent.py
└── test_transcribe.py
```

## 🚀 Key Features / Key Files

- `test_search_intent.py`: Implements core functionality starting with `import re`
- `test_transcribe.py`: Implements core functionality starting with `from faster_whisper import WhisperModel`
- `backend\manage.py`: Implements core functionality starting with `#!/usr/bin/env python`
- `frontend\next.config.ts`: Implements core functionality starting with `import type { NextConfig } from "next";`
- `backend\api_app\admin.py`: Implements core functionality starting with `from django.contrib import admin`

## 📦 Dependencies & Setup

Key libraries / dependencies referenced in project manifests:

- `aiohappyeyeballs==2.6.1`
- `annotated-types==0.7.0`
- `anyio==4.9.0`
- `argon2-cffi==25.1.0`
- `argon2-cffi-bindings==21.2.0`
- `arrow==1.3.0`
- `asgiref==3.9.1`
- `asttokens==3.0.0`
- `async-lru==2.0.5`
- `attrs==25.3.0`

## 📝 Notes

- No standalone `README.md` was found in the repository root; details were extracted directly from source code and git history.
- A total of **1** git commit(s) were recorded for this project.