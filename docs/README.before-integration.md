# 视界无疆 — AI 智慧养老监控预警系统

> 面向养老院 / 社区养老场景的 **AI 视频监控预警** 全栈 Web 应用：用摄像头 + AI 算法实时识别老人异常，并推送到管理后台。

---

## 目录

1. [这个项目是干什么的](#一这个项目是干什么的)
2. [重要澄清：这是全栈应用，不是纯前端](#二重要澄清这是全栈应用不是纯前端)
3. [技术栈](#三技术栈)
4. [运行流程（数据怎么流转）](#四运行流程数据怎么流转)
5. [目录结构详解（每个文件负责什么）](#五目录结构详解每个文件负责什么)
6. [前端 vs 后端：怎么区分](#六前端-vs-后端怎么区分)
7. [如何安装运行](#七如何安装运行)
8. [当前状态与限制（诚实说明）](#八当前状态与限制诚实说明)

---

## 一、这个项目是干什么的

这是一个 **智慧养老** 场景的 **AI 实时监控预警系统**。核心是：对着老人的摄像头画面，AI 在后台持续做三类检测，一旦发现异常立刻告警推送给管理员/家属：

| 检测能力 | 用的算法 | 作用 |
|---|---|---|
| 🚨 **摔倒检测** | YOLOv8-pose 人体姿态 + 时序状态机 | 识别"快速下坠 + 躺倒"过程，判定摔倒并保存告警截图 |
| 👤 **陌生人识别** | face_recognition / dlib 人脸库比对 | 画面里出现不在 `known_faces` 人脸库里的人 → 陌生人闯入告警 |
| 😢 **情绪分析** | DeepFace + TensorFlow | 识别老人表情是 happy / sad / neutral 等，持续悲伤触发预警 |
| ⚠️ **危险区域** | 预留 | 配置画面上某个区域，有人闯入即告警（页面已有，接口未接） |

检测到的异常通过 **WebSocket** 实时推到页面右侧告警栏，并弹 **浏览器通知**。

系统分两个角色：
- **管理员**（admin）：总看板、实时监控、告警管理、人脸库、报表、系统配置
- **家属**（family）：老人首页 + 告警记录（目前是占位页面）

> 一句话：**养老院的"AI 哨兵"，盯摄像头画面，老人摔倒/陌生人/情绪异常马上报警。**

---

## 二、重要澄清：这是全栈应用，不是纯前端

这是最常见的误解，务必看清楚 —— **前端只占项目的一小部分**：

```
┌─────────────────────────────────────────────────┐
│  前端（展示层）                                    │
│  templates/   = 页面长什么样（HTML 模板）           │
│  static/js/   = 页面怎么交互（JS）                 │
│  static/css/  = 页面怎么美化（样式）               │
├─────────────────────────────────────────────────┤
│  后端（真正的核心）                                 │
│  app.py             = 服务器入口：路由/登录/API      │
│  algorithm/         = AI 算法：直接开摄像头、跑模型  │
│  configs/           = 算法参数配置                  │
└─────────────────────────────────────────────────┘
```

关键点：
- **摄像头是后端打开的**（`cv2.VideoCapture`），画面在**后端 Python 进程**里跑 YOLO/人脸/情绪，画好检测框后编码成 base64，前端再显示。
- **前端只是"显示器"**。即使把 `templates/` 和 `static/` 全删了，AI 检测照常在后台跑（只是没人看）。
- AI 模型（YOLO、dlib、DeepFace）全在 `.venv` 虚拟环境里，属于后端依赖。

---

## 三、技术栈

| 层 | 技术 |
|---|---|
| 后端框架 | **Flask 3.1** + **Flask-SocketIO**（threading 模式） |
| 人体姿态/摔倒 | **Ultralytics YOLOv8n-pose**（`yolov8n-pose.pt`） |
| 人脸识别 | **face_recognition** + **dlib**（known_faces 照片库比对） |
| 情绪识别 | **DeepFace** + **TensorFlow / Keras**（mtcnn 人脸检测后端） |
| 图像处理 | **OpenCV**（读摄像头、画框、编码） |
| 前端 | Jinja2 模板 + **Bootstrap 5** + **ECharts** + socket.io（CDN 引入） |
| 数据库 | ❌ **无**（当前无数据库，见"当前状态与限制"） |

---

## 四、运行流程（数据怎么流转）

```
启动 app.py
   │
   ├─ Flask 开始监听 http://0.0.0.0:5000
   └─ 同时启动「融合检测线程」（yolo_fall_cam.camera_main_loop）
        │
        │  循环每一帧：
        │  ① 摄像头读帧（OpenCV，DSHOW 后端）
        │  ② YOLO 姿态 → fall_detector 状态机 → 摔倒判定
        │  ③ 人脸比对 → 陌生人判定
        │  ④ 脸上小图 → DeepFace → 情绪判定
        │  ⑤ 把检测框画到帧上，编码成 base64 存到全局变量
        │  ⑥ 有异常 → socketio.emit("new_alert") 推送前端
        │
        ▼
浏览器（管理员登录后）
   ├─ 打开 /monitor/live：前端 JS 每 300ms 轮询 /api/camera_frame
   │     拿到 base64 帧 → 画到 canvas（cam001 显示真实画面）
   └─ 页面右侧告警栏：socket 收到 new_alert → 插入告警卡片 + 浏览器通知
```

---

## 五、目录结构详解（每个文件负责什么）

### 根目录
| 文件/目录 | 职责 |
|---|---|
| **app.py** | **Flask 入口**。定义全部路由（登录、看板、监控、告警、人脸库、报表、配置）、登录会话、2 个帧接口（`/api/camera_frame`、`/api/camera`）。`__main__` 里启动算法线程 + 服务器 |
| **yolov8n-pose.pt** | YOLOv8 人体姿态模型权重（检测 17 个骨骼关键点） |
| **known_faces/** | 人脸库。每个文件是一张带人名的照片（如 `李爱华.jpg`），算法用它比对陌生人 |
| **uploads/alert_img/** | 摔倒告警截图保存目录（算法把摔倒瞬间的帧存成 jpg） |
| **configs/** | 算法配置文件 |
| **.venv/** | Python 3.13 虚拟环境，**所有依赖都在这里**（启动必须用它） |
| **.gitignore / .idea / .vscode** | 开发配置，与运行无关 |

### `algorithm/` — AI 算法层（核心）
| 文件 | 职责 |
|---|---|
| **yolo_fall_cam.py** | **实际运行的融合检测主循环**。读摄像头 → 摔倒检测 → 人脸+陌生人 → 情绪 → 画框 → 存帧 → 发告警。`start_detect()` / `get_frame()` 被 app.py 调用 |
| **fall_detector.py** | 摔倒**时序状态机**。根据髋部下坠速度 + 身体躺倒姿态（宽高比/躯干倾角），在 NORMAL → FALLING → DOWN → ALERTED 状态间迁移，过滤误报 |
| **pose_utils.py** | YOLO 姿态结果转成项目数据结构：提取 17 个 COCO 关键点、ROI 区域裁剪、多个人时选最大框 |
| **face_emotion_detect.py** | 独立的"人脸+情绪"检测模块（可单独运行）。yolo_fall_cam 复用了它的**人脸库加载**逻辑。它的摄像头循环在 app 里不跑（避免抢摄像头） |

### `configs/fall_detection.yaml` — 算法参数
模型路径、置信度阈值、ROI 区域（可裁剪只检测某区域）、摔倒判定阈值（下坠速度、角度、时间窗口）等。

### `templates/` — 前端页面（Jinja2 模板）
| 文件 | 页面 | 说明 |
|---|---|---|
| **base.html** | 后台母版 | 左侧导航 + 顶栏 + 右侧实时告警栏，所有后台页继承它 |
| **login.html** | 登录页 | 账号/密码/角色（管理员 or 家属） |
| **dashboard.html** | 总监控看板 | 4 个统计卡 + 3 个 ECharts 图表 + 快捷入口（**数据是演示值**） |
| **monitor/live_camera.html** | 实时监控 | 4 路摄像头画布，cam001 接真实 AI 画面，其余占位 |
| **alert/real_alert.html** | 实时告警 | 收 WebSocket 告警的列表页 |
| **alert/alert_history.html** | 历史告警 | 按类型/摄像头/日期筛选 + 导出（当前无数据源） |
| **person/list.html** | 人脸库列表 | 已录入人员展示 |
| **person/face_upload.html** | 人脸录入 | 上传照片 + 姓名，调用 `/api/person/save` 存库 |
| **emotion/emotion_stat.html** | 情感趋势报表 | 老人情感趋势分析（演示数据） |
| **emotion/interaction_stat.html** | 义工互动统计 | 服务时长分析（演示数据） |
| **setting/danger_zone.html** | 系统配置 | 危险区 + 告警灵敏度阈值滑块 |

### `static/` — 前端静态资源
| 文件 | 职责 |
|---|---|
| **js/video_render.js** | **实时画面渲染**：轮询 `/api/camera_frame`，把检测帧画到 canvas，处理"等待画面/未接入/连接失败"状态 |
| **js/socket_base.js** | **告警推送接收**：监听 socketio `new_alert`，插入告警卡片 + 申请浏览器通知 |
| **js/login.js** | 登录表单前端校验（非空、角色必选） |
| **css/global.css** | 全局样式（登录页、后台布局、告警卡片） |

---

## 六、前端 vs 后端：怎么区分

| | 前端 | 后端 |
|---|---|---|
| 目录 | `templates/`、`static/` | `app.py`、`algorithm/`、`configs/` |
| 运行在哪 | 用户浏览器 | 服务器 Python 进程 |
| 干什么 | 显示页面、发起请求、收 WebSocket | 开摄像头、跑 AI 模型、存数据、出 API |
| 被谁调用 | 浏览器直接加载 | 启动时 `python app.py` 加载 |
| 删了会怎样 | 页面打不开，但 AI 检测照常跑 | 整个系统瘫痪 |

**这个项目 ≈ 前端占 25%，后端占 75%。** 后端是核心。

---

## 七、如何安装运行

```powershell
cd D:\IJ\shijie-wujiang-master\shijie-wujiang-master
.\.venv\Scripts\python.exe app.py
```

> ⚠️ 必须用 `.venv\Scripts\python.exe`（虚拟环境），系统基础 Python（`C:\...\Python313\python.exe`）没装依赖。

看到 `Running on http://127.0.0.1:5000` 后，浏览器打开：

- **http://localhost:5000** （会自动跳到登录页）
- 管理员：`admin / 123456`
- 家属：`family / 123456`

### 登录后的入口
| 功能 | 地址 |
|---|---|
| 总监控看板 | `/dashboard` |
| **实时监控（真实 AI 画面）** | `/monitor/live` |
| 实时告警 | `/alert/real` |
| 人脸库 | `/person/list`、`/person/upload` |
| 系统配置 | `/setting/danger` |

### 环境还原（团队 / 换机器时）
```powershell
git clone <仓库地址>
cd shijie-wujiang-master
python -m venv .venv                                 # 创建虚拟环境（Python 3.13）
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

`.venv` 不入库（见 `.gitignore`），团队成员按这份 `requirements.txt` 还原依赖即可。

**本项目的 4 个特殊依赖坑**（版本号已锁进 requirements.txt，这里解释"为什么"）：
| 包 | 为什么特殊 |
|---|---|
| `setuptools==80.10.2` | 必须 **<81**，否则 ultralytics 的依赖解析会报错 |
| `dlib-bin` | 必须用 `dlib-bin`（官方预编译 wheel，含 Windows cp313）。直接 `pip install dlib` 会走源码编译，几乎必然失败 |
| `tf-keras` | TensorFlow 2.21 的 Keras 兼容层，DeepFace 依赖它 |
| `torch`（CPU 版） | 本项目是 **CPU 版 torch**（无 CUDA）。若按默认源安装会拉到 CUDA 版（好几个 GB）。要装 CPU 版：`pip install torch==2.13.0 torchvision==0.28.0 --index-url https://download.pytorch.org/whl/cpu` |

**DeepFace 权重**：首次情绪识别时 DeepFace 会联网下载模型权重到 `~/.deepface/weights/`。若网络受限，可手动把 `facial_expression_model_weights.h5` 放进该目录（本机已缓存，运行时不联网）。

---

## 八、当前状态与限制（诚实说明）

**已实现（真跑的）：**
- ✅ 全部页面可访问、登录会话正常
- ✅ YOLO 摔倒检测（真实算法，状态机判断）
- ✅ 陌生人识别（对比 `known_faces/李爱华.jpg`）
- ✅ DeepFace 情绪识别（mtcnn 后端 + 权重已缓存）
- ✅ 实时画面已接到前端 `/monitor/live`（cam001）
- ✅ 告警 WebSocket 推送框架

**限制 / 未完成（重要）：**
| 项 | 说明 |
|---|---|
| ❌ **无数据库** | 没有 MySQL/SQLite。告警不落库、历史告警页空、看板数字是写死的演示数据 |
| ⚠️ 摄像头 | 只有 **1 路**真实摄像头接入（cam002-004 是占位）。OpenCV 用 DSHOW 后端 |
| ⚠️ 家属端 | `/family/*` 是占位页面，功能未做 |
| ⚠️ 帧率 | 画面里有人脸时 DeepFace 每帧约 2 秒，帧率 ~0.5fps；无人脸时快 |
| ⚠️ 登录 | 账号写死在 app.py（`admin/123456`），无数据库验证 |
| ⚠️ 告警截图 | 摔倒截图存 `uploads/alert_img/`，但未接前端展示 |
| ⚠️ 危险区 | 配置页有 UI，后端未实现该检测 |

**本机环境注意（踩过的坑）：**
- 摄像头必须 `CAP_DSHOW`（本机 MSMF 抓不到帧）
- OpenCV 5.0 移除了 `CascadeClassifier`，DeepFace 必须用 `detector_backend="mtcnn"`
- GitHub 直连被运营商 DNS 拦截，需走本地代理 `127.0.0.1:5188`（DeepFace 权重已缓存，运行时不联网）
- `.venv\Scripts\python.exe` 启动时会多出一个"桩进程 + 真实进程"对，属正常现象

---

## 附：一句话总结

**这是一个全栈的 AI 养老监控系统：后端用 Flask + YOLO + 人脸 + 情绪算法盯摄像头，前端网页只是把检测结果和告警显示出来。核心价值在 `algorithm/` 的 AI 检测，不在页面。**
