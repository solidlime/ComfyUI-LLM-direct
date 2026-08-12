# MEMORY

## プロジェクト概要
- ComfyUI カスタムノード `llm-direct`（https://github.com/solidlime/ComfyUI-LLM-direct.git）
- ノード: `DirectGGUFPrompt`（表示名 "gguf-direct"）— llama_cpp 直叩き
- ノード: `DirectOpenAIPrompt`（表示名 "openai-direct"）— OpenAI 互換 API を httpx 直叩き（2026-08-12 追加）

## 学習した知識・教訓
- **ComfyUI のカスタムノード読み込みは spec_from_file_location** で、フォルダが sys.path に入らない → `sys.path.insert(0, ...)` で sibling モジュールを露出させる必要がある
- **ComfyUI の実行環境は `D:\Application\ComfyUI\venv_cu13`**（llama_cpp / folder_paths あり）。システム python には無い
- pytest を素の `pytest` で動かすには tests/pytest.ini に `pythonpath = ..` が必要（ComfyUI ルートの pytest.ini を拾わない rootdir ピン留めも同時に）
- テストは httpx MockTransport で client 注入する設計が有効（openai パッケージ不要）
- エラーメッセージに URL・ヘッダー・ボディを含めない（API キー漏洩防止）— #081 の指摘
- gguf-direct の strip ロジックは複数モデル形式（LFM2.5 / Qwen / GPT-OSS / Gemma4）に対応しており、等価性ゴールデンコーパステストで挙動不変を担保
- **opencode zen/go は 2026-08-12 時点で chat/completions が全リクエスト 500**（全モデル・不正キーでも同じ。models は認証なしで 200 = 公開）。クライアント実装は正しい、サーバー障害
- **thinking 制御の送信方式**（2026-08-12 実装）: オフ = `thinking: {"type": "disabled"}`（DeepSeek 系。reasoning_effort ではオフ不可）、程度 = トップレベル `reasoning_effort`（low/medium/high/max）。opencode zen/go は未知フィールドに 400 を返す STRICT 検証 → デフォルトでは追加フィールドを送らない設計
