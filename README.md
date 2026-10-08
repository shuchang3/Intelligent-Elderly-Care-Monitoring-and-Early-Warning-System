# 视界无疆：单机联调版 1.1.0-integration

本版保留 Flask/Jinja 网页，不需要 Vue。Java 管业务、MySQL 管正式数据、Python 管页面会话及视觉算法。**IDEA、VS Code 的不同不会造成接口不兼容。**

这次已新增可运行的 `backend` Maven 工程。它实现了计划中的核心接口和扩展接口，但**不是旧后端数据库的原地升级包**：旧附件、旧 `elder_care` 数据库不动，新版使用 `elder_care_dev`。后端同学应审查并接管这个工程，不能混用旧 JAR、新页面、新表。

## 现在怎么打开

本机旧程序占用了 5000/8080，因此本次 `.env.local` 已配置 **5001/8081**。默认示例仍是 5000/8080；脚本以配置为准。

```powershell
Set-Location 'D:\IJ\shijie-wujiang-master\shijie-wujiang-master'
.\scripts\start-local.ps1
```

浏览器打开 **http://127.0.0.1:5001**。如提示端口占用，先判断是否本项目已启动，不要强杀未知程序。

初始账户为 `admin`、`staff01`，随机密码在本机 `.env.local` 的 `BOOTSTRAP_ADMIN_PASSWORD`、`BOOTSTRAP_STAFF_PASSWORD`。不是原来的硬编码密码。该文件不能上传 Git、发群或贴到聊天中。家属账户需要管理员在页面创建并绑定老人。

停止本项目：

```powershell
.\scripts\stop-local.ps1
```

只停止记录了 PID、启动时间和项目路径的本项目进程树，不停止 MySQL 或旧程序。强制停止时未完成的录像可能不完整，不能认为已经保存。日常修改源码后先停止，再启动。

## 一次性准备：另一台电脑或重新部署时

1. 安装 JDK 21、MySQL 8；准备能运行的 Python。网页层已在 Python 3.12 验证，原算法环境 Python 3.13.5 已保留且可运行。
2. 优先验证已有 `.venv`，不要删除它：

   ```powershell
   .\.venv\Scripts\python.exe --version
   .\.venv\Scripts\python.exe -m pip check
   .\.venv\Scripts\python.exe -m pip install -r requirements-web.lock.txt
   ```

   `requirements-web.lock.txt` 是此次测试环境的版本记录，含 pytest。只需要网页时可用单独虚拟环境，使用 `requirements-web.txt`；本机 `.venv-web` 是额外验证环境，不替换原 `.venv`。
3. `scripts/setup-local.ps1` 提示输入本机 MySQL 密码，生成随机密钥和初始账号密码。已存在 `.env.local` 时拒绝覆盖；本机现在已经完成这一步。
4. `scripts/build-backend.ps1` 构建 JAR 并运行 Java 测试。首次需要下载 Maven 依赖；网络不可用时脚本会失败，不能假定构建完成。
5. `scripts/init-db.ps1` 创建并初始化 **elder_care_dev**。脚本只允许这个本机开发库，不执行附件里的 DROP TABLE。已有本版 schema_version=1 时不会重置账号或数据；遇到无版本标记的旧库会拒绝覆盖。
6. 运行 `scripts/check-env.ps1`，再运行 `scripts/start-local.ps1`。

如 PowerShell 阻止脚本执行，脚本不会自行改变系统执行策略。由电脑所有者按学校/电脑管理要求决定允许方式；也可以在 VS Code/IDEA 分别启动进程。

## 在 IDEA 启动前后端

本项目没有单独的 Vue/React 前端工程。浏览器页面由根目录的 Flask/Jinja 应用提供：Java Spring Boot 负责业务 API，Python 的 `app.py` 负责页面、会话及 API 代理。两个服务都启动后，再访问网页。

### 一次性准备

1. 安装并启动 MySQL 8，准备 JDK 21 和 Python。页面开发使用仓库已有的 `.venv\Scripts\python.exe`；确认它可用：

   ```powershell
   .\.venv\Scripts\python.exe --version
   .\.venv\Scripts\python.exe -m pip check
   ```

