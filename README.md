# 超イベント管理（仮称）

ユーザーの関心に合うイベントをGeminiで探索・検証し、「申込締切」と「開催日」を分けて提示するイベント管理アプリケーションです。

## デモ

- [Firebase Hosting](https://osaka-hackathon-260919.web.app)
- `develop` ブランチへのpushでGitHub Actionsが自動デプロイします。

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
- UIはモバイルファーストで実装し、PCでは中央に狭幅で表示する（[画面設計書](docs/画面設計書_スマホ.md)）
- 画面遷移は react-router で行い、端末の戻る操作が効く状態を保つ
- 日時は必ずイベントの `dates.timezone` で解釈して表示する
- API応答は `packages/contracts/schemas/*.json` に適合させる（`services/agent/tests/test_contracts.py` が検証）

## ドキュメント

- [プロジェクト要件定義書](docs/イベント自律管理AIエージェント%20要件定義書.md)
- [Agent詳細要件定義書](docs/Agent詳細要件定義書.md)
- [スマートフォン画面設計書](docs/画面設計書_スマホ.md) — 画面一覧は §2.2、各画面仕様は §4
- [ADR-001 駅すぱあと経路検索](docs/ADR-001-駅すぱあと経路検索.md)

スマホ画面の実寸モック: [docs/mockups/mobile.html](docs/mockups/mobile.html)（ブラウザで直接開けます。ビルド不要）

## セットアップ

### Web

```bash
cd apps/web
npm ci
npm run dev
```

### Agent API

```bash
cd services/agent
uv venv .venv
source .venv/bin/activate
uv pip install -r requirements.txt
cp .env.example .env
export PYTHONPATH=src
uvicorn event_agent.entrypoints.service:app --reload --host 0.0.0.0 --port 8080
```

Vite は `/api` を `localhost:8080` へプロキシします。

GCP環境の再構成には、WSLから以下を実行します。

```bash
./scripts/bootstrap-gcp.sh
./scripts/setup-firebase.sh
```
