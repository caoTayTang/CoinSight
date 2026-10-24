# Home server & deploy

Chạy toàn bộ hệ thống trên một máy luôn bật ở nhà và công bố tại `https://coinsight.kaiosthefox.dpdns.org`
qua Cloudflare Tunnel. Gồm kho dữ liệu, Kafka, Spark streaming, dữ liệu Binance live, batch Airflow hằng ngày,
các agent, prediction ledger và deploy tự động từ `main`.

Trang viết cho một coding agent chạy trên máy đó; vài bước trên dashboard đánh dấu **[bạn]**. Chạy lệnh từ thư
mục gốc repo.

## Kết quả cuối cùng

```text
Binance WS ─► live-producer ─► Kafka ─► Spark ─► Postgres ◄─ Airflow (archive hằng ngày)
                                                   │
          agent dự báo · anomaly · ledger ─────────┤
          agent Trade / SRE + gateway ─────────────┤
                                                   ▼
                    API ◄─ web (nginx :3000) ◄─ cloudflared ◄─ Cloudflare ◄─ người dùng
```

Chỉ web app đi qua tunnel; nó chuyển `/api` tới API. `/docs` trên cùng hostname là site tài liệu công khai, chạy
trên Cloudflare Worker (`frontend/wrangler.toml`), nên vẫn mở được khi máy này tắt. Postgres, Kafka UI, Airflow
và Jaeger chỉ nghe trên `127.0.0.1`.

## Yêu cầu

- RAM từ 8 GB (stack dùng khoảng 4 GB; Kafka và Spark lớn nhất), 20 GB đĩa trống.
- Docker Engine hoặc Docker Desktop với Compose v2, `git`, `curl`, `jq`, `uv`, Node 22, `cloudflared`.
- Máy không được ngủ. macOS: `sudo pmset -a sleep 0 disablesleep 1` và cắm sạc. Laptop Linux: đặt
  `HandleLidSwitch=ignore` trong `/etc/systemd/logind.conf`, rồi `sudo systemctl restart systemd-logind`.

```bash
docker compose version && git --version && jq --version && uv --version && node --version && cloudflared --version
```

## Mang sang những gì git không có **[bạn, trên máy dev]**

File model và secret không có trong repo:

```bash
tar czf ~/coinsight-models.tgz data/models/agent-serving-bundle/v1 data/models/warehouse-anomaly/v1   # ~10 MB
```

Chép `~/coinsight-models.tgz` và `.env` sang server bằng AirDrop, USB hoặc `scp`. **Không** gửi `.env` qua chat,
email hay git: nó chứa key Groq, OpenRouter và Bedrock.

## Lấy code và cấu hình

```bash
git clone git@github.com:caoTayTang/CoinSight.git ~/coinsight && cd ~/coinsight
tar xzf ~/coinsight-models.tgz            # tạo data/models/...
cp ~/.env.from-mac .env                   # nơi bạn đã chép
mkdir -p data/raw data/models
```

Sửa `.env`:

| Biến | Giá trị |
|---|---|
| `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `AWS_BEARER_TOKEN_BEDROCK` | Giữ như máy dev |
| `WAREHOUSE_AGENT_TOKEN` | Giá trị ngẫu nhiên mới: `python3 -c "import secrets;print(secrets.token_urlsafe(32))"` |
| `AIRFLOW_UID` | Kết quả `id -u` |
| `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY` | Theo [Đăng nhập](auth_setup.md) |
| `AGENT_OWNER_EMAILS` | Email của bạn: không giới hạn, thấy tab Admin |
| `POSTGRES_PASSWORD` | Tùy chọn; Postgres chỉ nghe trên 127.0.0.1 |

## Khởi động

```bash
deploy/home/deploy.sh --force
```

Lệnh này build và chạy lần lượt: stack chính (Postgres + migration, Kafka, Kafka UI, Spark, live producer, API, web,
Jaeger), Airflow, agent dự báo/anomaly/ledger, rồi agent Trade/SRE và gateway, và chờ health check. Lần build đầu
mất 10–20 phút.

```bash
docker ps --format '{{.Names}}\t{{.Status}}'      # mọi container Up, agent (healthy)
curl -s http://127.0.0.1:8000/health              # {"status":"ok"}
```

## Nạp lịch sử và bật batch

Live producer nạp nến 1 phút từ bây giờ. Lịch sử lấy từ archive ngày và tháng của Binance:

```bash
# Nến giờ từ 2020 cho ba asset mà agent hỗ trợ (tải archive vào data/raw).
DATABASE_URL=postgresql://crypto:crypto@localhost:5432/crypto_dw \
  uv run --python 3.12 --with-requirements pipeline/requirements.txt \
  python -m scripts.backfill_eda --symbols BTC,ETH,SOL --interval 1h --start 2020-01
