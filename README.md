# CoinSight: Crypto Data Warehouse & DSS

> **Trạng thái: research prototype, chưa phải DSS hoàn chỉnh hoặc production-ready.**
> Xem [đánh giá thẳng và backlog có tiêu chí nghiệm thu](docs/product_readiness.md).
> Build thành công và HTTP 200 chỉ kiểm chứng đường chạy kỹ thuật, không chứng minh
> chất lượng dự đoán, độ tin cậy vận hành hoặc tính hữu ích của sản phẩm.

Kho dữ liệu và hệ hỗ trợ quyết định cho thị trường tiền điện tử. Code được chia
theo kiến trúc (pipeline, kho dữ liệu, API), không chia theo thư mục từng người.

Jaeger local: **http://localhost:16686** — [phạm vi tracing và cách kiểm tra](docs/observability.md).

**Đọc tài liệu trên web:** <http://localhost:3000/docs/> — sidebar theo chủ đề,
tìm kiếm nội dung, mục lục từng trang, Mermaid và nút copy code. Có link Docs
trên dashboard. Nội dung lấy từ `README.md`, toàn bộ `docs/**/*.md` và
`frontend/DESIGN.md`; không cần viết thêm HTML cho từng tài liệu.
Sau khi sửa Markdown, chạy `docker compose up -d --no-deps --build frontend`;
khi dùng `npm --prefix frontend run dev`, nội dung được reload khi sửa file.
Frontend Docker build dùng context gốc repo để lấy docs:
`docker build -f frontend/Dockerfile .`. Link source code/PDF mở trên GitHub;
file PDF chỉ có local chưa được xuất bản trên trang docs.

## Tiến độ thực tế — 07/10/2026

Checklist dưới đây phân biệt **đã có implementation** với **đã đủ tin cậy để vận hành**.
Không dùng số lượng service hay màn hình để tính phần trăm hoàn thành.

### Đã có trong code

- [x] Batch Binance ZIP `1d/1h`: checksum, staging PostgreSQL, quality checks,
  upsert warehouse/mart và lineage về file nguồn.
- [x] Live Binance: nến `1m` đã đóng → Kafka → Spark → PostgreSQL;
  REST bù dữ liệu khi reconnect, checkpoint và khóa chống trùng.
- [x] FastAPI: lịch sử, live summary, quality, lineage, evaluation/prediction;
  WebSocket đẩy cập nhật tới browser sau DB commit.
- [x] UI Market/Operations: giá, chart lịch sử thật 30D/90D, trạng thái tín hiệu,
  chất lượng dữ liệu; chat có Markdown và chế độ mở rộng. Đây là hai workspace,
  **chưa phải phân quyền user/admin**. Reload data chỉ đọc lại API.
- [x] DSS thử nghiệm: logistic regression dùng chung BTC/ETH/SOL, dự đoán hướng
  ngày kế tiếp; lưu evaluation, artifact và prediction khi qua publication gate.
  Có model code không đồng nghĩa model đã thắng baseline hoặc có tín hiệu để dùng.
- [x] Airflow DAG: warehouse 06:00 UTC; DSS 07:30 UTC, train vào thứ Hai,
  predict hằng ngày. Chỉ chạy khi bật profile Airflow và unpause DAG.
- [x] Bedrock assistant gọi tool đọc dữ liệu và có tracing Jaeger;
  mỗi request độc lập, chưa có trí nhớ hội thoại hay skill framework.
- [x] Có instrumentation producer/Kafka headers, Spark và Airflow;
  chưa xác nhận đầy đủ trace end-to-end trên môi trường chạy thật.
- [x] Có workflow CI test/build/publish image. Có file workflow **không chứng minh
  CI trên PR đã xanh**, và publish image chưa phải tự động deploy server.
- [x] Đã xoá legacy `PriceTick` và test tương ứng. Kaggle replay vẫn là chế độ
  thử tùy chọn, không thuộc đường Binance mặc định.

### Chưa xong

- [ ] Forecasting theo proposal của Dương: dataset, năm model, đánh giá, registry,
  output schema, API và UI cho dự báo giờ kế tiếp — xem phần ngay dưới.
- [ ] Chứng minh chất lượng DSS: audit leakage, walk-forward, baseline theo coin,
  final test độc lập; artifact bất biến và lineage đủ mọi batch tạo feature.
- [ ] Kiểm chứng vận hành: replay không trùng, outage/restart recovery,
  khoảng trống dữ liệu, DAG retry/backfill và pipeline tracing thực tế.
- [ ] Agent: memory theo session, skills có contract, citations cho từng kết luận,
  eval dataset, timeout/cancel, hạn mức token/chi phí và xử lý provider lỗi.
- [ ] Observability: metrics bền vững, alerts có kiểm thử, lưu trữ/retention trace.
  Jaeger local hiện mất trace khi restart.
- [ ] Deployment: auth/rate limits, secrets, backup/restore, rollback, WebSocket
  load test và CD tới server/domain. Nginx cần kiểm tra lại khả năng đổi upstream
  khi API container được tạo lại mà không restart frontend.
- [ ] Usability: thử một tác vụ hoàn chỉnh với người mới; UI gọn hơn chưa chứng
  minh người dùng hiểu dữ liệu hay đưa ra quyết định tốt hơn.

Tiêu chí nghiệm thu chi tiết: [product_readiness.md](docs/product_readiness.md).

## Proposal forecasting của Dương: chưa triển khai

**Cập nhật 09/10/2026:** đã chốt [contract forecasting giờ](docs/hourly_forecast_contract.md)
và chọn **BTC XGBoost** để triển khai/train đầu tiên, kèm zero-return và mean-return
24h làm baseline. Chưa train: warehouse hiện chỉ có lịch sử giờ năm 2026, thiếu
train/validation 2020–2025 theo split đã chốt. Không dùng test 2026 để thay thế.
Các quyết định trong contract mới thay cho danh sách “cần chốt” phía dưới;
phần implementation, backfill và tích hợp vẫn chưa xong.

Đọc [forecasting_design.md](docs/forecasting_design.md). Đây là **đề xuất để duyệt**,
không tự thay thế [contract DSS hiện tại](docs/dss_contract_v1.md).

### Batch, live và train có vai trò gì?

| Nhánh | Mục tiêu | Model có dùng không? |
| --- | --- | --- |
| Batch ZIP Binance | Tạo lịch sử sạch, tái lập được cho chart, OLAP, train và đánh giá | Có: model hiện tại đọc daily + tổng hợp hourly từ DW; proposal đọc lịch sử hourly |
| Live Binance WebSocket | Quan sát thị trường vừa diễn ra: nến phút, biến động/volume 15 phút và metric Spark | Chưa dùng làm input model hiện tại; UI/chat đọc riêng để có ngữ cảnh mới |
| Airflow DSS | Gọi job train/predict, quản lý lịch và retry | Train đọc PostgreSQL warehouse qua `feature_builder.py`; Airflow không tự cung cấp dữ liệu |

