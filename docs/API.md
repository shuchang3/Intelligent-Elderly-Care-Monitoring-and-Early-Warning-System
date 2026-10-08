# 接口契约 1.0.0

`openapi.json` 可导入 Apifox，共47个HTTP路径、57个操作，路径由当前Controller导出。接口改动后运行 `scripts/export-openapi.py` 并复核字段。下面补充条件必填、权限及WebSocket语义，不能只看泛化的响应模型。

## 地址、认证、时间

- Java默认8080，本机联调配置8081；Flask默认5000，本机5001。页面只请求同源 `/api/v1/...`，Flask固定转发到 `JAVA_BASE_URL`，不能转发任意URL。
- Java用户接口：`Authorization: Bearer <token>`。算法接口：`X-AI-Key`，不能使用管理员JWT替代算法凭据。算法凭据只对应本单机机构的配置节点。
- Flask浏览器Cookie只存会话ID，JWT在服务端SQLite；修改请求必须有 `X-CSRF-Token`，值由页面meta提供，登录/退出表单使用 `csrf_token`。不要给浏览器持久化JWT。
- Flask对所有受角色限制的页面以及 `/api/camera_frame`、`/api/camera` 每次调用 `/api/v1/auth/me` 核对最新角色；其他普通页面请求最多缓存身份30秒。Java业务接口始终自行校验token、用户状态、角色和数据范围，不能依赖Flask缓存授权。
- 事件时间为Asia/Shanghai的本地时间字符串：`2026-09-01T08:30:00`，不带Z/时区偏移。开始日期转00:00:00，结束日期转23:59:59。
- 所有Java Long业务ID均以字符串返回。`eventNo`为UUID，与数据库 `id` 不同。
- 统一成功响应 `{ "code":200, "message":"success", "data":... }`。客户端同时检查HTTP状态与code。400参数、401登录失效、403无权限、404不存在、409业务冲突/未就绪、413文件超限、503数据库/可选功能不可用；Flask转发超时504。
- `confidence`可空；非空必须0..1且提供 `scoreType`。不把姿态置信分数称作跌倒概率。

## 登录、用户和家属

| 方法/路径 | 请求与权限 |
|---|---|
| POST `/api/v1/auth/login` | JSON username/password；返回token、expiresAt（Unix秒）、user{id,username,realName,role} |
| GET `/api/v1/auth/me` | 实时校验数据库用户状态、role和token_version |
| POST `/api/v1/auth/logout` | 作废该用户已有token，关闭对应WebSocket；随后重新登录 |
| PUT `/api/v1/auth/password` | oldPassword/newPassword，至少12字符；成功后原token作废 |
| GET/POST `/api/v1/users` | 管理员；创建username/password/realName/role |
| PUT `/api/v1/users/{id}` | 管理员；role=ADMIN/STAFF/FAMILY，status=NORMAL/DISABLED；禁止禁用或降级当前管理员 |
| GET/POST/DELETE `/api/v1/family-bindings` | 管理员；POST JSON userId/personCode；DELETE查询参数同名；只能将FAMILY用户绑定有效ELDER档案 |

用户状态或角色变化后旧token不能继续获得原权限；受角色限制的Flask页面和公共画面也会在下一次请求刷新角色。家属列表、事件详情、处理记录、截图、录像、统计、情绪与互动查询均按绑定老人范围过滤。家属不能读取公共摄像头、区域配置、轨迹列表或处理事件。

## 事件闭环

`POST /api/v1/ai/events` 必须multipart/form-data：

| 字段 | 规则 |
|---|---|
| eventNo | 必填UUID，重试不得换号 |
| eventType | FALL / STRANGER / DANGER_ZONE / EMOTION_ABNORMAL |
| cameraCode | 必填，属于当前节点且启用的摄像头编号 |
| eventTime | 必填，约定时间格式 |
| description | 必填，不超过1000字符 |
| personCode | 可空；非空须为有效人员 |
| zoneCode | DANGER_ZONE时必须为该摄像头下启用区域；不能任意选第一条区域 |
| trackId | 可空，摄像头进程实例与trackId共同形成稳定标识 |
| confidence / scoreType | 可空；二者语义必须明确 |
| snapshot | 可空图片文件，最大10MB、最多2000万像素，服务端验证并编码JPEG |

