# Kiểm chứng kho dữ liệu

Giai đoạn 1 kiểm chứng luồng chính: Binance ZIP → staging → kiểm tra chất lượng → warehouse/mart → API → giao diện Operations.

## 1. Cài cấu trúc lưu bằng chứng

```bash
docker compose up -d postgres
# Áp dụng các migration, bao gồm 005_warehouse_proof.sql.
docker compose run --rm migrate
docker compose up -d --build api frontend
```

Mở **Operations → Warehouse proof**. Có thể xem báo cáo trực tiếp qua API:

```bash
curl -s http://localhost:8000/v1/warehouse/proof
# Xem một lần nạp cụ thể thay vì lần mới nhất:
curl -s 'http://localhost:8000/v1/warehouse/proof?batch_id=42'
curl -s http://localhost:8000/v1/warehouse/lineage/BTC
```

## 2. Nạp thử một ngày đã được công bố

Chọn ngày UTC đã đóng và Binance đã công bố archive. Chỉ dùng BTC để demo nhỏ gọn.

```bash
make setup
DATABASE_URL=postgresql://crypto:crypto@localhost:5432/crypto_dw RAW_DIR=data/raw \
  .venv/bin/python -m pipeline.batch.ingest_binance_history \
  --symbols BTC --intervals 1h,1d --day 2026-10-04
make batch
```

Báo cáo lưu theo lần nạp, nguồn, coin và độ dài nến:

| Trường | Ý nghĩa |
| --- | --- |
| `staging_rows` — Staged | Tổng dòng đầu vào trước khi kiểm tra |
| `rejected_rows` — Rejected | Dòng vi phạm ít nhất một quy tắc; mỗi dòng chỉ tính một lần |
| `duplicate_rows` — Duplicates | Các bản sao hợp lệ bị loại vì trùng khóa nến |
| `accepted_rows` — Accepted | Số nến hợp lệ, không trùng, đủ điều kiện nạp |
| `changed_rows` — Changed | Số fact thực sự được thêm mới hoặc cập nhật |

Công thức đối chiếu: **staged = rejected + duplicates + accepted**.

Ví dụ: đọc 26 dòng, có 1 dòng lỗi và 1 bản sao trùng thì còn 24 nến được chấp nhận.
Nếu cả 24 nến đã có trong kho với cùng số liệu thì `changed = 0`, không phải 24.
Lần nạp vẫn có bản ghi audit mới. Báo cáo không mất khi staging được dọn.
Các lần nạp trước khi có tính năng này chưa có báo cáo chi tiết theo coin.

## 3. Báo cáo nến thiếu và trùng

```sql
select symbol, source_code, candle_interval, first_open, last_open,
       fact_rows, expected_candles, missing_candles, duplicate_rows
from meta.v_warehouse_coverage
order by symbol, candle_interval, source_code;

select batch_id, source_code, symbol, candle_interval,
       staging_rows, rejected_rows, duplicate_rows, accepted_rows, changed_rows
from meta.warehouse_load_report
where batch_id = (select max(batch_id) from meta.etl_batch where pipeline = 'batch_etl')
order by symbol, candle_interval;
```

Độ phủ được tính **chỉ trong khoảng từ nến đầu tới nến cuối đã quan sát**, riêng cho
mỗi nguồn. Không chứng minh đã nạp đủ toàn bộ khoảng lịch sử yêu cầu, hoặc không thiếu
ở trước/sau khoảng đang có. Một khoảng chỉ có một nến thì số nến kỳ vọng là 1.
Khóa chính của fact ngăn trùng trong warehouse; bản sao trùng ở staging được lưu riêng
trong báo cáo lần nạp.

## 4. Kiểm chứng nạp lại không làm thay đổi kho

Tính chất này gọi là **idempotency**: nạp lại cùng dữ liệu không tạo fact trùng hoặc
viết lại fact không thay đổi.

Dùng database demo/thử nghiệm đã áp dụng migration, không có loader lịch sử khác
chạy đồng thời. Lệnh dưới thực sự staging/load hai lần, không xóa staging của batch
khác. Sau lần đầu, script tính SHA-256 trên toàn bộ dòng fact ngày/giờ, bao gồm giá,
thời gian nạp và metadata truy vết. Sau lần thứ hai, script so lại dấu vân tay đó.

```bash
DATABASE_URL=postgresql://crypto:crypto@localhost:5432/crypto_dw \
  .venv/bin/python -m scripts.prove_archive_reload \
  data/raw/binance/BTCUSDT/1h/BTCUSDT-1h-2026-10-04.zip --symbol BTC --interval 1h
```

Tìm đường dẫn ZIP thật bằng `find data/raw -name '*.zip'`.
Kết quả mong đợi: `result: PASS`, `reload.rows_loaded: 0`, dấu vân tay trước/sau giống nhau.
Downloader có thể bỏ qua checksum đã nạp; script này cố tình nạp lại ZIP trong cache
để kiểm loader, không phải chỉ kiểm việc downloader bỏ qua file.

Chạy kiểm thử tích hợp, bao gồm nến thiếu và checksum chính xác:

```bash
DATABASE_URL=postgresql://crypto:crypto@localhost:5432/crypto_dw \
  uv run --python 3.12 --with pytest --with httpx \
  --with-requirements pipeline/requirements.txt --with-requirements app/requirements.txt \
  python -m pytest tests/batch/test_warehouse_loader.py -q
```

