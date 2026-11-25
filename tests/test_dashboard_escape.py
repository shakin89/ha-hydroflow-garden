"""button-card renders what a JS template returns as HTML: user-controlled
strings (controller, zone and program names, entity attributes) must go
through esc() before they are interpolated."""
from __future__ import annotations

import re
import shutil
import subprocess

import pytest

from custom_components.hydroflow_garden import i18n
from custom_components.hydroflow_garden.dashboard import render_dashboard
from custom_components.hydroflow_garden.model import Controller

from .conftest import TOPOLOGY

# `${variables.name}`, `${r.name}`, ... not wrapped in esc()
RAW = re.compile(r"\$\{(?:variables\.(?:name|title|sub|label|hint|icon|value|unit)|\w+\.(?:name|current_name))\}")
ESC_DEF = re.compile(r"const esc = \(s\) => String\(s \?\? ''\)[^\n]*\n")


def _blocks(node):
    if isinstance(node, str):
        if "[[[" in node:
            yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from _blocks(v)
    elif isinstance(node, list):
        for v in node:
            yield from _blocks(v)


def _templates(lang: str = "en") -> dict:
    ctrls = [Controller.from_dict(c) for c in TOPOLOGY["controllers"]]
    return render_dashboard(ctrls, "T", i18n.load(lang)["dashboard"])["button_card_templates"]


@pytest.mark.parametrize("lang", ["en", "it"])
def test_no_raw_interpolation_of_names(lang: str) -> None:
    for block in _blocks(_templates(lang)):
        assert not RAW.search(block), RAW.search(block).group(0)


def test_esc_defined_where_used() -> None:
    used = 0
    for block in _blocks(_templates()):
        if "esc(" in block.replace("const esc = (s)", ""):
            used += 1
            assert ESC_DEF.search(block), block[:80]
    assert used >= 15


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_esc_escapes_markup() -> None:
    block = next(b for b in _blocks(_templates()) if ESC_DEF.search(b))
    helper = ESC_DEF.search(block).group(0)
    script = helper + "process.stdout.write(esc(`<b a=\"1\">&'x'</b>`) + '|' + esc(null) + '|' + esc(5))"
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout
    assert out == "&lt;b a=&quot;1&quot;&gt;&amp;&#39;x&#39;&lt;/b&gt;||5"
