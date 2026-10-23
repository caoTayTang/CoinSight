# Tự host model (vLLM, Modal)

Router của agent nói chuyện với mọi server tương thích OpenAI qua provider `openai_compatible`, nên một model
open-weight tự host chỉ là thêm một route. Cùng bộ eval đo chất lượng; `evals/serving_bench.py` đo tốc độ và chi
phí với đúng dạng request của agent.

## Chạy model trên GPU

```bash
# Máy có một GPU NVIDIA (24 GB+ cho 8B BF16; FP8 cần Ada/Hopper: L4, L40S, H100)
docker compose -f deploy/vllm/compose.yml up -d qwen3-8b        # BF16, cổng 8100
docker compose -f deploy/vllm/compose.yml up -d qwen3-8b-fp8    # FP8, cổng 8101 (chạy một cái mỗi lần)

# Từ laptop
ssh -N -L 8100:127.0.0.1:8100 -L 8101:127.0.0.1:8101 gpu-host
curl http://127.0.0.1:8100/v1/models
```

Server phải bật tool calling (`--enable-auto-tool-choice --tool-call-parser hermes`): agent dựa vào tool call gốc
của model, không đọc tool call từ văn bản.

Không có GPU riêng thì dùng Modal: `deploy/modal/vllm_app.py` chạy vLLM có API key, tối đa một container, tự tắt
khi rảnh.

## Chất lượng: cùng eval với model thuê

```bash
make eval-db
make eval ROUTES=selfhosted-qwen3-8b,selfhosted-qwen3-8b-fp8,groq-gpt-oss-120b SPLIT=val
```

Route định nghĩa trong `evals/routes.json`; route tự host không cần key.

## Tốc độ và chi phí

```bash
python -m evals.serving_bench --base-url http://127.0.0.1:8100/v1 --model Qwen/Qwen3-8B \
  --concurrency 1,8,32 --requests 64 --gpu "1x L40S" --gpu-usd-per-hour <giá> \
  --out evals/reports/serving/qwen3-8b-bf16.json
```

Báo cáo gồm thời gian tới token đầu (p50/p95), latency toàn phần, token ra/giây và request/giây ở mỗi mức đồng
thời, cộng số lỗi HTTP 429. Chi phí tự host cho 1.000 câu hỏi = `USD/giờ GPU ÷ (request/giây × 3600) × 1000` ở
throughput tốt nhất đo được; so với API tính theo token bằng `evals/pricing.json`.

Cần xem:
- **Khoảng cách chất lượng:** pass rate, chọn tool và tỉ lệ số bịa của model 8B so với model thuê.
- **Giá của lượng tử hóa:** FP8 so với BF16 trên cùng eval; độ chính xác tool call có giảm không.
- **Đồng thời:** continuous batching của vLLM tăng token/giây khi tăng đồng thời, còn p95 TTFT tăng theo. Điểm vận
  hành tốt là mức đồng thời cao nhất mà p95 latency vẫn nằm trong ngân sách của agent.

## Đã chạy và còn thiếu

`Qwen/Qwen3-8B` đã chạy trên vLLM ở Modal, report trong `evals/reports/modal-qwen3-8b-{train,val}`: train 25/29
(86,2%), val 26/28 (92,9%), latency val p50 khoảng 17,0 giây, p95 khoảng 40,6 giây. Đây là agent và scorer ở thời
điểm ghi; không so trực tiếp với v4 khi cấu hình chưa khớp.

Chưa có: so sánh BF16 với FP8, đo đồng thời/TTFT và chi phí USD thực đo. Benchmark ở trên là cách thu số liệu đó.
