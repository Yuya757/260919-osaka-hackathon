# 超イベント管理（仮称）

ユーザーの関心に合うイベントをGeminiで探索・検証し、「申込締切」と「開催日」を分けて提示するイベント管理アプリケーションです。

## デモ

- [Firebase Hosting](https://osaka-hackathon-260919.web.app)
- `develop` ブランチへのpushでGitHub Actionsが自動デプロイします。つまり `develop` が本番であり、直接pushはしません（[ブランチ運用ルール](docs/ブランチ運用ルール.md)）。

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
├── evals/                      # Agent評価データセット（61ケース、§13）
├── infra/                      # GCP・Firebase構成
├── firestore.rules             # Firestore Security Rules（クライアント直接アクセスは全拒否）
├── firestore.indexes.json      # Firestore複合インデックス定義
├── docs/                       # 補足設計資料
├── scripts/                    # WSLで実行する開発・デプロイスクリプト
├── .claude/
│   └── skills/                 # プロジェクト固有のSkills（Claude Code）
├── .cursor/
│   └── skills/                 # 同内容のSkills（Cursor）。両者は同期して更新する
└── AGENTS.md                   # AI Agent向けプロジェクト規約
```

## 開発方針

- WebはSPAとして実装し、SSRを前提としない
- APIとAgent処理はPythonへ集約する
- 手動収集はCloud Tasks経由、定期収集はCloud SchedulerとCloud Run Jobで実行する
- Calendarへの書き込みはユーザーの明示操作後にのみ行う
- 日時情報には根拠URLを保持し、不明な値を推測しない
- 取得ページとユーザー発話はモデルへの入力として信頼しない（[ADR-004](docs/ADR-004-プロンプトインジェクション対策.md)）
- UIはモバイルファーストで実装し、PCでは中央に狭幅で表示する（[画面設計書](docs/画面設計書_スマホ.md)）
- 画面遷移は react-router で行い、端末の戻る操作が効く状態を保つ
- 日時は必ずイベントの `dates.timezone` で解釈して表示する
- API応答は `packages/contracts/schemas/*.json` に適合させる（`services/agent/tests/test_contracts.py` が検証）
- 永続化は `Store` プロトコル越しに行い、`MemoryStore` と `FirestoreStore` を入れ替え可能に保つ（[ADR-002](docs/ADR-002-Firestore永続化.md)）

## ドキュメント

- [プロジェクト要件定義書](docs/イベント自律管理AIエージェント%20要件定義書.md)
- [Agent詳細要件定義書](docs/Agent詳細要件定義書.md)
- [スマートフォン画面設計書](docs/画面設計書_スマホ.md) — 画面一覧は §2.2、各画面仕様は §4
- [ADR-001 駅すぱあと経路検索](docs/ADR-001-駅すぱあと経路検索.md)
- [ADR-002 Firestore永続化](docs/ADR-002-Firestore永続化.md) — コレクション構成と §9.3 の冪等性
- [ADR-003 定期Runのロックと負荷試験](docs/ADR-003-定期Runのロックと負荷試験.md) — §13.3 Load と §9.2 のRun単位クォータ
- [ADR-004 プロンプトインジェクション対策](docs/ADR-004-プロンプトインジェクション対策.md) — 検出・デリミタ・カナリアの3層と、ページと発話で扱いを分ける理由
- [ADR-005 PWA化とキャッシュ方針](docs/ADR-005-PWA化とキャッシュ方針.md) — `/api/` をキャッシュしない理由とアプリシェルだけを持つ Service Worker
- [ADR-006 主催者投稿フィード](docs/ADR-006-主催者投稿フィード.md) — 投稿を Event に実体化せず埋め込む理由、投稿本文の扱い、ボット投稿と固定枠のモデル
- [ADR-007 実ページからの抽出](docs/ADR-007-実ページからの抽出.md) — モデルは本文の該当行を引用するだけで、値は決定論的パーサが決める。本番はデモを切る
- [ADR-008 テーマ単位収集とコスト制御](docs/ADR-008-テーマ単位収集とコスト制御.md) — 収集はテーマ単位で共有し、一覧は読み出し時に採点。手動探索は設定で切替、既知ページは再抽出しない
- [ブランチ運用ルール](docs/ブランチ運用ルール.md) — `develop` が本番。作業ブランチは `develop` から切る

スマホ画面の実寸モック: [docs/mockups/mobile.html](docs/mockups/mobile.html)（ブラウザで直接開けます。ビルド不要）

## セットアップ

### Web

```bash
cd apps/web
corepack enable   # package.json の packageManager に従って pnpm を用意する
pnpm install --frozen-lockfile
pnpm run dev
```

### Agent API

テストと評価データセット:

```bash
cd services/agent && pytest         # 209件（Firestoreの56件は自動スキップ）
./scripts/run-evals.sh              # 61ケース、§13.2 の受入基準で判定
./scripts/run-integration-tests.sh  # Firestore Emulator上で273件（Java必須、§13.3）
```

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
