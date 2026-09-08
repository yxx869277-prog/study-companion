# 学习搭子 · Study Companion

Windows 上的单机学习伴侣：识别学习状态，用桌面猫咪、气泡和弹幕提醒你休息或继续学习；按需转写网课声音、提取课程画面文字，生成本机学习日报。

**v0.1.0-alpha.1 · Windows 单机实验版 · MIT**

A Windows desktop study companion with a cat avatar, optional local screen understanding, course transcription and local study reports. Collection is paused by default.

## 先看桌面演示

装有 Python 3.11 和 Tkinter 时，在项目目录运行：

```powershell
python demo.py
```

演示只播放虚构气泡和弹幕，不需要安装模型或第三方 Python 依赖，不读取屏幕、不录音、不联网。右键猫咪可重播或退出。演示用于查看界面；实际识别与转写需要完成下面的安装。

## 你会怎样使用

1. 启动后出现桌面猫咪，初始显示“已暂停 · 右键开始”，不采集屏幕、声音或摄像头。
2. 右键选择“开始屏幕识别”，阅读提示并开启。此后每隔一段时间读取主显示器画面，通过你电脑上的模型判断活动类别。
3. 需要整理网课时，单独开启“网课声音转写”和“网课文字提取”；摄像头和麦克风也分别控制。
4. 学习结束后，点击“生成今日本机日报”。文件默认保存至项目下 data/reports，可自行指定 Obsidian 内的目标目录。
5. 选择“暂停全部采集”会关闭采集及在线播报开关。下一次开启屏幕识别时，可选功能仍需重新开启。选择“退出学习搭子”结束程序。

## 功能范围

- 主显示器状态识别、桌面猫咪、弹幕与气泡。
- 本机 Ollama 或本机 llama.cpp；选择一个后端，识别、互动和日报使用同一后端。
- 按需录制系统声音、麦克风声音，使用本机 Whisper 转写。
- 按需提取被识别为网课时的整屏文字。
- 可选摄像头在位判断；原始画面不主动保存成图片，行为判断保存在本机。
- 本机 Markdown 日报和离线 HTML 仪表盘。模型不可用时明确标为原始摘录，不冒充智能总结。
- 可选在线语音播报：默认关闭，每次运行均需明确开启。

此版本不提供双机连接、跨设备推理、远端部署或后端自动切回。没有云端日报代理，也不会自动把私人互动加入随源码发布的语料。

## 安装

目标环境为 Windows 11 x64、Python 3.11（含 Tkinter）。本轮已在独立 Python 3.11.15 虚拟环境完成基础依赖安装、依赖一致性检查和隐私控制测试；这不等于在全新 Windows 电脑上的验收。模型速度和可用性取决于运行内存、后端和输入长度。

先运行 `python --version` 确认选中的是 Python 3.11；如果系统里有多个 Python，请使用对应 3.11 解释器的完整路径替代以下命令中的 `python`。不要直接用系统里另一个版本创建环境。

在项目目录执行：

~~~powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
~~~

安装包和模型下载需要联网；运行时处理学习内容使用本机模型。程序不在运行期间自动下载 Whisper 模型。

### 本机视觉与文本模型

安装 [Ollama](https://ollama.com/download/windows)，下载本地模型：

~~~powershell
ollama pull qwen3-vl:4b-instruct
~~~

按照 [Ollama 官方说明](https://docs.ollama.com/faq#how-do-i-disable-ollama-cloud-features)关闭云功能并重启 Ollama。也可先从托盘退出已有 Ollama，再在当前 PowerShell 会话运行：

~~~powershell
$env:OLLAMA_NO_CLOUD = "1"
$env:OLLAMA_HOST = "127.0.0.1:11434"
ollama serve
~~~

这些命令只设置该会话环境，不会替你修改系统配置。项目在发送学习内容前检查模型元数据，并拒绝声明为云端的模型；本机服务本身仍须是你信任的官方运行时。

首版默认由 CPU 运行 Ollama 模型，使用 4096 token 上下文、小批量处理，并在每次请求后释放模型内存。这组参数已用于虚构课件验证。加载和识别可能需要几十秒，采集间隔不等于模型响应时间；长日报素材可能超出上下文容量。

若已确认自己的显卡和 Ollama 后端工作正常，可在 config.local.json 中将 `OLLAMA_CPU_ONLY` 改为 `false`，让 Ollama 选择加速方式；也可调整 `OLLAMA_CTX`。这些设置只作用于本程序请求，不更改 Ollama 的全局设置。自动加速路径本轮曾出现内存分配错误，不能保证所有设备可用。

也可在 config.local.json 中选择本机 llama 后端。自行下载 [llama.cpp](https://github.com/ggml-org/llama.cpp) 和兼容的 Qwen3-VL GGUF、视觉投影文件，放到 config.py 指定的 vendor 和 models 位置。项目不附带二进制或模型权重。使用 llama 后端时，日报与互动也使用该本机服务。

### 本机语音转写模型

仅在需要录音转写时准备；由使用者主动执行下载：

~~~powershell
.venv\Scripts\python.exe -c "from huggingface_hub import snapshot_download; snapshot_download('Systran/faster-whisper-small', local_dir='models/whisper-small')"
~~~

代码从此目录离线加载模型。来源与许可见 [faster-whisper](https://github.com/SYSTRAN/faster-whisper) 和模型页面；缺少模型时不会自动启用录音。

### 个人配置与启动

将 config.example.json 复制为 config.local.json，修改模型名、端口、报告目录或识别间隔。这个个人文件不应提交。远程地址不是可配置项；所有采集及联网语音开关每次启动均为关闭。

~~~powershell
.venv\Scripts\python.exe check_environment.py
.venv\Scripts\python.exe main.py
~~~

也可双击 start.bat 在后台启动。此版本不自动安装开机启动项。

### 可选在线语音

~~~powershell
.venv\Scripts\python.exe -m pip install -r requirements-optional.txt
~~~

安装后仍默认关闭。开启菜单中的“在线语音播报”会把文案发送给在线服务；文案可能含从屏幕推导出的内容。详情见 [PRIVACY.md](PRIVACY.md)。

## 数据和限制

运行数据保存在 data/logs，日报保存在 data/reports 或你选择的目录。日志、转写、日报与后续截图都属于私人数据，不应随代码发布。界面暂停会停止后续采集；正在进行的设备调用或本机模型推理可能有短暂完成延迟。已发送的在线语音请求无法撤回。

活动分类、课程转写和时长是近似结果，存在识别错误与采样间隔误差，不用于成绩、考勤或人的专注度评判。网课 OCR 目前提取整屏，可能混入其他窗口文字。

## 验证

~~~powershell
.venv\Scripts\python.exe -B -m unittest discover -s tests -v
~~~

测试用模拟设备、虚构文本和临时本机 HTTP 服务验证采集开关、取消录音和数据发送边界，不打开真实屏幕采集、摄像头或麦克风。这不等于真实设备端到端验收。

## 参与和许可

欢迎按 [CONTRIBUTING.md](CONTRIBUTING.md) 反馈安装问题、使用体验或提交改进。反馈时提供必要的脱敏报错即可，不要上传私人学习记录。

项目源码和文档使用 [MIT License](LICENSE)，署名为 `yxx869277-prog`。第三方依赖和模型保持各自许可，详见 [THIRD_PARTY.md](THIRD_PARTY.md)。已验证内容与待验证范围见 [RELEASE_STATUS.md](RELEASE_STATUS.md)。
