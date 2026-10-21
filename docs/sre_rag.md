# SRE retrieval, drift và thí nghiệm fine-tune

## Trạng thái thực tế

SRE hiện có tool `search_runbooks` để tìm quy trình từ năm tài liệu allowlist trong `warehouse_agents/knowledge/`. Mặc định BM25 chạy CPU, không tải model, không cần vector database. Có code cho dense, reciprocal-rank hybrid và cross-encoder reranking nhưng **đã chạy CPU smoke benchmark với embedding/reranker thật trong môi trường riêng**. Không gọi BM25 là semantic RAG.

SRE có thể gọi `model_health` trực tiếp. Model-health hiện đo PSI trên feature của **Isolation Forest**, so với reference profile khóa trong artifact anomaly. Đây **không phải** drift toàn bộ feature CatBoost. Chưa có prospective prediction ledger nên chưa thể tính current MAE hoặc concept drift của forecast.

Unsloth có pipeline riêng và seed dataset kiểm tra định dạng. Chưa train model: laptop Mac ARM không có CUDA. Seed 4 train / 2 validation / 4 test chỉ kiểm tra plumbing, quá nhỏ để đưa ra kết luận hoặc dùng production.

## SRE biết gì khi container down?

`service_health` kiểm tra HTTP forecast, warehouse API và Jaeger. Connection refused/timeout nghĩa là endpoint không truy cập được từ agent; không đủ để kết luận Docker container đã stop. Network, DNS, sai URL hoặc process treo đều có thể tạo ra triệu chứng này. Agent không mount Docker socket và không tự restart.

Hỏi trong Desk:

```text
@sre Check service health, then retrieve the runbook for an unreachable service. Distinguish observation from suspected cause.
@sre Check BTC model_health and coverage. Retrieve the PSI runbook; explain reference, sample size and limitations.
@sre Check BTC missing hours over the last 24 hours, and retrieve the recovery procedure.
```

Health status luôn cần live tool. Runbook chỉ là hướng dẫn. Agent không tự theo dõi liên tục khi không có request; chưa có alert scheduler hoặc SLO paging.

## Drift được tính thế nào?

`closed_window(hours=336)` lấy candles đã đóng; feature rolling cần 169 giờ lịch sử hợp lệ, vì vậy cửa sổ feature hữu dụng nhỏ hơn số candles. Không fill gap thành quan sát thật. `population_shift` đếm tỷ lệ feature trong các bin cố định của reference và tính PSI. Ngưỡng 0.25 là heuristic, không là significance test.

Kết quả có cutoff, số feature rows, reference scope, model checksum và PSI từng feature. Kiểm tra coverage và quality trước khi nghi ngờ thị trường đổi regime. Drift có thể xảy ra với dữ liệu hoàn toàn hợp lệ. Drift không suy ra accuracy, xác suất crash hay yêu cầu retrain.

## Retrieval contract và bảo vệ

Input `query`: 1–2000 ký tự; `top_k`: 1–5. File chỉ từ allowlist, không cho LLM chọn path hoặc URL. Paragraph chunk tối đa 1600 ký tự; output giữ source, title, SHA-256 tài liệu và citation ID. Corpus checksum thay đổi khi nội dung thay đổi.

BM25 không có lexical overlap trả unavailable. Neural score không được xem là bằng chứng answerability. Không có auto fallback từ neural sang BM25 khi thiếu model. `validate_citations` chặn citation ID không có trong hits đã trả về. Nó **không chứng minh từng câu được citation hỗ trợ**, cũng không chặn mọi prompt injection. Retrieved text luôn là dữ liệu không đáng tin, không được thay đổi tool permissions.

Có metadata-only span `retrieval.runbooks`, `tool.search_runbooks` và tool model_health trong trace. Không ghi query, runbook text hoặc câu trả lời vào span attributes.

## Neural retrieval tùy chọn

