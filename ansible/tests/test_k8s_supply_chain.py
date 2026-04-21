"""Offline supply-chain guardrail: no mutable :latest tags in k8s manifests."""

from pathlib import Path
import re

REPO_ROOT = Path(__file__).resolve().parents[2]
K8S_APPS = REPO_ROOT / "k8s" / "apps"
IMAGE_PATTERN = re.compile(r"^\s*image:\s*(?P<image>\S+)")


def _images_in_file(path: Path) -> list[str]:
    images = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = IMAGE_PATTERN.match(line)
        if m:
            images.append(m.group("image"))
    return images


def test_no_latest_tags_in_workload_manifests():
    violations = []
    for path in sorted(K8S_APPS.rglob("*.yaml")):
        for image in _images_in_file(path):
            if ":latest" in image or (":" not in image and "@sha256:" not in image):
                violations.append(f"{path.name}: {image}")
    assert not violations, "Unpinned/mutable images found:\n" + "\n".join(violations)
