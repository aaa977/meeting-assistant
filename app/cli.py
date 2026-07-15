"""面向零基础用户的中文命令行菜单。"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path

from app.audio_recorder import AudioRecorderError, get_wav_duration, record_and_save
from app.assistant_runner import AssistantRunnerError, run_assistant_loop
from app.asr_client import AsrError, DummyAsrClient
from app.audio_stream import AudioStreamError, generate_wav_chunks
from app.config import AppConfig, load_config
from app.context_loader import load_project_context
from app.llm_client import DummyLlmClient, LlmError
from app.models import AsrFinalResult, AsrResultChunk, MeetingProject
from app.project_manager import ProjectManager
from app.realtime_pipeline import RealtimePipelineError, run_realtime_meeting
from app.speaker_labeler import SpeakerLabelerError, label_speakers
from app.summary_writer import SummaryWriterError, write_meeting_summary
from tools.evaluate import EvaluationError, main as evaluate_project
from tools.package import PackageError, main as package_project


LOGGER = logging.getLogger(__name__)
DIVIDER = "=" * 50


def run_cli(project_manager: ProjectManager, config: AppConfig) -> None:
    """显示菜单并处理用户操作，直到用户选择退出。"""
    _show_title()
    while True:
        _show_menu()
        try:
            choice = input("请输入菜单编号（1-12）：").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n已收到退出操作，程序安全结束。")
            return

        if choice == "1":
            _create_project(project_manager)
        elif choice == "2":
            _show_existing_projects(project_manager)
        elif choice == "3":
            _show_project_context(project_manager)
        elif choice == "4":
            print("感谢使用，程序已退出。")
            return
        elif choice == "5":
            _record_audio(project_manager, config)
        elif choice == "6":
            run_asr_demo(project_manager, config)
        elif choice == "7":
            _run_offline_assistant(project_manager, config)
        elif choice == "8":
            _write_offline_summary(project_manager)
        elif choice == "9":
            run_offline_speaker_labeling(project_manager, config)
        elif choice == "10":
            _run_online_realtime_meeting(project_manager, config)
        elif choice == "11":
            _run_offline_evaluation(project_manager)
        elif choice == "12":
            _generate_release_package(config)
        elif not choice:
            print("输入不能为空，请输入 1 到 12 之间的菜单编号。")
        elif not choice.isdigit():
            print("请输入数字菜单编号，例如输入 1 创建项目。")
        else:
            print("没有这个菜单选项，请输入 1 到 12 之间的菜单编号。")


def _show_title() -> None:
    """显示当前阶段标题。"""
    print(DIVIDER)
    print("面向会议场景的实时语音转录与智能辅助系统")
    print("第七阶段：质量评测与发布交付")
    print(DIVIDER)


def _show_menu() -> None:
    """显示主菜单。"""
    print("\n请选择要进行的操作：")
    print("1. 创建新的会议项目")
    print("2. 查看已有会议项目")
    print("3. 加载项目并查看背景资料摘要")
    print("4. 退出程序")
    print("5. 录音测试")
    print("6. 实时转录（离线模拟）")
    print("7. 实时辅助演示（离线）")
    print("8. 会议纪要整理（离线）")
    print("9. 说话人标注（离线）")
    print("10. 实时会议演示（在线）")
    print("11. 运行离线评测")
    print("12. 生成发布包")


def _create_project(project_manager: ProjectManager) -> None:
    """询问名称并创建项目。"""
    try:
        project_name = input("请输入会议项目名称：").strip()
        if not project_name:
            print("项目名称不能为空，请重新选择菜单 1 后输入名称。")
            return
        project = project_manager.create_project(project_name)
    except (KeyboardInterrupt, EOFError):
        print("\n已取消创建项目。")
        return
    except (OSError, ValueError) as error:
        LOGGER.warning("创建项目未完成：%s", error)
        print(f"创建项目失败：{error}")
        return

    print("\n项目创建成功：")
    print(f"项目名称：{project.project_name}")
    print(f"项目目录：{project.project_directory}")
    print(f"热词文件：{project.hotwords_file}")
    print(f"背景资料目录：{project.background_directory}")
    print(f"原始转录文件：{project.transcript_file}")
    print(f"会议纪要文件：{project.ai_notes_file}")
    print(f"实时辅助文件：{project.ai_assistant_file}")
    print(f"录音目录：{project.recordings_directory}")


def _show_existing_projects(project_manager: ProjectManager) -> None:
    """列出所有有效项目。"""
    try:
        projects = project_manager.list_projects()
    except OSError as error:
        LOGGER.warning("读取项目列表失败：%s", error)
        print(f"暂时无法读取项目列表：{error}")
        return

    if not projects:
        print("\n目前还没有有效的会议项目，请先选择菜单 1 创建。")
        return

    print("\n已有会议项目：")
    for number, project in enumerate(projects, start=1):
        print(
            f"{number}. {project.project_name} "
            f"（目录：{project.safe_directory_name}）"
        )


def _show_project_context(project_manager: ProjectManager) -> None:
    """让用户选择项目，并显示热词和背景资料摘要。"""
    try:
        projects = project_manager.list_projects()
    except OSError as error:
        LOGGER.warning("读取项目列表失败：%s", error)
        print(f"暂时无法读取项目列表：{error}")
        return

    if not projects:
        print("\n目前没有可加载的项目，请先选择菜单 1 创建。")
        return

    print("\n请选择要加载的项目：")
    for number, project in enumerate(projects, start=1):
        print(f"{number}. {project.project_name}")

    selected_project = _ask_for_project(projects)
    if selected_project is None:
        return

    context = load_project_context(selected_project)
    print("\n项目背景资料摘要：")
    print(f"项目名称：{context.project_name}")
    print(f"热词数量：{len(context.hotwords)}")
    print(
        "热词列表："
        + ("、".join(context.hotwords) if context.hotwords else "暂无热词")
    )
    print(f"Markdown 背景文件数量：{len(context.background_documents)}")
    if context.background_documents:
        print("背景文件名称：")
        for file_name in context.background_documents:
            print(f"- {file_name}")
    else:
        print("背景文件名称：暂无背景文件")
    print(f"背景资料总字符数：{len(context.combined_background_text)}")


def _ask_for_project(projects: list[MeetingProject]) -> MeetingProject | None:
    """读取项目编号并返回对应项目。"""
    try:
        selection = input("请输入项目编号，直接按回车可取消：").strip()
    except (KeyboardInterrupt, EOFError):
        print("\n已取消加载项目。")
        return None

    if not selection:
        print("已取消加载项目。")
        return None
    if not selection.isdigit():
        print("项目编号必须是数字，本次加载已取消。")
        return None

    index = int(selection) - 1
    if index < 0 or index >= len(projects):
        print("选择的项目不存在，请核对列表中的编号。")
        return None
    return projects[index]


def _record_audio(project_manager: ProjectManager, config: AppConfig) -> None:
    """选择项目，录制麦克风音频并显示 WAV 保存信息。"""
    try:
        projects = project_manager.list_projects()
    except OSError as error:
        LOGGER.warning("读取项目列表失败：%s", error)
        print(f"暂时无法读取项目列表：{error}")
        return

    if not projects:
        print("\n目前没有用于保存录音的项目，请先选择菜单 1 创建。")
        return

    print("\n请选择录音所属的会议项目：")
    for number, project in enumerate(projects, start=1):
        print(f"{number}. {project.project_name}")

    selected_project = _ask_for_project(projects)
    if selected_project is None:
        return

    print("\n即将开始使用本地麦克风录音。")
    try:
        input("准备好后按 Enter 开始录音：")
        print("正在录音，请说话；按 Enter 结束录音。")
        output_path = record_and_save(
            selected_project,
            sample_rate=config.audio_sample_rate,
            channels=config.audio_channels,
            block_size=config.audio_block_size,
        )
        file_size_kb = output_path.stat().st_size / 1024
        duration_seconds = get_wav_duration(output_path)
    except AudioRecorderError as error:
        LOGGER.warning("录音测试失败：%s", error)
        print(f"录音未完成：{error}")
        return
    except (KeyboardInterrupt, EOFError):
        LOGGER.info("用户取消录音测试。")
        print("\n已取消本次录音，主菜单仍可继续使用。")
        return
    except Exception as error:
        LOGGER.exception("录音测试发生未预期错误。")
        print(
            "录音未完成：找不到可用麦克风，或麦克风正被占用。"
            "请检查设备连接、Windows 麦克风权限和默认输入设备。"
        )
        return

    print("\n录音保存成功：")
    print(f"保存路径：{output_path}")
    print(f"文件大小：{file_size_kb:.1f} KB")
    print(f"录音时长：{duration_seconds:.2f} 秒")


def run_asr_demo(project_manager: ProjectManager, config: AppConfig) -> None:
    """选择已有 WAV，运行不会联网的 ASR 异步链路模拟。"""
    try:
        projects = project_manager.list_projects()
    except OSError as error:
        LOGGER.warning("读取项目列表失败：%s", error)
        print(f"暂时无法读取项目列表：{error}")
        return

    if not projects:
        print("\n目前没有可用于模拟转录的项目，请先创建项目并录音。")
        return

    print("\n请选择模拟转录所属的会议项目：")
    for number, project in enumerate(projects, start=1):
        print(f"{number}. {project.project_name}")
    selected_project = _ask_for_project(projects)
    if selected_project is None:
        return

    wav_files = sorted(
        selected_project.recordings_directory.glob("*.wav"),
        key=lambda path: path.name.casefold(),
    )
    if not wav_files:
        print("该项目还没有 WAV 录音，请先选择菜单 5 完成一段录音。")
        return

    selected_wav = _ask_for_wav_file(wav_files)
    if selected_wav is None:
        return

    LOGGER.info(
        "ASR 模拟开始：项目=%s，文件=%s",
        selected_project.safe_directory_name,
        selected_wav.name,
    )
    print("\n开始离线模拟。本操作不会连接网络或真实 ASR 服务。")
    try:
        asyncio.run(
            _run_asr_demo_async(
                project=selected_project,
                wav_file=selected_wav,
                sample_rate=config.audio_sample_rate,
                block_size=config.asr_block_size,
            )
        )
    except (AsrError, AudioStreamError, OSError, UnicodeError) as error:
        LOGGER.warning("ASR 离线模拟失败：%s", error)
        print(f"模拟转录未完成：{error}")
        return
    except (KeyboardInterrupt, EOFError):
        LOGGER.info("用户取消 ASR 离线模拟。")
        print("\n已取消模拟转录，主菜单仍可继续使用。")
        return
    except Exception:
        LOGGER.exception("ASR 离线模拟发生未预期错误。")
        print("模拟转录遇到未预期问题，请查看日志了解详细信息。")
        return

    LOGGER.info(
        "ASR 模拟结束：项目=%s，文件=%s",
        selected_project.safe_directory_name,
        selected_wav.name,
    )
    print(f"模拟转录已追加到：{selected_project.transcript_file}")


def _ask_for_wav_file(wav_files: list[Path]) -> Path | None:
    """显示 WAV 列表并读取用户选择。"""
    print("\n请选择用于离线模拟的 WAV 文件：")
    for number, wav_file in enumerate(wav_files, start=1):
        print(f"{number}. {wav_file.name}")

    try:
        selection = input("请输入 WAV 编号，直接按回车可取消：").strip()
    except (KeyboardInterrupt, EOFError):
        print("\n已取消模拟转录。")
        return None

    if not selection:
        print("已取消模拟转录。")
        return None
    if not selection.isdigit():
        print("WAV 编号必须是数字，本次模拟已取消。")
        return None

    index = int(selection) - 1
    if index < 0 or index >= len(wav_files):
        print("选择的 WAV 文件不存在，请核对列表中的编号。")
        return None
    return wav_files[index]


async def _run_asr_demo_async(
    project: MeetingProject,
    wav_file: Path,
    sample_rate: int,
    block_size: int,
) -> None:
    """把 WAV 切片送入模拟客户端，并追加最终模拟文本。"""
    final_texts: list[str] = []
    async with DummyAsrClient(sample_rate=sample_rate) as client:
        async for chunk in generate_wav_chunks(wav_file, block_size):
            await client.send_audio(chunk)
        await client.send_audio(b"", is_last=True)

        async for result in client.receive_results():
            _print_asr_result(result)
            if isinstance(result, AsrFinalResult) and result.text:
                final_texts.append(result.text)

    if not final_texts:
        raise AsrError("模拟客户端没有返回最终转录文本。")
    _append_simulated_transcript(project, "\n".join(final_texts))


def _print_asr_result(result: AsrResultChunk | AsrFinalResult) -> None:
    """以统一格式滚动显示中间结果和最终结果。"""
    if isinstance(result, AsrFinalResult):
        print(f"[Final] {result.text}", flush=True)
    else:
        print(f"[Partial] {result.text}", flush=True)


def _append_simulated_transcript(project: MeetingProject, final_text: str) -> None:
    """把最终模拟文本以 UTF-8 追加到项目原始转录文件。"""
    timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
    section = (
        f"\n\n## 模拟转录 {timestamp}\n\n"
        f"{final_text}\n"
    )
    try:
        with project.transcript_file.open("a", encoding="utf-8", newline="\n") as file:
            file.write(section)
    except OSError as error:
        raise OSError(f"无法追加模拟转录文件：{error}") from error


def _run_offline_assistant(
    project_manager: ProjectManager,
    config: AppConfig,
) -> None:
    """启动只使用 DummyLlmClient 的周期性实时辅助演示。"""
    project = _choose_project_for_feature(project_manager, "实时辅助")
    if project is None:
        return
    if not _transcript_has_content(project.transcript_file):
        print("转录文件没有可分析的内容，请先完成菜单 6 的离线转录模拟。")
        return

    print("\n实时辅助离线演示已启动，不会访问网络或真实 LLM。")
    print(
        f"程序每 {config.ai_assistant_interval_seconds} 秒检查一次转录变化；"
        "按 Ctrl+C 可结束演示并返回主菜单。"
    )
    client = DummyLlmClient()
    try:
        asyncio.run(
            run_assistant_loop(
                transcript_path=project.transcript_file,
                assistant_path=project.ai_assistant_file,
                llm_client=client,
                interval_sec=config.ai_assistant_interval_seconds,
            )
        )
    except (AssistantRunnerError, LlmError, OSError, UnicodeError) as error:
        LOGGER.warning("实时辅助离线演示失败：%s", error)
        print(f"实时辅助未完成：{error}")
    except (KeyboardInterrupt, EOFError):
        LOGGER.info("用户结束实时辅助离线演示。")
        print("\n实时辅助演示已结束，返回主菜单。")
    except Exception:
        LOGGER.exception("实时辅助离线演示发生未预期错误。")
        print("实时辅助遇到未预期问题，请查看日志了解详细信息。")


def _write_offline_summary(project_manager: ProjectManager) -> None:
    """使用 DummyLlmClient 生成并覆盖写入六章会议纪要。"""
    project = _choose_project_for_feature(project_manager, "会议纪要整理")
    if project is None:
        return
    if not _transcript_has_content(project.transcript_file):
        print("转录文件没有可整理的内容，请先完成菜单 6 的离线转录模拟。")
        return

    print("\n开始整理离线模拟纪要，不会访问网络或真实 LLM。")
    client = DummyLlmClient()
    try:
        asyncio.run(
            write_meeting_summary(
                transcript_path=project.transcript_file,
                summary_path=project.ai_notes_file,
                llm_client=client,
            )
        )
    except (SummaryWriterError, LlmError, OSError, UnicodeError) as error:
        LOGGER.warning("会议纪要离线整理失败：%s", error)
        print(f"会议纪要整理未完成：{error}")
        return
    except (KeyboardInterrupt, EOFError):
        LOGGER.info("用户取消会议纪要离线整理。")
        print("\n已取消会议纪要整理，返回主菜单。")
        return
    except Exception:
        LOGGER.exception("会议纪要离线整理发生未预期错误。")
        print("会议纪要整理遇到未预期问题，请查看日志了解详细信息。")
        return

    print("会议纪要整理完成：")
    print(f"保存位置：{project.ai_notes_file}")


def _choose_project_for_feature(
    project_manager: ProjectManager,
    feature_name: str,
) -> MeetingProject | None:
    """为离线 LLM 功能列出项目并返回用户选择。"""
    try:
        projects = project_manager.list_projects()
    except OSError as error:
        LOGGER.warning("读取项目列表失败：%s", error)
        print(f"暂时无法读取项目列表：{error}")
        return None
    if not projects:
        print(f"目前没有可用于{feature_name}的项目，请先创建会议项目。")
        return None

    print(f"\n请选择用于{feature_name}的会议项目：")
    for number, project in enumerate(projects, start=1):
        print(f"{number}. {project.project_name}")
    return _ask_for_project(projects)


def _transcript_has_content(transcript_path: Path) -> bool:
    """检查转录文件是否存在非空内容，读取失败时记录日志。"""
    try:
        return transcript_path.is_file() and bool(
            transcript_path.read_text(encoding="utf-8").strip()
        )
    except (OSError, UnicodeError) as error:
        LOGGER.warning("无法检查转录文件 %s：%s", transcript_path, error)
        return False


def run_offline_speaker_labeling(
    project_manager: ProjectManager,
    config: AppConfig,
) -> None:
    """选择已有 WAV，离线聚类并把说话人标签写入转录。"""
    project = _choose_project_for_feature(project_manager, "说话人标注")
    if project is None:
        return

    wav_files = sorted(
        project.recordings_directory.glob("*.wav"),
        key=lambda path: path.name.casefold(),
    )
    if not wav_files:
        print("该项目还没有 WAV 录音，请先选择菜单 5 完成一段录音。")
        return
    selected_wav = _ask_for_wav_file(wav_files)
    if selected_wav is None:
        return

    print("\n开始离线说话人标注。本操作只读取 WAV，不播放音频或访问声卡。")
    try:
        segments = asyncio.run(
            label_speakers(
                wav_path=selected_wav,
                transcript_path=project.transcript_file,
                n_mfcc=config.speaker_mfcc_n_mfcc,
                cluster_threshold=config.speaker_cluster_threshold,
                max_speakers=config.max_speakers,
            )
        )
    except SpeakerLabelerError as error:
        LOGGER.warning("离线说话人标注失败：%s", error)
        print(f"说话人标注未完成：{error}")
        return
    except (KeyboardInterrupt, EOFError):
        LOGGER.info("用户取消离线说话人标注。")
        print("\n已取消说话人标注，返回主菜单。")
        return
    except Exception:
        LOGGER.exception("离线说话人标注发生未预期错误。")
        print("说话人标注遇到未预期问题，请查看日志了解详细信息。")
        return

    print("\n说话人标注完成：")
    for segment in segments:
        print(
            f"[{segment.speaker_id}] "
            f"{segment.start_time:.2f} - {segment.end_time:.2f} 秒"
        )
    unique_speakers = {segment.speaker_id for segment in segments}
    print(f"识别到的说话人数：{len(unique_speakers)}")
    print(f"标注后转录文件：{project.transcript_file}")


def _run_online_realtime_meeting(
    project_manager: ProjectManager,
    config: AppConfig,
) -> None:
    """检查在线参数，选择项目并启动实时会议协同流水线。"""
    try:
        # 用户可能在程序运行期间修改 .env，进入在线菜单时重新读取。
        config = load_config()
    except (FileNotFoundError, OSError, ValueError) as error:
        LOGGER.warning("重新加载在线配置失败：%s", error)
        print(f"无法读取最新在线配置：{error}")
        return

    if not config.asr_api_key or not config.asr_websocket_url:
        print(
            "暂未配置在线参数，请先保存 .env，并填写 "
            "ASR_API_KEY 和 ASR_WEBSOCKET_URL。"
        )
        return

    project = _choose_project_for_feature(project_manager, "实时会议演示")
    if project is None:
        return

    if config.llm_api_key and config.llm_model:
        print("LLM 在线参数已配置，将使用 OpenAI-compatible Chat API。")
    else:
        print("LLM 参数不完整，将自动使用离线 DummyLlmClient。")
    print("\n即将启动麦克风、ASR WebSocket 和实时辅助。")
    print("会议过程中按 Ctrl+C 可停止，并按配置保存 WAV。")

    try:
        asyncio.run(run_realtime_meeting(project, config))
    except RealtimePipelineError as error:
        LOGGER.warning("实时会议演示失败：%s", error)
        print(f"实时会议未完成：{error}")
    except (KeyboardInterrupt, EOFError):
        LOGGER.info("用户停止实时会议演示。")
        print("\n实时会议已停止，录音和文本已按当前配置保存。")
    except Exception:
        LOGGER.exception("实时会议演示发生未预期错误。")
        print("实时会议遇到未预期问题，请查看日志了解详细信息。")


def _run_offline_evaluation(project_manager: ProjectManager) -> None:
    """选择项目，计算 WER 和时间戳平均间隔并生成报告。"""
    project = _choose_project_for_feature(project_manager, "离线评测")
    if project is None:
        return
    try:
        report_path = evaluate_project(project.project_directory)
    except EvaluationError as error:
        LOGGER.warning("离线评测失败：%s", error)
        print(f"离线评测未完成：{error}")
        return
    except Exception:
        LOGGER.exception("离线评测发生未预期错误。")
        print("离线评测遇到未预期问题，请查看日志了解详细信息。")
        return

    LOGGER.info("离线评测完成：%s", report_path)
    print("离线评测完成：")
    print(f"报告位置：{report_path}")


def _generate_release_package(config: AppConfig) -> None:
    """生成项目 ZIP 发布包和 SHA256 校验文件。"""
    print("\n开始生成发布包；密钥、日志、缓存、虚拟环境和 WAV 将被排除。")
    try:
        zip_path, checksum_path = package_project(config.app_version)
    except PackageError as error:
        LOGGER.warning("生成发布包失败：%s", error)
        print(f"发布包生成失败：{error}")
        return
    except Exception:
        LOGGER.exception("生成发布包时发生未预期错误。")
        print("发布包生成遇到未预期问题，请查看日志了解详细信息。")
        return

    LOGGER.info("发布包生成完成：%s", zip_path)
    print("发布包生成完成：")
    print(f"ZIP 文件：{zip_path}")
    print(f"SHA256 文件：{checksum_path}")
