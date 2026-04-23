"""Tests for bin/render_and_lint_templates.py"""

import sys
from pathlib import Path

import pytest
from jinja2 import TemplateNotFound
from jinja2.exceptions import UndefinedError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import render_and_lint_templates as rlt  # noqa: E402


# ── render_template ──────────────────────────────────────────────────────────


def test_render_template_renders_valid_template(tmp_path, monkeypatch):
    (tmp_path / "t.j2").write_text("hello: {{ name }}\n", encoding="utf-8")
    monkeypatch.setattr(rlt, "TEMPLATES_DIR", tmp_path)
    assert rlt.render_template("t.j2", {"name": "world"}).strip() == "hello: world"


def test_render_template_raises_on_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(rlt, "TEMPLATES_DIR", tmp_path)
    with pytest.raises(TemplateNotFound):
        rlt.render_template("missing.j2", {})


def test_render_template_raises_on_undefined_with_strict(tmp_path, monkeypatch):
    (tmp_path / "t.j2").write_text("hello: {{ missing_var }}\n", encoding="utf-8")
    monkeypatch.setattr(rlt, "TEMPLATES_DIR", tmp_path)
    with pytest.raises(UndefinedError):
        rlt.render_template("t.j2", {})


# ── main (end-to-end with synthetic templates) ──────────────────────────────


def _setup_happy_path(tmp_path, monkeypatch):
    """Write minimal valid templates matching the expected CASES shape."""
    server = tmp_path / "server-config.yaml.j2"
    agent = tmp_path / "agent-config.yaml.j2"
    server.write_text(
        "cluster-cidr: x\nservice-cidr: y\nflannel-backend: z\nnode-name: n\n",
        encoding="utf-8",
    )
    agent.write_text("node-name: n\n", encoding="utf-8")
    monkeypatch.setattr(rlt, "TEMPLATES_DIR", tmp_path)
    # Replace CASES with a version that doesn't require the real server/agent vars
    monkeypatch.setattr(
        rlt,
        "CASES",
        [
            (
                "server-config.yaml.j2",
                {},
                ["cluster-cidr", "service-cidr", "flannel-backend", "node-name"],
            ),
            ("agent-config.yaml.j2", {}, ["node-name"]),
        ],
    )


def test_main_happy_path_prints_success(tmp_path, monkeypatch, capsys):
    _setup_happy_path(tmp_path, monkeypatch)
    rlt.main()
    assert "All k3s templates validated successfully" in capsys.readouterr().out


def test_main_exits_on_yaml_parse_error(tmp_path, monkeypatch, capsys):
    (tmp_path / "t.j2").write_text("{not: valid: yaml: :\n", encoding="utf-8")
    monkeypatch.setattr(rlt, "TEMPLATES_DIR", tmp_path)
    monkeypatch.setattr(rlt, "CASES", [("t.j2", {}, [])])
    with pytest.raises(SystemExit) as exc:
        rlt.main()
    assert exc.value.code == 1
    assert "YAML parse error" in capsys.readouterr().out


def test_main_exits_when_rendered_is_not_mapping(tmp_path, monkeypatch, capsys):
    (tmp_path / "t.j2").write_text("- a\n- b\n", encoding="utf-8")
    monkeypatch.setattr(rlt, "TEMPLATES_DIR", tmp_path)
    monkeypatch.setattr(rlt, "CASES", [("t.j2", {}, [])])
    with pytest.raises(SystemExit) as exc:
        rlt.main()
    assert exc.value.code == 1
    assert "non-mapping" in capsys.readouterr().out


def test_main_exits_on_missing_required_key(tmp_path, monkeypatch, capsys):
    (tmp_path / "t.j2").write_text("present: yes\n", encoding="utf-8")
    monkeypatch.setattr(rlt, "TEMPLATES_DIR", tmp_path)
    monkeypatch.setattr(rlt, "CASES", [("t.j2", {}, ["missing_key"])])
    with pytest.raises(SystemExit) as exc:
        rlt.main()
    assert exc.value.code == 1
    assert "missing required key" in capsys.readouterr().out


def test_main_exits_on_render_error(tmp_path, monkeypatch, capsys):
    (tmp_path / "t.j2").write_text("value: {{ undefined_var }}\n", encoding="utf-8")
    monkeypatch.setattr(rlt, "TEMPLATES_DIR", tmp_path)
    monkeypatch.setattr(rlt, "CASES", [("t.j2", {}, [])])
    with pytest.raises(SystemExit) as exc:
        rlt.main()
    assert exc.value.code == 1
    assert "render error" in capsys.readouterr().out
