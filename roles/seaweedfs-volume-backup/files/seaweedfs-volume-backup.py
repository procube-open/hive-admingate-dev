#!/usr/bin/env python3
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

import boto3


def volume_list():
    with urllib.request.urlopen("http://seaweedfs-master:9333/vol/status?pretty=y", timeout=30) as response:
        status = json.load(response)
    return [
        volume
        for dc in status["Volumes"]["DataCenters"].values()
        for rack in dc.values()
        for node in rack.values()
        for volume in node
    ]


def backup_volume(volume, directory, data_dir, s3, bucket):
    vid = int(volume["Id"])
    collection = volume["Collection"]
    if collection and not re.fullmatch(r"[A-Za-z0-9_.-]+", collection):
        raise ValueError(f"unsupported collection name for volume {vid}")
    base = f"{collection}_{vid}" if collection else str(vid)
    output = subprocess.run(
        ["weed", "backup", "-master=seaweedfs-master:9333", f"-dir={directory}",
         f"-collection={collection}", f"-volumeId={vid}"],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
    )
    print(output.stdout, file=sys.stderr, end="")
    if output.returncode or f"Successfully backed up volume {vid}" not in output.stdout:
        raise RuntimeError(f"backup failed for volume {vid}")

    remote_name = volume.get("RemoteStorageName", "")
    if remote_name:
        if remote_name != "s3.default":
            raise RuntimeError(f"unsupported remote backend for volume {vid}")
        source_idx = data_dir / f"{base}.idx"
        source_vif = data_dir / f"{base}.vif"
        if not source_idx.is_file():
            raise RuntimeError(f"local index missing for volume {vid}")
        vif = json.loads(source_vif.read_text())
        files = vif.get("files", [])
        if len(files) != 1 or files[0].get("backendType") != "s3" or \
                files[0].get("backendId") != "default" or files[0].get("extension") != ".dat" or \
                int(files[0].get("offset", 0)) != 0 or not files[0].get("key"):
            raise RuntimeError(f"unsupported remote file metadata for volume {vid}")
        response = s3.get_object(Bucket=bucket, Key=files[0]["key"])
        with response["Body"] as body, (directory / f"{base}.dat").open("wb") as target:
            shutil.copyfileobj(body, target)
        if (directory / f"{base}.dat").stat().st_size != response["ContentLength"] or \
                response["ContentLength"] != int(files[0]["fileSize"]):
            raise RuntimeError(f"incomplete S3 object for volume {vid}")
        shutil.copyfile(source_idx, directory / f"{base}.idx")
        if (directory / f"{base}.idx").stat().st_size % 16:
            raise RuntimeError(f"incomplete index for volume {vid}")
        if json.loads(source_vif.read_text()).get("files", []) != files:
            raise RuntimeError(f"remote file changed during backup of volume {vid}")
    elif not (data_dir / f"{base}.dat").is_file():
        raise RuntimeError(f"volume {vid} changed tier during backup")


def main():
    volumes = volume_list()
    if not volumes:
        raise RuntimeError("no volumes found")
    bucket = os.environ["SEAWEEDFS_TIER_BUCKET"]
    s3 = boto3.client("s3")
    with tempfile.TemporaryDirectory(prefix="seaweedfs-backup-") as tmp:
        directory = Path(tmp)
        for volume in sorted(volumes, key=lambda item: int(item["Id"])):
            backup_volume(volume, directory, Path("/data"), s3, bucket)
        with tarfile.open(fileobj=sys.stdout.buffer, mode="w|gz") as archive:
            for path in sorted(directory.iterdir()):
                archive.add(path, arcname=path.name, recursive=False)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"SeaweedFS volume backup failed: {error}", file=sys.stderr)
        sys.exit(1)
