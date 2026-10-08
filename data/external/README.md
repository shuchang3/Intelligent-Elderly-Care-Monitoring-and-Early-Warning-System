# 算法评测数据

本目录保存公开数据集的来源材料、许可证、下载清单和校验值。大体积原始数据位于各数据集的 `raw/` 目录，已由 `.gitignore` 排除，不应提交到 Git 或重新分发。

## URFD

- 官方页面：<https://fenix.ur.edu.pl/~mkepski/ds/uf.html>
- 本地说明快照：`urfd/docs/official-dataset-page.html`
- 许可：CC BY-NC-SA 4.0，仅用于非商业学术用途，使用时按官方页面要求引用原论文。
- 下载范围：30 个摔倒序列和 40 个日常活动序列的 Camera 0 RGB 压缩包，共 70 个文件。
- 原始格式：ZIP 中的 PNG 图像序列。转换视频时不得改变时间顺序和帧率依据。

## UP-Fall

- 官方页面：<https://sites.google.com/up.edu.mx/har-up/>
- 本地说明快照：`upfall/docs/official-dataset-page.html`
- 官方论文：`upfall/docs/UP-Fall-paper.pdf`
- 官方页面标记 Copyright 2017–2019 Universidad Panamericana，并要求引用论文；页面没有给出等同于 URFD 的 Creative Commons 许可证。因此数据仅作为本校项目研究评测材料，不重新发布原始图像。
- 完整影像约 812 GB，本机不下载全量。首批只取 Subject 1、2 的 Camera 1：Activity 8（坐下）、9（捡物）、11（躺下），每项 3 次，共 18 个分包。
- 官方论文动作编号：1–5 为五种跌倒，6 走路，7 站立，8 坐下，9 捡物，10 跳跃，11 躺下。

## 文件说明

- `download-manifest.csv`：计划下载和实际状态。
- `checksums.sha256`：下载完成后生成的 SHA-256。
- `dataset_manifest.csv`：由官方帧标签和同步时间生成的事件时间区间、固定用途划分及来源信息。
- `scripts/prepare-evaluation-datasets.py`：从官方页面生成下载清单、下载文件并校验。
- `scripts/prepare-urfd-evaluation.py`：读取 ZIP 内图像序列生成 MP4、清单与视频校验值，不批量解压原图。
- `scripts/evaluate-urfd-falls.py`：复用生产摔倒状态机执行 GPU 离线评测。

URFD 官方逐帧标签中 `0` 表示摔倒过程、`1` 表示倒地、`-1` 表示非倒地。清单中的 `eventStartMs`、`groundContactMs` 和 `eventEndMs` 据官方标签与同步时间自动换算；正式论文使用前仍建议两人视觉复核。

固定划分为：序号 01–10 用作调参与排错，摔倒 11–30 和日常活动 11–40 用作首版保留测试。首版测试结果已经产生，不能再反复用该测试集调阈值。

## 当前下载状态（2026-09-01）

- URFD：70/70 个 Camera 0 RGB 包已下载并通过 ZIP 完整性校验，共 4,489,073,943 字节。
- UP-Fall：0/18。18 个官方 Google Drive 文件均返回下载配额过高或公开权限限制，详情见 `download-errors.csv`。没有使用许可证未知的镜像替代。

Google Drive 限制解除后，在项目根目录重试：

```powershell
.\.venv-web\Scripts\python.exe scripts\prepare-evaluation-datasets.py --dataset upfall
```

脚本会跳过已完成文件，并重新生成下载状态和校验值。
