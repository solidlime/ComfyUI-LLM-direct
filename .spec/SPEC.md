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
- [ ] 機能4：thinking のストリーミングリアルタイム表示（自前ウィジェット・B 案）
  - ユーザー要求: **「thinking だけ見たい」**（2026-08-12 回答）。回答テキストのノード表示は不要（出力ポートは現状維持）
  - **A 案（send_progress_text）は実機検証で不採用**: 受信自体は確認できたが（DevTools で progress_text イベント到達）、(1) 送信設計が content のみで thinking が除外される、(2) フロントエンド標準の handleProgressText が canvas ストア依存のノード ID 検索で弾く（ComfyUI バンドル内でパッチ不可）
  - **B 案（自前ウィジェット）**: バックエンドが `send_sync("llm_direct_reasoning", {"node": node_id, "text": 累積thinking})` を送信 → フロントエンド JS（`WEB_DIRECTORY="./web"`）が `api.addEventListener` で受信 → addDOMWidget の div に表示（スクロール可、置き換え or 追記）
  - openai 版: `delta.reasoning_content` を累積して送信（content は送らない。content のみのチャンクは無視）
  - gguf 版: **思考終了マーカー（`</think>` / `<|channel|>final<|message|>` / `<channel|>`）出現前のテキストのみ**送信（llama_cpp は thinking が content に混在するため。strip_think は最終返却値のみに適用。on_reasoning のセマンティクスを openai 版と揃える）
  - send_sync はスレッドセーフ（server.py:1392-1394、loop.call_soon_threadsafe）
  - フロントエンド JS の制約（#081 修正必須）:
    - **テキスト挿入は `textContent` 必須（`innerHTML` 禁止）** — モデル出力は信頼できない外部データ、XSS 境界
    - **表示は置き換えに確定**: `el.textContent = 累積全文`（on_reasoning は累積テキストを渡す設計なので追記は二重表示）

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
- `chat_completion_stream(client, base_url, model, messages, api_key, temperature, top_p, max_tokens, seed, enable_thinking=True, reasoning_effort="auto", on_reasoning=None, on_chunk=None)`:
  - `stream=True` で POST、`with client.stream("POST", ...)` + `iter_lines()` で SSE パース
  - 行パース: `data: {...}` → `choices[0].delta.content` / `delta.reasoning_content` を別々に累積、`data: [DONE]` で終了。`data:` 以外の行（空行・コメント）は無視
  - `on_reasoning`: reasoning_content の累積が空でないとき `on_reasoning(累積thinking)` を呼ぶ（thinking 表示用。ComfyUI import なし維持のためコールバック注入）
  - `on_chunk`: content の累積が空でないとき `on_chunk(累積テキスト)` を呼ぶ（従来仕様。テスト互換で維持）
  - 返り値: content の完全テキスト（chat_completion と同じ戻り値契約。thinking は含まない）
  - エラー契約は chat_completion と同一（ValueError 集約、URL/ヘッダー/ボディを含めない。SSE パース中の HTTPError・JSON 失敗も同様）
  - thinking 制御フィールド（enable_thinking / reasoning_effort）は chat_completion と同一ロジックを共有
  - ストリーム内で非 200 応答をチェック（非 stream 版のエラー契約と同一）
  - 最初のチャンク（role のみ/空 content）と空累積のコールバック呼び出しはスキップ

### ノード側の node_id 取得（#081 修正必須反映）
- `from comfy_execution.utils import get_executing_context` で `ctx = get_executing_context()` → `ctx.node_id` を優先（execution.py:305 の CurrentNodeContext が generate 実行中は自ノードを確実に指す。ContextVar なので同時実行競合なし）
- フォールバック: `getattr(PromptServer.instance, "last_node_id", None)`（pytest 等 PromptServer 不在環境は None → 送信スキップ）
- **last_node_id の直接使用は不可**（server.client_id が None の API 実行では古い値のまま）
- 送信は `PromptServer.instance.send_sync("llm_direct_reasoning", {"node": node_id, "text": 累積thinking})`（B 案。sid デフォルト None = 全クライアントへブロードキャスト）
- 表示失敗は生成を中断しない（try/except で隔離。表示はベストエフォート）
- gguf 版: **思考終了マーカー（`</think>` / `<|channel|>final<|message|>` / `<channel|>`）出現前のみ抽出**して送る（llama_cpp は thinking が delta.content に混在するため。返却用 text は `shown` 変数と分離し、strip_think / strip_turn_markers は従来どおり最終返却値のみに適用）

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
