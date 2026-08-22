# ComfyUI-LLM-direct

> **2026-08-12 改名のお知らせ**: 旧名 `gguf-direct` / `openai-direct` / `hf-direct` は `*-llm-direct` に改名されました。旧名は使用できません。既存ワークフローはノードを再配置してください。

LLM 呼び出しをシンプルに直接行う ComfyUI カスタムノード集。

- **gguf-llm-direct**: llama_cpp 直叩きのローカル GGUF 推論ノード
- **api-llm-direct**: OpenAI 互換 API を httpx 直叩きするノード
- **hf-llm-direct**: transformers 直読みのローカル HF モデルノード（CausalLM / VLM）

プリセットなし・クリーンアップパイプラインなし。モデルの応答をそのまま返す。

## マルチモーダル入力（画像・動画）

3 ノードすべてに `image`（IMAGE）/ `video`（VIDEO）/ `video_frames` の optional 入力がある。未接続なら従来どおりテキストのみで動作し、既存ワークフローに影響しない。

- `video` は指定フレーム数（デフォルト 4、最大 32）を均等サンプリングで抽出し、複数画像として送信
- **音声入力は未対応**（将来課題）
- 内部の `media.py` が `av` / `numpy` / `Pillow` を使用（いずれも ComfyUI 本体同梱。requirements.txt に明記済み）

ノードごとの差異:

- **api-llm-direct**: OpenAI 互換マルチモーダル API にそのまま送信する。vision 対応モデルが必要
- **gguf-llm-direct**: `mmproj_path`（optional）にマルチモーダル GGUF 用の mmproj ファイル名を指定する。画像/動画入力時は必須で、未指定ならエラーになる。`llama-cpp-python >= 0.3.10` が必要。対応モデル例: Qwen2.5-VL / LLaVA 系
- **hf-llm-direct**: VLM アーキテクチャ（`ForConditionalGeneration` / ImageTextToText）もモデル一覧に列挙される。VLM モデルは `AutoProcessor` 経由で chat template を適用し pixel_values を生成する

## api-llm-direct

OpenAI 互換の `/chat/completions` エンドポイントを直接叩くノード。非ストリーミング。

### 使い方

- `base_url`: ローカルサーバー（例: `http://127.0.0.1:8080/v1`）または公式 API（`https://api.openai.com/v1`）を指定
- `model`: モデル名（手入力）
- `api_key`: ノード入力、または環境変数 `OPENAI_API_KEY`。ローカルサーバーなら空で可
  - **環境変数を推奨**: ノード入力を指定すると API キーが workflow JSON に保存されるため
- サンプリング: `temperature` / `top_p` / `max_tokens` / `seed`（`seed > 0` のときだけ送信）
- `timeout`: 応答停止対策の読み取りタイムアウト（秒、デフォルト 300）
- `enable_thinking`: False で DeepSeek 系の思考をオフ（`thinking: {"type": "disabled"}` を送信）
- `reasoning_effort`: auto（送信しない）/ low / medium / high / max から選択。思考の程度を制御
- thinking のリアルタイム表示: 生成中の思考テキストをノード内ウィジェットに表示（自前ウィジェット、`web/` から配信。JS バンドルへのパッチ不要）（medium は opencode 系のみ。DeepSeek 公式は low/high/max のみ対応）

### 注意

- `seed` パラメータを拒否するサーバーがある（未対応の互換サーバー等）。その場合 `seed` を 0 にして送信を止めること
- `enable_thinking` の `thinking` フィールドを受け付けないサーバーでは 400 になる可能性がある。その場合は True に戻すこと
- o 系モデルは reasoning のみ消費して空応答になることがある。その場合 `max_tokens` を上げるか thinking を止める

## hf-llm-direct

Hugging Face transformers でローカルモデルを直接実行するノード。ストリーミング。

### 使い方

- `model`: `models/LLM` 直下のディレクトリから選択（combo）
  - `config.json` の `architectures` に `ForCausalLM` または `ForConditionalGeneration`（VLM）を含むディレクトリを列挙（それ以外の vision 系は除外）。VLM モデルはマルチモーダル入力と組み合わせて使用できる
- `system_prompt` / `user_input` / `resolution` / `duration` / `inject_shape`: gguf-llm-direct と同じ shape ヘッダー注入
- サンプリング: `temperature` / `top_p` / `max_new_tokens` / `seed`（`seed > 0` のとき `torch.manual_seed` で決定性を確保。`temperature=0.0` は greedy になる）
- モデルは 1 つ常駐、切り替え時に前のモデルを解放（`gc.collect()` + `torch.cuda.empty_cache()`）
- thinking のリアルタイム表示: api-llm-direct と同じノード内ウィジェット

### 注意

- **`transformers` のインストールが必要**（`AutoModelForCausalLM` / `AutoTokenizer` / `TextIteratorStreamer`）。未インストール時はノードがエラーを返す
- モデルに chat template が無い場合のメッセージ整形は transformers のデフォルトに委ねる
- ロードは `device_map="auto"` + `torch_dtype=torch.bfloat16`（CUDA 時）/ `float32`（CPU 時）

## requirements

- `httpx`: OpenAI 互換 API 呼び出しに使用（ComfyUI の推移的依存だが、自ノードの保証のため requirements.txt に明記）
