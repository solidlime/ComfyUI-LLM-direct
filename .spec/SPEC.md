# SPEC - 技術仕様・要件定義

## 機能要件
- [ ] 機能1：openai-direct ノード（DirectOpenAIPrompt）の追加
  - OpenAI 互換 API（`{base_url}/chat/completions`）を httpx で直接叩く
  - base_url 入力でローカルサーバー / 公式 API を切り替え（デフォルトはローカル）
  - api_key 入力（空なら環境変数 OPENAI_API_KEY を参照、ローカルは空で可）
  - model は手入力 STRING
  - system_prompt / user_input（multiline）
  - gguf-direct と同じ: resolution / duration / inject_shape / strip_think
  - サンプリング: temperature / top_p / max_tokens / seed
  - タイムアウト設定（応答停止対策、非ストリーミング）
  - 思考マーカー除去・ターンマーカー除去は gguf-direct と共通ヘルパーに切り出して再利用
- [ ] 機能2：gguf-direct の strip ロジックを共通ヘルパーへ抽出（挙動は変更しない）

## 非機能要件
- パフォーマンス：非ストリーミングでシンプルに。タイムアウト必須
- セキュリティ：APIキーをログに出さない。環境変数フォールバック
- 制約条件：openai パッケージを追加しない（httpx のみ）。ComfyUI 外でもテスト可能なように ComfyUI import を含まないモジュールに分離

## 技術構成
- 言語・フレームワーク：Python / httpx（導入済み 0.28.1）
- インフラ・環境：ComfyUI カスタムノード（Python 3.12）
- 外部サービス・API：OpenAI 互換 /chat/completions

## データ構造・インターフェース
- ノード: `DirectOpenAIPrompt` / 表示名 "openai-direct" / CATEGORY "LLM" / RETURN STRING
- 入力: base_url, model, system_prompt, user_input, api_key, resolution, duration, inject_shape, strip_think, temperature, top_p, max_tokens, seed, timeout
- 共通ヘルパー: `openai_client.py`（strip_think / strip_turn_markers / chat_completion）
