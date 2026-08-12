# Project guide line

## 1. プロジェクト概要
- 本プロジェクトのプラン作成、および回答は全て日本語で行います。
- ComfyUI カスタムノード `llm-direct`: llama_cpp / OpenAI 互換 API を直接叩くシンプルな LLM ノード集（gguf-direct, openai-direct）

# Memory & Handoff Instructions

## 3ファイルの役割と哲学
- 本ファイル（AGENTS.md）は「厳格なルール」、人が作成
- MEMORY.mdは「積み上がる経験」、AIが作成・AIが利用
- HANDOFF.mdは「セッション間の引き継ぎ」、AIが作成・AIが利用、ただし人間がレビューし必要な情報をキュレーションする

## セッション開始時（必須）
セッション開始時、ユーザーへの最初の応答の前に、以下の2ファイルを読み込み、読み込んだことを報告すること：
- `.agent/memory/MEMORY.md`  （学習した知識・教訓）
- `.agent/handoff/HANDOFF.md` （前回の作業引き継ぎ）

## メモリ管理
- 新しい知識・教訓を記録する際は `.agent/memory/MEMORY.md` を更新
- 既存のMEMORY.mdを更新する前に、現在のファイルを`.agent/memory/YYYY-MM-DD.md` にアーカイブしてから新規作成
- ローカルの自動メモリ機能（~/.claude/ 配下）は使用しない
- MEMORY.mdは200行以内を維持すること
- 本ファイルと重複する内容はMEMORY.mdに書かない

## ハンドオフ管理
- ハンドオフは `/handoff` コマンドで作成（Claude Codeの場合）
- 保存先は `.agent/handoff/HANDOFF.md`（固定名）
- 作成時は既存ファイルを `.agent/handoff/YYYY-MM-DD-HHMM.md` にリネームしてからHANDOFF.mdを新規作成する
- 時刻はローカル時刻・24時間表記

## 仕様駆動開発（SDD）ルール
- コーディングや業務作業を開始する前に、必ず `.spec/` 配下の4ファイルを確認・更新すること
- 作業の順序：PLAN（目的確認）→ SPEC（要件確認）→ TODO（タスク確認）→ 実作業
- **PLAN.mdは人間の口頭メモ・自由記述**であり、箇条書き・口語・断片的な内容で構わない
- PLAN.mdを読んだら、そのまま実装に入らず、不明点をヒアリングしながらSPEC.mdを作成・確定させること
- SPEC.mdが確定してからTODO.mdのタスク分解を行い、ユーザーの承認を得てから実作業を開始する
- 作業完了後は TODO.md の該当タスクにチェックを入れ、KNOWLEDGE.md に学びを記録する
- 仕様が不明確な場合は作業を開始せず、ユーザーに確認してから SPEC.md を更新する

## 品質ゲート

### トリアージ（3段階）
作業開始前にレベルを判定し、ゲートの重みを変える。

| レベル | 対象 | ゲート |
|--------|------|--------|
| 軽量 | 単一ファイル20行未満・機械的・1文で説明できるdiff | lint + 型チェック + 影響範囲テストのみ。REVIEW 省略可 |
| 標準 | 単一機能（数百行以内・ファイル分散 ≤5） | フルパイプライン（下記） |
| 本格 | 複数ファイル・アーキテクチャ/API/UI変更 | フル + 事前アーキテクチャ判断（#081）+ 実ブラウザ確認 + 契約テスト |

### パイプライン（検証ループ方式）
**EXPLORE** → **PLAN** → **IMPLEMENT** → **TEST**（検証ループ） → **REVIEW** → **GATE**（機械的条件式） → **COMMIT** → **PUSH**

各フェーズは Grill 方式で開始する: Goal（何を達成するか）→ Success criteria（どうなれば成功か）→ Success type（test / build / lint / command / fileExists）→ Execute agent / Verify agent を分離 → Max attempts（デフォルト3）→ 必要なら Context files。

