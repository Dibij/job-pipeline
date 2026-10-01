# ai-tutorer
> Repository portfolio profile for ai-tutorer (CSS, HTML, JavaScript, Python, TypeScript)

---

## 📋 Overview

**ai-tutorer** is a software project developed by Dibij.

According to the project documentation:

> Suisik is a cutting-edge, AI-powered tutoring platform designed to transform static educational materials into dynamic, personalized learning experiences. Upload your PDFs, documents, or texts, and Suisik will automatically extract topics, generate hierarchical chunks, and create adaptive quizzes for you.


- **Semantic Content Processing:** Advanced PDF/DOCX parsing with hierarchical chunking.
- **Topic Extraction:** Automated identification of key concepts using LLMs (Mistral/Llama).
- **RAG-Powered Learning:** Retrieval Augmented Generation for context-aware Q&A and quiz generation.
- **Adaptive Quizzes:** AI-generated multiple-choice, true/false, and multi-select questions tailored to your knowledge level.

The codebase is built primarily using **CSS, HTML, JavaScript, Python, TypeScript**, comprising 238 total files across the repository structure.

## 🗓️ Timeline

| Field | Value |
|-------|-------|
| **Started** | September 2025 |
| **Last Active** | February 2026 |
| **Duration** | ~6 months |

## 🔗 Repository

| Field | Value |
|-------|-------|
| **GitHub** | https://github.com/Dibij/ai-tutorer |
| **Created on GitHub** | September 08, 2025 |
| **Last pushed** | February 26, 2026 |

## 🛠️ Tech Stack

- **CSS**
- **HTML**
- **JavaScript**
- **Python**
- **TypeScript**

## 📁 Project Structure