Train học từ **nhiều sample lịch sử đã có kết quả thực tế**. Predict dùng
model đã train và những nến mới nhất hợp lệ để dự báo kết quả chưa xảy ra.
168 giờ trong proposal là cửa sổ của **mỗi sample**, không phải toàn bộ lịch sử train.
Vì thế train mỗi tuần và predict mỗi giờ có thể hợp lý; nhưng đường cấp input
mới mỗi giờ vẫn phải được xây dựng và kiểm chứng riêng.

| | Code hiện tại | Proposal của Dương |
| --- | --- | --- |
| Bài toán | Xác suất giá đóng ngày kế tiếp tăng | Log-return và giá đóng giờ kế tiếp |
| Dữ liệu | Feature ngày + tổng hợp giờ | Nến giờ Binance, lookback tối đa 168 giờ |
| Model | Logistic regression chung BTC/ETH/SOL | Model riêng từng coin: XGBoost, GRU, LSTM, PatchTST-based, iTransformer-based |
| Baseline / metric | Tỷ lệ ngày tăng / Brier score | Zero-return, rolling mean / MAE return, RMSE và Relative MAE |
| Output | `probability_up`, `as_of_date`, `target_date` | `predicted_log_return`, forecast close, cutoff/target time và run metadata |
| Trạng thái | Có train/predict/API; chất lượng còn phải kiểm định | Chưa có implementation của năm model hay API forecast giờ |

**Khoảng cách quan trọng:** bảng `dw.fact_ohlcv_hourly` có hạt một giờ, nhưng
DAG ZIP hiện chỉ nạp ngày trước vào 06:00 UTC. Nó phục vụ lịch sử train;
chưa cấp nến vừa đóng mỗi giờ cho inference. Nhánh live hiện cũng chưa ghi
nến giờ vào bảng này. Không thể chỉ đổi lịch predict thành hourly là xong.

Thứ tự làm tiếp:

1. Chốt contract với Dương: tách `input_open_time`, thời điểm đóng/cutoff,
   `generated_at` và target time; thống nhất đơn vị **USDT** cho cặp Spot USDT.
   Proposal đang dùng cả tên `forecast_price_usd`; cần làm rõ trước khi viết API.
2. Chốt biên lookback và warm-up: sequence `t-167…t` có 168 nến, nhưng lag 168
   và return đầu sequence cần dữ liệu trước biên đó. Quy định chung cho mọi model.
3. Tạo dataset lịch sử, gap/leakage tests, split cố định và hai baseline; chạy BTC
   trước. Sau đó XGBoost rồi mới mở rộng bốn model còn lại theo cùng protocol.
4. Bổ sung nguồn nến giờ mới đóng (REST hoặc aggregate từ phút với kiểm tra đủ
   nến), freshness gate và trigger inference sau khi dữ liệu hợp lệ đã commit.
5. Chốt bảng output, artifact/run identity, API và agent tool cho hourly forecast;
   không ghi return/giá vào endpoint `probability_up` của daily classifier.
6. Hiển thị forecast/actual và metric; kiểm chứng cả trường hợp thiếu dữ liệu,
   model không thắng baseline và provider lỗi trước khi gọi là DSS hoàn chỉnh.

## Trước khi PR / merge

- [ ] Review cả staged, unstaged và untracked; giữ `.env`, cache, model artifact
  và dữ liệu local ngoài commit. Chọn rõ tài liệu/PDF nào thuộc phạm vi PR.
- [ ] Chạy Python tests với PostgreSQL, frontend tests/build và Compose validation.
- [ ] Build mọi image, kiểm tra Airflow DAG import, xem CI của chính PR thành công.
- [ ] Kiểm tra migrations trên DB mới và DB có dữ liệu; demo live update và trạng
  thái model bị từ chối. Không dùng forecast giả để làm UI trông hoàn thiện.
- [ ] PR ghi rõ phạm vi implementation và các mục chưa hoàn thành ở trên.

Kiểm tra local ngày 07/10/2026: **53 Python tests pass, không skip** (PostgreSQL
đang chạy), **7 frontend tests pass**, Vite build, `docker compose config --quiet`,
`git diff --check` và link nội bộ README đều đạt. Python chạy bằng môi trường
`uv run` dùng requirements của pipeline/API vì máy hiện chưa có `.venv` cho
`make test`; chạy `make setup` trước nếu muốn dùng lệnh đó. Chưa build lại mọi
image, kiểm tra DAG import hoặc xác nhận GitHub CI trong lần cập nhật README này.

## Đọc project trong 5 phút

**Bắt đầu ở [Luồng dữ liệu CoinSight](docs/data_flow.md):** một trang đi từ Binance
qua staging/Kafka, warehouse, model tới API/UI; có sơ đồ và vị trí code từng bước.

Một **nến OHLCV** tóm tắt giá mở/cao/thấp/đóng và volume trong một khoảng
thời gian. `BTCUSDT` là giá BTC tính bằng USDT. CoinSight dùng nến Spot Binance
để trả lời: dữ liệu thị trường hiện thế nào, nguồn có đáng tin không, và model
có đủ bằng chứng để công bố xác suất giá đóng ngày mai tăng không?

```text
                       LỊCH SỬ (batch, 1d/1h)
Binance ZIP → data/raw → PostgreSQL staging → quality → dw facts/dimensions → marts
                               ↑ Airflow chạy và theo dõi hằng ngày       │
                                                                           ├→ Daily DSS model
                       TRỰC TIẾP (stream, 1m)                             │
Binance WebSocket → producer → Kafka → Spark → dw minute candles + 7d metric
                                              ↓
                                 FastAPI → dashboard / Bedrock chat tools
```

Cả hai nguồn chính đều do **Binance** cung cấp: lịch sử lấy ZIP từ
`data.binance.vision`; dữ liệu live lấy WebSocket, dùng Binance REST chỉ để
bù nến khi mất kết nối. Kaggle replay là chế độ thử riêng, không cần để vận
hành hệ thống mặc định.

```mermaid
flowchart LR
  B[Binance Spot ZIP 1d/1h] --> R[data/raw cache]
  R --> S[(staging.stg_ohlcv)]
  S --> Q[Quality checks + dedup]
  Q --> W[(dw facts + dimensions)]
  W --> M[(mart views)]
  W --> D[DSS: features, train, predict]
  L[Binance closed 1m WebSocket] --> P[Live producer]
  P --> K[Kafka topic]
  K --> SP[Spark Structured Streaming]
  SP --> C[(dw.fact_candle_minute_live)]
  SP --> SM[(dw.fact_stream_metric_v1)]
  C --> N[PostgreSQL NOTIFY after commit]
  SM --> N
  W --> API[FastAPI]
  D --> API
  N --> WS[FastAPI WebSocket]
  WS --> UI
  API --> UI[React dashboard]
  API --> AG[Bedrock chat tools]
  AF[Airflow] -. schedules .-> S
  AF -. schedules .-> D
```

**Đọc code ở đâu?** `pipeline/batch/` tải và nạp lịch sử;
`pipeline/stream/` nhận Kafka và xử lý live; `pipeline/decision/` tạo feature
và model; `airflow/dags/` định lịch; `postgres/` định nghĩa bảng;
`app/api.py` đọc kết quả; `frontend/` hiển thị. Bắt đầu từ
`airflow/dags/coinsight_warehouse.py` cho đường batch và
`pipeline/stream/spark_stream_processor.py` cho đường live.