位置从摄像头档案读取。相同eventNo、相同提交内容及截图返回原事件200；内容冲突409。唯一索引防止并发重复。事件、初始录像状态和通知任务在事务内写入，提交后才广播。失败写入不能推送假告警。

```json
{"code":200,"message":"success","data":{"id":"123","eventNo":"83860bfc-d614-428b-a0a9-0f7bc5f64a69","eventType":"FALL","cameraCode":"CAM001","personCode":null,"eventTime":"2026-09-01T08:30:00","description":"人工模拟事件","status":"PENDING","eventLevel":"URGENT","imageUrl":"/api/v1/events/123/snapshot","videoState":"PENDING"}}
```

| 方法/路径 | 说明 |
|---|---|
| GET `/api/v1/events/page` | page从1开始，size为1..100；筛选eventType/status/cameraCode/personCode/startTime/endTime；data={records,total,current,size,pages} |
| GET `/api/v1/events` | 分页接口别名 |
| GET `/api/v1/events/latest` | data为事件对象数组，不是JSON字符串数组 |
| GET `/api/v1/events/{id}` | 单条真实事件，imageUrl为鉴权接口 |
| PUT `/api/v1/events/{id}/status` | 护理人员/管理员；JSON status=PROCESSING/DONE、可选remark；DONE不可退回，重复相同状态不重复新增处理记录 |
| GET `/api/v1/events/{id}/records` | 处理人、前后状态、时间、备注 |
| GET `/api/v1/events/{id}/snapshot` | JPEG；当前用户必须有事件权限 |
| GET `/api/v1/events/{id}/video` | READY时MP4，支持Range/206；未就绪返回409，不返回磁盘路径 |
| GET `/api/v1/statistics/event-count` | total/today/pending/processing/done；按事件发生时间统计 |
| GET `/api/v1/events/statistics` | event-count别名 |
| GET `/api/v1/statistics/type-count` | 类型计数对象数组 |
| GET `/api/v1/statistics/event-trend` | 近7日日期/数量；没有事件的日期可缺项 |

Redis仅可选缓存非家属总计数10秒，事件新增/状态更新提交后切换缓存版本。家属不缓存；列表、详情和其他统计直读MySQL。Redis失败返回数据库结果，健康状态显示DEGRADED，不能因此伪造数据。

## WebSocket

1. 已登录页面经Flask调用 `POST /api/v1/auth/ws-ticket`，获得30秒一次性票据。
2. 原生WebSocket连接 `/ws/events?ticket=...`，Origin必须匹配配置。
3. 不要用 `io()`，不要把长期JWT放在URL。
4. 消息外层统一如下；两种消息的data均是完整事件对象。

```json
{"messageType":"EVENT_CREATED","data":{"id":"123","eventType":"FALL","status":"PENDING"}}
```

另一种为 `EVENT_STATUS_UPDATED`。页面以数据库id去重；重连必须重新查询列表和统计。token到期/禁用/退出后连接关闭，后台周期最多约5秒检查一次，用户管理操作也会主动检查。每次广播重新检查家属范围。

## 人员、人脸、摄像头与区域

