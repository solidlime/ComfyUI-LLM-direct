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
- `chat_completion(client, base_url, model, messages, api_key, temperature, top_p, max_tokens, seed)`:
  - **client を引数で受け取る**（httpx.Client 注入可能 → MockTransport でテスト可能。内部で Client を生成しない）
  - `url = f"{base_url.rstrip('/')}/chat/completions"`
  - api_key 空なら `os.environ.get("OPENAI_API_KEY", "")`。キーがあれば `Authorization: Bearer <key>`
  - タイムアウトは呼び出し側で `httpx.Timeout(connect=10.0, read=timeout)`（read は分単位、デフォルト 300.0）
  - エラー契約（全て ValueError に集約、詳細は URL/ヘッダー/ボディを含めない）:
    - httpx.HTTPError（timeout 含む）→ `openai-direct: request failed: <概要>`
    - 非 200 → `openai-direct: API error <status>`
    - `content` が None（o 系モデルが reasoning のみ消費）→ ユーザー可読メッセージ
    - 応答形状不正（KeyError/IndexError/JSON 失敗）→ `openai-direct: unexpected response`
- `_START_STOPS` は gguf 専用なのでヘルパーに入れない

### ノード `DirectOpenAIPrompt`
- INPUT_TYPES required: base_url, model, system_prompt, user_input, api_key, resolution, duration, inject_shape, strip_think, temperature, top_p, max_tokens, seed, timeout
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
