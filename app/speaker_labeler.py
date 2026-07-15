"""从本地 WAV 提取 MFCC，并进行轻量增量说话人聚类。"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import librosa
import numpy as np
from sklearn.metrics.pairwise import cosine_distances

from app.models import SpeakerSegment


LOGGER = logging.getLogger(__name__)
EXPECTED_SAMPLE_RATE = 16000
SEGMENT_DURATION_SECONDS = 2.0
MAX_SUPPORTED_SPEAKERS = 3
SPEAKER_PREFIX = re.compile(r"^\[speaker_\d+\]\s*")


class SpeakerLabelerError(Exception):
    """MFCC 提取、聚类、时间对齐或转录写入失败。"""


async def label_speakers(
    wav_path: Path,
    transcript_path: Path,
    n_mfcc: int = 13,
    cluster_threshold: float = 0.6,
    max_speakers: int = 3,
) -> list[SpeakerSegment]:
    """读取 WAV、提取 MFCC、增量聚类并写入说话人标签。"""
    wav_path = Path(wav_path)
    transcript_path = Path(transcript_path)
    LOGGER.info("speaker labeling start: %s", wav_path)

    try:
        features, time_ranges = extract_mfcc(wav_path, n_mfcc=n_mfcc)
        cluster_ids = incremental_cluster(
            features,
            cluster_threshold=cluster_threshold,
            max_speakers=max_speakers,
        )
        segments = [
            SpeakerSegment(
                start_time=start_time,
                end_time=end_time,
                speaker_id=f"speaker_{cluster_id}",
            )
            for (start_time, end_time), cluster_id in zip(
                time_ranges,
                cluster_ids,
                strict=True,
            )
        ]
        _apply_labels_to_transcript(transcript_path, segments)
    except SpeakerLabelerError:
        LOGGER.exception("说话人标注失败。")
        raise
    except Exception as error:
        LOGGER.exception("说话人标注发生未预期错误。")
        raise SpeakerLabelerError(f"说话人标注失败：{error}") from error

    LOGGER.info("speaker labeling finish: %s", transcript_path)
    return segments


def extract_mfcc(
    wav_path: Path,
    n_mfcc: int = 13,
) -> tuple[np.ndarray, list[tuple[float, float]]]:
    """按固定时长切分 WAV，并返回每段 MFCC 统计特征和时间范围。"""
    wav_path = Path(wav_path)
    if n_mfcc <= 0:
        raise SpeakerLabelerError("MFCC 特征数量必须大于 0。")
    if not wav_path.is_file():
        raise SpeakerLabelerError(f"找不到 WAV 文件：{wav_path}")

    try:
        audio, sample_rate = librosa.load(
            str(wav_path),
            sr=None,
            mono=False,
            dtype=np.float32,
        )
    except Exception as error:
        raise SpeakerLabelerError(f"无法读取 WAV 文件：{error}") from error

    if sample_rate != EXPECTED_SAMPLE_RATE:
        raise SpeakerLabelerError(
            f"WAV 采样率必须是 {EXPECTED_SAMPLE_RATE} Hz。"
        )
    if audio.ndim != 1:
        raise SpeakerLabelerError("WAV 必须是单声道音频。")
    if audio.size == 0:
        raise SpeakerLabelerError("WAV 文件没有可分析的音频数据。")

    samples_per_segment = int(sample_rate * SEGMENT_DURATION_SECONDS)
    feature_rows: list[np.ndarray] = []
    time_ranges: list[tuple[float, float]] = []
    for start_sample in range(0, audio.size, samples_per_segment):
        end_sample = min(start_sample + samples_per_segment, audio.size)
        segment_audio = audio[start_sample:end_sample]
        if segment_audio.size < 512:
            segment_audio = np.pad(segment_audio, (0, 512 - segment_audio.size))

        mfcc = librosa.feature.mfcc(
            y=segment_audio,
            sr=sample_rate,
            n_mfcc=n_mfcc,
            n_fft=512,
            hop_length=160,
        )
        feature_rows.append(
            np.concatenate((np.mean(mfcc, axis=1), np.std(mfcc, axis=1)))
        )
        time_ranges.append(
            (start_sample / sample_rate, end_sample / sample_rate)
        )

    return np.vstack(feature_rows), time_ranges


def incremental_cluster(
    features: np.ndarray,
    cluster_threshold: float = 0.6,
    max_speakers: int = 3,
) -> list[int]:
    """按余弦距离在线更新聚类中心，返回最多三个说话人编号。"""
    if features.ndim != 2 or features.shape[0] == 0:
        raise SpeakerLabelerError("没有可用于聚类的 MFCC 特征。")
    if not np.all(np.isfinite(features)):
        raise SpeakerLabelerError("MFCC 特征中包含无效数值。")
    if cluster_threshold <= 0 or cluster_threshold > 2:
        raise SpeakerLabelerError("聚类阈值必须大于 0 且不超过 2。")
    if max_speakers <= 0:
        raise SpeakerLabelerError("最大说话人数必须大于 0。")

    speaker_limit = min(max_speakers, MAX_SUPPORTED_SPEAKERS)
    centroids: list[np.ndarray] = []
    cluster_counts: list[int] = []
    labels: list[int] = []

    for feature in features:
        if not centroids:
            centroids.append(feature.copy())
            cluster_counts.append(1)
            labels.append(0)
            continue

        distances = cosine_distances(
            feature.reshape(1, -1),
            np.vstack(centroids),
        )[0]
        closest_cluster = int(np.argmin(distances))
        if (
            distances[closest_cluster] > cluster_threshold
            and len(centroids) < speaker_limit
        ):
            centroids.append(feature.copy())
            cluster_counts.append(1)
            labels.append(len(centroids) - 1)
            continue

        labels.append(closest_cluster)
        cluster_counts[closest_cluster] += 1
        count = cluster_counts[closest_cluster]
        centroids[closest_cluster] += (
            feature - centroids[closest_cluster]
        ) / count

    return labels


def align_speakers(
    segments: list[SpeakerSegment],
    transcript_line_count: int,
) -> list[str]:
    """按整段时间线均分转录行，并返回每行对应的 speaker_id。"""
    if not segments:
        raise SpeakerLabelerError("没有可用于对齐的说话人音频段。")
    if transcript_line_count <= 0:
        raise SpeakerLabelerError("转录文件没有可标注的文本行。")

    total_duration = segments[-1].end_time
    labels: list[str] = []
    for line_index in range(transcript_line_count):
        midpoint = total_duration * (line_index + 0.5) / transcript_line_count
        matching_segment = next(
            (
                segment
                for segment in segments
                if segment.start_time <= midpoint < segment.end_time
            ),
            segments[-1],
        )
        labels.append(matching_segment.speaker_id)
    return labels


def _apply_labels_to_transcript(
    transcript_path: Path,
    segments: list[SpeakerSegment],
) -> None:
    """为转录正文行增加或替换 [speaker_n] 前缀。"""
    if not transcript_path.is_file():
        raise SpeakerLabelerError(f"找不到转录文件：{transcript_path}")
    try:
        original_text = transcript_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise SpeakerLabelerError(f"无法读取转录文件：{error}") from error

    lines = original_text.splitlines()
    content_indexes = [
        index for index, line in enumerate(lines) if _is_transcript_content_line(line)
    ]
    labels = align_speakers(segments, len(content_indexes))
    for line_index, speaker_id in zip(content_indexes, labels, strict=True):
        clean_line = SPEAKER_PREFIX.sub("", lines[line_index].strip())
        lines[line_index] = f"[{speaker_id}] {clean_line}"

    updated_text = "\n".join(lines)
    if original_text.endswith(("\n", "\r")):
        updated_text += "\n"
    try:
        transcript_path.write_text(updated_text, encoding="utf-8", newline="\n")
    except OSError as error:
        raise SpeakerLabelerError(f"无法写入说话人标注：{error}") from error


def _is_transcript_content_line(line: str) -> bool:
    """排除 Markdown 标题、说明和元数据，只选择转录正文。"""
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.startswith(("#", ">", "---", "创建时间：")):
        return False
    return True
