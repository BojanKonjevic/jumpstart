# Configuration

Zenit reads a user-level config file on every run. It sets personal defaults that pre-select options in the interactive prompts - you can still change them before confirming. The file is optional; Zenit works without it.

---

## File location

| Platform | Path |
|---|---|
| Linux / macOS | `$XDG_CONFIG_HOME/zenit/zenit.toml` (default: `~/.config/zenit/zenit.toml`) |
| Windows | `%APPDATA%\zenit\zenit.toml` (default: `~/AppData/Roaming/zenit/zenit.toml`) |

Create the file and its parent directory manually:

```bash
mkdir -p ~/.config/zenit
touch ~/.config/zenit/zenit.toml
```

---

## Available settings

### `default_template`

Pre-selects a template in `zenit create`. Must match a template ID Zenit knows about (`blank` or `fastapi`).

```toml
default_template = "fastapi"
```

### `default_addons`

Pre-selects addons in `zenit create`. Addons incompatible with the selected template are silently ignored. Addon dependencies are resolved automatically - listing `celery` without `redis` is fine; Zenit selects both.

```toml
default_addons = ["docker", "github-actions"]
```

---

## Viewing current settings

```bash
zenit config
```

Output when the file exists:

```
  Config file:  /home/you/.config/zenit/zenit.toml
  ✓  file exists

  default_template  =  fastapi
  default_addons    =  docker, github-actions
```

Output when the file does not exist:

```
  Config file:  /home/you/.config/zenit/zenit.toml
  file does not exist - using built-in defaults

  default_template  =  not set
  default_addons    =  not set

  Create the file to set your own defaults.  Example:

    default_template = "fastapi"
    default_addons = ["docker", "github-actions"]
```

---

## How defaults interact with `zenit create`

Defaults pre-select options in the interactive prompts - they do not skip them. You still navigate and confirm before anything is written.

In the template picker, the default template opens with the cursor on it. In the addon picker, pre-selected addons appear with `●`; you can deselect them before confirming.

If `default_addons` includes an addon incompatible with the template you actually select (e.g. `auth-manual` when picking `blank`), it is silently dropped before the picker opens.

---

## Example configs

### FastAPI API project

```toml
default_template = "fastapi"
default_addons = ["docker", "redis", "github-actions"]
```

### Scripts and small tools

```toml
default_template = "blank"
default_addons = ["github-actions"]
```

### Always start with CI, nothing else pre-selected

```toml
default_addons = ["github-actions"]
```
