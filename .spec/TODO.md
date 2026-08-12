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

## 優先度：低
- [ ] T008：実サーバーでの動作確認（ユーザー環境のローカルサーバー or 公式 API）← ユーザー実行

## 完了済み
- [x] 初期セットアップ（make_project_skill）
- [x] SPEC.md 確定（#081 レビュー反映: transport 注入 / 等価性テスト / エラー契約 / タイムアウト設計）
