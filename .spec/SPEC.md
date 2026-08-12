# SPEC - 技術仕様・要件定義

> **2026-08-12 改名**: 旧名 `gguf-direct` / `openai-direct` / `hf-direct` → `gguf-llm-direct` / `api-llm-direct` / `hf-llm-direct`（完全置き換え、旧名エイリアスなし）。クラス名は GGUFLLMDirect / APILLMDirect / HFLLMDirect。

## 機能要件
- [ ] 機能1：api-llm-direct ノード（APILLMDirect）の追加
  - OpenAI 互換 API（`{base_url}/chat/completions`）を httpx で直接叩く
  - base_url 入力でローカルサーバー / 公式 API を切り替え（デフォルト: `http://127.0.0.1:8080/v1`）
  - api_key 入力（空なら環境変数 OPENAI_API_KEY を参照、ローカルは空で可）
  - model は手入力 STRING
  - system_prompt / user_input（multiline）
  - gguf-llm-direct と同じ: resolution / duration / inject_shape / strip_think
  - サンプリング: temperature / top_p / max_tokens / seed（seed > 0 のときだけ送信）
  - 非ストリーミング + タイムアウト（応答停止対策）
  - 思考マーカー除去・ターンマーカー除去は共通ヘルパーを再利用
- [ ] 機能2：gguf-llm-direct の strip ロジックを共通ヘルパーへ抽出（**挙動不変**）
- [ ] 機能3：api-llm-direct に thinking 制御を追加（gguf-llm-direct の enable_thinking に相当）
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
- [ ] 機能5：transformers 直読みノード（HFLLMDirect / 表示名 "hf-llm-direct"）の追加
  - ユーザー要求: 「gguf-llm-directはggufだけ対応だよね？通常モデルにも対応させたいけどできる？」→ **A 案（transformers 直読み）で確定**（2026-08-12 回答。依存追加を承諾済み）
  - models/LLM 配下の HF モデルディレクトリを folder_paths で登録 → combo 列挙（gguf-llm-direct の _gguf_choices パターン踏襲）
  - **列挙フィルタ（#081 修正必須）: config.json の architectures に `ForCausalLM` を含むディレクトリのみ**（Llava 系 joycaption / florence は AutoModelForCausalLM でロード不可のため除外。json.load の軽量チェック）
  - AutoModelForCausalLM + AutoTokenizer（transformers 5.15.0 は venv_cu13 に導入済み・追加インストール不要）
  - **モデルロード（#081 確定）: `device_map="auto"`（accelerate 1.14.0 導入済み）+ `torch_dtype=torch.bfloat16`（cuda 時）/ float32（cpu 時）**。実モデルのネイティブ dtype と整合（Ampere+ で bf16 がネイティブ演算）
  - 1 モデル常駐キャッシュ（gguf-llm-direct と同パターン。モデル切替時 clear + gc + **torch.cuda.empty_cache()**（hf は cuda テンソルなので VRAM 競合対策））
  - ストリーミング表示: TextIteratorStreamer（skip_prompt=True, skip_special_tokens=True）+ threading で generate を実行、streamer から逐次テキスト取得 → **思考終了マーカー（`</think>` / `<|channel|>final<|message|>` / `<channel|>`）出現前のみ `_send_reasoning` に配線**（gguf 版と同じ shown 抽出。返却値は strip_think / strip_turn_markers 適用）
  - **スレッド例外伝播（#081 修正必須）: generate スレッドの例外（OOM 等）はメインスレッドに自動伝播しない → errors リストに握り、streamer 消費終了 → join → あれば ValueError 集約（`hf-llm-direct: generation failed: <型名>`）。無言終了は最悪の故障形態**
  - サンプリング入力: max_new_tokens / temperature / top_p / seed（seed=0 は未指定=毎回ランダム。openai 版の seed>0 契約と整合）

## 非機能要件
- パフォーマンス：非ストリーミング。タイムアウト必須
- セキュリティ：APIキーをログ・エラーメッセージに出さない。エラー出力に URL 全体・ヘッダー・ボディを含めない
- 制約条件：openai パッケージを追加しない（httpx のみ）。ComfyUI import を含まないモジュールに分離し単体テスト可能にする
- 制約条件（機能5）: transformers の導入を承諾済み（venv_cu13 に 5.15.0 導入済み）。transformers/torch は **ノードファイル内で遅延 import**（ComfyUI 起動時に無条件ロードしない。gguf ノードの llama_cpp と同じ扱い）

## 技術構成
- 言語・フレームワーク：Python / httpx 0.28.1（導入済み・推移的依存）/ pytest 9.0.2 / transformers 5.15.0 + torch 2.11.0+cu130（機能5・venv_cu13 導入済み）
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
    - httpx.HTTPError（timeout 含む）→ `api-llm-direct: request failed: <概要>`
    - 非 200 → `api-llm-direct: API error <status>`
    - `content` が None（o 系モデルが reasoning のみ消費）→ ユーザー可読メッセージ
    - 応答形状不正（KeyError/IndexError/JSON 失敗）→ `api-llm-direct: unexpected response`
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

