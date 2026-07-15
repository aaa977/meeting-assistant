# 面向会议场景的实时语音转录与智能辅助系统

## 项目简介

本项目用于课程设计《面向会议场景的实时语音转录与智能辅助系统设计与实现》。系统计划逐步支持会议录音、实时语音转录、智能辅助、会议纪要和说话人标注。

## 第七阶段说明

第七阶段聚焦自动化评测、质量门和可交付发布，不增加新的会议功能链路。

- `tests/` 包含说话人聚类、音频静音检测、ASR JSON 解析和 Dummy LLM 契约测试，共 17 个纯离线用例。
- 菜单 `11. 运行离线评测` 读取项目转录和 `transcripts/reference.txt`，生成 `evaluation.md`。
- 菜单 `12. 生成发布包` 创建 `dist/meeting_assistant_<version>.zip` 和 `dist/SHA256.txt`。
- `.pre-commit-config.yaml` 串联 Black、isort、Ruff 和 pytest，作为提交前质量门。

### 评测指标说明

WER 是词错误率，计算公式为“替换数 + 删除数 + 插入数”除以参考文本词数，数值越低越好。中文按单字、英文和数字按连续词进行基础分词。

平均转录延迟使用 `raw_transcript.md` 中相邻 `[HH:MM:SS]` 时间戳的平均间隔表示。没有足够时间戳时结果为 `0.00` 秒，并不代表真实网络延迟为零。

运行评测前，在项目中创建：

```text
projects/<项目目录>/transcripts/reference.txt
```

文件内容应为人工校对后的参考文本。评测报告生成在项目根目录的 `evaluation.md`。

### 发布包规则

发布包包含项目源代码、配置模板、测试、工具和文档，自动排除 `.env`、`.venv/`、`.git/`、`logs/`、`dist/`、`__pycache__/`、`*.pyc` 和 `*.wav`。SHA256 校验值写入 `dist/SHA256.txt`。

## 第六阶段功能回顾

第六阶段新增在线全链路框架：使用 `asyncio` 并发调度麦克风 PCM 采集、Qwen-ASR WebSocket 收发和 LLM 实时辅助。菜单 `10. 实时会议演示（在线）` 由用户手动启动；按 `Ctrl+C` 后会取消协程、关闭音频流和 WebSocket，并按配置保存 WAV。

Qwen-ASR 客户端使用 `ASR_API_KEY` 和 `ASR_WEBSOCKET_URL`，支持 WebSocket 心跳、错误状态解析和延时重连。中间及最终结果会滚动显示、追加到 `transcripts/raw_transcript.md`，并通过异步队列提供给助手协程。

LLM 参数完整时使用 `OpenAiCompatibleClient`；缺少 `LLM_API_KEY` 或 `LLM_MODEL` 时自动回退 `DummyLlmClient`。真实 LLM 请求失败时也会记录日志并回退 Dummy，避免会议链路中断。

菜单 `10` 至少需要在 `.env` 中填写：

```env
ASR_API_KEY=你的真实阿里云密钥
ASR_WEBSOCKET_URL=真实的Qwen-ASR-WebSocket地址
```

如需真实 LLM 辅助，再填写：

```env
LLM_API_KEY=你的真实LLM密钥
LLM_BASE_URL=兼容OpenAI的API地址
LLM_MODEL=模型名称
```

如果 ASR 参数缺失，菜单 `10` 会提示“暂未配置在线参数”并返回主菜单。如果 LLM 参数不完整，在线会议仍可启动，但助手使用离线 Dummy。程序会在每次进入菜单 `10` 时重新读取磁盘中的 `.env`，因此修改后必须先在 VS Code 中保存文件。

## 第五阶段功能回顾

当前代码已完成第五阶段：在项目管理、本地录音、ASR 和 LLM 离线模拟基础上，新增了 **MFCC 特征提取、最多三人的轻量增量聚类、时间线对齐和离线说话人标注**。

菜单 `9. 说话人标注（离线）` 会直接读取已有 WAV，不播放声音、不访问麦克风或声卡。程序按 2 秒切分音频，提取 MFCC 均值和标准差特征，使用余弦距离在线更新聚类中心，再把 `[speaker_0]`、`[speaker_1]`、`[speaker_2]` 标签写入 `transcripts/raw_transcript.md`。

重复执行说话人标注时会替换已有 `[speaker_n]` 前缀，不会重复叠加标签。