Các test tạo database PostgreSQL tạm và xóa khi kết thúc. Cần chạy **không có test bị
skip** mới được coi là bằng chứng kiểm chứng warehouse.

## 5. Truy từ fact tới đúng archive và SHA-256

```sql
select symbol, candle_interval, open_time, close_price, batch_id,
       extract_batch_id, source_file, sha256, source_url
from meta.v_fact_archive_lineage
where symbol = 'BTC'
order by open_time desc, candle_interval
limit 20;
```

Fact mới hoặc có số liệu thay đổi lưu đúng extraction batch và tên file staging đã
cung cấp nó. View nối cặp này với manifest để lấy checksum.
Fact không thay đổi giữ nguyên lineage cũ; báo cáo lần nạp mới vẫn ghi rằng nó được
chấp nhận nhưng không viết lại.

Fact trước migration có thể có filename/checksum `null`: không đoán archive từ một
batch chứa nhiều file. Khi số liệu được sửa, lineage chuyển sang extraction cung cấp
bản sửa. Đây là truy vết của dòng hiện tại, chưa phải lịch sử mọi phiên bản sửa đổi.

## 6. Cách triển khai trong mã nguồn

### 6.1. Lưu báo cáo trước khi dọn staging

`pipeline/batch/quality_checks.py` đã có hai bảng tạm:

- `stg_passed`: dòng vượt các quy tắc kiểm tra, có thể còn trùng.
- `stg_valid`: dòng hợp lệ sau loại trùng theo nguồn/coin/interval/thời điểm mở nến.

`pipeline/batch/warehouse_loader.py` đếm từ staging, `stg_passed` và `stg_valid`, rồi
lưu vào **`meta.warehouse_load_report`**. Vì là bảng PostgreSQL thật, báo cáo vẫn còn
sau khi loader xóa staging của extraction đã xử lý. Nếu batch bị từ chối do quá nhiều
lỗi, báo cáo kiểm tra vẫn được giữ; phần thay đổi fact chưa được commit.

### 6.2. Đếm fact thực sự thay đổi bằng PostgreSQL

Loader dùng `INSERT ... ON CONFLICT ... DO UPDATE`, nhưng chỉ cập nhật khi bộ số liệu
OHLC/volume/trade count khác bản đang có (`IS DISTINCT FROM`).

Đã thêm `RETURNING asset_key, source_key`: PostgreSQL trả đúng các dòng được insert
hoặc update. Python nhóm kết quả theo asset/source và ghi `changed_rows` vào báo cáo.
Không lấy số dòng đầu vào làm số dòng đã thay đổi.

### 6.3. Tính số nến thiếu bằng view

Migration `postgres/migrations/005_warehouse_proof.sql` tạo view
**`meta.v_warehouse_coverage`**, đọc cả fact ngày và fact giờ.

```text
số nến kỳ vọng = (thời điểm cuối − thời điểm đầu) / độ dài nến + 1
số nến thiếu   = số nến kỳ vọng − số thời điểm mở nến khác nhau
số nến trùng   = tổng số dòng − số thời điểm mở nến khác nhau
```

Ví dụ có nến giờ 00:00 và 02:00: kỳ vọng 3, thực tế 2 → thiếu 1 nến.
View không sinh nến giả để lấp chỗ trống và chưa liệt kê từng vị trí thiếu.

### 6.4. Gắn nguồn chính xác vào fact

Hai bảng fact ngày/giờ được thêm `source_file` và `extract_batch_id`.
Khi ghi fact, loader lấy hai giá trị từ **chính dòng `stg_valid` được chọn**, không
lấy một file bất kỳ trong batch. View **`meta.v_fact_archive_lineage`** nối hai giá trị
đó với `meta.source_file_manifest` để lấy SHA-256 và URL.

SHA-256 trong manifest là dấu vân tay của **file ZIP**. SHA-256 trong script reload
là dấu vân tay của **các dòng fact**. Chúng chứng minh hai việc khác nhau, không so hai
loại hash này với nhau.

### 6.5. Đưa bằng chứng lên giao diện

`app/api.py` cung cấp `/v1/warehouse/proof` và `/v1/warehouse/lineage/{symbol}`.
`frontend/src/WarehouseProof.jsx` đọc API và hiển thị bảng trong Operations.
Frontend không tự tính số nến thiếu hay số dòng thay đổi; nguồn báo cáo là database.

### 6.6. Bằng chứng đã chạy

- Kiểm thử tích hợp nạp ZIP tổng hợp có nến 00:00 và 02:00: phát hiện thiếu 1 nến.
- Nạp ZIP đó hai lần: lần hai thay đổi 0 fact, giữ nguyên dòng và metadata.
- So checksum truy từ fact với SHA-256 thực của ZIP.
- Nạp lại ZIP BTC giờ `BTCUSDT-1h-2026-09-12.zip` trên kho local: 24 dòng được chấp
  nhận, lần hai thay đổi 0 fact, dấu vân tay của 21.700 fact ngày/giờ giữ nguyên.
- Tập kiểm tra Python: 55 test pass với PostgreSQL, không skip; frontend: 11 test pass.
