# 第三方组件与来源

学习搭子自身的源码和文档使用 [MIT](LICENSE) 许可证。依赖包、模型和系统字体分别遵守各自条款。本仓库只分发项目源码和文档，依赖安装包、运行时、模型权重及字体均由使用者另行安装。

下表按安装包中的许可证文件、元数据及官方上游核对，核查日期为 2026-09-08。完整安装版本固定在 [requirements-lock.txt](requirements-lock.txt)。

| 直接依赖 | 版本 | 许可说明 |
| --- | --- | --- |
| [mss](https://github.com/BoboTiG/python-mss) | 10.2.0 | MIT |
| [Pillow](https://github.com/python-pillow/Pillow) | 12.3.0 | MIT-CMU；安装包含额外组件通知 |
| [NumPy](https://github.com/numpy/numpy) | 2.4.6 | BSD-3-Clause；安装包还含其他组件许可 |
| [Requests](https://github.com/psf/requests) | 2.34.2 | Apache-2.0；安装包保留 NOTICE |
| [PyAudioWPatch](https://github.com/s0d3s/PyAudioWPatch) | 0.2.12.8 | Apache-2.0；包含 PortAudio 相关组件 |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | 1.2.1 | MIT；依赖 CTranslate2、PyAV 等组件 |
| [RapidOCR](https://github.com/RapidAI/RapidOCR/blob/v1.4.4/LICENSE) | 1.4.4 | Apache-2.0；安装包自带 OCR 模型，使用 ONNX Runtime |
| [Windows-Toasts](https://github.com/DatGuy1/Windows-Toasts/blob/main/LICENSE) | 1.3.1 | Apache-2.0，已核对安装包 LICENSE |
| [opencv-python](https://github.com/opencv/opencv-python) | 5.0.0.93 | Python 打包代码 MIT；OpenCV 主库 Apache-2.0；另见安装包 LICENSE-3RD-PARTY.txt |
| [keyboard](https://github.com/boppreh/keyboard) | 0.13.5 | MIT |
| [edge-tts](https://github.com/rany2/edge-tts/blob/master/LICENSE)，可选 | 7.2.8 | 主要代码 LGPLv3，srt_composer.py 为 MIT；本项目不复制或捆绑其源码 |

安装包中的许可证和通知文件应保留。特别是 NumPy、Pillow、OpenCV、PyAV/FFmpeg 等包含多个组件，上表的简写不能替代这些完整通知。将本项目进一步打成包含依赖或运行时的安装器时，需要针对实际装入的文件重新核对再分发要求。

## 单独安装的运行时和模型

- [Ollama](https://github.com/ollama/ollama)：MIT；由使用者独立安装，随其发布包附带的其他组件仍适用各自许可。
- [llama.cpp](https://github.com/ggml-org/llama.cpp)：MIT；作为可选后端，二进制及其附带组件不进入本仓库。
- [Qwen3-VL-4B-Instruct](https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct)：官方模型使用 Apache-2.0。示例只指定模型名，不附权重。第三方量化文件还需阅读对应模型卡和通知。
- [faster-whisper-small](https://huggingface.co/Systran/faster-whisper-small)：Whisper 模型的 CTranslate2 格式转换，模型卡列出 MIT；由使用者下载。
- 如果自行换成其他模型，请核对那个具体版本的许可。例如 Qwen2.5-VL-3B-Instruct 使用 [Qwen Research License](https://huggingface.co/Qwen/Qwen2.5-VL-3B-Instruct/blob/main/LICENSE)，不能按本项目的 MIT 许可证推定其可直接商用。

在线语音的代码许可不等同于在线服务使用条款。该功能单独安装、默认关闭，数据流向见 [PRIVACY.md](PRIVACY.md)。

## 项目内的内容

- 桌面猫咪由操作系统绘制 Unicode 表情；仓库没有从系统字体提取的图像或字体。
- corpus.json 与 demo.py 中的文案为本项目编写的虚构示例，没有复制私人互动、录音、课件或学习日报。
- 应用由作者组织需求并使用 AI 辅助开发。本次源码与搭建记录核对未发现需要随包携带的第三方代码目录；该核对不构成对所有潜在代码相似性的鉴定。
- 后续引入第三方片段、图标或素材时，应在这里补充出处并保留对应许可与署名。
