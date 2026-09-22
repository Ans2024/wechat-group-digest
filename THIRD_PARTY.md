# 来源、固定版本与核查结论

核查日期：2026-09-20。开发时通过 GitHub API 检查固定提交源码；第三方完整源码不随此仓库打包，不运行其缓存密钥或后台服务命令。

## WeChatMsg

- 原始项目：https://github.com/LC044/WeChatMsg
- 当前主页声明 MIT，停止更新；当前主分支仅见文档，不能据此宣称已获得 4.1.13 可运行读取实现。
- 未采用该项目代码，也未将历史 3.x 的字段或密钥偏移套用到本机。

## erbanku/weixin-cli

- 来源：https://github.com/erbanku/weixin-cli
- 固定提交：`08af894594b4afd468e23e17dbd783f15403f13b`
- 源码链接：https://github.com/erbanku/weixin-cli/tree/08af894594b4afd468e23e17dbd783f15403f13b
- LICENSE：Apache-2.0；许可证文本随本项目保留为 LICENSE。
- 文档声明 Windows x86_64、macOS、Linux 的微信 4.x，存在真实 `src/scanner/windows.rs`、`src/crypto/mod.rs`、`src/crypto/wal.rs`、`src/daemon/query.rs`。
- 核查了内存 `x'<key><salt>'` 扫描、4096 页/80 保留区、SQL 查询及 zstd 内容。该字符串扫描在本机实测为零候选，不能作为本机主方法。
- `wal.rs` 缺少累计帧校验和、提交边界处理，其第 1 页路径也不能直接作为本机依据；**没有复用它的 WAL 合并逻辑**。
- 本项目 `windows.py` 的旧式扫描思路及 `crypto.py` 的页布局参考了这些文件，重新实现并增加逐页认证、只读内存数据生命周期。

## fanyuantaier/wechatauto-replica

- 来源：https://github.com/fanyuantaier/wechatauto-replica
- 固定提交：`492a8fb70b95865613d6d8d9740323233dbfa197`
- 源码链接：https://github.com/fanyuantaier/wechatauto-replica/blob/492a8fb70b95865613d6d8d9740323233dbfa197/wechatauto/db.py
- LICENSE：Apache-2.0，与随附文本一致。
- Windows 微信 4.x；README_pypi.md 专门记录 4.1.13 配置对象取钥修复，并提及 4.1.13.65 的 UI 兼容测试。其声明不是本项目成功依据；本机数据库首页/有效页 HMAC 与 SQLite 校验才是依据。
- 核查 `CONFIG_CIPHER_NAME`、`CONFIG_XOR_MASK`、`_collect_key_candidates`、`_verify_enc_key`、`_decrypt_page`。本项目 `windows.py::config_candidates` 根据这些函数改写，只读取内存，限制候选长度和指针范围，再对选定账号指定库执行 HMAC 验证。
- 重大修改：不导入上游包、不使用其磁盘密钥缓存、不自动选择其他账号、不保留明文数据库、不采用其未经完整帧校验的 WAL 合并。
- 与本机实际结构匹配：联系人表 `contact(username,nick_name,remark)`；群表 `chat_room`；成员表 `chatroom_member`；消息表 `Msg_<md5(group_id)>`；分片内 `Name2Id(rowid,user_name)`。运行时检查核心列，不伪造未知字段。

## 格式依据

- SQLite 官方文件格式与 WAL 提交、校验算法：https://www.sqlite.org/fileformat2.html#walformat
- SQLCipher 官方实现：https://github.com/sqlcipher/sqlcipher/blob/master/src/sqlcipher.c
- 已核查 SQLCipher raw-key、HMAC 派生盐异或、快速 KDF、页号小端参与 HMAC 的逻辑。只参考算法，未复制其代码；本机每个有效页均验证成功。
- 不使用任意猜测的 256000 次密码派生流程：本项目从已认证候选获取的是派生后的 32 字节原始 AES key，HMAC key 使用该 key 和变换后的盐经 2 次 PBKDF2-HMAC-SHA512 派生。

## 安装依赖

pycryptodome 3.23.0、zstandard 0.25.0、Pillow 12.3.0、psutil 7.2.2、Playwright 1.63.0，固定在 requirements.txt。原始安装包在项目虚拟环境中保留自身许可。Playwright 仅用于开发期页面验证；实际 PNG 用 Pillow 本机中文字体渲染。

上述第三方代码和算法仍归各自作者；本文件记录本项目所作修改，不声称原始作者为本项目背书。
