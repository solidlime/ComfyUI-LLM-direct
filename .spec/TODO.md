# TODO - タスクリスト

## 優先度：高
- [x] T001：`openai_client.py` 作成（strip_think / strip_turn_markers 逐語移動 + build_user_content + chat_completion）
- [x] T002：strip 等価性テスト（ゴールデンコーパス: LFM2.5 / Qwen / GPT-OSS / Gemma4 / 混在 / なし）
- [x] T003：`__init__.py` の gguf-direct をヘルパー使用に切替（挙動不変をテストで確認）
- [x] T004：`DirectOpenAIPrompt` 実装（MockTransport 注入可能な設計）
- [x] T005：chat_completion テスト（200 / 400 / timeout / content=None / seed / api_key ヘッダー）
- [x] T006：ComfyUI 起動確認（venv_cu13 でノード登録を実機確認: DirectGGUFPrompt + DirectOpenAIPrompt）

## 優先度：中
- [x] T007：README 更新（openai-direct の使い方、env var 推奨、seed 注記）

## 優先度：中
- [x] T009：SPEC 更新（thinking 制御: enable_thinking + reasoning_effort）
- [x] T010：chat_completion に enable_thinking / reasoning_effort 追加 + payload テスト
- [x] T011：DirectOpenAIPrompt に入力 2 つ追加（generate 配線含む）
- [x] T012：README 更新（thinking 制御の説明と opencode zen/go 注記）

## 優先度：中（ストリーミング表示）
- [x] T014：SPEC 更新（機能4 ストリーミングリアルタイム表示、chat_completion_stream 契約）
- [x] T015：chat_completion_stream 実装 + SSE パーステスト（MockTransport: チャンク累積 / [DONE] / エラー時 ValueError / on_chunk 呼び出し）
- [x] T016：DirectOpenAIPrompt の generate を stream 化 + send_progress_text 配線
- [x] T017：DirectGGUFPrompt の generate を stream 化 + send_progress_text 配線（llama_cpp 0.3.34 は chat handler が stream 対応）
- [x] T018：README 更新（リアルタイム表示の説明）
- [x] T019：#081 事前アーキテクチャ判断（本格トリアージ: UI 表示機構 + 複数ファイル）

## 優先度：中（表示方式の切替: A 案 → B 案、2026-08-12）
- [x] T020：SPEC 更新（機能4 を B 案に書換: thinking のみ表示、自前ウィジェット。A 案は実機検証で不採用）
- [x] T021：#081 事前アーキテクチャ判断（B 案: send_sync + addDOMWidget）
- [x] T022：chat_completion_stream に on_reasoning 追加（reasoning_content 累積）+ テスト
- [x] T023：web/llm-direct.js 新規（WEB_DIRECTORY 配信、addDOMWidget で thinking 表示）
- [x] T024：両ノードの generate を on_reasoning 配線に切替（send_progress_text 除去、デバッグ print 除去）
- [x] T025：README 更新（thinking リアルタイム表示の説明）

## 優先度：中（hf-direct: transformers 直読みノード、2026-08-12）
- [x] T026：SPEC 更新（機能5 hf-direct）+ #081 事前アーキテクチャ判断（CausalLM フィルタ列挙・スレッド例外伝播・bf16・遅延 import）
- [x] T027：hf_client.py 作成（build_inputs / run_generate、スレッド例外 errors 集約→ValueError、seed>0 manual_seed、temperature=0.0 greedy）
- [x] T028：openai_client.py 共通化（split_before_think_end / build_messages 抽出、gguf 版置換）
- [x] T029：DirectHFPrompt 実装（CausalLM 列挙・1 モデルキャッシュ+gc+empty_cache・TextIteratorStreamer）+ web/llm-direct.js 対象追加 + tests/test_hf_client.py（Fake 注入）+ README 更新

## 優先度：低
- [ ] T008：実サーバーでの動作確認（ユーザー環境のローカルサーバー or 公式 API）← ユーザー実行
- [ ] T013：opencode zen/go サーバー障害の再確認（2026-08-12 時点: chat/completions が全リクエストで 500。クライアント側の問題ではない）

## 完了済み
- [x] 初期セットアップ（make_project_skill）
- [x] SPEC.md 確定（#081 レビュー反映: transport 注入 / 等価性テスト / エラー契約 / タイムアウト設計）
