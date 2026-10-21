# 本机一键驱动（machine-specific，备胎）

SwitchSuite 界面已覆盖大部分操作，这里只留**没有 GUI 等价**的备胎。
内含本机绝对路径；内容为纯 ASCII 或 GBK 编码（cmd 按 GBK 读批处理）。
桌面上的副本才是运行入口；要改先改这里的，再复制到桌面。

| 文件 | 用途 | 前提 |
|---|---|---|
| `合并sunflower2到Sunflower.bat` | 全量 sync + dedupe（记忆/连接器/设置/会话整体并入；sunflower 2 会腾空）——GUI 无此入口 | 客户端完全退出 |
| `clean_orphans.bat` | 清理 2026-10-21 中断运行遗留的孤儿文件（GBK） | 无需退客户端 |

已退役（GUI 按钮覆盖）：复制会话、智能合并、反向复制及其驱动。
