"""说话人增量聚类的纯数组单元测试。"""

import numpy as np
import pytest

from app.speaker_labeler import SpeakerLabelerError, incremental_cluster


def test_similar_features_stay_in_one_cluster() -> None:
    features = np.array([[1.0, 0.0], [0.99, 0.01], [0.98, 0.02]])
    labels = incremental_cluster(features, cluster_threshold=0.1)
    assert labels == [0, 0, 0]


def test_distant_features_create_new_cluster() -> None:
    features = np.array([[1.0, 0.0], [0.0, 1.0]])
    labels = incremental_cluster(features, cluster_threshold=0.2)
    assert labels == [0, 1]


def test_cluster_count_never_exceeds_three() -> None:
    features = np.array(
        [[1.0, 0.0], [0.0, 1.0], [-1.0, 0.0], [0.0, -1.0]]
    )
    labels = incremental_cluster(
        features,
        cluster_threshold=0.1,
        max_speakers=3,
    )
    assert len(set(labels)) <= 3


def test_max_speakers_setting_limits_clusters() -> None:
    features = np.array([[1.0, 0.0], [0.0, 1.0], [-1.0, 0.0]])
    labels = incremental_cluster(
        features,
        cluster_threshold=0.1,
        max_speakers=2,
    )
    assert len(set(labels)) == 2


def test_invalid_cluster_threshold_is_rejected() -> None:
    with pytest.raises(SpeakerLabelerError):
        incremental_cluster(np.array([[1.0, 0.0]]), cluster_threshold=0.0)
