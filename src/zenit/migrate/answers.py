"""User prompting, answer resolution, validation, and stabilization."""

from __future__ import annotations

import getpass
import re
import sys
from dataclasses import dataclass, field
from typing import Any

from zenit.cli.ui import DIM, RESET, YELLOW, warn
from zenit.schema.exceptions import ZenitError

from .copier import (
    CopierConfig,
    CopierQuestion,
    QuestionClass,
    QuestionType,
    _coerce_yaml_value,
)
from .env import COPIER_ENV, _render_copier_default


@dataclass
class MigrationAnswers:
    render_vars: dict[str, Any] = field(default_factory=dict)
    explicit_names: set[str] = field(default_factory=set)


def _regex_search_func(pattern: str, value: str) -> bool:
    return bool(re.search(pattern, str(value)))


def _validate_answer(
    question: CopierQuestion,
    value: object,
    render_vars: dict[str, Any],
) -> str | None:
    if not question.validator:
        return None

    context = dict(render_vars)
    context["regex_search"] = _regex_search_func
    context["answer"] = value
    context[question.name] = value

    try:
        result = COPIER_ENV.from_string(
            f"{{% if ({question.validator}) %}}ok{{% else %}}fail{{% endif %}}"
        ).render(**context)
    except Exception:
        return None

    if result.strip() == "fail":
        return f"Validation failed for '{question.name}': {question.validator}"
    return None


def _coerce_question_value(
    question: CopierQuestion,
    value: object,
) -> object:
    if question.type == QuestionType.MULTISELECT:
        if isinstance(value, str):
            parts = [p.strip() for p in value.split(",") if p.strip()]
            return [question.choices_map.get(p, p) for p in parts]
        if isinstance(value, list):
            return [question.choices_map.get(str(v), v) for v in value]
        return []

    if not isinstance(value, str):
        return value

    match question.type:
        case QuestionType.BOOL:
            return value.strip().lower() in ("1", "true", "yes", "y", "on")
        case QuestionType.INT:
            return int(value) if value.strip() else 0
        case QuestionType.FLOAT:
            return float(value) if value.strip() else 0.0
        case QuestionType.CHOICE:
            return question.choices_map.get(value, value)
        case QuestionType.YAML:
            return _coerce_yaml_value(value)
        case _:
            return value


def _mask_secrets(
    text: str,
    render_vars: dict[str, Any],
    secret_names: set[str],
) -> str:
    result = text
    for name in secret_names:
        value = render_vars.get(name)
        if isinstance(value, str) and value:
            result = result.replace(value, "******")
    return result


def _prompt_questions(
    config: CopierConfig,
    classes: dict[str, QuestionClass],
) -> MigrationAnswers:
    if sys.stdin.isatty():
        from zenit.cli.copier_prompt import prompt_copier_questions

        return prompt_copier_questions(config, classes)

    answers = MigrationAnswers()

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
                raw = input(f"  {msg} [{default_str}]: ").strip()
                if raw:
                    parts = [p.strip() for p in raw.split(",") if p.strip()]
                    answers.render_vars[q.name] = [
                        q.choices_map.get(p, p) for p in parts
                    ]
                    answers.explicit_names.add(q.name)
                else:
                    answers.render_vars[q.name] = default_value
            elif q.type == QuestionType.BOOL:
                msg = f"{q.help or q.name}"
                raw = input(f"  {msg} {DIM}[Y/n]{RESET}  ").strip().lower()
                if raw:
                    answer = raw in ("y", "yes")
                    answers.explicit_names.add(q.name)
                else:
                    answer = bool(default_value)
                answers.render_vars[q.name] = answer
            elif qclass == QuestionClass.CHOICE_VAR:
                choices_str = ", ".join(q.choices)
                msg = f"{q.help or q.name} {DIM}({choices_str}){RESET}"
                raw = input(f"  {msg} [{default_value}]: ").strip()
                if raw and raw in q.choices:
                    answers.render_vars[q.name] = q.choices_map.get(raw, raw)
                    answers.explicit_names.add(q.name)
                else:
                    answers.render_vars[q.name] = default_value
            elif q.type == QuestionType.INT:
                default_str = str(default_value) if default_value != "" else ""
                msg = f"{q.help or q.name}"
                raw = input(f"  {msg} [{default_str}]: ").strip()
                if raw:
                    answers.render_vars[q.name] = int(raw)
                    answers.explicit_names.add(q.name)
                else:
                    answers.render_vars[q.name] = default_value
            elif q.type == QuestionType.FLOAT:
                default_str = str(default_value) if default_value != "" else ""
                msg = f"{q.help or q.name}"
                raw = input(f"  {msg} [{default_str}]: ").strip()
                if raw:
                    answers.render_vars[q.name] = float(raw)
                    answers.explicit_names.add(q.name)
                else:
                    answers.render_vars[q.name] = default_value
            elif q.type == QuestionType.SECRET:
                msg = f"{q.help or q.name}"
                raw = getpass.getpass(f"  {msg}: ").strip()
                if raw:
                    answers.render_vars[q.name] = raw
                    answers.explicit_names.add(q.name)
                else:
                    answers.render_vars[q.name] = default_value
            elif q.type == QuestionType.YAML:
                default_str = str(default_value) if default_value != "" else ""
                msg = f"{q.help or q.name}"
                raw = input(f"  {msg} [{default_str}]: ").strip()
                if raw:
                    answers.render_vars[q.name] = _coerce_yaml_value(raw)
                    answers.explicit_names.add(q.name)
                else:
                    answers.render_vars[q.name] = default_value
            else:
                default_str = str(default_value) if default_value != "" else ""
                msg = f"{q.help or q.name}"
                raw = input(f"  {msg} [{default_str}]: ").strip()
                if raw:
                    answers.render_vars[q.name] = raw
                    answers.explicit_names.add(q.name)
                else:
                    answers.render_vars[q.name] = default_value

            err = _validate_answer(q, answers.render_vars[q.name], answers.render_vars)
            if err:
                if q.name in answers.explicit_names:
                    print(f"  {YELLOW}{err}{RESET}")
                    answers.explicit_names.discard(q.name)
                    del answers.render_vars[q.name]
                    continue
                warn(f"{err} - using default anyway.")
            break

    return answers