Tách môi trường neural để không tăng bộ nhớ của stack laptop mặc định. `warehouse_agents/requirements-neural.lock` ghi lại môi trường benchmark. Chạy `python -m warehouse_agents.prepare_retrieval_models` để tải model vào local directories; manifest lưu commit SHA đã resolve. Embedding: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`; reranker: `cross-encoder/ms-marco-MiniLM-L-2-v2` (reranker thiên về tiếng Anh). Runtime dùng `local_files_only=True`, `trust_remote_code=False`; không download trong request.

Thiết lập `SRE_EMBEDDING_PATH`, `SRE_RERANKER_PATH` và `SRE_RETRIEVAL_MODE=hybrid_rerank`. Cần mount hai model read-only, thêm dependency vào image riêng và đo memory trước khi nâng chế độ này: image mặc định chưa chứa Sentence Transformers và giới hạn 768 MiB có thể không đủ. Dùng model multilingual khi đánh giá câu hỏi tiếng Việt; benchmark hiện tại chỉ có English smoke cases.

Chạy so sánh bằng cùng corpus và cases:

```bash
python -m warehouse_agents.evaluate_retrieval --mode bm25 --output data/models/warehouse-agent-validation/retrieval_bm25.json
# Trong môi trường đã cài và cấu hình model:
python -m warehouse_agents.evaluate_retrieval --mode dense --output /tmp/dense.json
python -m warehouse_agents.evaluate_retrieval --mode hybrid --output /tmp/hybrid.json
python -m warehouse_agents.evaluate_retrieval --mode hybrid_rerank --output /tmp/rerank.json
```

10 smoke questions được tác giả nhìn trong quá trình phát triển. BM25, dense, hybrid và hybrid+reranker đều có Recall@3 và MRR@3 đạt 1.0 trên 9 câu có nguồn; con số này chỉ kiểm tra wiring và corpus nhỏ, **không phải chất lượng tổng quát**. Chưa có independent holdout, human-reviewed faithfulness, LLM judge calibration hoặc production success metrics.

## Fine-tune khoảng 1B

Mặc định thí nghiệm Qwen3-0.6B bằng Unsloth, task hẹp: intent + chọn read-only tool + arguments. Không học trạng thái warehouse. Không có adapter nào được đưa vào routing hiện tại.

Đọc `warehouse_agents/finetune/train.py`, `seed.jsonl`, `evaluate.py` và `generate.py`. GPU environment cần PyTorch CUDA, Unsloth, TRL và Datasets tương thích; không cài vào serving image. Theo [Unsloth requirements](https://unsloth.ai/docs/get-started/fine-tuning-for-beginners/unsloth-requirements) và [Qwen Unsloth guide](https://github.com/QwenLM/Qwen3/blob/main/docs/source/training/unsloth.md). Chọn commit revision của model trước khi chạy; lưu environment và data hash vào manifest.

```bash
python -m warehouse_agents.finetune.train --data warehouse_agents/finetune/seed.jsonl --output /tmp/seed-check --revision MODEL_COMMIT --validate-only
# Chỉ chạy sau khi có dataset đã review và GPU:
python -m warehouse_agents.finetune.train --data reviewed.jsonl --output data/models/sre-intent/experiment-001 --revision MODEL_COMMIT
python -m warehouse_agents.finetune.evaluate --data reviewed.jsonl --predictions heldout_predictions.json
```

Dataset bắt buộc có ba splits, scenario_id không trùng giữa splits, labels đúng tool schema. Cần mở rộng bằng tình huống độc lập và review nhãn; seed không đủ để train. Evaluator yêu cầu đúng coverage của test IDs, đo JSON object rate, tool accuracy và exact match; không thực thi tool. Có `finetune/generate.py` cho generation base/adapter trên test questions, không thực thi tools. Chưa chạy base-versus-adapter benchmark hay promotion gate. Training code chưa được xác nhận trên GPU trong lượt triển khai này.

## Đọc code và kiểm tra

1. `warehouse_agents/knowledge/`: nguồn RAG được review.
2. `warehouse_agents/retrieval.py`: chunking, BM25, neural branches và citations.
3. `warehouse_agents/tools.py`: read-only retrieval, health và drift.
4. `warehouse_agents/graph.py`: role permissions, prompt, tool budget và output guard.
5. `warehouse_agents/anomaly.py`: feature causal và PSI thực tế.
6. `warehouse_agents/evaluate_retrieval.py`, `finetune/`: benchmark và training experiment.
7. `tests/warehouse_agents/test_retrieval.py`, `test_finetune.py`: bounds, unavailable, citation, split leakage và scoring.

```bash
python -m pytest tests/warehouse_agents -q
```

Không thêm Docker control, SQL writes, restart, backfill hoặc retrain vào tool của agent. Một chẩn đoán có source và live checks vẫn cần người vận hành quyết định remediation.

## Read-only Jaeger trace investigation

SRE now has `search_traces` and `inspect_trace` through its existing tool loop. Search accepts one allowlisted CoinSight service, a 1–1440 minute lookback and up to five traces. Inspect requires a 32-character hex trace ID. The integration uses the stable Jaeger v3 HTTP API, matching the deployed Jaeger version.

```text
@sre Search recent coinsight-api traces, inspect a relevant failed or slow request, and distinguish observed errors from suspected causes.
@sre Inspect trace TRACE_ID. Explain service/span timing, error types and missing evidence.
```

Only bounded timing, parent/span IDs, service names and allowlisted error/provider metadata are returned. SQL, prompts, exception messages, span events/logs and request/response bodies are omitted. Responses are bounded to 1 MiB on input and 64 spans on inspection; oversized results are unavailable, not silently treated as healthy. Empty search results may reflect no traffic, sampling or retention. Span timing alone does not establish root cause. Existing `JAEGER_URL` supplies the server URL; users cannot choose arbitrary URLs.

The Desk renders a timeline from returned trace spans and links to local Jaeger. Command details also provide **Ask SRE about this trace**. Desk can stay docked, be dragged by its header into a floating window, be resized, and be docked again. Geometry is stored locally in the browser; conversation content is not persisted by the layout feature.
