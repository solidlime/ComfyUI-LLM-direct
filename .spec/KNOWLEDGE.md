# KNOWLEDGE - ドメイン知識・調査結果

## 業務・ドメイン知識
- ComfyUI カスタムノード: `__init__.py` に NODE_CLASS_MAPPINGS / NODE_DISPLAY_NAME_MAPPINGS を定義して登録
- モデル解決は `folder_paths` 機構（models/LLM/GGUF）

## 調査・リサーチ結果
- gguf-llm-direct（既存）: llama_cpp 直叩き、166 行単一ファイル、モデル常駐キャッシュ（1モデルのみ、切替時に clear + gc）
- 環境: `openai` 未導入、`httpx 0.28.1` 導入済み → httpx 直叩きを採用

## 技術的な知見
- llama_cpp の `create_chat_completion` は enable_thinking 等の追加 kwargs を落とす → `_chat_handlers` を直接呼ぶ
- 思考マーカー: `</think>`（LFM2.5） / `<|channel|>final<|message|>`（GPT-OSS） / `<channel|>`（Gemma 4）

## 決定事項と理由
- 接続先は両対応（base_url 入力で切替、デフォルトはローカル）— ユーザー指定
- gguf-llm-direct の名前は変更しない — ユーザー指定（※2026-08-12 撤回: 3 ノードをリネーム。旧名エイリアスなし）
- openai パッケージを追加しない — 依存最小化（httpx で十分）
- 非ストリーミング + タイムアウト — 既存ノードの「応答停止」問題を回避