- GET/POST `/persons`、PUT/DELETE `/persons/{code}`：管理员修改，护理人员读，家属只读关联老人。personType=ELDER/WORKER/FAMILY是档案类别，与登录role分开。删除为停用保留历史。
- POST `/persons/{code}/face`：multipart file，提交成功仅PENDING。Python确认单张有效脸并生成编码后才ACTIVE；无脸、多脸或编码失败为FAILED；没有照片NONE；删除后确认REMOVED。
- GET/POST `/cameras`、PUT `/cameras/{code}`：管理员配置，护理人员读。cameraCode与captureSource分开，源为设备序号字符串、视频路径或RTSP。config仅允许fallEnabled/strangerEnabled/emotionEnabled/dangerEnabled/soundEnabled/sadSeconds/missingSeconds，错误字段返回400。
- GET/POST `/danger-zones`、PUT/DELETE `/danger-zones/{code}`：摄像头关联，points为3..32个归一化[x,y]顶点，不允许重复、零面积和自交；enterSeconds默认1、exitSeconds默认2；修改/删除递增version。页面只有version=appliedVersion才能说明算法已确认。
- GET `/ai/config`：当前节点摄像头和区域，以及人员版本、启用状态和hasFace。
- GET `/ai/persons/{code}/face`：算法鉴权下载登记照片。
- POST `/ai/ack`：kind=person/camera/zone，code/version；person额外state/error；旧版本409，不能更新新版本生效状态。
- POST `/ai/heartbeat`：cameraCode、status=ONLINE/OFFLINE/ERROR/DISABLED、可选error。超过15秒无心跳时查询返回OFFLINE。

上述短路径均有 `/api/v1` 前缀。算法只有当前节点的摄像头权限，不能混用其他节点配置。

## 采样、轨迹、互动、录像及通知

| 方法/路径（含/api/v1前缀） | 说明 |
|---|---|
| POST `/ai/samples` | kind=emotion/track；共同必填sampleNo(UUID)/cameraCode/sampleTime；emotion需personCode/emotion/score；track需trackId/x/y，personCode可空；分数坐标均0..1；采样号去重 |
| GET `/analytics/emotion` | 按人员、日期、情绪聚合有效采样数和平均分，最多200组；personCode/cameraCode筛选 |
| GET `/analytics/tracks` | 最新500个点，护理人员/管理员；personCode/cameraCode筛选；不是三维定位 |
| POST `/ai/interactions` | recordNo(UUID)/cameraCode/elderCode/workerCode/startTime/endTime，保存CANDIDATE，不自动确认服务有效 |
| GET `/analytics/interactions` | 最近200条、按elderCode做人员筛选，家属范围隔离 |
| PUT `/analytics/interactions/{id}` | 护理人员/管理员；status=CONFIRMED/REJECTED；只有CANDIDATE可复核 |
| POST `/ai/events/{no}/video` | no为eventNo，不是数据库id；multipart state=READY/FAILED；READY必须file(MP4≤64MB)，FAILED可error |
| GET/PUT `/alert-rules` | 管理员；修改eventType/eventLevel并记录日志；默认跌倒URGENT、区域/陌生人WARNING、情绪CARE |
| GET `/operation-logs` | 管理员查询最近100条操作记录 |
| GET `/notifications/public-key` | 未配置VAPID时503，不能显示订阅成功 |
| POST/DELETE `/notifications/subscriptions` | 登记当前用户浏览器订阅；endpoint及keys.p256dh/keys.auth；HTTPS厂商域名白名单；DELETE删除当前用户所有已登记订阅 |
| GET `/notifications/jobs` | 管理员查询最近100条发送状态 |
| GET `/ai/notification-jobs` | 算法服务读取待发送任务，再次校验用户启用状态和家属范围 |
| POST `/ai/notification-jobs/{id}` | state=SENT/RETRY/FAILED、error，保存次数和结果 |

录像环形缓冲约10秒，事件后继续20秒，初启时不足10秒的前段不能凭空补齐。采集固定5fps，前后窗口为工程配置基线；设备掉线、编码失败、队列满都有失败状态。通知及手机部署步骤见 `手机与通知部署.md`。

## 对旧接口的兼容边界

本版使用通用 `/persons`，不是旧 `/elders`；新版 schema.sql 不能直接套到旧库。旧 JWT、Socket.IO、新旧事件消息、旧静态uploads公开URL不兼容。升级应先备份、明确数据字段映射、编写和演练迁移，再由团队执行；本次没有擅自迁移旧业务数据。