2. 确认根目录 `.env.local` 已存在并包含本机数据库密码、密钥和端口设置。它已被 Git 忽略，不要提交或分享。新环境可参考“一次性准备”中的 `scripts/setup-local.ps1` 生成；此脚本在 `.env.local` 已存在时会拒绝覆盖。
3. 第一次使用时，在项目根目录执行 `scripts/check-env.ps1` 检查配置，再执行 `scripts/init-db.ps1` 初始化开发库 `elder_care_dev`。该脚本只针对本机开发库；不要把旧库改名或用于本项目。以后数据库已初始化就不必重复执行。
4. 当前本机 `.env.local` 将网页端口设为 **5001**、Java 端口设为 **8081**。下面步骤和浏览器地址按这组配置说明；若你本机配置不同，以 `.env.local` 的 `PORT`、`BACKEND_PORT`、`JAVA_BASE_URL`、`WS_PUBLIC_URL` 为准。

### 启动 Java 后端

1. 用 IDEA 打开项目根目录。在 Maven 工具窗口点“+”并选 `backend/pom.xml`，或右键 `backend/pom.xml` 选择“添加为 Maven 项目”。
2. 在 Project Structure 中将 Project SDK 设为 **JDK 21**；Maven Runner 使用的 JRE 也设为 JDK 21。
3. IDEA 右上角选择仓库自带的 **“后端 Java（本地）”** 运行配置并点击运行。配置入口是 `com.eldercare.platform.Application`，工作目录为 `backend`。如果 IDEA 未显示该配置，也可打开该类，点击 `main` 方法旁的运行按钮。
4. 后端从根目录 `.env.local` 读取数据库连接、密钥及端口。确认 MySQL 正在运行，控制台出现 Spring Boot started 且没有数据库连接错误后再启动页面。

若之前通过 `scripts/start-local.ps1` 启动过整套服务，先在项目根目录运行 `scripts/stop-local.ps1`，避免后台 Java 已占用 8081。不要同时用脚本和 IDEA 启动同一个 Java 服务。

### 启动页面（Python / Flask）

1. IDEA 需要启用 Python 插件。打开 **Run → Edit Configurations**，新增 **Python** 配置：
   - Script path：项目根目录的 `app.py`
   - Working directory：项目根目录
   - Python interpreter：项目根目录 `.venv\Scripts\python.exe`
   - Environment variables：`AI_ENABLED=false`
2. 保存并运行该配置。`app.py` 会读取根目录 `.env.local`，显式设置的环境变量优先；AI 默认关闭，避免启动摄像头或推理进程。
3. 浏览器打开 **http://127.0.0.1:5001**。确认页面可打开、Java 后端在 8081 运行，才算前后端联调就绪。

如果 IDEA 找不到 Python 解释器，先确认 `.venv\Scripts\python.exe` 存在；也可从 IDEA Terminal 在项目根目录执行 `.\.venv\Scripts\python.exe app.py`。网页使用 Waitress 启动，不启用调试自动重载；同一时间只运行一个 `app.py` 进程。修改代码后停止对应运行配置再重新运行。

### 停止服务与常见问题

- 在 IDEA 中分别点击 Java、Python 运行窗口的停止按钮。MySQL 是独立服务，不需要随项目关闭。
- `Address already in use` 表示对应端口已有进程监听。先确认是否已通过 IDEA 或 `scripts/start-local.ps1` 启动了同一服务，再停止重复进程；不要强制结束不认识的进程。
- 网页能打开但接口报错时，检查 Java 控制台和 `.env.local` 中 `JAVA_BASE_URL` / `WS_PUBLIC_URL` 是否指向运行中的后端端口。
- 不需要开发 AI 功能时保持 `AI_ENABLED=false`。启用摄像头/算法服务请使用项目提供的整套启动流程，并先核对“摄像头与规则”中的采集源。

接口闭环验收后，需要现场测试摄像头时：

```powershell
.\scripts\stop-local.ps1
.\scripts\start-local.ps1 -EnableAI
```

**这个命令会打开数据库中启用的摄像头。** 先在“摄像头与规则”核对采集源。默认 `CAM001` 是业务编号，采集源字符串 `0` 是本机设备序号，不能混用。其他测试摄像头已停用。本次最终默认仍为 `AI_ENABLED=false`。

## 可重复运行的测试