### SQL, staging và ETL/ELT

Các file `.sql` là **lệnh tạo hoặc truy vấn database**, không phải file dữ liệu
được tải từ Binance. Chúng được chia theo thời điểm sử dụng:

| File | Làm gì / chạy khi nào |
| --- | --- |
| `postgres/init/01_staging_meta.sql` | Tạo `staging.stg_ohlcv` và `meta.*` (log batch, checksum, data quality, lineage) khi PostgreSQL volume mới được khởi tạo. |
| `postgres/init/02_dw_schema.sql` | Tạo dimension, fact và view nền của warehouse lúc khởi tạo. |
| `postgres/init/03_seed.sql` | Nạp thông tin coin/nguồn tham chiếu lúc khởi tạo. |
| `postgres/init/04_marts.sql` | Tạo view/materialized view cho phân tích OLAP lúc khởi tạo. |
| `postgres/migrations/*.sql` | Nâng database **đã tồn tại** lên schema/contract mới; service `migrate` chạy trước API và Spark. |
| `postgres/queries/olap_examples.sql` | Câu SQL mẫu để học và thử truy vấn; chạy bằng `make olap`, không tạo dữ liệu nguồn. |

`staging.stg_ohlcv` là **bảng PostgreSQL thật**. Extractor giải nén CSV, đổi
timestamp và số sang kiểu phù hợp, rồi dùng `COPY` ghi nhanh vào staging.
`StringIO` trong `staging_writer.py` chỉ là buffer ngắn cho `COPY`; dữ liệu
staging không chỉ ở RAM. Quality checks loại dòng có giá không dương,
`high < open/close/low`, `low > open/close`, volume âm, thời gian không khớp
UTC hoặc nguồn lạ. Cảnh báo batch theo dõi nến trùng, khoảng trống, freshness
và mức chênh volume ngày/giờ. Loader giữ bản nến mới nhất theo khóa, upsert
dimension/fact, rồi refresh mart; batch daily thành công xóa dòng staging của
chính batch đó. `meta.*` giữ log kiểm tra và nguồn file để truy ngược.

Tên chính xác của flow này là **E → L(staging) → T → L(warehouse)**: tải/parse
Binance, *load* vào staging, kiểm tra + chuẩn hóa + dedup, rồi *load* vào DW.
Vì transform chính xảy ra sau khi dữ liệu đã vào PostgreSQL, nó gần **ELT**
hơn ETL cổ điển, dù phần parse ZIP/CSV đã transform nhẹ trước staging. Spark
là nhánh khác: parse/filter/dedup event rồi tính aggregate trước khi ghi DB.

### Dữ liệu lưu ở đâu, UI live hiển thị gì?

`data/raw/` **không obsolete**: nó cache ZIP Binance; CSV Kaggle chỉ cần nếu
chủ động chạy replay. `data/models/` giữ artifact model DSS trên máy;
`data/sample.csv` là dữ liệu thử. Warehouse lâu dài nằm trong PostgreSQL named volume
`postgres-data`; Kafka và Spark checkpoint có named volume riêng. Đừng xóa
`data/` khi đang dùng bootstrap, replay hoặc train model local.

Live producer chỉ gửi **nến 1 phút đã đóng** vào Kafka (BTC/ETH/SOL theo
`pipeline/settings.yaml`). Kafka giữ event và offset; Spark đọc liên tục,
ghi từng nến vào `dw.fact_candle_minute_live` (khóa `pair, open_time`, nên
replay/backfill không nhân đôi), đồng thời ghi aggregate cửa sổ **7 ngày trượt
mỗi 1 ngày** vào `dw.fact_stream_metric_v1`. Airflow không chạy Spark; nó chỉ
điều phối batch warehouse và DSS theo lịch.

Dashboard <http://localhost:3000> tách **Market** và **Operations**. Lịch sử lấy dữ liệu
REST khi mở/chọn coin hoặc bấm `Reload data`. Live mở WebSocket
`/api/v1/assets/{symbol}/stream`: trigger PostgreSQL phát `NOTIFY` sau khi
Spark commit nến/metric, FastAPI `LISTEN` rồi đẩy API envelope của coin đó.
Kết nối mới nhận snapshot ngay; client tự reconnect nếu đứt mạng.

| Phần UI | API và dữ liệu thực tế |
| --- | --- |
| Market: giá gần nhất và biến động 15 phút | WebSocket `live-summary`: giá nến 1m đã đóng, % đổi giá, quote volume, coverage và freshness. |
| Market: danh sách coin và chart 30D/90D | REST `snapshot` và `prices`: giá đóng ngày từ warehouse, không phải giá tick hay mock. |
| Market: Signal | REST `prediction`, `model/evaluation`: xác suất hướng ngày kế tiếp nếu hợp lệ; không có forecast thì hiển thị lý do. |
| Operations: quality, lineage, Stream diagnostics | REST `data-status`, `lineage` và metric Spark từ WebSocket `live`; dành cho kiểm tra nguồn và vận hành. |

UI dùng React + Vite, build thành static assets rồi Nginx phục vụ. `MetricCard`,
`StatusBadge`, `EvidenceCard`, `SectionHeading` dùng chung cho hai nhánh;
`useLiveStream` quản lý WebSocket/reconnect theo coin. Thiết kế ba cột Stitch
vẫn responsive trên điện thoại. Next.js chưa cần vì trang đọc FastAPI và không
dùng server rendering. Browser không poll live REST; heartbeat WebSocket chỉ
kiểm tra kết nối và độ mới khi chưa có nến mới.

Để kiểm tra live end-to-end: `make live`, mở <http://localhost:3000>, chọn BTC,
rồi so sánh với `curl http://localhost:8000/v1/assets/BTC/live-summary` và
`curl http://localhost:8000/v1/assets/BTC/live`. Nếu producer chạy mà UI báo
`unavailable`, kiểm tra `docker compose ps spark` và
`docker compose logs --tail 100 spark`: producer chỉ đưa event tới Kafka;
**Spark phải chạy** thì bảng PostgreSQL và UI mới cập nhật.

## Phân công

```text
 A - STREAMING (Đại)
 [Kaggle replay] --\
                    >-> [Kafka] -> [Spark Structured Streaming] -> [Live metric 7 ngày]
 [Binance API] ----/       ^                                            |
                       [Kafka UI]                                       v
                                                                 [PostgreSQL DW]
 B - KHO DỮ LIỆU (Nhi)                                                  ^
 [Binance Public Data] -> [staging] -> [Kiểm tra DQ] -> [dw: star schema] -> [mart OLAP]
                          \_________ Airflow chạy mỗi ngày _________/

 C - DSS (Dương)
 [Lịch sử từ DW] -> [Phân loại hướng giá] --\
                                         >-> [FastAPI] <-> [Dashboard]
 [Live metric] ------------------/
```

