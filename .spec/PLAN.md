# PLAN - やりたいこと

<!-- ここに思ったことを自由に書いてください。箇条書きでも口語でもOK -->
<!-- Claude がこの内容を読んでヒアリングし、SPEC.md を作成します -->

- プロジェクト名は llm-direct（フォルダは既に custom_nodes/llm-direct）
- 既存の gguf-direct ノード（DirectGGUFPrompt）は名前を変えずに残す
- openai-direct ノードを追加したい
  - 参考: 既存の gguf-direct ノードの構造
  - 接続先: OpenAI 互換 API（ローカルサーバーと公式 API の両対応、base_url で切り替え）
  - 既存の OpenAI 系ノードは応答が止まったりするので、シンプルに自作
  - openai パッケージは使わず httpx 直叩き（環境に openai は未導入、httpx は導入済み）
- gguf-direct と同じパラメータ体系（inject_shape, strip_think, temperature, top_p, max_tokens, seed など）