### ノード `APILLMDirect`
- INPUT_TYPES required: base_url, model, system_prompt, user_input, api_key, resolution, duration, inject_shape, enable_thinking, reasoning_effort, strip_think, temperature, top_p, max_tokens, seed, timeout
- enable_thinking: BOOLEAN デフォルト True（gguf-llm-direct と同名だが、API 版はデフォルト True: オフ時は DeepSeek 専用フィールドを送るため、他のサーバーで 400 になるリスクを避けデフォルト送信しない）
- reasoning_effort: combo ("auto", "low", "medium", "high", "max") デフォルト "auto"
- timeout: FLOAT デフォルト 300.0, min 5.0, max 3600.0
- RETURN_TYPES: ("STRING",) / RETURN_NAMES: ("text",) / FUNCTION: "generate" / CATEGORY: "LLM"
- 登録: NODE_CLASS_MAPPINGS["APILLMDirect"] / 表示名 "api-llm-direct"

### テスト `tests/test_openai_client.py`（pytest + httpx MockTransport）
- strip_think 等価性ゴールデンコーパス: LFM2.5（`</think>`）/ Qwen（`<think>...</think>`）/ GPT-OSS（`<|channel|>final<|message|>`）/ Gemma4（`<channel|>`）/ マーカー混在 / マーカーなし の各ケースで旧インライン実装とヘルパーが同一出力
- chat_completion: 200 正常 / 400 エラー→ValueError / タイムアウト→ValueError / content=None→ValueError / seed>0 で payload に seed 含む / api_key が Authorization ヘッダーに載る

### ノード `HFLLMDirect`（機能5）
- INPUT_TYPES required: model（combo: models/LLM 配下の HF モデルディレクトリ）, system_prompt, user_input, resolution, duration, inject_shape, strip_think, max_new_tokens, temperature, top_p, seed
- モデル列挙: `folder_paths.get_folder_paths("llm_models")` 相当で models/LLM 配下の `config.json` を持つディレクトリを列挙（GGUF と同居。gguf の _gguf_choices と同方式で combo 化）
- モデルロード: `AutoModelForCausalLM.from_pretrained(path, torch_dtype=torch.bfloat16 if cuda else torch.float32, device_map="auto")` — **#081 事前判断で確定**（accelerate 1.14.0 導入済み。float16 ではなく bf16: 実モデルのネイティブ dtype と整合、Ampere+ でネイティブ演算）
- キャッシュ: 1 モデル常駐（gguf と同じ。選択変更時 clear + gc.collect + **torch.cuda.empty_cache()**）
- 生成: `generate(input_ids, max_new_tokens, temperature, top_p, seed, streamer=TextIteratorStreamer(...))` を別スレッドで実行。streamer イテレーションで逐次テキスト取得
- thinking 表示: gguf 版と同じ shown 抽出（思考終了マーカー出現前のみ `_send_reasoning`）。返却値は strip_think / strip_turn_markers / build_user_content ヘルパー再利用
- エラー契約: transformers/torch の例外は ValueError に集約（ユーザー可読メッセージ。パスを含まない）
- RETURN_TYPES: ("STRING",) / RETURN_NAMES: ("text",) / FUNCTION: "generate" / CATEGORY: "LLM"
- 登録: NODE_CLASS_MAPPINGS["HFLLMDirect"] / 表示名 "hf-llm-direct"
- transformers/torch import はノードクラス定義前に try/except でガード（不在時は InputTypes で model を空 combo にし、generate で明確なエラーメッセージ）

## データ構造・インターフェース
- ノード: `APILLMDirect` / 表示名 "api-llm-direct" / CATEGORY "LLM" / RETURN STRING
- ノード: `HFLLMDirect` / 表示名 "hf-llm-direct" / CATEGORY "LLM" / RETURN STRING（機能5）
- 入力: base_url, model, system_prompt, user_input, api_key, resolution, duration, inject_shape, strip_think, temperature, top_p, max_tokens, seed, timeout
- 共通ヘルパー: `openai_client.py`（strip_think / strip_turn_markers / build_user_content / chat_completion）

## ファイル構成
- 新規: `openai_client.py`、`tests/test_openai_client.py`
- 変更: `__init__.py`（ヘルパー使用に切替 + APILLMDirect 追加 + 登録）
- 更新: `README.md`（使い方、env var 推奨、seed 拒否サーバー注記）
- 新規（機能5）: `hf_client.py`（transformers 直読みの純粋ロジック。ComfyUI import なし・単体テスト可能）/ `tests/test_hf_client.py`
- 変更（機能5）: `__init__.py`（HFLLMDirect 追加 + 登録）