第四阶段保留以下两个离线菜单：

- `7. 实时辅助演示（离线）`：周期读取最近转录，生成术语解释、关键点、风险和待追问问题，并追加写入 `assistant/realtime_assistant.md`。
- `8. 会议纪要整理（离线）`：分批处理完整转录，生成六个固定章节，并覆盖写入 `notes/meeting_notes.md`。

菜单 `7`、`8` 只实例化 `DummyLlmClient`，不会读取 API KEY、连接网络或调用真实模型。

## 当前阶段尚未实现

- 真实 ASR WebSocket 连接和云端实时转录
- 真实 LLM 实时辅助和云端会议纪要生成
- 面向生产环境的说话人声纹识别模型

ASR 和 LLM 离线演示结果始终标记为“模拟文本”，不会冒充真实服务结果。

## 项目目录

```text
meeting_assistant/
├─ main.py                     程序入口
├─ requirements.txt            Python 依赖清单
├─ .env.example                环境变量示例
├─ .gitignore                  Git 忽略规则
├─ README.md                   使用说明
├─ config/
│  └─ settings.yaml            普通配置
├─ app/
│  ├─ __init__.py
│  ├─ config.py                配置加载
│  ├─ logger.py                日志设置
│  ├─ models.py                数据模型
│  ├─ project_manager.py       会议项目管理
│  ├─ context_loader.py        热词和背景资料加载
│  ├─ audio_recorder.py        本地录音和 WAV 保存
│  ├─ audio_stream.py          WAV 异步切片
│  ├─ asr_client.py            真实 ASR 接口和离线模拟客户端
│  ├─ llm_client.py            OpenAI-compatible 接口和离线模拟客户端
│  ├─ assistant_runner.py      周期性实时辅助
│  ├─ summary_writer.py        六章会议纪要整理
│  ├─ speaker_labeler.py       MFCC 与离线说话人聚类标注
│  ├─ realtime_pipeline.py     在线会议三协程调度器
│  └─ cli.py                   中文命令行菜单
├─ tests/
│  ├─ test_speaker.py          说话人聚类测试
│  ├─ test_audio.py            音频缓冲与静音测试
│  ├─ test_asr.py              ASR 结果解析测试
│  └─ test_llm.py              Dummy LLM 契约测试
├─ tools/
│  ├─ __init__.py
│  ├─ evaluate.py              WER 与延迟评测
│  └─ package.py               ZIP 与 SHA256 生成
├─ .pre-commit-config.yaml     提交前质量门
├─ projects/                   运行后创建会议项目
│  └─ .gitkeep
└─ logs/                       运行后写入日志
   └─ .gitkeep
```

## 环境要求

- Windows 10 或 Windows 11
- Python 3.11 或更高版本
- Visual Studio Code
- 建议安装 VS Code 的 Python 扩展

## 在 VS Code 中打开

1. 启动 VS Code。
2. 选择“文件” -> “打开文件夹”。
3. 选择本项目的 `meeting_assistant` 文件夹。
4. 选择“终端” -> “新建终端”，确认终端类型为 PowerShell。

下面所有命令都需要由用户在 VS Code 的 PowerShell 终端中手动执行。

## 创建虚拟环境

先确认终端位于项目根目录，再执行：

```powershell
py -3.12 -m venv .venv
```

激活虚拟环境：

```powershell
.\.venv\Scripts\Activate.ps1
```

如果以后更换了 Python 版本，也可以让启动器自动使用当前默认版本：

```powershell
py -m venv .venv
```

如果电脑上没有 `py` 命令，也可以尝试：

```powershell
python -m venv .venv
```

## 第七阶段质量依赖与安装

虚拟环境激活后，由用户手动安装测试、评测和格式化依赖：

```powershell
python -m pip install pytest python-Levenshtein pre-commit ruff black isort
```

手动运行质量检查：

```powershell
pytest -q
pre-commit run --all-files
```

### 贡献代码指南

首次参与项目开发时，在虚拟环境中手动执行：

```powershell
pre-commit install
```

此后执行 `git commit` 时会自动运行 Black、isort、Ruff 和 pytest。格式化或测试失败时，先根据终端提示修改，再重新提交。

## 第六阶段依赖与安装

第六阶段复用 `sounddevice`、`soundfile`、`numpy`、`websockets` 和 `openai`：

```powershell
python -m pip install --timeout 300 sounddevice soundfile numpy "websockets>=15,<16" openai
```

