# SPEC: マルチモーダル対応（画像・動画入力）

## 目的
ComfyUI-LLM-direct の3ノード（gguf / api / hf）に画像・動画入力を追加し、VLM によるマルチモーダル推論を可能にする。

## スコープ

### 対象
- 3ノード全部（GGUFLLMDirect / APILLMDirect / HFLLMDirect）
- 入力: ComfyUI 標準コネクタ型（IMAGE / VIDEO）
- 動画: フレーム抽出→複数画像方式（業界標準。Gemini も内部で 1fps サンプリング）
- 既存ノード拡張（optional 入力、既存ワークフロー非破壊）

### 対象外（将来課題）
- 音声入力。api は `input_audio` 公式形式（wav/mp3 base64）で追加可能な設計は維持。gguf はプロセス内バインディング未確認のため llama-server subprocess 方式が必要になる。

## 要件

### R1: 共通メディアモジュール media.py（新規）
ComfyUI 非依存の純粋関数のみ。
- `image_tensor_to_data_uris(images)`: ComfyUI IMAGE バッチ [B,H,W,C] float 0-1 → PNG/JPEG base64 data URI リスト
- `extract_video_frames(video, n)`: VIDEO オブジェクトから均等サンプリング n 枚 → PIL Image リスト
- `build_multimodal_content(text, uris)`: 画像なし=str（従来通り）、あり=OpenAI content 配列 `[{"type":"text",...},{"type":"image_url",...}]`

### R2: メッセージ組み立て拡張
- `openai_client.build_messages` を拡張し、メディア data URI から content 配列を生成
- strip_think / split_before_think_end 等の既存ロジックは無変更

### R3: ノード INPUT_TYPES 拡張（3ノード共通）
- optional に `image: ("IMAGE",)` / `video: ("VIDEO",)` / `video_frames: INT(default 4, min 1, max 32)` を追加
- 未接続なら完全に従来動作（既存ワークフロー破壊ゼロ）

### R4: GGUF ノード
- `mmproj_path: STRING` 追加（プロジェクタ GGUF パス）
- mmproj 指定時は mtmd 系ハンドラで Llama 初期化、モデルキャッシュキーに mmproj_path を含める
- llama-cpp-python <0.3.10 の場合はバージョンチェックしてエラー
- 画像接続あり + mmproj 未指定 → エラー

### R5: HF ノード
- `_hf_choices` フィルタを VLM アーキテクチャ（ForConditionalGeneration 系）も含めるよう拡張
- `hf_client` にマルチモーダル入力経路追加: AutoProcessor + `apply_chat_template(return_dict=True)` → generate
- transformers ≥4.49 前提（Qwen2_5_VLForConditionalGeneration 等）

### R6: API ノード
- payload 変更ほぼゼロ（content 配列がそのまま通る）
- image_url は公式形式 data URI

## エラーハンドリング
- 動画デコード失敗 → 明確なメッセージで raise（黙って空配列にしない）
- gguf: 画像接続 + mmproj 未指定 → raise
- VIDEO 型は新しい ComfyUI 機能。古い環境では optional 入力が表示されないだけ（壊れない）

## テスト方針
- `tests/test_media.py` 新規: tensor→URI 変換、フレーム抽出（モック）、content 配列組み立て
- `test_openai_client.py` 拡張: build_messages マルチモーダルケース
- 実機スモーク: api ノード + ローカル VLM サーバーで実画像1枚

## 技術的制約・調査結果（2026-08-22 #042 調査）
- llama-cpp-python stable 0.3.35 で mtmd ctypes バインディング済み（≥0.3.10 必須）。mtmd は breaking changes 予告中 → バージョンピン推奨
- mmproj GGUF を `clip_model_path` に渡し、画像は data URI base64 で OK。n_ctx 増加必須
- OpenAI 形式: `image_url`（公式）/ `input_audio`（公式 wav/mp3 のみ・今回は対象外）/ `video_url`（vLLM 拡張・不使用）
- 動画は全プロバイダ実質フレームサンプリングが共通解
