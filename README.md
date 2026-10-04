# Wishclaim · 礼物愿望认领

发布 → 认领锁定（互斥+TTL）→ 核销/释放；已认领愿望可被挑战进入**争议裁决**。

| 服务 | 端口 |
| --- | --- |
| 前端 | 5200 |
| API | 10200 |

```bash
docker compose up --build
pytest backend/app/tests
```

## 争议裁决（dispute）

- **发起**：愿望 `claimed` 时，他人可 `POST /api/wishes/{id}/disputes` 开争议单（原认领人/挑战者/截止时刻）；争议中任何人不得直接认领，第三人不得再开单。
- **预览**：`GET /api/disputes/{id}/preview?winner=X` 给出胜/败结果，不落库、不改 claimer。
- **确认**：`POST /api/disputes/{id}/adjudicate` 经条件更新写锁翻单（重复确认以首次为准），胜者成为唯一 claimer。
- **拍板① · expires_at 重开满额**：确认后胜者认领期 = 裁决时刻 + 完整 `ttl_seconds`，墙卡/详情/规则倒计时同源。
- **拍板② · 截止未裁决自动维持原认领人**：到期扫尾记挑战者败诉（`auto_keep_original`）；争议期间愿望被释放/核销/易主则争议作废（`moot`）。
- **败诉**：败者在「我的认领」留败诉记录，该愿望释放（含 TTL 自动释放）前不得再认领或再争议。
- 无争议单不得变更 claimer。

模块：`dispute_ticket`（争议单+扫尾）/ `dispute_verdict`（裁决写锁）/ `dispute_projection`（墙卡·详情·我的认领投影+禁认判定）。

0-1：`wish_comment` / `secret_santa` / `price_cap`。