安装依赖不会自动连接麦克风、ASR 或 LLM；只有用户主动选择菜单 `10` 才会启动在线链路。

## 第五阶段依赖与安装

第五阶段增加 `librosa`、`scikit-learn` 和 `scipy`。虚拟环境激活后，建议执行：

```powershell
python -m pip install --timeout 300 librosa scikit-learn scipy
```

这些依赖只读取和分析已有 WAV 文件，不会访问麦克风或播放音频。

`requirements.txt` 同时列出了后续阶段明确需要的全部依赖。等开发到对应阶段、网络状况良好时，再手动执行：

```powershell
python -m pip install --timeout 120 -r requirements.txt
```

完整依赖下载量较大；如果下载超时，可以稍后重新执行。第五阶段离线演示不会建立 WebSocket、HTTP、ASR 或 LLM 连接。

## 准备环境变量

复制示例文件：

```powershell
Copy-Item .env.example .env
```

第一阶段不要求填写 API 密钥。请勿把含有真实密钥的 `.env` 文件发送给他人或提交到 Git。

## 启动程序

在已激活虚拟环境的 VS Code PowerShell 终端中执行：

```powershell
python main.py
```

程序会显示八个中文菜单，包括录音测试、实时转录离线模拟、实时辅助演示和会议纪要整理。

## 第一阶段回归验收

请按以下顺序操作：

1. 启动 `main.py`，确认终端显示中文标题和四个菜单选项。
2. 选择菜单 `1`，输入项目名称 `软件需求讨论会议`。
3. 打开 `projects/软件需求讨论会议`，确认存在项目说明、热词文件以及 `background`、`transcripts`、`notes`、`assistant`、`recordings` 子目录。
4. 再次创建同名项目，确认原目录未被覆盖，新目录名称增加了时间戳。
5. 选择菜单 `2`，确认两个项目都能被列出。
6. 编辑某个项目的 `hotwords.md`，加入每行一个热词和 `- 热词` 格式的内容，并故意重复一个热词。
7. 在该项目的 `background` 中新建一个 `.md` 或 `.markdown` 文件；也可以放进新建的子目录，以检查递归读取。
8. 选择菜单 `3` 并选择该项目，确认显示去重后的热词数量、背景文件数量、文件名称和背景资料总字符数，且不会输出很长的完整正文。
9. 检查 `logs/meeting_assistant.log`，确认其中含有时间、日志级别、模块名称和日志内容。
10. 分别尝试空输入、非数字菜单编号和不存在的项目编号，确认程序显示容易理解的中文提示。
11. 按 `Ctrl+C` 或选择菜单 `4`，确认程序能够友好退出。

## 第二阶段手动验收

开始前请确认电脑连接了可用麦克风，并允许 VS Code 或终端访问麦克风。录音只保存在所选会议项目的 `recordings` 目录，不会发送到网络。

1. 启动 `main.py`，确认菜单出现 `5. 录音测试`，且原有菜单 `1-4` 编号不变。
2. 选择菜单 `5`，从列表中选择一个已经创建的会议项目。
3. 按提示开始录音，对着麦克风说话数秒，然后按 Enter 结束录音。
4. 确认终端显示 WAV 保存路径、文件大小和录音时长。
5. 打开所选项目的 `recordings` 目录，双击播放 WAV，确认声音内容和时长正常。
6. 再次录音，确认生成新的时间戳文件，并且没有覆盖上一条录音。
7. 在没有麦克风、麦克风权限关闭或设备被占用的情况下选择录音，确认程序显示中文提示并返回主菜单。
8. 查看 `logs/meeting_assistant.log`，确认包含 INFO 级别的“开始录音”和“保存 WAV 完成”日志。

## 第三阶段手动验收

第三阶段使用第二阶段已经保存的 WAV 文件进行离线模拟，不需要麦克风、API 密钥或网络连接。

1. 启动 `main.py`，确认菜单出现 `6. 实时转录（离线模拟）`，原有菜单 `1-5` 编号不变。
2. 选择菜单 `6`，按提示选择一个已有会议项目，再选择该项目 `recordings` 目录中的 WAV 文件。
3. 确认终端依次滚动显示三条 `[Partial]` 模拟中间结果和一条 `[Final]` 模拟最终结果。
4. 打开所选项目的 `transcripts/raw_transcript.md`，确认末尾追加了标题为“模拟转录 yyyy-mm-dd hh:mm:ss”的文本段落。
5. 检查 `logs/meeting_assistant.log`，确认包含 INFO 级别的“ASR 模拟开始”和“ASR 模拟结束”日志。
6. 在项目没有 WAV、WAV 格式错误或选择编号错误时重试，确认程序显示中文提示并返回主菜单。
7. 在选择项目、选择 WAV 或模拟输出期间按 `Ctrl+C`，确认程序友好取消且不会连接网络。