# Nến ngày cho dashboard và model ngày.
make eda-backfill
```

Sau đó để Airflow giữ dữ liệu mới:

```bash
docker compose exec airflow airflow dags unpause coinsight_warehouse_daily
docker compose exec airflow airflow dags unpause coinsight_direction_daily
docker compose exec airflow airflow dags trigger coinsight_warehouse_daily     # chạy lần đầu ngay
```

## Công bố qua Cloudflare

1. Tạo tunnel và route:

   ```bash
   cloudflared tunnel login                         # trình duyệt: chọn zone kaiosthefox.dpdns.org
   cloudflared tunnel create coinsight              # in tunnel ID, ghi ~/.cloudflared/<ID>.json
   cp deploy/cloudflared/config.example.yml ~/.cloudflared/config.yml   # điền <TUNNEL_ID> và <user>
   cloudflared tunnel route dns coinsight coinsight.kaiosthefox.dpdns.org
   ```

2. Chạy tunnel như một container luôn bật:

   ```bash
   docker compose --env-file .env -p coinsight-tunnel -f deploy/home/compose.tunnel.yml up -d
   ```

3. **[bạn]** Bật đăng nhập Google/GitHub theo [Đăng nhập](auth_setup.md). Web app công khai: dashboard và docs
   ai cũng xem được, khách hỏi được vài câu miễn phí, đăng nhập để hỏi nhiều hơn. Giới hạn ở
   [Model, router & giới hạn](model_router.md).
4. **[bạn]** SSH qua tunnel (`ssh.kaiosthefox.dpdns.org`) vẫn cần một ứng dụng Cloudflare Access riêng. Không xóa nó.
5. Deploy docs lên `/docs`: `npm --prefix frontend run deploy:docs`.

Không thêm route tunnel cho Airflow, Kafka UI hay Jaeger. Nếu cần từ xa, mỗi cái một hostname riêng sau một ứng
dụng Access riêng.

Bật deploy tự động từ `main` theo [CI/CD & rollback](deployment.md).

## Kiểm tra

| Kiểm tra | Mong đợi |
|---|---|
| `/drift` trong Desk | drift của anomaly và dự báo, số dòng ledger tăng |
| "check service health" | API, forecast, traces, Airflow, Kafka, Postgres ok; stream mới (< 5 phút) |
| `select count(*) from ml.prediction_ledger` | +1 mỗi giờ; dòng đã chấm xuất hiện sau một giờ |
| Desk → History / Memory | chỉ cuộc trò chuyện và ghi chú của bạn |
| Chưa đăng nhập, `/api/v1/me` | `anonymous: true`, 5 câu miễn phí |
| `curl -I https://coinsight.kaiosthefox.dpdns.org/docs/` | 200, không cần đăng nhập |
| `tail data/deploy.log` | có dòng `deployed` cho `main` hiện tại |

## Vận hành

- Log: `docker compose logs --tail 100 <service>`; agent: `docker compose -f warehouse_agents/compose.yml logs`.
- Restart một phần mà không deploy lại: `docker compose restart live-producer`.
- Đĩa: retention của Kafka và archive trong `data/raw` tăng chậm; `docker system prune` dọn image cũ sau deploy.
- Mất điện: mọi container chạy lâu có `restart: unless-stopped` (`deploy/home/compose.restart.yml`), nên stack tự
  lên lại khi Docker khởi động. Cho Docker tự chạy khi khởi động máy, và kiểm tunnel và cron sau khi reboot.

### Batch ngày dừng: `Permission denied` trong `data/raw`

Sự cố 2026-10-22 → 24: một lần chạy extract thủ công bằng root tạo `data/raw/binance/*` thuộc root. Airflow chạy
với uid 1000 nên mọi extract sau đó lỗi `PermissionError`, run ngày 22 kẹt ở `running` và chặn các ngày sau; dashboard
đứng ở giá đóng cửa 20/10.

```bash
docker exec -u 0 crypto-dw-dss-airflow-1 chown -R 1000:0 /opt/airflow/data/raw   # trả quyền cho Airflow
# run kẹt: đánh dấu failed qua API (Airflow local cấp token khi mọi user là admin), rồi chạy lại
T=$(curl -s localhost:8081/auth/token | jq -r .access_token)
curl -X PATCH -H "Authorization: Bearer $T" -H 'Content-Type: application/json' -d '{"state":"failed"}' \
  "localhost:8081/api/v2/dags/coinsight_warehouse_daily/dagRuns/<run_id>"
docker exec crypto-dw-dss-airflow-1 airflow dags trigger coinsight_warehouse_daily
```

Chạy tay thì chạy trong container Airflow (`docker exec crypto-dw-dss-airflow-1 …`), không chạy bằng root trên host.
