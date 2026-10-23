# CI/CD & rollback

Trang này giải thích cách một thay đổi đi từ Git tới deployment. Cài máy chủ theo [home server](home_server.md); cấu hình Google/GitHub theo [đăng nhập](auth_setup.md). Không chép lại các bước đó tại đây.

## CI kiểm gì?

`.github/workflows/ci.yml` tách môi trường dependency:

| Job | Phạm vi |
| --- | --- |
| `test` | API, pipeline và tests dùng PostgreSQL; admin queries có database riêng |
| `warehouse-agents-test` | Agent/eval tests và replay cassette, không cần provider key |
| `agents-test` | Frozen prediction/anomaly serving và Compose contract |
| `images` | Build core images, frontend tests, HTTP và WebSocket smoke |
| `publish` | Push image SHA/`latest` tới GHCR khi main pass các dependency được khai báo |

Xem workflow để biết dependency chính xác. Một job xanh không thay thế việc kiểm cả commit và live acceptance; replay đo regression của các response đã ghi, không đo provider hiện tại.

## Hai đường deploy

**Docs:** `.github/workflows/deploy-docs.yml` build static docs và deploy Cloudflare Worker khi main thay đổi đúng paths. `/docs` độc lập với API/home server. Thay file trên laptop chưa tự cập nhật site public; cần đi qua workflow hoặc lệnh deploy docs đã cấu hình.

**Application:** server chạy `deploy/home/deploy.sh` định kỳ. Script fetch main, kiểm check-runs qua GitHub API công khai (`curl` + `jq`, không cần token), chỉ fast-forward và build khi các check đã hoàn tất thành công. Repo công khai, nên không GitHub runner nào được truy cập máy nhà bạn.

```text
merge PR ─► GitHub Actions: ci.yml (test, replay eval, build image)
                            deploy-docs.yml (nếu đổi docs) ─► Worker /docs
server cron mỗi 5 phút: deploy/home/deploy.sh
  main đổi? ─ không ─► thoát
  CI của commit đó xong và xanh? ─ chưa ─► ghi "skip", thoát
  git merge --ff-only ─► docker compose up -d --build ─► health check ─► ghi "deployed <sha>"
```

Bật cron trên server (PATH cần có docker, git, curl, jq):

```bash
*/5 * * * * cd $HOME/coinsight && PATH=/usr/local/bin:/usr/bin:/bin deploy/home/deploy.sh >> data/deploy.log 2>&1
```

`tail -f data/deploy.log` cho thấy từng quyết định (`skip … CI pending`, `deploying …`, `deployed …`).

Docs tự deploy cần hai secret của repo: token Cloudflare (My Profile → API Tokens → Custom: Account › Workers
Scripts › Edit, Zone › Workers Routes › Edit, zone `kaiosthefox.dpdns.org`) và Account ID (`npx wrangler whoami`):

```bash
gh secret set CLOUDFLARE_API_TOKEN
gh secret set CLOUDFLARE_ACCOUNT_ID
```

`deploy/home/deploy.sh --force` bỏ kiểm main/CI cho lượt đó và deploy checkout hiện tại. Dùng khi đã chủ động chọn đúng branch/commit; đây không phải lệnh merge PR.

## Khi deployment thay đổi database

Core Compose chạy service `migrate` trước API. Các migration nằm ở `postgres/migrations/`; init scripts không phải cách cập nhật một database đã có dữ liệu. Trước đổi schema trên server đang dùng, giữ backup và biết version image/code tương ứng. Không xóa Docker volumes để chữa migration.

Sau deploy, kiểm `/ready`, data freshness, agent gateway, sign-in/owner permissions và ledger theo [home-server verification](home_server.md#kiểm-tra). HTTP 200 của frontend không xác nhận toàn hệ thống khỏe.

## Rollback

Revert commit trên main để đi lại quy trình CI/CD, hoặc chọn commit đã biết tốt trên server rồi dùng `--force`. Rollback code không tự đảo migration; phải kiểm compatibility hoặc dùng kế hoạch restore đã chuẩn bị. Giữ Tunnel/Access hoạt động trong lúc điều tra; không mở public API để bỏ qua lỗi sign-in.
