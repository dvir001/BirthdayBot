import json
import re
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_deployment_uses_published_image_and_private_database():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    assert "build" not in compose["services"]["bot"]
    assert "ghcr.io/dvir001/birthdaybot" in compose["services"]["bot"]["image"]
    assert "ports" not in compose["services"]["db"]
    assert compose["services"]["bot"]["read_only"]


def test_workflows_pin_actions_and_publish_both_architectures():
    for path in (ROOT / ".github" / "workflows").glob("*.yml"):
        workflow = yaml.safe_load(path.read_text())
        for job in workflow["jobs"].values():
            for step in job["steps"]:
                if "uses" in step:
                    assert re.fullmatch(r"[\w/-]+@[a-f0-9]{40}", step["uses"])
    ci = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    assert "'" not in ci["jobs"]["checks"]["services"]["postgres"]["options"]
    build = ci["jobs"]["image"]["steps"][-1]
    assert build["with"]["platforms"] == "linux/amd64,linux/arm64"
    assert ci["jobs"]["image"]["needs"] == "checks"
    assert ci["jobs"]["image"]["if"] == "github.event_name == 'push'"


def test_locale_and_lockfile_are_valid():
    messages = json.loads((ROOT / "static/locales/en-US.json").read_text())
    assert all(isinstance(value, str) and value for value in messages.values())
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    assert any(package["name"] == "discord-py" for package in lock["package"])
