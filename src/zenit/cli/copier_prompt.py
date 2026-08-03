"""Interactive TUI prompt for Copier template questions.

Uses ``rich.prompt`` for type-appropriate widgets - STR, BOOL, INT, FLOAT,
CHOICE, MULTISELECT, SECRET, and YAML.  Designed for the Copier question
model (ordered heterogeneous types) which differs from the addon
multi-select model in ``cli/prompt/``.
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.prompt import Confirm, FloatPrompt, IntPrompt, Prompt

from zenit.cli.ui import DIM, RESET, YELLOW
from zenit.migrate.answers import (
    MigrationAnswers,
    _coerce_question_value,
    _validate_answer,
)
from zenit.migrate.copier import (
    CopierConfig,
    QuestionClass,
    QuestionType,
    _coerce_yaml_value,
)
from zenit.migrate.env import _render_copier_default

_CONSOLE = Console()
_FILE_CONSOLES: dict[Path, Console] = {}


def _console_for(path: Path) -> Console:
    if path not in _FILE_CONSOLES:
        _FILE_CONSOLES[path] = Console(file=path.open("a", encoding="utf-8"))
    return _FILE_CONSOLES[path]


def prompt_copier_questions(
    config: CopierConfig,
    classes: dict[str, QuestionClass],
    log_path: Path | None = None,
) -> MigrationAnswers:
    """Interactive TUI prompt for Copier template questions.

    Type-appropriate rich widgets, inline validation, help text, and
    hidden-question resolution.
    """
    answers = MigrationAnswers()
    out = _console_for(log_path) if log_path else _CONSOLE

    for q in config.questions:
        qclass = classes.get(q.name, QuestionClass.RENDER_VAR)

        if q.when is False:
            answers.render_vars[q.name] = _coerce_question_value(
                q,
                _render_copier_default(q.default, answers.render_vars),
            )
            continue

        while True:
            default_value = _coerce_question_value(
                q,
                _render_copier_default(q.default, answers.render_vars),
            )

            if q.type == QuestionType.MULTISELECT:
                choices_str = ", ".join(q.choices)
                msg = f"{q.help or q.name} {DIM}(comma-separated, options: {choices_str}){RESET}"
                default_list = (
                    default_value
                    if isinstance(default_value, list)
                    else [default_value]
                )
                default_str = ", ".join(str(v) for v in default_list)
                raw = Prompt.ask(
                    msg,
                    default=default_str,
                    console=out,
                ).strip()
                if raw and raw != default_str:
                    parts = [p.strip() for p in raw.split(",") if p.strip()]
                    answers.render_vars[q.name] = [
                        q.choices_map.get(p, p) for p in parts
                    ]
                    answers.explicit_names.add(q.name)
                else:
                    answers.render_vars[q.name] = default_value
            elif q.type == QuestionType.BOOL:
                msg = f"{q.help or q.name}"
                try:
                    answer = Confirm.ask(
                        msg,
                        default=bool(default_value),
                        console=out,
                    )
                except Exception:
                    answer = bool(default_value)
                answers.render_vars[q.name] = answer
                answers.explicit_names.add(q.name)
            elif qclass == QuestionClass.CHOICE_VAR:
                choices_str = ", ".join(q.choices)
                msg = f"{q.help or q.name} {DIM}({choices_str}){RESET}"
                raw = Prompt.ask(
                    msg,
                    default=str(default_value) if default_value != "" else "",
                    console=out,
                ).strip()
                if raw and raw != str(default_value) and raw in q.choices:
                    answers.render_vars[q.name] = q.choices_map.get(raw, raw)
                    answers.explicit_names.add(q.name)
                else:
                    answers.render_vars[q.name] = default_value
            elif q.type == QuestionType.INT:
                msg = f"{q.help or q.name}"
                try:
                    answers.render_vars[q.name] = IntPrompt.ask(
                        msg,
                        default=int(str(default_value)) if str(default_value) else None,
                        console=out,
                    )
                except Exception:
                    answers.render_vars[q.name] = default_value
                answers.explicit_names.add(q.name)
            elif q.type == QuestionType.FLOAT:
                msg = f"{q.help or q.name}"
                try:
                    answers.render_vars[q.name] = FloatPrompt.ask(
                        msg,
                        default=float(str(default_value))
                        if str(default_value)
                        else None,
                        console=out,
                    )
                except Exception:
                    answers.render_vars[q.name] = default_value
                answers.explicit_names.add(q.name)
            elif q.type == QuestionType.SECRET:
                msg = f"{q.help or q.name}"
                import getpass

                raw = getpass.getpass(f"  {msg}: ").strip()
                if raw:
                    answers.render_vars[q.name] = raw
                    answers.explicit_names.add(q.name)
                else:
                    answers.render_vars[q.name] = default_value
            elif q.type == QuestionType.YAML:
                msg = f"{q.help or q.name}"
                raw = Prompt.ask(
                    msg,
                    default=str(default_value) if default_value != "" else "",
                    console=out,
                ).strip()
                if raw and raw != str(default_value):
                    answers.render_vars[q.name] = _coerce_yaml_value(raw)
                    answers.explicit_names.add(q.name)
                else:
                    answers.render_vars[q.name] = default_value
            else:
                msg = f"{q.help or q.name}"
                raw = Prompt.ask(
                    msg,
                    default=str(default_value) if default_value != "" else "",
                    console=out,
                ).strip()
                if raw and raw != str(default_value):
                    answers.render_vars[q.name] = raw
                    answers.explicit_names.add(q.name)
                else:
                    answers.render_vars[q.name] = default_value

            err = _validate_answer(q, answers.render_vars[q.name], answers.render_vars)
            if err:
                if q.name in answers.explicit_names:
                    out.print(f"  {YELLOW}{err}{RESET}")
                    answers.explicit_names.discard(q.name)
                    del answers.render_vars[q.name]
                    continue
                from zenit.cli.ui import warn as _warn

                _warn(f"{err} - using default anyway.")
            break

    return answers
