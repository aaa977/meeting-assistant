"""计算项目转录 WER 与平均输出间隔，并生成 Markdown 报告。"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path


FINAL_LINE = re.compile(r"\[Final\]\s*(.*)", re.IGNORECASE)
TIME_STAMP = re.compile(r"\[(\d{2}:\d{2}:\d{2})\]")
SPEAKER_PREFIX = re.compile(r"^\[speaker_\d+\]\s*", re.IGNORECASE)
MARKDOWN_PREFIX = re.compile(r"^[#>*+\-\s]+")


class EvaluationError(Exception):
    """评测输入缺失、文本无效或报告写入失败。"""


def compute_wer(reference: str, hypothesis: str) -> float:
    """按词计算错误率；参考文本为空时给出明确错误。"""
    reference_words = _tokenize(reference)
    hypothesis_words = _tokenize(hypothesis)
    if not reference_words:
        raise EvaluationError("参考文本没有可用于计算 WER 的词。")
    edit_distance = _word_edit_distance(reference_words, hypothesis_words)
    return edit_distance / len(reference_words)


def compute_latency(markdown_path: Path) -> float:
    """根据实时块时间戳计算相邻转录结果的平均输出间隔。"""
    markdown_path = Path(markdown_path)
    if not markdown_path.is_file():
        raise EvaluationError(f"找不到转录文件：{markdown_path}")
    try:
        content = markdown_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise EvaluationError(f"无法读取转录文件：{error}") from error

    seconds = [_time_to_seconds(value) for value in TIME_STAMP.findall(content)]
    intervals: list[float] = []
    for previous, current in zip(seconds, seconds[1:]):
        difference = current - previous
        if difference < 0:
            difference += 24 * 60 * 60
        intervals.append(float(difference))
    return sum(intervals) / len(intervals) if intervals else 0.0


def main(project_dir: Path) -> Path:
    """评测一个会议项目并返回 evaluation.md 路径。"""
    project_dir = Path(project_dir)
    transcript_path = project_dir / "transcripts" / "raw_transcript.md"
    reference_path = project_dir / "transcripts" / "reference.txt"
    if not transcript_path.is_file():
        raise EvaluationError(f"找不到转录文件：{transcript_path}")
    if not reference_path.is_file():
        raise EvaluationError(
            "缺少参考文本，请先创建 transcripts/reference.txt。"
        )

    try:
        transcript_markdown = transcript_path.read_text(encoding="utf-8")
        reference_text = reference_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise EvaluationError(f"无法读取评测文本：{error}") from error

    hypothesis_text = _extract_hypothesis(transcript_markdown)
    if not hypothesis_text.strip():
        raise EvaluationError("转录文件没有可用于评测的正文。")

    wer = compute_wer(reference_text, hypothesis_text)
    latency = compute_latency(transcript_path)
    report_path = project_dir / "evaluation.md"
    report = _build_report(
        project_name=project_dir.name,
        reference_text=reference_text,
        hypothesis_text=hypothesis_text,
        wer=wer,
        latency=latency,
    )
    try:
        report_path.write_text(report, encoding="utf-8", newline="\n")
    except OSError as error:
        raise EvaluationError(f"无法写入评测报告：{error}") from error
    return report_path


def _tokenize(text: str) -> list[str]:
    """进行适合中英文混合文本的基础分词。"""
    normalized = text.casefold()
    return re.findall(r"[\u4e00-\u9fff]|[a-z0-9]+", normalized)


def _word_edit_distance(reference: list[str], hypothesis: list[str]) -> int:
    """使用动态规划计算词级 Levenshtein 距离。"""
    previous_row = list(range(len(hypothesis) + 1))
    for reference_index, reference_word in enumerate(reference, start=1):
        current_row = [reference_index]
        for hypothesis_index, hypothesis_word in enumerate(hypothesis, start=1):
            substitution_cost = 0 if reference_word == hypothesis_word else 1
            current_row.append(
                min(
                    current_row[-1] + 1,
                    previous_row[hypothesis_index] + 1,
                    previous_row[hypothesis_index - 1] + substitution_cost,
                )
            )
        previous_row = current_row
    return previous_row[-1]


def _extract_hypothesis(markdown_text: str) -> str:
    """优先提取 Final 行；没有时退回普通 Markdown 正文。"""
    final_lines = [
        match.group(1).strip()
        for line in markdown_text.splitlines()
        if (match := FINAL_LINE.search(line)) and match.group(1).strip()
    ]
    if final_lines:
        return "\n".join(final_lines)

    content_lines: list[str] = []
    for line in markdown_text.splitlines():
        stripped = SPEAKER_PREFIX.sub("", line.strip())
        if not stripped or stripped.startswith(("#", ">", "创建时间：")):
            continue
        stripped = TIME_STAMP.sub("", stripped)
        stripped = MARKDOWN_PREFIX.sub("", stripped).strip()
        if stripped:
            content_lines.append(stripped)
    return "\n".join(content_lines)


def _time_to_seconds(value: str) -> int:
    """把 HH:MM:SS 转换为当天秒数。"""
    parsed = datetime.strptime(value, "%H:%M:%S")
    return parsed.hour * 3600 + parsed.minute * 60 + parsed.second


def _build_report(
    project_name: str,
    reference_text: str,
    hypothesis_text: str,
    wer: float,
    latency: float,
) -> str:
    """生成包含指标、规模和结论的 Markdown 报告。"""
    if wer <= 0.1:
        conclusion = "转录与参考文本较为接近。"
    elif wer <= 0.3:
        conclusion = "转录存在一定误差，建议检查热词和录音质量。"
    else:
        conclusion = "转录误差较高，建议检查音频、ASR 参数和参考文本。"
    return (
        f"# {project_name} - 离线评测报告\n\n"
        "| 指标 | 结果 | 说明 |\n"
        "| --- | ---: | --- |\n"
        f"| WER | {wer:.2%} | 词错误率，越低越好 |\n"
        f"| 平均转录延迟 | {latency:.2f} 秒 | 相邻时间戳平均间隔 |\n"
        f"| 参考词数 | {len(_tokenize(reference_text))} | 评测基准规模 |\n"
        f"| 转录词数 | {len(_tokenize(hypothesis_text))} | 实际输出规模 |\n\n"
        f"## 简要结论\n\n{conclusion}\n"
    )


if __name__ == "__main__":
    raise SystemExit("请通过主程序菜单 11 运行离线评测。")