| Phần | Người | Nội dung |
| --- | --- | --- |
| A | Đại | Binance/CSV replay, Kafka, Spark Streaming, live market aggregate |
| B | Nhi | Batch ETL, star schema PostgreSQL, data quality, OLAP/data mart, Airflow |
| C | Dương | Đề xuất forecasting giờ trong `docs/forecasting_design.md`; classifier ngày hiện tại là implementation thử nghiệm, chưa phải proposal này |

Tài liệu chi tiết phần B: [`docs/data_warehouse.md`](docs/data_warehouse.md)
(tóm tắt cho nhóm) và [`docs/dw_design.md`](docs/dw_design.md) (thiết kế).

## Cấu trúc thư mục

```text
CoinSight/
├── README.md                            Hướng dẫn cài đặt và sử dụng
├── pipeline/
│   ├── settings.yaml                    Coin, interval, lịch và ngưỡng xử lý
│   ├── settings.py                      Đọc YAML và biến môi trường
│   ├── telemetry.py                     Trace producer, Spark và Airflow task
│   ├── batch/
│   │   ├── binance_archive_format.py    Tên archive và định dạng CSV Binance
│   │   ├── binance_archive_downloader.py Tải ZIP, kiểm checksum
│   │   ├── staging_writer.py           Ghi archive vào staging và manifest
│   │   ├── ingest_binance_history.py   Điều phối ingest lịch sử Binance
│   │   ├── quality_checks.py           Rule kiểm tra dữ liệu batch
│   │   └── warehouse_loader.py         Nạp fact/dimension, refresh mart
│   ├── stream/
│   │   ├── kaggle_replay_producer.py    Replay CSV Kaggle vào Kafka
│   │   ├── binance_live_client.py       Đọc Binance REST/WebSocket
│   │   ├── kafka_publisher.py           Gửi Kafka, lưu tiến độ theo coin
│   │   ├── spark_stream_processor.py   Lọc event, tính metric bằng Spark
│   │   └── stream_sink_writer.py       Ghi nến và metric vào PostgreSQL
│   ├── decision/
│   │   ├── feature_builder.py          Đọc warehouse, tạo feature/label
│   │   └── direction_model.py          Train, đánh giá, dự đoán hướng giá
│   ├── Dockerfile                       Image Python cho batch và producer
│   ├── Dockerfile.spark                 Image Spark
│   └── requirements.txt                Thư viện Python cho pipeline
├── airflow/
│   ├── dags/coinsight_warehouse.py     Lịch ingest và load warehouse
│   ├── dags/coinsight_dss.py           Daily classifier: train thứ Hai, predict mỗi ngày
│   ├── create_metadata_db.py           Tạo metadata DB cho Airflow
│   ├── Dockerfile                       Image Airflow
│   ├── requirements-tracing.txt         Phiên bản tracing tương thích image Airflow
│   └── requirements.txt                Thư viện Airflow cần thêm
├── app/
│   ├── api.py                           Endpoint FastAPI
│   ├── api_schemas.py                   Schema request/response Pydantic
│   ├── chat_agent.py                    Bedrock chat và tool đọc dữ liệu
│   ├── live_stream.py                   LISTEN PostgreSQL và đẩy WebSocket
│   ├── telemetry.py                     Trace assistant, Bedrock và tool/query
│   ├── static/dashboard.html            Trang dashboard
│   ├── static/dashboard.css             Kiểu giao diện
│   ├── static/dashboard.js              Gọi API, cập nhật giao diện
│   ├── Dockerfile                       Image API
│   └── requirements.txt                Thư viện API
├── frontend/
│   ├── index.html                       React mount point
│   ├── src/App.jsx                      Workspace Market/Operations và chat
│   ├── src/MarketOverview.jsx           Giá, biến động, chart 30D/90D, trạng thái tín hiệu
│   ├── src/readiness.js                 Kiểm freshness/coverage và hiệu lực prediction
│   ├── src/readiness.test.js            Test dữ liệu cũ, thiếu và prediction hết hạn
│   ├── src/components.jsx               Card, badge, chart, chat dùng lại
│   ├── src/useLiveStream.js              WebSocket và reconnect theo coin
│   ├── src/format.js                     API client và format giá/thời gian
│   ├── styles.css                       Style responsive theo thiết kế Stitch
│   ├── package.json / package-lock.json React + Vite cố định phiên bản
│   ├── nginx.conf                       Proxy REST + WebSocket tới FastAPI
│   ├── code.html                        Mockup Stitch gốc để đối chiếu
│   ├── DESIGN.md                        Quy tắc layout, màu sắc và typography
│   ├── screen.png                       Ảnh tham chiếu giao diện
│   └── Dockerfile                       Build Vite rồi phục vụ bằng Nginx
├── postgres/
│   ├── init/01_staging_meta.sql         Staging, ETL log, lineage, DQ
│   ├── init/02_dw_schema.sql            Dimension, fact và view nền
│   ├── init/03_seed.sql                 Coin tham chiếu
│   ├── init/04_marts.sql                View OLAP
│   ├── migrations/001_contracts_v1.sql Nâng DB cũ lên contract v1
│   ├── migrations/002_decision_pipeline.sql  Bảng DSS
│   ├── migrations/003_live_notifications.sql Thông báo khi live commit
│   └── queries/olap_examples.sql       Truy vấn OLAP mẫu
├── tests/
│   ├── batch/test_ingest_binance_history.py  Test ZIP, checksum, parse nến
│   ├── batch/test_warehouse_loader.py        Test staging, DQ, fact, mart
│   ├── stream/test_kaggle_replay_producer.py  Test đọc CSV replay
│   ├── stream/test_binance_live_client.py     Test nến live và reconnect
│   ├── decision/test_feature_builder.py       Test label theo ngày UTC
│   ├── app/test_dss_contract.py                Test API DSS publish/reject
│   ├── app/test_api.py                        Test health và API response
│   ├── app/test_chat_agent.py                 Test tool agent được phép gọi
│   ├── app/test_telemetry.py                  Test trace API/assistant bằng exporter giả lập
│   ├── observability/test_pipeline_tracing.py Test propagation và spans của pipeline
│   └── app/test_live_stream.py                Test WebSocket push
├── docs/
│   ├── data_flow.md                    Luồng dữ liệu toàn hệ thống và vị trí code từng bước
│   ├── data_warehouse.md               Tiến độ và phân công DW
│   ├── dw_design.md                    Thiết kế schema và ETL chi tiết
│   ├── data_contracts_v1.md           Contract, lineage, chất lượng
│   ├── dss_contract_v1.md              Handoff model, bảng output và API cho Dương
│   ├── forecasting_design.md           Proposal hourly forecasting của Dương, chưa triển khai
│   ├── hourly_forecast_contract.md     Contract giờ đã chốt; BTC XGBoost là model đầu tiên
│   ├── product_readiness.md            Critique, backlog và tiêu chí nghiệm thu
│   ├── observability.md                Jaeger, phạm vi tracing và giới hạn
│   ├── deployment.md                  Hướng dẫn triển khai
│   ├── frontend_progress.md           Checklist tiến độ giao diện thật
│   ├── DW_Review_1_....pdf            Slide môn học tham khảo
│   ├── diagrams/EERD.pdf              Sơ đồ thực thể
│   └── diagrams/Relation-schema.pdf   Sơ đồ quan hệ
├── scripts/generate_diagrams.py        Sinh sơ đồ DW
├── scripts/demo_direction_model.py     Thử classifier với dữ liệu tổng hợp
├── data/sample.csv                     CSV mẫu; data/raw/ là cache local
├── .env.example                        Mẫu cấu hình triển khai
├── .gitignore                           Bỏ qua cache, môi trường và dữ liệu local
├── .github/workflows/ci.yml           Test, build và publish image
├── docker-compose.yml                  Container, volume và network
└── Makefile                            Lệnh tắt để chạy project
```

