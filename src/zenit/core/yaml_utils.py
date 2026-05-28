from __future__ import annotations

from io import StringIO

from ruamel.yaml import YAML

_compose_yaml = YAML()
_compose_yaml.default_flow_style = False


def compose_yaml_dumps(data: object) -> str:
    buf = StringIO()
    _compose_yaml.dump(data, buf)
    return buf.getvalue()


def compose_yaml_load(text: str) -> dict[str, object]:
    result = _compose_yaml.load(text)
    return result if isinstance(result, dict) else {}
