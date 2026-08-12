# ComfyUI-LLM-direct

LLM 呼び出しをシンプルに直接行う ComfyUI カスタムノード集。

- **gguf-direct**: llama_cpp 直叩きのローカル GGUF 推論ノード
- **openai-direct**: OpenAI 互換 API を httpx 直叩きするノード

プリセットなし・クリーンアップパイプラインなし。モデルの応答をそのまま返す。

## openai-direct

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

## requirements

- `httpx`: OpenAI 互換 API 呼び出しに使用（ComfyUI の推移的依存だが、自ノードの保証のため requirements.txt に明記）
