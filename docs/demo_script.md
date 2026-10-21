# Kịch bản demo

Dùng kịch bản này để trình diễn luồng end-to-end. Chạy lệnh từ thư mục gốc repo.

## 1. Khởi động hệ thống local

```bash
cp .env.example .env  # chỉ lần đầu; không ghi đè .env đã có
docker compose up --build -d
docker compose ps --all
```

Mở:

- Dashboard: <http://localhost:3000>
- Tài liệu: <http://localhost:3000/docs/>
- API docs: <http://localhost:8000/docs>
- Kafka UI: <http://localhost:8080>
- Jaeger: <http://localhost:16686>

## 2. Kiểm tra API

```bash
curl -s http://localhost:8000/health
curl -s http://localhost:8000/v1/data-status
```

## 3. Nạp một ngày đã đóng

Chọn ngày UTC đã được Binance công bố archive.

```bash
make extract-daily DAY=2026-10-04
make batch
curl -s http://localhost:8000/v1/data-status
```

Giải thích các bước khi demo:

1. Tải archive hoặc dùng bản đã cache.
2. COPY các dòng vào staging.
3. Chạy kiểm tra chất lượng.
4. Nạp fact và refresh mart.
5. API trả trạng thái lần nạp.

Muốn demo nhỏ chỉ BTC, xem [Kiểm chứng kho dữ liệu](warehouse_proof.md).
Trang đó có báo cáo số dòng, nến thiếu/trùng, kiểm chứng nạp lại và truy checksum.

## 4. Xem PostgreSQL

Kết nối local mặc định:

```text
host: localhost
port: 5432
database: crypto_dw
user: crypto
password: crypto
```

Truy vấn mẫu:

```sql
select a.symbol, count(*) as candles, min(f.open_time) as first_open, max(f.open_time) as last_open
from dw.fact_ohlcv_hourly f
join dw.dim_asset a on a.asset_key = f.asset_key
group by a.symbol
order by a.symbol;
```

## 5. Bật và trình diễn biểu đồ live

Biểu đồ cần service live chạy và ít nhất hai nến phút đã đóng được Spark ghi vào DB.
Danh sách live được cấu hình cùng danh sách batch trong `pipeline/settings.yaml`.

```bash
docker compose up --build -d kafka kafka-ui live-producer spark api frontend
docker compose logs --tail=100 live-producer spark
curl -s http://localhost:8000/v1/assets/BTC/live-summary
```

Kiểm tra DB nếu cần:

```sql
select symbol, open_time, close_price, volume_quote
from dw.fact_candle_minute_live
where symbol = 'BTC'
order by open_time desc
limit 10;
```

Mở <http://localhost:3000> và lần lượt chỉ:

1. Danh sách coin.
2. Trạng thái live và thời điểm nến mới nhất.
3. Biểu đồ nến 1 phút riêng; rê chuột để xem OHLC/volume.
4. Biểu đồ giá đóng ngày trong lịch sử.
5. Operations → Warehouse proof: số dòng và độ phủ.
6. Liên kết trang tài liệu.

Live chỉ dùng xem trạng thái thị trường hiện tại, không phải chart phân tích lịch sử
hay dự báo. Nếu vừa khởi động/thêm coin và chart rỗng, đợi có ít nhất hai nến phút đóng.

Nếu UI hiện **“Model below baseline. Signal withheld.”**, giải thích rằng mô hình ngày
bị từ chối vì không vượt phương pháp đối chiếu; hệ thống không công bố tín hiệu chưa
được chấp nhận. Trạng thái này độc lập với luồng live.

## 6. Trình diễn tài liệu

Mở <http://localhost:3000/docs/>.

Các trang nên xem:

1. Luồng dữ liệu.
2. Chạy và kiểm tra hệ thống.
3. Schema & phép tổng hợp.
4. Kiểm chứng kho dữ liệu.
5. Tiến độ và việc còn thiếu.
6. Lộ trình hoàn thiện.

## 7. Chạy kiểm thử

Frontend:

```bash
npm --prefix frontend test
npm --prefix frontend run build
```

Python — dùng URL PostgreSQL local để test warehouse không bị skip vì sai hostname:

```bash
DATABASE_URL=postgresql://crypto:crypto@localhost:5432/crypto_dw \
  uv run --python 3.12 --with pytest --with httpx \
  --with-requirements pipeline/requirements.txt \
  --with-requirements app/requirements.txt \
  python -m pytest -q
```

Nếu đã đổi credentials trong `.env`, thay URL bằng cấu hình của bạn.

## 8. Những giới hạn phải nói rõ

- CoinSight là bản nghiên cứu, không phải sản phẩm giao dịch.
- Dữ liệu lịch sử phục vụ kiểm chứng luồng warehouse.
- Nến live 1 phút cho biết trạng thái feed/thị trường hiện tại.
- Dự đoán hướng ngày là thử nghiệm và có thể bị từ chối.
- Dự báo giờ đã có giao ước nhưng chưa triển khai đầy đủ.
- Báo cáo không có nến thiếu chỉ đúng trong khoảng đã quan sát.
- Fact cũ trước migration có thể chưa có truy vết tới đúng archive/checksum.