```powershell
# Web环境：Flask、规则、持久化队列、通知和人脸替换隔离测试
.\.venv-web\Scripts\python.exe -m pytest -q --ignore=tests\test_fall_detector.py --ignore=tests\test_pose_utils.py

# AI环境：跌倒状态机和姿态框匹配单元测试
.\.venv-ai\Scripts\python.exe -m pytest -q tests\test_fall_detector.py tests\test_pose_utils.py

# Java接口、权限、事务与WebSocket测试
.\scripts\build-backend.ps1

# 前端HTTP/WebSocket协议测试（已安装Node.js时）
node --test tests\frontend-contract.test.cjs

# 需要运行Java和Flask：创建标注为TEST的事件，真实入库、截图、处理和退出
.\.venv\Scripts\python.exe scripts/smoke-test.py

# 人员、区域、家属隔离、情绪/轨迹/互动、实际MP4与分段读取
.\.venv\Scripts\python.exe scripts/test-management.py

# 真实YOLO/DeepSORT处理两段人工生成视频；不打开实体摄像头
.\.venv\Scripts\python.exe scripts/test-two-videos.py
```

根目录 `pytest.ini` 将测试发现限制在 `tests`，不会扫描 `runtime`、数据集、输出目录或虚拟环境。Web与AI测试使用不同虚拟环境，不能再用 `.venv-web` 收集依赖NumPy的AI测试。

测试写入的是独立开发库，使用 TEST 名称；不会删除已有业务数据。管理测试结束会停用自己创建的人员、家属账户和区域；两路视频测试会停用自己的摄像头。中途失败留下的 TEST 数据可以由管理员检查后停用，不应在正式库运行这些脚本。

## 文件职责

| 文件/目录 | 用途 |
|---|---|
| `webapp.py`、`app.py` | 真实登录、服务端会话、CSRF、固定白名单代理、AI开关、Waitress入口 |
| `backend/src/main/java/com/eldercare/platform` | Java业务接口、权限、事务、幂等、媒体、WebSocket、可选缓存 |
| `backend/src/main/resources/schema.sql` | 新版空库表结构，账号由初始化流程生成 |
| `static/js/api.js`、`socket_base.js`、`pages.js` | 统一请求、原生WebSocket、真实页面操作 |
| `static/js/video_render.js` | 多路预览和独立区域覆盖层，绘制/编辑/停用 |
| `algorithm/runtime.py` | 摄像头、每目标状态机、DeepSORT、情绪队列、录像任务 |
| `algorithm/faces.py`、`rules.py`、`outbox.py` | 人脸版本同步、持续规则、持久化重试 |
| `notifications.py` | 可选Web Push发送器，默认不启用 |
| `runtime` | 会话SQLite、上报队列、测试视频、PID和日志；不是第二套业务库 |
| `backend/uploads` | 受鉴权访问的截图、人脸照片、录像，不映射任意磁盘路径 |
| `docs` | 接口说明、团队交接、申请书对照、部署边界 |

旧模板和旧算法辅助文件保留用于对照，但 `webapp.py` 的路由已经切到新的真实数据模板，旧演示图表不再用于服务页面。

## 运行限制与未完成验收

- 两路合成视频通过不代表真实跌倒、陌生人或情绪识别准确率达标。缺少标注测试集、多人遮挡视频、现场摄像头/声音设备测试，不能承诺低误报或紧急消息必达。
- 单摄像头 DeepSORT 使用本地颜色直方图作为关联特征，是可运行基线，不是训练完成的 Re-ID，也未实现跨摄像头三维定位、模型剪枝、GMM或多模型投票研究成果。
- 当前平台只有一个机构、一个 Java 实例、一个 Python 进程。不要直接当作多租户或互联网生产系统。
- 手机响应式页面、Service Worker、订阅和任务接口已提供，但 Android 真机 HTTPS/Web Push 送达仍须现场验证。默认不会发送外部通知。
- 原 `.venv` 使用 `dlib-bin==20.0.1` 提供可导入的 dlib。`pip check` 按发行包名认为 face-recognition 缺少 dlib；诊断脚本只对这一个已核实差异给出警告，不掩盖其他冲突。`requirements-ai-observed.lock.txt` 是环境记录，不代表在所有 Windows/Python 版本上可一条命令重建。
- 不自动安装 Docker、Redis、摄像头驱动、证书，不更改防火墙，不自动发布公网。

完整的本轮修改及后续分工见 `docs/实施交接与验收.md`；接口以 `docs/API.md` 和 `docs/openapi.json` 为准，旧 Apifox 导出不能继续作为本版接口的唯一依据。
