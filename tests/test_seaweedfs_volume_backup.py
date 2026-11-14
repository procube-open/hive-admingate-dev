import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


path = Path(__file__).parents[1] / "roles/seaweedfs-volume-backup/files/seaweedfs-volume-backup.py"
spec = importlib.util.spec_from_file_location("seaweedfs_volume_backup", path)
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


def test_remote_backup_preserves_data_and_deletions(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    destination = tmp_path / "backup"
    destination.mkdir()
    source.joinpath("example_3.idx").write_bytes(b"index and delete" * 2)
    source.joinpath("example_3.vif").write_text(json.dumps({"files": [{
        "backendType": "s3", "backendId": "default", "extension": ".dat",
        "key": "object-key", "fileSize": "15",
    }]}))

    def run(*args, **kwargs):
        destination.joinpath("example_3.dat").write_bytes(b"incomplete")
        destination.joinpath("example_3.idx").write_bytes(b"stale")
        return SimpleNamespace(returncode=0, stdout="Successfully backed up volume 3")

    class S3:
        def get_object(self, **kwargs):
            assert kwargs == {"Bucket": "bucket", "Key": "object-key"}
            return {"Body": io.BytesIO(b"complete object"), "ContentLength": 15}

    monkeypatch.setattr(backup.subprocess, "run", run)
    backup.backup_volume(
        {"Id": 3, "Collection": "example", "RemoteStorageName": "s3.default"},
        destination, source, S3(), "bucket",
    )
    assert destination.joinpath("example_3.dat").read_bytes() == b"complete object"
    assert destination.joinpath("example_3.idx").read_bytes() == b"index and delete" * 2


def test_remote_backup_rejects_truncated_object(tmp_path, monkeypatch):
    tmp_path.joinpath("3.idx").write_bytes(b"x" * 16)
    tmp_path.joinpath("3.vif").write_text(json.dumps({"files": [{
        "backendType": "s3", "backendId": "default", "extension": ".dat",
        "key": "key", "fileSize": "10",
    }]}))
    monkeypatch.setattr(
        backup.subprocess, "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="Successfully backed up volume 3"),
    )

    class S3:
        def get_object(self, **kwargs):
            return {"Body": io.BytesIO(b"short"), "ContentLength": 10}

    with pytest.raises(RuntimeError, match="incomplete S3 object"):
        backup.backup_volume(
            {"Id": 3, "Collection": "", "RemoteStorageName": "s3.default"},
            tmp_path, tmp_path, S3(), "bucket",
        )


@pytest.mark.parametrize("file_info", [
    {"backendType": "s3", "backendId": "other", "extension": ".dat", "key": "key", "fileSize": "10"},
    {"backendType": "s3", "backendId": "default", "extension": ".dat", "fileSize": "10"},
])
def test_remote_backup_rejects_unsupported_file_metadata(tmp_path, monkeypatch, file_info):
    tmp_path.joinpath("3.idx").write_bytes(b"x" * 16)
    tmp_path.joinpath("3.vif").write_text(json.dumps({"files": [file_info]}))
    monkeypatch.setattr(
        backup.subprocess, "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="Successfully backed up volume 3"),
    )
    with pytest.raises(RuntimeError, match="unsupported remote file metadata"):
        backup.backup_volume(
            {"Id": 3, "Collection": "", "RemoteStorageName": "s3.default"},
            tmp_path, tmp_path, None, "bucket",
        )


def test_remote_backup_rejects_object_size_mismatch(tmp_path, monkeypatch):
    tmp_path.joinpath("3.idx").write_bytes(b"x" * 16)
    tmp_path.joinpath("3.vif").write_text(json.dumps({"files": [{
        "backendType": "s3", "backendId": "default", "extension": ".dat",
        "key": "key", "fileSize": "11",
    }]}))
    monkeypatch.setattr(
        backup.subprocess, "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="Successfully backed up volume 3"),
    )

    class S3:
        def get_object(self, **kwargs):
            return {"Body": io.BytesIO(b"0123456789"), "ContentLength": 10}

    with pytest.raises(RuntimeError, match="incomplete S3 object"):
        backup.backup_volume(
            {"Id": 3, "Collection": "", "RemoteStorageName": "s3.default"},
            tmp_path, tmp_path, S3(), "bucket",
        )


def test_backup_rejects_volume_tier_change(tmp_path, monkeypatch):
    monkeypatch.setattr(
        backup.subprocess, "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="Successfully backed up volume 3"),
    )
    with pytest.raises(RuntimeError, match="changed tier"):
        backup.backup_volume({"Id": 3, "Collection": ""}, tmp_path, tmp_path, None, "bucket")