| フェーズ | 担当 | やること | 通過条件 | 失敗時 |
|---------|------|---------|---------|--------|
| **EXPLORE** | #009 or orchestrator | コードベース探索、関連ファイル特定、依存関係把握 | 変更範囲が明確になっている | PLAN に進めない（再探索） |
| **PLAN** | orchestrator（委譲禁止） | 実装計画書の作成。影響範囲・ファイル一覧・テスト方針を明記 | 計画に具体性がある（ファイルパス・変更内容） | IMPLEMENT に進めない（計画の練り直し） |
| **IMPLEMENT** | #011（複数ファイルは並列）or 直接 | 計画に従い実装。単一ファイル20行未満は直接、それ以外は #011 | コードが計画通りに書かれている | TEST に進めない（#011 に差し戻し） |
| **TEST** | #011（Execute）+ 検証エージェント（Verify） | 検証ループ（下記「TEST = 検証ループ」参照） | 全チェック通過 | max3 再試行 → 人間エスカレーション |
| **REVIEW** | #081（oracle・独立コンテキスト） | diff + 基準のみを見て correctness のギャップを反駁。スタイル好みは指摘しない。編集権限なし | **PASS（完全）**。それ以外は BLOCK | BLOCK → IMPLEMENT に戻る。BLOCK を上書き禁止 |
| **GATE** | orchestrator | 機械的条件式（下記）で全項目を判定 | 条件式が成立 | COMMIT 禁止。未解決項目を修正 |
| **COMMIT** | orchestrator | `git add` + `git commit`。バグ修正は重大度に応じたプレフィックス | コミット成功 | — |
| **PUSH** | orchestrator | `git push` | プッシュ成功 | コンフリクト時は解決して再コミット |

### TEST = 検証ループ
1. **Execute**: 実装エージェント（#011）が変更を適用。
2. **Verify**: 検証エージェントが successCommand を実行して成功を機械判定する:
   - テスト: 全テスト失敗 0
   - 型チェック: exit 0（lint 通過 ≠ コンパイル通過）
   - lint/format: エラー 0
   - カバレッジ: ≥60%（プロジェクト規模で調整）
3. **失敗時**: エラー出力を Execute に返して再試行。max attempts = 3。
4. **3回失敗** → onEscalated: 人間へ理由付きでエスカレーション。自動解決禁止。
5. **手動レビューが必要な変更** → onManualReview: 人間が approve/fail を判定し、resolveManualReview まで COMMIT 禁止。
6. **onLoopComplete**: 結果と試行回数を記録して GATE へ。

### GATE = 機械的条件式
```
TYPECHECK=pass AND TESTS=0-fail AND COVERAGE≥60% AND LINT=0 AND FORMAT=ok
AND CONTRACT=pass AND SECRETS=0 AND AUDIT≤moderate AND DOCS=synced
AND DIFF=単一目的（300-500行以内、1000行超は分割、50ファイル分散は過大）
AND 禁止操作なし
```
- CONTRACT: 契約テスト（マイクロサービス構成なら Pact 等）が pass。
- SECRETS: シークレット検出（gitleaks）0件。
- AUDIT: 依存監査（`npm audit --audit-level=moderate`）が moderate 以下。
- DOCS: 公開API・CLIフラグ・env var 変更時は README / .env.example / APIドキュメントを同期更新（`documentation-sync` を参照）。
- 禁止操作: `git push --force` / `git commit --no-verify` / `DROP TABLE` / `DELETE FROM` なし。

### CI 二重ゲート
- **第1ゲート（ローカル）**: pre-commit で lint/format を変更分のみ高速実行（速度優先）。
- **第2ゲート（CI）**: GitHub Actions で全テスト・型・カバレッジ・契約テスト・gitleaks・npm audit を実行（正しさの最終判定）。
- **最終ゲート**: merge queue 導入時は必須 status check 通過まで自動マージ不可。

### 補足ルール
- 軽量トリアージ: lint + 型チェック + 影響範囲テストのみ実施し、限定版 GATE（型・テスト・lint）通過で COMMIT 可。
- TEST 範囲: #011/#057 は変更ファイルのみ。orchestrator は全件（プロジェクト全体の回帰確認）。
- UI変更 (#057) 後は `ドッグフーディングテスト`（実ブラウザでの目視確認）が必須。テスト成功のみでは完了としない。
- 既存壊れテスト: 変更起因 → 即修正。既存障害 → #081 が修正/削除判断。
- サブエージェント作業中に発見した副次的な問題は `## Drive-by Findings` 形式で報告。セッション終了時までに対応（修正 or 記録）。
- テスト失敗/未完了 → コミット禁止。
