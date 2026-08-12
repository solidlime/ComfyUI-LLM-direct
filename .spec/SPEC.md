# SPEC - 技術仕様・要件定義

## 機能要件
- [ ] 機能1：openai-direct ノード（DirectOpenAIPrompt）の追加
  - OpenAI 互換 API（`{base_url}/chat/completions`）を httpx で直接叩く
  - base_url 入力でローカルサーバー / 公式 API を切り替え（デフォルト: `http://127.0.0.1:8080/v1`）
  - api_key 入力（空なら環境変数 OPENAI_API_KEY を参照、ローカルは空で可）
  - model は手入力 STRING
  - system_prompt / user_input（multiline）
  - gguf-direct と同じ: resolution / duration / inject_shape / strip_think
  - サンプリング: temperature / top_p / max_tokens / seed（seed > 0 のときだけ送信）
  - 非ストリーミング + タイムアウト（応答停止対策）
  - 思考マーカー除去・ターンマーカー除去は共通ヘルパーを再利用
- [ ] 機能2：gguf-direct の strip ロジックを共通ヘルパーへ抽出（**挙動不変**）
- [ ] 機能3：openai-direct に thinking 制御を追加（gguf-direct の enable_thinking に相当）
  - `enable_thinking` BOOLEAN: False なら `thinking: {"type": "disabled"}` を送信（DeepSeek 系の思考オフ方式。opencode zen/go の workaround と同じ）
  - `reasoning_effort` combo（auto/low/medium/high/max）: auto 以外なら `reasoning_effort` を送信（程度の切り替え）
  - 未知フィールドを常時送らない（opencode zen/go は STRICT 検証で未知フィールドに 400 を返す。選択時のみ送信で回避）
- [ ] 機能4：両ノードのストリーミングリアルタイム表示
  - 生成中のテキストをノード上にリアルタイム表示（ユーザー要求: 「進行してるのが見たい」。出力ポートは現状維持）
  - **JS ゼロの A 案**: `PromptServer.instance.send_progress_text(text, node_id)` で送信 → フロントエンドが `$$node-text-preview` ウィジェットを自動表示（server.py:1469-1479 の公式機構。node_id は 4byte 長 + bytes 前置きで BinaryEventTypes.TEXT 送信）
  - send_progress_text は毎回置き換え（追記不可）→ **累積テキストを毎回送信**して追記風表示
  - 完了時クリアはしない（次の実行で上書き）

## 非機能要件
- パフォーマンス：非ストリーミング。タイムアウト必須
- セキュリティ：APIキーをログ・エラーメッセージに出さない。エラー出力に URL 全体・ヘッダー・ボディを含めない
- 制約条件：openai パッケージを追加しない（httpx のみ）。ComfyUI import を含まないモジュールに分離し単体テスト可能にする

## 技術構成
- 言語・フレームワーク：Python / httpx 0.28.1（導入済み・推移的依存）/ pytest 9.0.2
- インフラ・環境：ComfyUI カスタムノード（Python 3.12）
- 外部サービス・API：OpenAI 互換 /chat/completions

## 設計契約（#081 レビュー反映）

### 共通ヘルパー `openai_client.py`（ComfyUI import なし）
- `strip_think(text)` / `strip_turn_markers(text)`: 既存 `__init__.py` のロジックを**逐語移動**（順序・split 意味論を変更しない）。正規表現の冗長な代替は抽出時に直さない
- `build_user_content(resolution, duration, user_input, inject_shape)`: resolution/duration ヘッダー組立（2ノード共通化、ドリフト防止）
- `chat_completion(client, base_url, model, messages, api_key, temperature, top_p, max_tokens, seed, enable_thinking=True, reasoning_effort="auto")`:
  - **client を引数で受け取る**（httpx.Client 注入可能 → MockTransport でテスト可能。内部で Client を生成しない）
  - `url = f"{base_url.rstrip('/')}/chat/completions"`
  - api_key 空なら `os.environ.get("OPENAI_API_KEY", "")`。キーがあれば `Authorization: Bearer <key>`
  - タイムアウトは呼び出し側で `httpx.Timeout(timeout, connect=10.0)`（read は分単位、デフォルト 300.0。httpx.Timeout はデフォルトか 4 パラメータ全部の指定が必須: 2 パラメータだけだと ValueError）
  - thinking 制御（選択時のみ追加フィールド、デフォルトでは payload 不変）:
    - `enable_thinking=False` → `"thinking": {"type": "disabled"}`
    - `enable_thinking=True` かつ `reasoning_effort != "auto"` → `"reasoning_effort": <値>`
  - エラー契約（全て ValueError に集約、詳細は URL/ヘッダー/ボディを含めない）:
    - httpx.HTTPError（timeout 含む）→ `openai-direct: request failed: <概要>`
    - 非 200 → `openai-direct: API error <status>`
    - `content` が None（o 系モデルが reasoning のみ消費）→ ユーザー可読メッセージ
    - 応答形状不正（KeyError/IndexError/JSON 失敗）→ `openai-direct: unexpected response`
