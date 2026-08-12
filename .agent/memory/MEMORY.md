# MEMORY

## プロジェクト概要
- ComfyUI カスタムノード `llm-direct`（https://github.com/solidlime/ComfyUI-LLM-direct.git）
- ノード: `GGUFLLMDirect`（表示名 "gguf-llm-direct"）— llama_cpp 直叩き
- ノード: `APILLMDirect`（表示名 "api-llm-direct"）— OpenAI 互換 API を httpx 直叩き（2026-08-12 追加）

## 学習した知識・教訓
- **ComfyUI のカスタムノード読み込みは spec_from_file_location** で、フォルダが sys.path に入らない → `sys.path.insert(0, ...)` で sibling モジュールを露出させる必要がある
- **ComfyUI の実行環境は `D:\Application\ComfyUI\venv_cu13`**（llama_cpp / folder_paths あり）。システム python には無い
- pytest を素の `pytest` で動かすには tests/pytest.ini に `pythonpath = ..` が必要（ComfyUI ルートの pytest.ini を拾わない rootdir ピン留めも同時に）
- テストは httpx MockTransport で client 注入する設計が有効（openai パッケージ不要）
- エラーメッセージに URL・ヘッダー・ボディを含めない（API キー漏洩防止）— #081 の指摘
- gguf-llm-direct の strip ロジックは複数モデル形式（LFM2.5 / Qwen / GPT-OSS / Gemma4）に対応しており、等価性ゴールデンコーパステストで挙動不変を担保
- **opencode zen/go は 2026-08-12 時点で chat/completions が全リクエスト 500**（全モデル・不正キーでも同じ。models は認証なしで 200 = 公開）。クライアント実装は正しい、サーバー障害
- **thinking 制御の送信方式**（2026-08-12 実装）: オフ = `thinking: {"type": "disabled"}`（DeepSeek 系。reasoning_effort ではオフ不可）、程度 = トップレベル `reasoning_effort`（low/medium/high/max）。opencode zen/go は未知フィールドに 400 を返す STRICT 検証 → デフォルトでは追加フィールドを送らない設計
- **ストリーミングリアルタイム表示**（2026-08-12 実装・B 案に切替）: A 案（send_progress_text）は実機で「バックエンド正常・表示されない」で不採用（フロントエンド 1.48.7 の handleProgressText が canvas ストア依存で弾く・thinking 除外）。**B 案 = send_sync("llm_direct_reasoning", {"node": node_id, "text": 累積thinking}) + WEB_DIRECTORY="./web" + web/llm-direct.js（addDOMWidget で自前ウィジェット、textContent 置き換え、innerHTML 禁止 = XSS 境界）**。node_id は `comfy_execution.utils.get_executing_context().node_id` を優先（last_node_id 直接使用は API 実行で古い値になるため不可、pytest 環境は ImportError → スキップ）
- **JS の注意点**（#081 BLOCK で発覚）: バックエンドの node_id は文字列（'279'）、LiteGraph の this.id は数値（279）→ Map キーは両側 String() 正規化必須。onRemoved で Map エントリ削除も推奨
- **llama_cpp 0.3.34 の chat handler は stream=True 対応**（`_chat_handlers["chat_template.default"]` に stream=True を渡すとジェネレータ）。チャンク形状: `chunk["choices"][0]["delta"]["content"]` は最初（role のみ）と最後（finish_reason）で不在 → `.get()` 必須。gguf は thinking が content に混在するので、表示は思考終了マーカー出現前のみ抽出して送る（B 案）
- **SSE パース**: `client.stream("POST", ...)` + `iter_lines()`。`data: ` プレフィックス行のみ処理、`data: [DONE]` で終了、delta は content / reasoning_content / 空 の 3 形状。エラー契約は非 stream 版と同一（ValueError、URL 非含有）。MockTransport で bytes を返せばテスト可能