Các file `__init__.py` chỉ đánh dấu thư mục Python package, không chứa logic.

Chạy dashboard mới tại <http://localhost:3000> bằng
`docker compose up --build -d frontend`. Trang này đọc dữ liệu
thật từ FastAPI qua `/api`; `frontend/code.html` chỉ là file tham chiếu Stitch
và không được phục vụ. Dashboard cũ vẫn ở <http://localhost:8000>.
Theo dõi phần đã làm và còn thiếu trong [frontend_progress.md](docs/frontend_progress.md).

Model phân loại hướng giá ngày kế tiếp đã có; kết quả chỉ được công bố khi
đánh giá tốt hơn baseline. Xem trạng thái hiện tại tại `/v1/model/evaluation`.

## Cài đặt

Đã thử trên Linux; macOS tương tự, Windows nên dùng WSL2. Các lệnh chạy từ thư
mục gốc của repo.

| Công cụ | Để làm gì | Kiểm tra |
| --- | --- | --- |
| Docker và Docker Compose v2 | Chạy PostgreSQL, Kafka, Spark, Airflow, API | `docker compose version` |
| git | Lấy code | `git --version` |
| [uv](https://docs.astral.sh/uv/) | Tạo môi trường Python 3.12 cho các lệnh `make` | `uv --version` |
| make | Chạy lệnh tắt trong `Makefile` | `make --version` |
| DBeaver hoặc extension PostgreSQL của VS Code (tùy chọn) | Xem bảng bằng giao diện | |

Cần khoảng 70 MB cho dữ liệu Binance và vài GB cho Docker image (Kafka, Spark,
Airflow khoảng 1,5 GB).

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # nếu chưa có uv
export PATH="$HOME/.local/bin:$PATH"

git clone git@github.com:caoTayTang/CoinSight.git
cd CoinSight
cp .env.example .env
id -u                 # nếu khác 1000, sửa AIRFLOW_UID trong .env
make setup            # tạo .venv và cài thư viện Python
```

`.env` chứa giá trị nhìn **từ bên trong container** (host `postgres`, đường dẫn
`/data/...`). Các lệnh `make extract`, `make batch`, `make test` chạy trên máy
thật nên tự đổi sang `localhost` và đường dẫn trong repo; không cần sửa `.env`
cho chúng. `.env` không được đưa lên git.

Khi chạy script Python trực tiếp (không qua `make`), kích hoạt môi trường trước:

```bash
source .venv/bin/activate
```

## `docker compose up` chạy gì?

```bash
docker compose up --build -d
```

`up` khởi động các service mặc định trong `docker-compose.yml`. `--build` build
image từ code hiện tại; `-d` để container chạy nền và trả terminal lại. Nếu
bỏ `-d`, terminal hiện log; `Ctrl+C` sẽ dừng các container do lệnh đó chạy.
Mặc định là **Binance live**, không cần file Kaggle.

| Service | Chạy liên tục hay xong rồi thoát? | Việc nó làm |
| --- | --- | --- |
| `postgres` | Liên tục | Lưu bảng warehouse, live và metadata. Các file `postgres/init/*.sql` **chỉ chạy khi volume database mới được tạo**, không chạy lại mỗi lần `up`. |
| `migrate` | **Một lần mỗi khi container này được khởi động**, rồi `Exited (0)` | Chạy các file `postgres/migrations/*.sql` trên DB đang có. SQL được viết để chạy lại an toàn; `Exited (0)` là thành công, không phải lỗi. |
| `kafka` | Liên tục | Nhận và giữ event nến 1 phút. |
| `kafka-ui` | Liên tục | Giao diện xem Kafka tại cổng 8080. |
| `live-producer` | Liên tục | Nghe Binance WebSocket; nến đóng mỗi phút được gửi vào Kafka. REST chỉ bù nến khi mất kết nối. |
| `spark` | Liên tục | Đọc topic `crypto-prices-live`, lưu nến phút và tính metric 7 ngày vào PostgreSQL. |
| `api` | Liên tục | FastAPI đọc warehouse/live và đẩy cập nhật WebSocket cho browser. |
| `frontend` | Liên tục | Phục vụ dashboard tại cổng 3000. |

**`up` không tải ZIP lịch sử, không chạy batch ETL, không train model và không
bật Airflow.** Vì vậy Live có thể lên giá trong khi chart lịch sử hoặc dự đoán
vẫn chưa có dữ liệu. Kaggle `producer` cũng không chạy; nó thuộc profile
`replay` riêng.

Những việc cần gọi riêng:

| Lệnh | Khi nào dùng | Chạy kiểu gì? |
| --- | --- | --- |
| `make extract` | Lần đầu nạp toàn bộ lịch sử Binance và khi muốn kiểm file mới | Tải ZIP → ghi staging, **xong thì thoát**. Chạy lại được; file đã nạp không bị nhân đôi. |
| `make batch` | Sau `make extract`, hoặc khi staging còn batch chờ load | Kiểm chất lượng → nạp warehouse, **xong thì thoát**. |
| `make airflow` | Muốn các bước batch/DSS tự chạy theo lịch | Bật **service Airflow chạy liên tục**; task của DAG chạy từng lượt theo lịch. |
| `make dss-train`, `make dss-predict` | Muốn thử model/thực hiện suy luận thủ công | Mỗi lệnh **chạy một lượt rồi thoát**. Model bị từ chối thì không công bố dự đoán. |
| `make stream` | Chỉ để demo replay CSV Kaggle | `producer` đọc hết file rồi thoát; Kafka/Spark/API vẫn chạy liên tục. Không cần cho chế độ Binance mặc định. |

Kiểm tra trạng thái bằng `docker compose ps --all`: các service liên tục cần
`Up`, riêng `migrate` cần `Exited (0)`. Lần đầu build có thể lâu vì Docker tải
Kafka và Spark.

| Cổng | Service | Địa chỉ |
| --- | --- | --- |
| 5432 | PostgreSQL | `localhost:5432` |
| 8000 | FastAPI và dashboard cũ | <http://localhost:8000>, tài liệu API <http://localhost:8000/docs> |
| 3000 | Dashboard chính | <http://localhost:3000> |
| 8080 | Kafka UI (A) | <http://localhost:8080> |
| 8081 | Airflow (B), chạy bằng `make airflow` | <http://localhost:8081> |

Dashboard chính có Market và Operations: lịch sử tải theo coin hoặc khi bấm
Reload data; live nhận WebSocket sau mỗi lần Spark commit nến/metric mới.

### Chạy từ đầu và kiểm tra từng nhánh

Từ thư mục gốc repo, với Docker đang mở:

```bash
docker compose up --build -d
docker compose ps
curl -s http://localhost:8000/v1/assets/BTC/live-summary
```

Mở <http://localhost:3000> để xem dashboard. Sau khi có ít nhất một nến phút
đã đóng, phần Live có giá mới; lúc vừa khởi động nó có thể báo chưa đủ `15/15`
nến. Xem đường dữ liệu nếu chưa lên:

```bash
docker compose logs --tail=50 live-producer spark
```

Lệnh trên **chỉ chạy nhánh live**. Để nạp lịch sử Binance `1d/1h` và có phần
Batch, chart lịch sử, DQ, lineage của file nguồn:

```bash
make setup                 # chỉ lần đầu: tạo .venv
make extract               # Binance ZIP → data/raw → staging
make batch                 # staging → quality → warehouse/mart
curl -s http://localhost:8000/v1/data-status
```

`make extract` và `make batch` là **lệnh chạy một lượt rồi kết thúc**, không
phải container chạy mãi. `make extract` lần đầu tải từ tháng
`batch.start_month` cho 20 coin trong `pipeline/settings.yaml`, nên có thể
mất thời gian. Nếu chỉ muốn thử một ngày (vẫn với các coin đã cấu hình), dùng
`make extract-daily DAY=YYYY-MM-DD` cho ngày UTC đã công bố, rồi `make batch`.
Sau khi bootstrap, bật scheduler bằng `make airflow`, mở
<http://localhost:8081>, bật DAG `coinsight_warehouse_daily` và
`coinsight_direction_daily` nếu muốn chạy theo lịch. **Container Airflow chạy
liên tục; từng DAG task chỉ chạy một lượt vào giờ hẹn rồi kết thúc.** Airflow
không chạy khi chỉ gọi `docker compose up`.

Kiểm tra lineage của lần load gần nhất:

```bash
docker compose exec -T postgres psql -U crypto -d crypto_dw -Atc \
"select batch_id from meta.etl_batch where pipeline='batch_etl' and status='success' order by batch_id desc limit 1;"
curl -s http://localhost:8000/v1/lineage/batches/10   # thay 10 bằng batch_id vừa lấy
```

`docker compose down` giữ lại volume database, Kafka và Spark checkpoint;
`docker compose down --volumes` mới xóa chúng.

Nếu `.env` cũ còn `KAFKA_TOPIC` hoặc `STREAM_CHECKPOINT`, Compose hiện bỏ qua
hai tên cũ. Xem `.env.example` để dùng `LIVE_KAFKA_TOPIC`,
`STREAM_KAFKA_TOPIC` và `STREAM_CHECKPOINT_PATH` khi cần đổi cấu hình.

Kafka UI, Airflow và dashboard không có đăng nhập khi chạy local, và Kafka UI có
thể sửa topic. Không mở các cổng này trên máy dùng chung hoặc mạng công cộng.

Dừng service, giữ nguyên dữ liệu:

```bash
make down
```

## A - Streaming

- `pipeline/stream/kaggle_replay_producer.py` replay dữ liệu OHLCV lịch sử vào Kafka theo thứ tự thời
  gian sự kiện; mặc định chọn BTC, ETH và SOL.
- `pipeline/stream/binance_live_client.py` nhận nến 1 phút đã đóng từ Binance WebSocket;
  khi reconnect dùng REST để bù nến bị lỡ.
- `pipeline/stream/spark_stream_processor.py` kiểm tra và loại trùng sự kiện, tính metric cửa sổ
  trượt 7 ngày theo ngày, rồi upsert vào `fact_live_metric` cũ và
  `fact_stream_metric_v1` có nguồn/chế độ rõ ràng.
- Kafbat UI hiển thị topic, partition, offset và nội dung message.
- Kafka log, producer cursor và Spark checkpoint đều ở named volumes; thử
  `down`/`up` không cần xóa database. Các event trùng được Spark loại theo ID.
- `docker compose down` giữ named volumes; `down -v` xóa dữ liệu và checkpoint.
  Khởi động lại có thể tạo thêm log của job được chạy chủ động, nhưng fact
  được upsert theo khóa nên không nhân đôi các nến cũ.

### Dữ liệu replay (tùy chọn)

Nguồn replay là dataset Kaggle
[Cryptocurrency Prices (Top 200+) - Daily Updated](https://www.kaggle.com/datasets/isaaclopgu/cryptocurrency-historical-prices-top-100-2025),
phiên bản 105: OHLCV theo ngày của 250 coin trong `Crypto_historical_data.csv`,
giấy phép CC BY-SA 4.0. Đặt file tại:

```text
data/raw/Crypto_historical_data.csv
```

Đổi `replay.symbols` trong `pipeline/settings.yaml` để chọn coin khác, hoặc đặt
`[]` để replay tất cả.

### Xem stream chạy

Chạy Binance live (mặc định):

```bash
docker compose up --build -d
# hoặc make live nếu muốn xem log trực tiếp trong terminal
```

Chỉ khi cần demo đường replay lịch sử từ Kaggle:

```bash
make stream
```

Cả hai cách mở dashboard chính tại <http://localhost:3000>. `make stream`
chuyển Spark sang topic/checkpoint replay và chỉ khởi động Kaggle producer khi
được gọi; cần có file CSV ở đường dẫn trên. Để quay lại Binance sau replay,
chạy lại `docker compose up --build -d` (hoặc `make live`). Dòng trạng thái
`API connected` chỉ cho biết trang kết nối FastAPI, không chứng minh đã có nến.

Live producer chỉ phát nến khi Binance đánh dấu đã đóng (`k.x = true`). REST
được dùng để bù các phút bị lỡ sau reconnect. `volume` là quote volume tính
bằng **USDT**, không phải USD chính xác tuyệt đối. Đổi `live.symbols` trong
`pipeline/settings.yaml` để dùng coin khác có cặp USDT. Replay và live dùng topic cũng như Spark
checkpoint riêng, nên có thể chuyển qua lại bằng `make stream` / `make live`
mà không xóa volume. Không chạy cả hai lệnh cùng lúc vì chúng cùng quản lý
container Spark trong một Compose project.

API contract và lineage mới ở [`docs/data_contracts_v1.md`](docs/data_contracts_v1.md).
`/v1/assets/{symbol}/snapshot` đọc nến ngày Binance; `/v1/assets/{symbol}/live`
chỉ đọc metric mode `live`; `/v1/assets/{symbol}/stream` đẩy nến phút và metric
qua WebSocket; `/v1/data-status` và `/v1/lineage/batches/{id}`
cho biết chất lượng và nguồn file của lần ETL. Migration `migrate` tự chạy
trước API/Spark khi dùng Compose. Với database chạy bên ngoài Compose, chạy
`postgres/migrations/001_contracts_v1.sql` trước khi khởi động API mới.

**Lineage hiện có:** nhánh batch lưu `fact.batch_id → meta.batch_dependency →
meta.source_file_manifest` (URL file Binance, checksum SHA-256, coin, interval,
số dòng). Nhánh live lưu `pair + open_time`, nguồn `binance-ws` hoặc
`binance-rest-backfill`, cùng Kafka topic/partition/offset trên **từng nến phút**
trong `dw.fact_candle_minute_live`. Metric Spark 7 ngày chỉ lưu nguồn,
window và số event; hiện **chưa có mapping từng nến → từng metric** hay API
lineage riêng cho stream. Không nên coi `/v1/lineage/batches/{id}` là lineage
của dữ liệu live.

Mở <http://localhost:8080> rồi chọn:

```text
local -> Topics -> crypto-prices-live (hoặc crypto-prices-replay) -> Messages
```

Bấm vào một message để xem JSON. Các trường chính:

- `symbol`: mã coin, ví dụ `BTC`.
- `event_time`: ngày gốc trong dữ liệu lịch sử.
- `open_price`, `high_price`, `low_price`, `close_price`: giá của nến.
- `volume`: quote volume của nến.
- `event_id`: định danh ổn định Spark dùng để loại trùng.
- `source`: `kaggle-replay`, `binance-ws` hoặc `binance-rest-backfill`.

Topic có 3 partition. Offset chỉ là vị trí của message trong partition, không
phải giá hay thời gian.

Xem Spark đọc sự kiện và lưu metric:

```bash
docker compose logs --follow spark
```

Tìm dòng `stored ... metric updates from batch ...`; bấm `Ctrl+C` để thôi xem,
container vẫn chạy. Truy vấn các cửa sổ 7 ngày đã sinh:

```bash
docker compose exec postgres psql -U crypto -d crypto_dw -c \
"select symbol, count(*) as windows, max(event_count) as max_events
 from fact_live_metric group by symbol order by symbol;"
```

Với replay Kaggle, một cửa sổ 7 ngày đầy đủ có khoảng 7 event/ngày/coin.
Với Binance live nến 1 phút, `event_count` lớn hơn nhiều và độ phủ cần xem
theo `last_event_time`, không so với số 7.

Lần đầu Spark khởi động sẽ tải Kafka connector. Để replay lại từ trạng thái hoàn
toàn sạch, xóa cả volume database lẫn checkpoint rồi chạy lại:

```bash
docker compose --profile replay --profile airflow down --volumes
make stream
```

## B - Kho dữ liệu

- `pipeline/batch/ingest_binance_history.py` tải nến USDT theo ngày và theo giờ từ
  [Binance Public Data](https://data.binance.vision), kiểm tra checksum SHA-256,
  cache trong `data/raw/binance/` và nạp vào `staging.stg_ohlcv`.
- `pipeline/batch/warehouse_loader.py` chạy 12 rule chất lượng dữ liệu trên staging, loại
  dòng lỗi, upsert phần còn lại vào kho và làm mới các mart. Kết quả ghi trong
  `meta.etl_batch` và `meta.dq_result`.
- `postgres/init/` tạo các schema `staging`, `dw`, `mart`, `meta`. `dw` là
  galaxy schema: `fact_ohlcv_daily` và `fact_ohlcv_hourly` dùng chung
  `dim_asset`, `dim_date`, `dim_time`, `dim_source` với bảng live metric và
  forecast. View `mart.fact_price` giữ tương thích với API.
- `postgres/init/04_marts.sql` định nghĩa các mart OLAP dùng `ROLLUP`, `CUBE` và
  `GROUPING SETS`. `postgres/queries/olap_examples.sql` minh họa roll-up,
  drill-down, slice, dice và pivot.
- `airflow/dags/coinsight_warehouse.py` chạy pipeline lúc 06:00 UTC mỗi ngày:
  `extract_binance -> transform_load -> quality_report`.

### Dựng kho dữ liệu

```bash
docker compose up -d postgres      # tự tạo schema ở lần chạy đầu
make extract                       # tải dữ liệu Binance vào staging
make batch                         # kiểm tra chất lượng, nạp vào kho, làm mới mart
make olap                          # chạy 9 truy vấn OLAP mẫu
```

| Lệnh | Thời gian | Dòng cuối |
| --- | --- | --- |
| `make extract` lần đầu | khoảng 5 phút | `batch N: loaded ... rows into staging.stg_ohlcv` |
| `make extract` các lần sau | 1–2 phút, chỉ tải file mới | như trên |
| `make batch` | khoảng 30 giây | `batch N: read ..., rejected 0, accepted ... daily and ... hourly, ...` |

Lần nạp ngày 30/09/2026 có khoảng 1,18 triệu dòng; số dòng tăng mỗi ngày vì
Binance công bố thêm dữ liệu. File đã tải được giữ trong `data/raw/binance/`,
nên chạy lại không tải lại.

### Xem dữ liệu

Kết nối bằng DBeaver, VS Code hoặc `psql`:

| Trường | Giá trị |
| --- | --- |
| Host | `localhost` |
| Port | `5432` |
| Database | `crypto_dw` |
| User | `crypto` |
| Password | `crypto` |

```bash
psql postgresql://crypto:crypto@localhost:5432/crypto_dw
```

| Schema | Nội dung |
| --- | --- |
| `staging` | `stg_ohlcv`: dữ liệu vừa tải, chưa kiểm tra |
| `dw` | Bảng `dim_*` và `fact_*` |
| `mart` | View (`v_*`, `fact_price`) và materialized view (`mv_*`) để phân tích |
| `meta` | `etl_batch` (log mỗi lần chạy), `dq_result` (kết quả kiểm tra chất lượng) |
| `public` | Bỏ qua: bảng cũ nếu database được tạo trước khi đổi schema |

Trong DBeaver, materialized view nằm ở thư mục riêng `mart → Materialized
Views`. Trong `psql`: `\dt dw.*` liệt kê bảng, `\dv mart.*` liệt kê view,
`\dm mart.*` liệt kê materialized view.

### Chạy bằng Airflow

```bash
make airflow
```

Mở <http://localhost:8081>. Nếu DAG `coinsight_warehouse_daily` đang tắt,
bật công tắc cạnh tên DAG để chạy theo lịch, hoặc bấm ▶ để chạy ngay. Một lần
chạy mất khoảng 1–3 phút; log của task `quality_report` liệt kê kết quả kiểm
tra chất lượng. Airflow nằm trong profile `airflow` nên `docker compose up` không
khởi động nó. Metadata của Airflow nằm trong database riêng `airflow` trên cùng
server PostgreSQL, tự tạo ở lần chạy đầu.

### Cấu hình

`pipeline/settings.yaml` chứa lựa chọn của pipeline: coin, interval (`1d`/`1h` cho
batch), tháng bắt đầu, số worker, ngưỡng loại dữ liệu, lịch Airflow, tham số
replay/live/stream và DSS. Sửa file này rồi khởi động lại service liên quan;
container `producer` và `live-producer` cần `docker compose up --build` vì file
được đóng gói vào image. Interval batch hiện chỉ hỗ trợ `1d` và `1h` trong
warehouse; không thêm `1m` vào đó nếu chưa mở rộng schema/ETL.
Danh sách `dss.symbols` hiện phải khớp ba coin mà API DSS và agent hỗ trợ
(BTC, ETH, SOL); nếu đổi danh sách này, cần cập nhật cả API contract.

`.env` chứa giá trị phụ thuộc nơi triển khai: địa chỉ DB/Kafka/Binance, đường dẫn
file/checkpoint, credentials, Bedrock model ID và UID cho Airflow. Xem
`.env.example` để biết tên biến.

| Biến | Mặc định | Ý nghĩa |
| --- | --- | --- |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | `crypto_dw`, `crypto`, `crypto` | Database và tài khoản; chỉ có hiệu lực khi tạo volume mới |
| `DATABASE_URL` | `postgresql://crypto:crypto@postgres:5432/crypto_dw` | Chuỗi kết nối cho các container |
| `BINANCE_DATA_URL` | `https://data.binance.vision` | Nơi tải file lịch sử |
| `AIRFLOW_UID` | `1000` | User id trên máy thật mà Airflow dùng, để ghi được `data/raw` |
| `LIVE_KAFKA_TOPIC`, `STREAM_KAFKA_TOPIC` | `crypto-prices-live` | Topic Binance producer ghi và Spark đọc; phải khớp nhau khi chạy live |
| `STREAM_CHECKPOINT_PATH` | `/checkpoints/live-metrics-v2` | Spark checkpoint của chế độ live; replay dùng checkpoint khác |

Thêm coin: thêm mã vào `batch.symbols` trong `pipeline/settings.yaml` và thêm tên, nhóm của coin vào
`postgres/init/03_seed.sql`; nếu không, coin vẫn được nạp nhưng tên là mã coin
và không có nhóm.

Chạy thử nhanh với ít dữ liệu:

```bash
DATABASE_URL=postgresql://crypto:crypto@localhost:5432/crypto_dw RAW_DIR=data/raw \
  .venv/bin/python -m pipeline.batch.ingest_binance_history --symbols BTC,ETH --intervals 1d --start 2025-01
```

## C - DSS

**Hiện tại:** daily direction classifier bên dưới. **Hướng tiếp theo đang đề xuất:**
hourly regression trong [forecasting_design.md](docs/forecasting_design.md).
Hai bài toán khác target, metric và output; chưa tích hợp proposal vào API.

- Đưa kết quả batch và live ra qua API.
- Duy trì dashboard React/Vite tại `frontend/`, Nginx proxy REST và WebSocket FastAPI.
- Duy trì Docker Compose, kiểm tra service, test tích hợp và kịch bản demo.
- File hiện có: `app/api.py`, `app/live_stream.py`, `frontend/src/`, `docker-compose.yml`,
  `tests/app/test_api.py`.

Pipeline quyết định hiện có `pipeline/decision/direction_model.py`: một model phân loại chung cho
BTC/ETH/SOL dự đoán khả năng nến ngày mai đóng cao hơn hôm nay. `make dss-train`
đánh giá theo thứ tự thời gian với baseline; model chỉ được công bố nếu thắng
baseline. `make dss-predict` ghi dự đoán vào `dw.fact_direction_prediction`.
Nếu chưa đủ dữ liệu hoặc model bị từ chối, API trả trạng thái rõ ràng và
`/v1/model/evaluation` cho biết lý do. Airflow chạy ingest hằng ngày 06:00 UTC,
đánh giá model thứ Hai và suy luận hằng ngày 07:30 UTC. Bootstrap lịch sử vẫn
chạy riêng qua `make extract` rồi `make batch`.

API mới: `/v1/assets/BTC/live-summary` (15 nến 1 phút và độ phủ),
`/v1/assets/BTC/prediction`, `/v1/model/evaluation`, `/v1/agent/chat`.
Agent chỉ có tool đọc dữ liệu; cần cấu hình `BEDROCK_MODEL_ID` để bật.
UI mới theo thiết kế Stitch nằm ở `frontend/`; dashboard cũ ở `app/static/`.
Contract data flow ở [data_contracts_v1.md](docs/data_contracts_v1.md);
contract DSS/API để Dương triển khai ở [dss_contract_v1.md](docs/dss_contract_v1.md).
`make dss-demo` chạy logistic regression hiện có trên dữ liệu **tổng hợp** để
thử train và so Brier với baseline khi Docker đang tắt; lệnh này không publish
model hay prediction. `make dss-train` mới đọc warehouse thật.

## Test

```bash
docker compose up -d postgres      # các test kho dữ liệu cần PostgreSQL
make test
```

Test kiểm tra validation, lọc và sắp xếp CSV, chuẩn hóa nến Binance, đọc file
Binance, nạp kho và rule chất lượng dữ liệu, mart OLAP, và API. Nếu PostgreSQL
chưa chạy, các test kho tự bỏ qua (`skipped`).

## Làm lại từ đầu

Đổi schema trên database đang có dữ liệu: chạy `docker compose up -d migrate`.
Chỉ khi muốn chủ động xóa sạch dữ liệu local mới dùng:

```bash
docker compose --profile replay --profile airflow down --volumes   # xóa dữ liệu PostgreSQL local
docker compose up -d postgres
make extract
make batch
```

`data/raw/` không bị xóa, nên `make extract` lần này nhanh.

## Lỗi thường gặp

| Lỗi | Nguyên nhân | Cách xử lý |
| --- | --- | --- |
| `could not translate host name "postgres"` | Chạy script Python trực tiếp trên máy thật, nên nó đọc `DATABASE_URL` của container trong `.env` | Dùng `make extract` / `make batch`, hoặc đặt `DATABASE_URL=...@localhost:5432/...` trước lệnh |
| `connection refused` ở cổng 5432 | PostgreSQL chưa chạy | `docker compose up -d postgres` |
| `make test` báo nhiều test `skipped` | PostgreSQL chưa chạy | Bật PostgreSQL rồi chạy lại |
| `port is already allocated` cho 5432 | Máy đã có PostgreSQL khác dùng cổng 5432 | Tắt PostgreSQL đó, hoặc đổi cổng bên trái trong `docker-compose.yml` (ví dụ `"5433:5432"`) và dùng cổng mới khi kết nối |
| `schema "staging" does not exist` hoặc `relation "staging.stg_ohlcv" does not exist` | Database cũ, tạo trước khi đổi schema | Chạy `docker compose up -d migrate`; nếu bản DB quá cũ thì backup trước khi tái tạo |
| `URLError`, `timed out` khi `make extract` | Mạng chập chờn; mỗi request đã tự thử lại 3 lần | Chạy lại; file đã tải được giữ trong cache |
| Airflow báo `Permission denied` với `data/raw` | `AIRFLOW_UID` khác user id trên máy | Đặt `AIRFLOW_UID` bằng kết quả `id -u`, rồi `make airflow` |
| `.venv/bin/python: No such file or directory` | Chưa tạo môi trường Python | `make setup` |
