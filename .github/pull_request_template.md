## 変更内容

<!-- 何を変えたか。差分を読めば分かる範囲ではなく、変更の単位を書く。 -->

## 変更理由

<!-- なぜこの変更が必要か。関連するIssue、設計書の節番号があれば示す。 -->

## 影響範囲

- [ ] `apps/web`
- [ ] `services/agent`
- [ ] `packages/contracts`
- [ ] `evals`
- [ ] `infra` / `.github/workflows`
- [ ] `docs`

## 検証

<!-- 実行したコマンドと結果を書く。 -->

- [ ] `pytest -q`（`services/agent`）
- [ ] `npm run check` / `npm run build`（`apps/web`）
- [ ] `./scripts/run-evals.sh`（Prompt・Schema・Validation Rule・モデルを変更した場合は必須、§13.3）

## 確認事項

- [ ] baseが `develop` になっている（`main` ではない）
- [ ] シークレット、OAuthトークン、`.env`、生成された資格情報を含んでいない
- [ ] 契約を変更した場合、`packages/contracts/` を先に更新した
