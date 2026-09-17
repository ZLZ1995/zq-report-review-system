# Windows 本地验收记录

## 已验证环境

- Windows 10/11 兼容主机，Python 3.10.11 构建环境。
- Microsoft Excel、Microsoft Word、WPS 表格和 WPS 文字注册项均存在。
- 主 EXE 原生启动、登录窗口、Qt WebEngine 原生导入、内置规则及锁定模板哈希通过。
- 独立启动器和更新器 EXE 可启动并正确解析命令接口。
- 普通更新包与托管接管包 ZIP 完整性通过，未包含项目运行目录、浏览器资料、账号凭据或私钥。

## 必须在干净机器补验

- 全新 Windows 用户配置下首次解压托管接管包并启动。
- 仅 Office、仅 WPS、Office+WPS 三种组合下 Word/Excel 生成与批注视觉检查。
- 从托管 0.2.7 安装一个后续测试版本并执行一次故障回退。
- Windows Defender/企业安全软件误报和下载信誉；当前没有 Authenticode 证书，不能标记为已通过代码签名验收。

当前结论：本机可运行验收通过；独立干净 Windows 环境因用户暂无测试机而明确阻塞，不能计入 G11 最终通过。
