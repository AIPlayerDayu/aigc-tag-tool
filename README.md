# 🔎 AIGC 标识检测去除工具（macOS / Windows）

检测**图片 / 视频**是否携带「AI 生成 / AIGC 标识」等元数据痕迹，并可**一键去除这些标识**生成干净副本。全程本机离线，不上传任何文件。

> 🪟 **Windows 用户** → 看这里：[Windows安装说明.md](Windows安装说明.md)（新手向，三步搞定）。

> ⚠️ **免责声明**：本工具仅供**技术研究、学习与合法的元数据检测测试**之用，**请勿用于任何违法违规用途**。
> 部分国家/地区（如中国《人工智能生成合成内容标识办法》及 GB 45438-2025）明确**禁止恶意删除、篡改、伪造或隐匿**生成合成内容标识。
> 使用者应确保仅对**自己拥有合法权利的文件**进行操作，并自行判断与遵守所在地法律；**因使用本工具产生的一切后果由使用者自行承担，与作者无关。**

## 使用

无论 mac 还是 Windows，都是打开后弹出一个**网页窗口**，把图片/视频从文件管理器**直接拖进方框**（可批量）即可检测；也可以点方框选择文件。

- **macOS**：双击 `AI元数据检测器.app`（首次右键→打开）。还可把文件拖到 **App 图标**上，此时按原始路径检测、去标识后直接把干净副本存到原文件旁边。
- **Windows**：双击 `启动_Windows.bat`（详见 [Windows安装说明.md](Windows安装说明.md)）。拖进窗口检测，去标识后干净副本自动下载到「下载」文件夹。

## 判定分档

| 结果 | 含义 |
|------|------|
| 🔴 **检测到 AI 生成元数据** | C2PA/IPTC 合成声明、**中国 AIGC 标识(GB 45438-2025)**、Stable Diffusion / ComfyUI / NovelAI 生成参数、或知名生成器署名（Midjourney、DALL·E、Firefly、Sora、可灵、即梦…） |
| 🟠 **疑似 / 含内容凭证** | C2PA 内容凭证或 AI 编辑痕迹（生成式填充、Topaz、Remini…），需人工判断 |
| 🟢 **未发现 AI 元数据** | 没找到相关标记 |

> ⚠️ 元数据可被编辑、压缩，或被平台在转发时抹除，也可能被伪造。「未发现」**不代表**内容一定由人类创作。结果仅供参考。

## 去除 AI / AIGC 标识

检出为 🔴/🟠 的文件下方会出现「🧹 去除 AI / AIGC 标识并保存」按钮：

- **视频**：用 `ffmpeg -map_metadata -1 -c copy` 去掉容器里的全部标签（含 AIGC），**流拷贝、不重新编码 → 画质无损、速度快**。
- **图片**：用 `exiftool -all=` 抹除全部元数据（EXIF/XMP/IPTC/C2PA）。
- 可勾选「同时随机化普通元数据」：去标识后再写入随机的普通日期/编码器信息，让文件更像常规拍摄/编辑产物。
- 处理完会**自动复检**并显示结果（正常应变为 🟢）。

> 适用场景：只是给图片/视频做了美颜/剪辑，却被工具自动打上了 AIGC 标识，想在发布前去掉这个标签。
> 注意：本功能只移除**元数据**，不改动画面像素；若某些平台把标识写进了视频码流(SEI)而非容器标签，则需重新编码才能去除（本工具默认不重编码以保画质）。

## 检测依据

- **C2PA / Content Credentials**：Adobe、OpenAI、相机厂商等的来源溯源清单（JUMBF）
- **中国 AIGC 隐式标识**：GB 45438-2025《人工智能生成合成内容标识方法》写入的 `AIGC` 元数据（`Label/ContentProducer/ProduceID`），`Label:"1"` 表示 AI 生成合成
- **IPTC DigitalSourceType**：`trainedAlgorithmicMedia` / `compositeSynthetic` 等国际合成媒体标准
- **XMP / EXIF**：`CreatorTool` / `Software` 等署名字段
- **PNG 文本块**：Stable Diffusion(WebUI) 的 `parameters`、ComfyUI 的 `prompt/workflow`、NovelAI 等
- **已知生成器署名**：数十种主流图像/视频生成与 AI 修图工具

## 安装

- **macOS**：打开 `AI元数据检测器.dmg` → 把 App 拖到「应用程序」→ 首次右键 App → **打开**（自签名应用，绕过 Gatekeeper 一次）。
- **Windows**：装好 Python 后双击 `启动_Windows.bat` 即可，详见 [Windows安装说明.md](Windows安装说明.md)。

## 依赖

| 功能 | 需要什么 |
|------|----------|
| 图片检测（PNG/JPEG/WebP…） | **零依赖**（纯 Python） |
| 图片去标识 | **零依赖**（纯 Python 无损剥离元数据） |
| 视频检测（含 AIGC 标识） | **零依赖**（`ffprobe`/`exiftool` 存在时结果更全，但非必需） |
| 视频去标识 | 需要 **`ffmpeg`**（无损流拷贝去容器标签）。macOS：`brew install ffmpeg`；Windows：`winget install Gyan.FFmpeg` |

> HEIC 等少见格式的深度解析会用到 `exiftool`（可选）。缺失时页面会给出提示，常见格式不受影响。

## 架构 / 从源码构建

纯标准库 Python，跨平台。启动器负责「起本地服务 + 打开网页」：mac 用 AppleScript applet，Windows 用 `.bat`/`.vbs`。

- `src/detect.py` —— 检测引擎（PNG/JPEG/WebP/MP4 字节解析 + 纯 Python 图片去标识 + 可选 exiftool/ffprobe）
- `src/server.py` —— 本地服务（`127.0.0.1:8765`，检测/去标识/下载；30 分钟无活动自动退出）
- `src/index.html` —— 拖拽前端
- `src/make_icon.py` —— 程序化生成图标（无版权素材）
- `启动_Windows.bat` / `启动_Windows(无窗口).vbs` —— Windows 启动器
- `build.sh` / `make_dmg.sh` —— macOS 打包（无需 Xcode）

```bash
# macOS 打包
./build.sh       # 生成 AI元数据检测器.app
./make_dmg.sh    # 打包为 AI元数据检测器.dmg

# 任意平台直接跑（开发/调试）
python3 src/server.py    # 然后浏览器打开 http://127.0.0.1:8765/
```

## 隐私

所有解析与去标识都在本机完成，服务只监听 `127.0.0.1`，不联网、不上传。
