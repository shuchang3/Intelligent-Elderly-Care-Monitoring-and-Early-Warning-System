# 摔倒检测首版离线评测记录

评测日期：2026-09-01（Asia/Shanghai）

## 数据与授权

- 数据集：UR Fall Detection Dataset（URFD），Camera 0 RGB。
- 数量：30 段摔倒、40 段日常活动，70 个官方 ZIP 均通过完整性校验。
- 许可：CC BY-NC-SA 4.0，仅限符合许可的非商业学术使用；报告或论文需要引用官方数据集论文。
- 本项目保留官方页面、许可文本、逐帧标签、同步时间、下载清单及 SHA-256；大体积原始数据和转换视频不提交 Git。
- 划分在运行评测前固定：01–10 为调参与排错集，剩余 20 段摔倒和 30 段日常活动为首版保留测试集。

UP-Fall 的官方页面和论文也已归档。计划的 18 个 RGB 子包均受 Google Drive 配额或公开权限限制，当前下载为 0/18；没有改用许可证未知的镜像。

## 可复现环境

- Python 3.12.13
- PyTorch 2.13.0+cu126
- Ultralytics 8.4.136
- 模型：`yolov8n-pose.pt`
- 模型 SHA-256：`c6fa93dd1ee4a2c18c900a45c1d864a1c6f7aba75d84f91648a30b7fb641d212`
- GPU：NVIDIA GeForce RTX 4070 Laptop GPU

环境安装：

```powershell
.\scripts\setup-ai-env.ps1
```

评测命令：

```powershell
$env:YOLO_CONFIG_DIR = Join-Path (Get-Location) '.ultralytics'
.\.venv-ai\Scripts\python.exe scripts\evaluate-urfd-falls.py --split tune --device 0 --name tune-ground-v1
.\.venv-ai\Scripts\python.exe scripts\evaluate-urfd-falls.py --split test --device 0 --name final-v1
```

## 结果

调参与排错集在加入时间状态机、缺失重置和画面底部约束后得到：TP 10、FN 0、FP 0、TN 10，precision 1.00、recall 1.00，无重复事件。该结果只说明前 20 段样本被拟合良好。

保留测试集的首版结果为：

| 指标 | 结果 |
| --- | ---: |
| TP / FN | 9 / 11 |
| FP / TN | 10 / 20 |
| Precision | 0.474 |
| Recall | 0.450 |
| 重复事件 | 2 |
| 平均姿态覆盖率 | 75.2% |
| 平均处理速度 | 118.9 FPS |
| 已检出事件的触地后中位延迟 | 108 ms |

首版没有通过 precision ≥ 0.80、recall ≥ 0.90、每小时误报 ≤ 1、无重复事件四项门槛。原始逐片结果保存在 `output/evaluation/urfd/test-final-v1.json` 和同名 CSV 中，失败结果必须保留。

## 原因和下一步边界

11 个漏报中，多段在进入 `DOWN` 后因人物遮挡或关键点消失而在确认前重置；`fall-21` 的姿态模型几乎没有形成有效下降特征。10 个误报主要是快速坐下、躺下等动作，它们同样具有髋部快速下降和横向躯干特征。固定的画面底部阈值只适用于部分机位，不能代表真实地面标定。

已完成的工程修复包括：每个稳定 trackId 使用独立状态机；轨迹框与姿态框按全局一对一 IoU 匹配；姿态长时间缺失会清除陈旧候选；每次摔倒事件只在状态首次确认时上报；事件描述记录实际规则依据，不把姿态分数伪称为摔倒概率。

后续不得继续用这 50 段保留测试反复调阈值。算法同学应在新的开发集上完成机位地面标定、遮挡期间的轨迹/姿态连续性和摔倒与主动躺下的时序分类，再用新的未见样本复验。公开视频仍需补多人、侧脸、弱光、人员进出画面等当前 URFD Camera 0 没有充分覆盖的场景。

## 尚缺材料

- DeepFace 情绪模型权重及 SHA-256；程序当前拒绝隐式下载，情绪功能会显示降级。
- UP-Fall 首批 18 个官方 RGB 子包；等待官方共享配额或权限恢复。
- 经授权的多人、弱光、遮挡和进出画面视频及逐段预期结果。
- 算法同学对模型来源、训练/验证划分、准确率和性能结论的签字或提交记录。