- `_START_STOPS` は gguf 専用なのでヘルパーに入れない
- `chat_completion_stream(client, base_url, model, messages, api_key, temperature, top_p, max_tokens, seed, enable_thinking=True, reasoning_effort="auto", on_chunk=None)`:
  - `stream=True` で POST、`with client.stream("POST", ...)` + `iter_lines()` で SSE パース
  - 行パース: `data: {...}` → `choices[0].delta.content` / `delta.reasoning_content` を累積（thinking は表示に含めない）、`data: [DONE]` で終了。`data:` 以外の行（空行・コメント）は無視
  - チャンクごとに `on_chunk(累積テキスト)` を呼ぶ（ComfyUI import なし維持のためコールバック注入）
  - 返り値: 完了した完全テキスト（chat_completion と同じ戻り値契約）
  - エラー契約は chat_completion と同一（ValueError 集約、URL/ヘッダー/ボディを含めない。SSE パース中の HTTPError・JSON 失敗も同様）
  - thinking 制御フィールド（enable_thinking / reasoning_effort）は chat_completion と同一ロジックを共有
  - ストリーム内で非 200 応答をチェック（非 stream 版のエラー契約と同一）
  - 最初のチャンク（role のみ/空 content）と空累積テキストの on_chunk はスキップ

### ノード側の node_id 取得（#081 修正必須反映）
- `from comfy_execution.utils import get_executing_context` で `ctx = get_executing_context()` → `ctx.node_id` を優先（execution.py:305 の CurrentNodeContext が generate 実行中は自ノードを確実に指す。ContextVar なので同時実行競合なし）
- フォールバック: `getattr(PromptServer.instance, "last_node_id", None)`（pytest 等 PromptServer 不在環境は None → send_progress_text 呼び出しスキップ）
- **last_node_id の直接使用は不可**（server.client_id が None の API 実行では古い値のまま）
- send_progress_text は `PromptServer.instance.send_progress_text(累積テキスト, node_id)`。**prompt_id を前置しない**（supports_progress_text_metadata フラグが無いため node_id + text 形式でパースされる）
- gguf 版: on_chunk 表示は **strip_think + strip_turn_markers 適用済みの累積テキスト**を送る（最終返却値と表示が一致する。llama_cpp は thinking が delta.content に混在するため）

### ノード `DirectOpenAIPrompt`
- INPUT_TYPES required: base_url, model, system_prompt, user_input, api_key, resolution, duration, inject_shape, enable_thinking, reasoning_effort, strip_think, temperature, top_p, max_tokens, seed, timeout
- enable_thinking: BOOLEAN デフォルト True（gguf-direct と同名だが、API 版はデフォルト True: オフ時は DeepSeek 専用フィールドを送るため、他のサーバーで 400 になるリスクを避けデフォルト送信しない）
- reasoning_effort: combo ("auto", "low", "medium", "high", "max") デフォルト "auto"
- timeout: FLOAT デフォルト 300.0, min 5.0, max 3600.0
- RETURN_TYPES: ("STRING",) / RETURN_NAMES: ("text",) / FUNCTION: "generate" / CATEGORY: "LLM"
- 登録: NODE_CLASS_MAPPINGS["DirectOpenAIPrompt"] / 表示名 "openai-direct"

### テスト `tests/test_openai_client.py`（pytest + httpx MockTransport）
- strip_think 等価性ゴールデンコーパス: LFM2.5（`</think>`）/ Qwen（`<think>...</think>`）/ GPT-OSS（`<|channel|>final<|message|>`）/ Gemma4（`<channel|>`）/ マーカー混在 / マーカーなし の各ケースで旧インライン実装とヘルパーが同一出力
- chat_completion: 200 正常 / 400 エラー→ValueError / タイムアウト→ValueError / content=None→ValueError / seed>0 で payload に seed 含む / api_key が Authorization ヘッダーに載る

## データ構造・インターフェース
- ノード: `DirectOpenAIPrompt` / 表示名 "openai-direct" / CATEGORY "LLM" / RETURN STRING
- 入力: base_url, model, system_prompt, user_input, api_key, resolution, duration, inject_shape, strip_think, temperature, top_p, max_tokens, seed, timeout
- 共通ヘルパー: `openai_client.py`（strip_think / strip_turn_markers / build_user_content / chat_completion）

## ファイル構成
- 新規: `openai_client.py`、`tests/test_openai_client.py`
- 変更: `__init__.py`（ヘルパー使用に切替 + DirectOpenAIPrompt 追加 + 登録）
- 更新: `README.md`（使い方、env var 推奨、seed 拒否サーバー注記）