## 第四阶段手动验收

第四阶段只读取项目中的 Markdown 转录，并使用固定 JSON 模板生成模拟结果。没有 `.env`、API KEY 或网络连接也可以运行。

1. 启动 `main.py`，确认菜单出现 `7. 实时辅助演示（离线）` 和 `8. 会议纪要整理（离线）`，原有菜单 `1-6` 编号不变。
2. 选择菜单 `7` 和一个已有模拟转录的项目，确认终端立即显示“🛈 新术语”“🛈 关键点”“⚠ 风险”和“🛈 待追问”。
3. 保持菜单 `7` 运行，在 `raw_transcript.md` 末尾增加文本；等待配置的间隔时间，确认终端出现新提示，`assistant/realtime_assistant.md` 追加一个带时间戳的辅助更新。
4. 按 `Ctrl+C`，确认实时辅助结束并返回主菜单。
5. 选择菜单 `8` 和同一项目，确认终端提示整理完成。
6. 打开 `notes/meeting_notes.md`，确认原内容被覆盖，并包含会议目标、已确认信息、关键问题、风险和不确定性、待追问问题、行动项六个章节。
7. 确认六个章节均包含以 `<模拟` 开头的占位文本。
8. 检查 `logs/meeting_assistant.log`，确认包含“LLM 模拟开始”和“LLM 模拟结束”日志。
9. 使用没有有效转录的项目、取消项目选择或按 `Ctrl+C`，确认程序显示中文提示并返回主菜单。

## 第五阶段手动验收

第五阶段使用项目中已经保存的 WAV 和转录文件，不需要麦克风、API KEY 或网络连接。

1. 启动 `main.py`，确认菜单出现 `9. 说话人标注（离线）`，原有菜单 `1-8` 编号不变。
2. 选择菜单 `9`，按提示选择一个已有会议项目和该项目中的 WAV 文件。
3. 确认终端打印每个音频段的 `[speaker_n]`、开始时间和结束时间，并显示识别到的说话人数。
4. 打开项目的 `transcripts/raw_transcript.md`，确认转录正文行以 `[speaker_0]`、`[speaker_1]` 或 `[speaker_2]` 开头。
5. 再次执行同一文件的标注，确认旧标签被替换，没有出现重复前缀。
6. 检查 `logs/meeting_assistant.log`，确认包含 INFO 级别的 `speaker labeling start` 和 `speaker labeling finish`。
7. 选择格式错误、非 16 kHz 或非单声道 WAV，确认程序显示中文提示并返回主菜单。
8. 在项目或 WAV 选择时按 `Ctrl+C`，确认程序友好取消。

## 第六阶段手动验收

第六阶段会实际访问麦克风、阿里云 ASR 和可选的 LLM API，只能由用户在确认密钥、网络和设备权限后手动执行。

1. 在 `.env` 填写真实 `ASR_API_KEY` 和 `ASR_WEBSOCKET_URL`；如需真实辅助，再填写 `LLM_API_KEY`、`LLM_BASE_URL` 和 `LLM_MODEL`。
2. 启动 `main.py`，确认菜单出现 `10. 实时会议演示（在线）`，原有菜单 `1-9` 编号不变。
3. 暂时移除 ASR 密钥或地址后选择菜单 `10`，确认显示“暂未配置在线参数”并返回主菜单。
4. 恢复在线参数，选择菜单 `10` 和一个会议项目，确认终端滚动显示 `[Partial]` 与 `[Final]` 实时文字。
5. 持续讲话约 30 秒，确认每隔配置的时间出现术语、关键点、风险和待追问提示。
6. 按 `Ctrl+C` 停止会议，确认程序返回主菜单，没有遗留运行中的音频流或连接。
7. 检查项目 `recordings/`，确认生成新的 WAV 文件且没有覆盖旧文件。
8. 检查 `transcripts/raw_transcript.md`，确认追加了实时会议标题、中间结果和最终结果。
9. 检查 `assistant/realtime_assistant.md`，确认追加了最新辅助段落。
10. 检查日志是否包含 `realtime_pipeline start`、`realtime_pipeline stop`、`asr reconnect` 和 `llm request`；使用 Dummy 时还应包含 `llm fallback dummy`。
11. 临时断开网络后恢复，确认日志记录 `asr reconnect`，恢复后链路继续接收结果。

