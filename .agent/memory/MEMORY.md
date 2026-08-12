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
