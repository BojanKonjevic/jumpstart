# zenit graph

Render the addon dependency graph. Shows which addons depend on which, both for the current project and the full ecosystem.

```
zenit graph [--all] [--reverse] [--dot] [--json]
```

---

## Default mode

Without flags, `zenit graph` shows the dependency tree of addons installed in the current project:

```
╭─ Zenit Graph ───────────────────────────────╮
│                                             │
│   ● redis                                   │
│     ● hiredis                               │
│   ○ sentry                                  │
│                                             │
│   ◉ installed 2   ○ available 1             │
│   my-api  │  /home/user/my-api              │
╰─────────────────────────────────────────────╯
```

This requires `.zenit.toml` in the current directory.

---

## `--all`

Show the full addon ecosystem - every addon Zenit knows about, not just the ones installed in the current project. Useful when exploring what addons exist before deciding what to install.

```
zenit graph --all
```

Does not require `.zenit.toml`.

---

## `--reverse`

Show the reverse dependency tree - for each addon, which other addons depend on it.

```
zenit graph --reverse
```

```
╭─ Zenit Dependencies ────────────────────────╮
│                                             │
│   ● redis                                   │
│     ● celery                                │
│   ● sqlalchemy                              │
│     ● auth-manual                           │
│     ● sqlmodel                              │
│                                             │
│   ◉ installed 4   ○ available 0             │
│   my-api  │  /home/user/my-api              │
╰─────────────────────────────────────────────╯
```

---

## `--dot`

Output the dependency graph in Graphviz DOT format. Pipe to `dot` to render an image:

```
zenit graph --dot | dot -Tpng -o graph.png
zenit graph --all --dot | dot -Tsvg -o graph.svg
```

---

## `--json`

Output machine-readable JSON with full addon metadata:

```
zenit graph --json
```

```json
{
  "project": {
    "name": "my-api",
    "template": "fastapi",
    "dir": "/home/user/my-api"
  },
  "addons": [
    {
      "id": "auth-manual",
      "installed": true,
      "requires": ["sqlalchemy"],
      "required_by": []
    },
    {
      "id": "celery",
      "installed": false,
      "requires": ["redis"],
      "required_by": []
    },
    {
      "id": "redis",
      "installed": true,
      "requires": [],
      "required_by": ["celery"]
    }
  ]
}
```

The `requires` field lists addons this addon depends on. The `required_by` field lists addons that depend on this one (reverse edges). Only addons visible in the current invocation are included - use `--all` to include every known addon.

---

## Error conditions

| Condition | Behaviour |
|---|---|
| No `.zenit.toml` and no `--all` | Error: "No .zenit.toml found. Use --all to see the full ecosystem." |
| No `.zenit.toml` with `--all` | Works - shows every known addon, none marked installed |
| No addons installed and no `--all` | "No addons to show." |