## 第七阶段手动验收

1. 激活虚拟环境并手动安装 `pytest`、`python-Levenshtein`、`pre-commit`、`ruff`、`black` 和 `isort`。
2. 手动执行 `pytest -q`，确认不少于 10 个测试全部通过。
   项目已通过 `pytest.ini` 使用 `importlib` 导入模式，允许根目录存在同名的个人测试脚本。
3. 在某个会议项目的 `transcripts/` 中创建 UTF-8 编码的 `reference.txt`，填写人工参考文本。
4. 启动主程序，确认菜单出现 `11. 运行离线评测` 和 `12. 生成发布包`，原菜单 `1-10` 编号不变。
5. 选择菜单 `11` 和准备好的项目，确认项目根目录生成 `evaluation.md`。
6. 打开报告，确认包含 WER、平均转录延迟、参考词数、转录词数和简要结论。
7. 删除或重命名 `reference.txt` 后再次评测，确认程序显示中文缺失提示并返回菜单。
8. 选择菜单 `12`，确认生成 `dist/meeting_assistant_<version>.zip` 和 `dist/SHA256.txt`。
9. 检查 ZIP，确认不包含 `.env`、`.venv`、日志、缓存或 WAV 文件。
10. 手动执行 `pre-commit install`，再执行 `pre-commit run --all-files`，确认格式化、静态检查和 pytest 钩子运行。

## 新建项目的内容

每个会议项目会自动生成：

```text
项目目录/
├─ project_info.yaml
├─ hotwords.md
├─ background/
│  └─ README.md
├─ transcripts/
│  └─ raw_transcript.md
├─ notes/
│  └─ meeting_notes.md
├─ assistant/
│  └─ realtime_assistant.md
└─ recordings/
   └─ .gitkeep
```

项目名称中的 Windows 非法字符会被替换。同名项目会增加时间戳，不会覆盖已有项目文件。

## 配置说明

普通配置位于 `config/settings.yaml`。第六阶段使用 `asr.reconnect_seconds` 控制重连等待时间，使用 `pipeline.wav_save` 控制停止时是否保存 WAV，并使用 `pipeline.wav_path_pattern` 设置录音文件名。离线菜单不会连接 ASR 或 LLM 地址。

密钥类配置位于本地 `.env`。没有 `.env` 或没有 API 密钥不会阻止第一阶段运行。日志只记录“密钥未配置”的提示，不会记录密钥内容。

## 常见问题

### 找不到 Python

在 PowerShell 执行 `py --version` 或 `python --version`。如果两个命令都不可用，请从 Python 官方网站安装 Python 3.11 或更高版本，并在安装界面勾选将 Python 添加到 PATH。

### 提示找不到模块

先确认 VS Code 使用的是项目 `.venv` 中的 Python，再激活虚拟环境并手动安装第三阶段依赖：`python -m pip install --timeout 120 python-dotenv PyYAML sounddevice soundfile numpy websockets`。常见缺少模块为 `dotenv`、`yaml`、`sounddevice`、`soundfile` 或 `websockets`。

### YAML 配置错误

YAML 使用空格缩进，不能使用 Tab。请对照默认的 `config/settings.yaml` 检查冒号、引号和缩进。不要随意删除 `paths`、`logging`、`audio`、`asr`、`llm` 或 `speaker` 配置段。

### 项目名称为空

项目名称不能是空白内容，也不能只由 Windows 文件名非法字符组成。请使用能说明会议用途的名称，例如“软件需求讨论会议”。

### 中文路径问题

本项目所有文本文件都使用 UTF-8，并通过 `pathlib` 处理路径。建议把项目放在当前 Windows 用户有读写权限的文件夹中；不要放在受系统保护的目录。如果终端中文显示异常，请确认 VS Code 文件编码和终端编码为 UTF-8。

### PowerShell 不允许激活虚拟环境

可以仅对当前 PowerShell 窗口调整执行策略，然后重新激活：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

该设置只影响当前终端窗口，关闭窗口后失效。
