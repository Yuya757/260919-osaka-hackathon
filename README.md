# 超イベント管理（仮称）

ユーザーの関心に合うイベントをGeminiで探索・検証し、「申込締切」と「開催日」を分けて提示するイベント管理アプリケーションです。

## 技術構成

- Frontend: React + Vite + TypeScript
- API / Agent: FastAPI + Google ADK for Python
- AI: Vertex AI Gemini + Google Search Grounding
- Hosting: Firebase Hosting
- Runtime: Cloud Run Service / Cloud Run Job
- Data: Cloud Firestore
- Authentication: Firebase Authentication
- Scheduling: Cloud Scheduler

## リポジトリ構成

```text
.
├── apps/
│   └── web/                    # React + Viteフロントエンド
├── services/
│   └── agent/                  # FastAPI + Google ADKバックエンド
├── packages/
│   └── contracts/              # Web・Agent間の共有Schema
├── evals/                      # Agent評価データと評価ケース
├── infra/                      # GCP・Firebase構成
├── docs/                       # 補足設計資料
├── scripts/                    # WSLで実行する開発・デプロイスクリプト
├── .cursor/
│   └── skills/                 # プロジェクト固有のCursor Skills
└── AGENTS.md                   # AI Agent向けプロジェクト規約
```

## 開発方針

- WebはSPAとして実装し、SSRを前提としない
- APIとAgent処理はPythonへ集約する
- 手動収集はCloud Tasks経由、定期収集はCloud SchedulerとCloud Run Jobで実行する
- Calendarへの書き込みはユーザーの明示操作後にのみ行う
- 日時情報には根拠URLを保持し、不明な値を推測しない

## ドキュメント

- [プロジェクト要件定義書](docs/イベント自律管理AIエージェント%20要件定義書.md)
- [Agent詳細要件定義書](docs/Agent詳細要件定義書.md)

## セットアップ

実装開始時に、各ディレクトリへ個別のセットアップ手順を追加します。