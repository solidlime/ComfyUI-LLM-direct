# HANDOFF - 2026-08-12

## 使用ツール
OpenCode（orchestrator）

## 現在のタスクと進捗
- [x] プロジェクトセットアップ（make_project_skill）: フォルダ・初期ファイル作成、git init、push
- [ ] api-llm-direct ノード追加: 未着手
- [ ] 実装計画の作成: 未着手（writing-plans スキルで作成予定）

## 試したこと・結果
- ✅ gguf-llm-direct ノードの構造把握: 単一ファイル 166 行、llama_cpp 直叩き、モデル常駐キャッシュ、思考マーカー除去
- ✅ 環境確認: `openai` パッケージは未導入、`httpx 0.28.1` 導入済み → api-llm-direct は httpx 直叩きが方針

## 次のセッションで最初にやること
1. api-llm-direct の実装計画を .spec/ に落とし、ユーザー承認を得る
2. 計画に従って実装（gguf-llm-direct の strip ロジックを共通ヘルパー化して再利用）
3. テスト・検証

## 注意点・ブロッカー
- ユーザー決定事項（※2026-08-12 撤回: 3 ノードをリネーム。旧名エイリアスなし）: gguf-llm-direct / api-llm-direct / hf-llm-direct に統一
- 接続先は両対応（base_url 入力で切り替え、デフォルトはローカルサーバー）
- openai パッケージは追加しない（依存最小化）

## 推奨スキル
- `writing-plans`: 実装計画の作成
- `verification-before-completion`: 完了報告前の検証

## 参照
- ノード実装: `__init__.py`
- リポジトリ: https://github.com/solidlime/ComfyUI-LLM-direct.git
