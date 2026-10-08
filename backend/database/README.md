# 数据库交付边界

本版唯一基线为 `src/main/resources/schema.sql`（schema_version=1）。使用根目录 `scripts/init-db.ps1` 建立独立 `elder_care_dev`，它只创建空库和最少的管理员、护理人员、CAM001及告警等级，不含演示老人/事件。

测试数据由 `scripts/smoke-test.py`、`test-management.py`、`test-two-videos.py` 单独生成并使用TEST标识。不要在正式库运行这些测试。

初始化已完成时，不覆盖已有用户密码、配置和事件。没有本版schema_version但已有sys_user时拒绝初始化，不将旧ZIP的表结构误认作本版。

**本次没有新增基线之后的数据库字段，所以没有待执行的V2增量迁移。旧附件数据库→本版的映射迁移尚未实现。** 后端同学必须先取得旧库备份、对照elder/person、event、角色、摄像头、图片地址等字段，制作单独迁移脚本并在副本验证；不能通过重导DROP TABLE完成所谓“升级”。

下一次表结构变更应增加有版本号的增量脚本，明确前置版本、备份、回滚步骤，不修改已经交付的V1含义。正式长期运行前还需评估索引、数据保留策略、媒体清理、备份与恢复。
