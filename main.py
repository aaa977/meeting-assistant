"""第一阶段程序入口。"""

from __future__ import annotations

import logging
from pathlib import Path

from app.cli import run_cli
from app.config import load_config
from app.logger import setup_logging
from app.project_manager import ProjectManager


PROJECT_ROOT = Path(__file__).resolve().parent


def main() -> None:
    """初始化程序，并启动中文命令行菜单。"""
    logger = logging.getLogger(__name__)

    try:
        setup_logging(PROJECT_ROOT / "logs", "INFO")
    except OSError as error:
        print(f"无法创建日志文件，请检查项目文件夹权限。\n详细信息：{error}")
        return

    try:
        config = load_config()
        setup_logging(config.logs_root, config.log_level)
        logger.info("第七阶段程序启动。")

        project_manager = ProjectManager(
            projects_root=config.projects_root,
            project_version=config.app_version,
        )
        run_cli(project_manager, config)
    except FileNotFoundError as error:
        logger.error("缺少必要文件：%s", error)
        print(f"\n程序无法继续：找不到必要文件。\n详细信息：{error}")
    except PermissionError as error:
        logger.error("文件访问权限不足：%s", error)
        print("\n程序无法读写文件，请检查项目文件夹的访问权限。")
    except ValueError as error:
        logger.error("配置或输入内容有误：%s", error)
        print(f"\n程序发现一处需要修改的内容：{error}")
    except KeyboardInterrupt:
        logger.info("用户按下 Ctrl+C，程序结束。")
        print("\n已停止操作，程序安全退出。")
    except Exception:
        logger.exception("程序发生未处理的异常。")
        print(
            "\n程序遇到了未预期的问题。请查看 "
            "logs/meeting_assistant.log 获取详细信息。"
        )
    finally:
        logging.getLogger(__name__).info("第七阶段程序结束。")


if __name__ == "__main__":
    main()
