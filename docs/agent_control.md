# Điều khiển agent và tool

Đọc [Tổng quan hiện tại](current_progress.md) trước nếu bạn chưa rõ các service. Các lệnh dưới đây chạy từ **root repo CoinSight**. Desk đã có [@trade, @sre và slash tool](desk_commands.md); trang này hướng dẫn cấu hình/CLI bên dưới. Chưa có màn hình quản trị key/model/quota.

## 1. Chọn đúng bộ service

| Bộ | Cổng localhost | Cần key LLM? | Dùng để làm gì? |
| --- | --- | --- | --- |
| App chính | Web 3000, API 8000 | Chỉ Desk chat cần Bedrock | Xem thị trường/warehouse và chat cũ |
| Tool dự báo | MCP 8010, forecast A2A 8011, MAD A2A 8012 | Không | Gọi model dự báo đã đóng băng |
| Agent phân tích | MCP 8020, Analyst 8021, Operations 8022 | Có, với tool hỏi agent | LLM chọn tool và phối hợp A2A |

**Đổi router tác động @trade/@sre; plain-text Desk vẫn đi Bedrock cũ.** CatBoost và Isolation Forest không nằm trong vòng provider/model LLM.

## 2. Bật, xem log và dừng bộ agent phân tích

```sh
# Build và chạy riêng extension agent.
docker compose --env-file .env -f warehouse_agents/compose.yml up -d --build

# Xem trạng thái.
docker compose --env-file .env -f warehouse_agents/compose.yml ps

# Xem lỗi provider/tool/task đã được rút gọn; không in key.
docker compose --env-file .env -f warehouse_agents/compose.yml logs --tail 80 analyst operations warehouse-mcp

# Dừng riêng extension; app, database và stream vẫn là bộ khác.
docker compose --env-file .env -f warehouse_agents/compose.yml down
```

Mô hình anomaly cần bundle tin cậy ở `data/models/warehouse-anomaly/v1/`. Image agent kế thừa `coinsight-local-agents:0.1.0`; fresh checkout cần chuẩn bị các image/artifact theo hướng dẫn nguồn. Build/start không tự train model.

Bộ forecast riêng dùng `compose.agents.yml`; [hướng dẫn bộ dự báo](local_agents.md) mô tả bundle và cách chạy. Đó là bộ 8010–8012, không phải hai reasoning agent mới.

## 3. Chọn đúng tool

Kết nối MCP client với `http://localhost:8020/mcp` (Streamable HTTP):

| Tool | Ví dụ yêu cầu / input | Kết quả |
| --- | --- | --- |
| `market_anomaly` | Không truyền cutoff để lấy giờ đã đóng mới nhất | Isolation Forest score, threshold/flag, MAD và snapshot hash |
| `model_health` | Không truyền cutoff hoặc cùng cutoff với anomaly | Feature PSI, watch flags và giới hạn metric |
| `ask_analyst` | `question`: “Dự báo BTC giờ và kiểm tra dữ liệu bất thường”; `symbol`: `BTC` | Câu trả lời, evidence, routing, token usage, task ID |
| `ask_operations` | `question`: “Kiểm coverage BTC 24 giờ và mart parity”; `symbol`: `BTC` | Tool DB/Airflow được chọn, bằng chứng và kết luận |

Anomaly/drift trực tiếp không gọi LLM. `ask_analyst`/`ask_operations` có thể phát sinh phí provider. Không cần chạy liên tục 30 ngày; service xử lý theo request, không tự bật lịch retrain hay giao dịch.

Mỗi kết quả `routing` cho biết provider/model đã chọn và các lần chuyển dự phòng; `evidence` ghi tool nào được gọi. Task A2A của Analyst và Operations có ID riêng. Thông tin này hiện nằm trong kết quả MCP/A2A, **được hiển thị trong Command details của Desk với @agent hoặc slash tool**.

## 4. Metric có nghĩa gì?

- **Predicted log return:** đầu ra forecast; không phải xác suất đúng. Relative MAE so với zero-return mới là thước so sánh lỗi.
- **Anomaly flag:** nến khác thường so với phân bố đã học; không có nghĩa giá chắc chắn giảm hoặc dữ liệu bị hỏng.
- **PSI watch:** phân bố feature thay đổi; không chứng minh model mất accuracy và không thay được MAE trên nhãn tương lai.
- **Coverage / lineage / mart parity:** kiểm vận hành warehouse. Dữ liệu OHLC hợp lệ vẫn có thể thiếu giờ, thiếu nguồn hoặc mart chưa refresh.
- **`/health` xanh:** process chạy; không chứng minh mọi dependency truy cập được hoặc dữ liệu đủ mới.

## 5. Giới hạn vận hành đang có

Hai agent dùng LangGraph, tối đa bốn lượt LLM mỗi investigation, hai investigation đồng thời/service và deadline có giới hạn. Chỉ gọi tool nằm trong danh sách, schema được kiểm trước khi thực thi. Không có shell hay SQL tùy ý do LLM tạo; SQL dùng truy vấn cố định, tham số hóa và transaction chỉ đọc.

Task ở RAM, tối đa 256 task, TTL một giờ; restart mất task. Cần lưu kết quả riêng nếu muốn audit lâu dài. Không có chức năng tự retry một nghiệp vụ, restart DAG, sửa DB, train lại hoặc đặt lệnh mua bán.

Container chỉ bind localhost, chạy nonroot, filesystem/model mount chỉ đọc, giới hạn CPU/RAM/log. `WAREHOUSE_AGENT_TOKEN` bật bearer auth cho extension nếu được cấu hình. Đây chưa phải thiết kế phân quyền nhiều người dùng hay dịch vụ public.

## 6. Kiểm chứng sau khi đổi cấu hình

```sh
# Môi trường kiểm chứng local đã có trên máy này.
data/models/warehouse-agent-runtime/venv/bin/python -m warehouse_agents.check_runtime
```

Lệnh dùng provider thật và lưu proof tại `data/models/warehouse-agent-validation/live_acceptance.json`. Nó kiểm MCP, anomaly/drift, cutoff tương lai và luồng Analyst → Operations. Warehouse/Airflow có thể trả unavailable một cách hợp lệ; checker pass không có nghĩa toàn bộ warehouse đã được audit.

Nếu chỉ kiểm tool không muốn gọi LLM:

```sh
data/models/warehouse-agent-runtime/venv/bin/python -m warehouse_agents.check_runtime --market-only
```

Mode này ghi rõ đã bỏ qua LLM; không được báo như nghiệm thu toàn luồng.

## 7. Khi có lỗi

| Dấu hiệu | Đọc thế nào / xử lý |
| --- | --- |
| 429 provider | Bị giới hạn; router bỏ qua route đang cooldown và thử route khác. Đọc [router](model_router.md). |
| 401/403 | Kiểm key/quyền; đổi `.env` rồi recreate container. |
| 503 provider | Provider/model không phục vụ request lúc đó; kiểm fallback thực tế, không mặc định là hết tiền. |
| `RouterUnavailable` | Không route nào hoàn thành trước deadline; đọc sanitized attempts trong log. |
| Ops warehouse unavailable | Kiểm URL, network, schema/migration và quyền SELECT; không diễn giải là warehouse khỏe. |
| Airflow unavailable | Tool dùng Airflow 3 `/api/v2`, cần endpoint/token hợp lệ. |
| Forecast unavailable | Kiểm service 8011 và nguồn nến đóng; không thay bằng dự báo giả. |

Không dán key hoặc toàn bộ output `docker inspect`/`compose config` vào chat: chúng có thể chứa credential.