def _prompt_required_noninteractive_fallback(q: CopierQuestion) -> str:
    msg = f"{q.help or q.name}"
    if q.choices:
        choices_str = ", ".join(q.choices)
        print(f"  {msg} {DIM}({choices_str}){RESET}")
        raw = input("  Enter value: ").strip()
    else:
        raw = input(f"  {msg}: ").strip()
    return raw


def _resolve_answers_noninteractive(
    config: CopierConfig,
    overrides: dict[str, str],
) -> MigrationAnswers:
    answers = MigrationAnswers()

    for q in config.questions:
        if q.name in overrides:
            raw = overrides[q.name]
            match q.type:
                case QuestionType.BOOL:
                    answers.render_vars[q.name] = raw.lower() in (
                        "y",
                        "yes",
                        "true",
                        "1",
                        "",
                    )
                case QuestionType.INT:
                    answers.render_vars[q.name] = int(raw)
                case QuestionType.FLOAT:
                    answers.render_vars[q.name] = float(raw)
                case QuestionType.MULTISELECT:
                    parts = [p.strip() for p in raw.split(",") if p.strip()]
                    answers.render_vars[q.name] = [
                        q.choices_map.get(p, p) for p in parts
                    ]
                case QuestionType.CHOICE:
                    answers.render_vars[q.name] = q.choices_map.get(raw, raw)
                case QuestionType.YAML:
                    answers.render_vars[q.name] = _coerce_yaml_value(raw)
                case _:
                    answers.render_vars[q.name] = raw
            err = _validate_answer(q, answers.render_vars[q.name], answers.render_vars)
            if err:
                raise ZenitError(err)
        elif q.required and not q.default:
            if sys.stdin.isatty():
                raw = _prompt_required_noninteractive_fallback(q)
                if raw:
                    answers.render_vars[q.name] = raw
                    answers.explicit_names.add(q.name)
                    err = _validate_answer(
                        q, answers.render_vars[q.name], answers.render_vars
                    )
                    if err:
                        raise ZenitError(err)
                    continue
            raise ZenitError(
                f"Question '{q.name}' is required and has no default. "
                f"Pass it with -D {q.name}=<value>"
            )
        elif q.default is not None:
            answers.render_vars[q.name] = _coerce_question_value(
                q,
                _render_copier_default(q.default, answers.render_vars),
            )
            err = _validate_answer(q, answers.render_vars[q.name], answers.render_vars)
            if err:
                raise ZenitError(err)
        elif q.choices:
            if q.type == QuestionType.MULTISELECT:
                first_val = q.choices_map.get(q.choices[0], q.choices[0])
                answers.render_vars[q.name] = [first_val]
            else:
                answers.render_vars[q.name] = q.choices_map.get(
                    q.choices[0], q.choices[0]
                )
        elif q.when is False:
            answers.render_vars[q.name] = _coerce_question_value(
                q,
                _render_copier_default(
                    q.default if q.default is not None else "", answers.render_vars
                ),
            )
        else:
            raise ZenitError(
                f"Question '{q.name}' has no default and was not provided. "
                f"Pass it with -D {q.name}=<value>"
            )

    for key, value in overrides.items():
        if key not in answers.render_vars:
            answers.render_vars[key] = value

    return answers


def _stabilise_render_vars(
    config: CopierConfig,
    answers: MigrationAnswers,
    overridden_names: set[str],
    max_iterations: int = 5,
) -> None:
    for _iteration in range(1, max_iterations + 1):
        changed = False

        for q in config.questions:
            if q.name in overridden_names:
                continue
            if not isinstance(q.default, str):
                continue
            if (
                "{{" not in q.default
                and "{%" not in q.default
                and "{#" not in q.default
            ):
                continue

            rendered = _render_copier_default(q.default, answers.render_vars)
            coerced = _coerce_question_value(q, rendered)
            current = answers.render_vars.get(q.name)

            if coerced != current:
                answers.render_vars[q.name] = coerced
                changed = True

        if not changed:
            return

    warn(
        f"Variable resolution did not stabilize after {max_iterations} "
        f"iterations. Check for circular dependencies in template defaults."
    )