```
ai-tutorer/
├── frontend/
│   ├── app/
│   │   ├── dashboard/
│   │   │   ├── components/
│   │   │   ├── layout.tsx
│   │   │   └── page.tsx
│   │   ├── login/
│   │   │   └── page.tsx
│   │   ├── quiz/
│   │   │   ├── [id]/
│   │   │   ├── generate/
│   │   │   ├── list/
│   │   │   ├── results/
│   │   │   ├── layout.tsx
│   │   │   └── page.tsx
│   │   ├── register/
│   │   │   └── page.tsx
│   │   ├── resources/
│   │   │   ├── layout.tsx
│   │   │   └── page.tsx
│   │   ├── globals.css
│   │   ├── layout.tsx
│   │   └── page.tsx
│   ├── components/
│   │   ├── LandingPage/
│   │   │   ├── FeatureCard.tsx
│   │   │   └── Footer.tsx
│   │   ├── modals/
│   │   │   ├── GoalsModal.tsx
│   │   │   └── UploadModal.tsx
│   │   └── shared/
│   │       ├── Footer.tsx
│   │       ├── Layout.tsx
│   │       └── Navbar.tsx
│   ├── lib/
│   │   ├── api.ts
│   │   ├── auth-utils.ts
│   │   ├── store.ts
│   │   └── utils.ts
│   ├── types/
│   │   └── google.d.ts
│   ├── .eslintrc.json
│   ├── .gitignore
│   ├── middleware.ts
│   ├── next-env.d.ts
│   ├── next.config.js
│   ├── package-lock.json
│   ├── package.json
│   ├── postcss.config.js
│   ├── tailwind.config.ts
│   ├── tsconfig.json
│   └── tsconfig.tsbuildinfo
├── mysite/
│   ├── mysite/
│   │   ├── __init__.py
│   │   ├── asgi.py
│   │   ├── celery_config.py
│   │   ├── settings.py
│   │   ├── settings.py.backup
│   │   ├── settings_production.py
│   │   ├── urls.py
│   │   └── wsgi.py
│   ├── static/
│   │   ├── css/
│   │   │   ├── input.css
│   │   │   ├── mobile-responsive.css
│   │   │   └── skeleton.css
│   │   └── js/
│   │       ├── auto-save.js
│   │       ├── keyboard-shortcuts.js
│   │       ├── mobile-handler.js
│   │       ├── progress-indicator.js
│   │       ├── skeletons.js
│   │       └── toast.js
│   ├── student/
│   │   ├── api/
│   │   │   ├── v1/
│   │   │   ├── __init__.py
│   │   │   ├── exceptions.py
│   │   │   ├── health.py
│   │   │   └── rag_endpoints.py
│   │   ├── management/
│   │   │   ├── commands/
│   │   │   └── __init__.py
│   │   ├── middleware/
│   │   │   ├── __init__.py
│   │   │   ├── rate_limit.py
│   │   │   └── request_id.py
│   │   ├── migrations/
│   │   │   ├── 0001_initial.py
│   │   │   ├── 0002_studentresource_topics.py
│   │   │   ├── 0003_add_explanation_timing_history.py
│   │   │   ├── 0004_rename_student_qui_owner_i_idx_student_qui_owner_i_c15bea_idx_and_more.py
│   │   │   ├── 0004_topic_hierarchy_and_analytics.py
│   │   │   ├── 0005_quizgenerationsession_useractivitylog.py
│   │   │   ├── 0005_student_goals_and_quiz_analysis.py
│   │   │   ├── 0006_add_multiple_answers_support.py
│   │   │   ├── 0006_add_topics_to_question.py
│   │   │   ├── 0007_merge_20251031_0406.py
│   │   │   ├── 0008_merge_20251031_0422.py
│   │   │   ├── 0009_auto_learning_style.py
│   │   │   ├── 0010_rename_student_stu_topic_idx_student_stu_topic_e_65b663_idx_and_more.py
│   │   │   ├── 0011_merge_20251031_1415.py
│   │   │   ├── 0012_remove_studenttopicembedding_parent_topic_id_and_more.py
│   │   │   ├── 0013_studentresource_character_count_and_more.py
│   │   │   ├── 0014_studentquestion_char_range_end_and_more.py
│   │   │   ├── 0015_alter_topic_resource_kgtopic_kgsubtopic_and_more.py
│   │   │   ├── 0016_studentresource_kg_generated_and_more.py
│   │   │   ├── 0017_alter_studentaccount_options_and_more.py
│   │   │   ├── 0018_studentresource_created_at.py
│   │   │   ├── 0019_studentresourcechunk_metadata.py
│   │   │   ├── 0020_studentquiz_resource_and_more.py
│   │   │   ├── 0021_alter_topic_options_and_more.py
│   │   │   ├── 0022_chunk_hierarchy_and_similarity.py
│   │   │   ├── 0023_remove_studentresourcechunk_chunk_id_and_more.py
│   │   │   ├── 0024_readd_chunk_hierarchy_and_similarity.py
│   │   │   ├── 0025_rename_student_chunksim_chunk_f_02d83c_idx_student_chu_chunk_f_bdb1b7_idx_and_more.py
│   │   │   ├── 0026_outline_and_topic_chunks.py
│   │   │   ├── 0027_rename_student_doc_resource_6ebc72_idx_student_doc_resourc_cef62f_idx_and_more.py
│   │   │   ├── 0028_topicchunk_topic_name_and_parent.py
│   │   │   ├── 0029_studentresource_deleted_at_and_more.py
│   │   │   ├── 0030_studentresourcechunk_chunk_type.py
│   │   │   ├── 0031_topic_related_chunks.py
│   │   │   ├── 0032_remove_topic_related_chunks_topic_mention_count_and_more.py
│   │   │   ├── 0033_studentquiz_status_studentquiz_total_questions.py
│   │   │   └── __init__.py
│   │   ├── processing/
│   │   │   ├── __init__.py
│   │   │   └── rag_processor.py
│   │   ├── scripts/
│   │   │   ├── health_check.py
│   │   │   ├── health_check_simple.py
│   │   │   └── rechunk_resource.py
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── content_processor.py
│   │   │   ├── deduplicator.py
│   │   │   ├── embedding_service.py
│   │   │   ├── knowledge_graph.py
│   │   │   ├── llm_service.py
│   │   │   ├── ollama_service.py
│   │   │   ├── pdf_extractor.py
│   │   │   ├── quiz_optimizer.py
│   │   │   └── topic_extractor.py
│   │   ├── static/
│   │   │   ├── css/
│   │   │   └── js/
│   │   ├── templates/
│   │   │   ├── socialaccount/
│   │   │   ├── student/
│   │   │   └── landing.html
│   │   ├── templatetags/
│   │   │   ├── __init__.py
│   │   │   └── quiz_extras.py
│   │   ├── tests/
│   │   │   ├── __init__.py
│   │   │   ├── test_content_processor.py
│   │   │   ├── test_quiz_optimizer.py
│   │   │   └── test_rag.py
│   │   ├── utils/
│   │   │   ├── __init__.py
│   │   │   ├── auth_utils.py
│   │   │   ├── exceptions.py
│   │   │   ├── permissions.py
│   │   │   └── validators.py
│   │   ├── views/
│   │   │   ├── __init__.py
│   │   │   ├── auth_views.py
│   │   │   ├── dashboard_views.py
│   │   │   ├── download_views.py
│   │   │   ├── helpers.py
│   │   │   ├── quiz_views.py
│   │   │   └── resource_views.py
│   │   ├── __init__.py
│   │   ├── adapters.py
│   │   ├── admin.py
│   │   ├── admin_api.py
│   │   ├── api.py
│   │   ├── apps.py
│   │   ├── book_ingestion.py
│   │   ├── cache.py
│   │   ├── chunking.py
│   │   ├── core.py
│   │   ├── exceptions.py
│   │   ├── hierarchical_quiz_generator.py
│   │   ├── hierarchical_rag.py
│   │   ├── models.py
│   │   ├── nextjs_api.py
│   │   ├── quizzes.py
│   │   ├── rag.py
│   │   ├── rag_utils.py
│   │   ├── sse_manager.py
│   │   ├── student_goals_api.py
│   │   ├── tasks.py
│   │   ├── topics.py
│   │   ├── urls.py
│   │   └── views.py
│   ├── celery_config.py
│   ├── check_quiz_db.py
│   ├── fix_embeddings_clean.py
│   ├── health_report_20251222_165435.txt
│   ├── manage.py
│   ├── nuke_oauth.py
│   ├── package-lock.json
│   ├── package.json
│   ├── README.md
│   ├── start_server.bat
│   └── tailwind.config.js
├── .gitignore
├── audit-report.md
├── CHANGELOG.md
├── debug_chunker.py
├── PROJECT_ANALYSIS.md
├── README.md
└── requirements.txt
```

## 🚀 Key Features / Key Files

- `debug_chunker.py`: Implements core functionality starting with `import os`
- `frontend\middleware.ts`: Implements core functionality starting with `import { NextRequest, NextResponse } from 'next/server'`
- `frontend\next-env.d.ts`: Implements core functionality starting with `/// <reference types="next" />`
- `frontend\next.config.js`: Implements core functionality starting with `/** @type {import('next').NextConfig} */`
- `frontend\postcss.config.js`: Implements core functionality starting with `module.exports = {`

## 📦 Dependencies & Setup

Key libraries / dependencies referenced in project manifests:

- `aiohappyeyeballs==2.6.1`
- `aiohttp==3.13.0`
- `aiosignal==1.4.0`
- `alembic==1.17.0`
- `amqp==5.3.1`
- `annotated-types==0.7.0`
- `anyio==4.11.0`
- `asgiref==3.9.1`
- `async-timeout==5.0.1`
- `attrs==25.4.0`

## 📝 Notes

- An existing `README.md` was present in the repository and integrated into this profile.
- A total of **1** git commit(s) were recorded for this project.