# 本机一键驱动（machine-specific）

这些 .bat 是**本机专用**运行入口（内含本机绝对路径）。桌面上的副本才是日常双击对象；
要改先改这里的，再复制到桌面。内容为纯 ASCII 或 GBK 编码——cmd 按 GBK 读批处理，
含中文路径的脚本必须以 GBK 生成（参考 ours/make_merge_bat.py 的做法）。

| 文件 | 用途 | 前提 |
|---|---|---|
| `复制会话.bat` | Sunflower → sunflower 2 复制会话（copy_sessions.py 驱动，带进度） | 客户端完全退出 |
| `智能合并sunflower2到Sunflower.bat` | smart_merge 内容感知合并（复制 + exe dedupe） | 客户端完全退出 |
| `复制sunflower2新会话到Sunflower.bat` | 反向 copy（同根源防线自动跳过已有副本） | 客户端完全退出 |
| `合并sunflower2到Sunflower.bat` | sync 全量合并 + dedupe（sunflower 2 会腾空） | 客户端完全退出 |
| `clean_orphans.bat` | 清理 2026-10-21 中断运行遗留的孤儿文件（GBK） | 无需退客户端 |
| `copy_sessions.py` | 复制会话进度驱动（位置无关，自动定位仓库根） | 随 .bat 调用 |
