# ACE-Step 1.5：Apple Silicon 安装

在你的 Mac 上保存 `install-acestep-macos.sh`，打开终端，在脚本所在目录执行：

```bash
bash install-acestep-macos.sh --plan
bash install-acestep-macos.sh --install
```

1. 先在非 VPN 网络运行。每大阶段默认尝试 3 次；临时网络故障可自动重试。如流量紧张，可用 `ACE_RETRIES=1 bash install-acestep-macos.sh --install` 让它失败即停。
2. 如果还是网络问题，让命令跑完或按 Ctrl+C，然后自己连接 VPN，再在**同一个安装目录**内运行同一条命令。已验证完成的模型文件会跳过；不完整的大文件在 Hugging Face 的 HTTP 下载缓存支持时续传。Python 包重用 uv 的已完成缓存；无法保证每个中断的依赖包都按字节续传。
3. 安装成功不会自动运行。准备本地制作时：

```bash
bash install-acestep-macos.sh --start
```

**Python 版本：** 此脚本固定的 ACE-Step 只支持 Python 3.11/3.12，不能复用 Python 3.14。优先沿用此安装目录已有的兼容解释器，否则从终端 PATH 查找原生 arm64 的 3.12/3.11；找不到时 uv 只在本安装目录中准备 3.12。不会卸载或修改你已有的 Python 3.14，依赖也不装进系统 Python。

默认安装到 `~/ace-step-local`。如果第一次使用了 `ACE_INSTALL_DIR=/绝对路径`，重试和启动都要用同一个值。访问 `http://127.0.0.1:7860` ；按 Ctrl+C 停止。启动不执行依赖同步，Hugging Face/Transformers 使用离线选项；模型缺件则报错，不启动。脚本不会启用公网分享或变更系统网络设置。

流量：选官方约 **10.1 GB** 主包（Turbo、文本编码器、音频编解码器、包内 1.7B），不额外下载 0.6B。全新环境含源码和依赖预计 **11–12 GB**；建议预留 20 GB 磁盘给模型、解包、环境和缓存。模型清单超过 11 GB 时会停止，不是对总网络流量的硬上限。第一次成功取到的清单会锁定模型提交；后续不会自动跟随上游更新。

验证边界：脚本语法及模拟下载中断、缓存复用流程在云端校验；没有在你的 Mac 上安装，也没有下载权重或验证完整首歌的实际推理。
