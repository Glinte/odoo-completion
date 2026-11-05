# odoo-completion

Command completion for **Odoo 20.0 and 20.1 development checkouts**, in **Bash,
Zsh, and Fish**. It follows the checkout you invoke, including registered wrapper
scripts, and discovers CLI commands supplied by addons.

Tab uses cached parser metadata. It does not import Odoo, start an Odoo server,
load the ORM, or execute the command being completed.

```text
odoo-bin db <Tab>                       init, load, dump, duplicate, rename, drop
odoo-bin --log-level=<Tab>              logging levels
odoo-bin -u sale,acc<Tab>               matching account modules
odoo-bin -d <Tab>                       available PostgreSQL databases
odoo-bin --test-tags /sale:Test<Tab>     test classes
odoo-bin --test-tags /sale:Class.t<Tab>  test methods
```

## Install

Requires Python 3.12 or newer. Install the tool into its own environment; do not
add it to Odoo's requirements. PostgreSQL client libraries are supplied by the
`psycopg[binary]` dependency.

From this repository:

```sh
uv tool install .
# Alternatively: pipx install .

odoo-completion register \
  --command "$HOME/.local/bin/odoo-bin" \
  --odoo-root /path/to/odoo \
  --python /path/to/venv/bin/python

odoo-completion install bash
# Or: odoo-completion install zsh
# Or: odoo-completion install fish
```

Open a new shell after installing. To enable completion immediately without
editing your profile, use your shell's command below:

```sh
# Bash or Zsh; Zsh's compinit must have run first.
source <(odoo-completion init bash)  # use zsh for Zsh
```

```fish
odoo-completion init fish | source
```

The installer appends a marked block to `.bashrc`/`.zshrc`, or installs a Fish
`conf.d` file. It preserves other configuration and can be run repeatedly.
`odoo-completion uninstall bash` removes only this tool's integration. To remove
the package itself, use `uv tool uninstall odoo-completion` or `pipx uninstall`.

Supported targets are Linux, macOS, and Linux under WSL: Bash 4.4+, Zsh 5.8+,
and Fish 3.6+. PowerShell and native Windows are outside this release's scope.

## Checkouts, addons, and refresh

Register each checkout with its own Python environment. The interpreter must
already be able to import that Odoo checkout and its CLI dependencies. Keep the
virtualenv path: resolving its symlink to the underlying Python loses the
virtualenv.

```sh
odoo-completion register \
  --command /work/20.0/odoo/odoo-bin \
  --odoo-root /work/20.0/odoo \
  --python /work/20.0/.venv/bin/python \
  --addons-path /work/20.0/enterprise,/work/20.0/custom

odoo-completion refresh --all
odoo-completion doctor
odoo-completion coverage --command /work/20.0/odoo/odoo-bin
```

After registering additional wrapper names, rerun `install` for your shell.

Direct paths and `./odoo-bin` resolve to their registered source tree. Wrappers
are explicitly associated with a checkout, regardless of the current working
directory. No wrapper parsing or shell evaluation is involved. For unregistered
checkouts, a bundled Odoo 20.0 **core** schema supplies commands/options/choices;
register the checkout for exact syntax, addon commands, and source indexes.

`--addons-path` on registration tells discovery which additional addon CLI
modules and tests to index. It does not change Odoo's launcher or configuration.
During completion, command-line/config/environment values determine the effective
module paths. Register or refresh after adding addon CLI commands, changing their
options, switching Odoo branches, or changing tests. Newly mentioned addons paths
can supply module names immediately; their command grammars need explicit discovery.

Discovery runs only on `register` and `refresh`. It imports trusted CLI code under
the registered interpreter and intercepts argument parsing before command
execution. A write/network/process guard prevents common accidental side effects;
it is **not a sandbox for hostile Python code**. Each command has a 20-second
limit. Failed commands are reported, and previously captured metadata is retained
for those commands. A failed initial discovery does not count as complete coverage.

`doctor` reports versions, source revisions, missing interpreters, parser failures,
and changes to tracked parser files/directories. `coverage` lists each argument,
its provider, and the reason for its classification; both commands support `--json`.

## What completes

| Area | Behavior |
| --- | --- |
| CLI grammar | Commands, nested commands, short/long options, fixed choices, positional arguments, repeated and optional values |
| Invocation | Implicit `server`, explicit commands, leading `--addons-path=…`, forwarded server arguments in `start` and `cloc` |
| Modules | Addon manifests on effective paths; installed modules when a database is selected; comma-separated lists |
| PostgreSQL | Database names, installed modules, model names, table columns, populate blueprints and session IDs |
| Filesystem | Files, directories, directory lists, dump/translation files, scaffold templates, upgrade scripts |
| Other values | Language/country codes, shell interfaces, development features, logging levels and handlers, upgrade versions |
| Tests | Tags, modules, test-file paths, classes, methods, exclusions, and statically resolvable inheritance |

All arguments have an explicit classification. Passwords, new database names,
URLs, numeric limits, regular expressions, and other unrestricted values remain
free text. Arbitrary values are never rejected by completion. Source-generated
test names and parameter expressions are not executed to discover suggestions.

The engine handles `--option=value`, `--option value`, attached short values,
short-option clusters, `--`, comma-separated lists, spaces, quotes, Unicode, and
the cursor position. Each shell retains its native insertion and matching behavior.
Names containing literal tab, newline, carriage return, or NUL are not offered.

Configuration follows Odoo's CLI → environment → config file → default order.
Config selection honors `-c/--config`, `ODOO_RC`, the platform's Odoo config
directory, and legacy rc files. Paths are resolved relative to the invocation's
working directory. Missing config files and unavailable databases do not interrupt
completion.

Database discovery uses read-only transactions and fixed metadata queries. It
never prompts for a password. It honors Odoo connection settings and libpq
credentials such as `.pgpass`. A worker has a **300 ms deadline**; failure returns
cached values or no candidates. Database results live for 30 seconds; module
listings for 5 seconds. Credentials are not persisted in caches or diagnostics.

## Overrides and custom providers

Nonstandard addon parsers can use a TOML override file supplied at registration
with `--overrides /path/to/completion.toml`.

```toml
[[argument]]
command = "custom_command subcommand"
dest = "region"
choices = ["eu", "us"]

[[argument]]
command = "custom_command"
dest = "input"
provider = "file"

[[argument]]
command = "custom_command"
dest = "tenant"
argv = ["/absolute/path/to/tenant-completer"]
```

An external provider is explicitly configured executable code, run on Tab with a
300 ms deadline and no shell. It receives JSON on stdin:
`{"protocol":1,"prefix":"…","cwd":"…"}` and returns a JSON array of strings.
Candidates are filtered by the typed prefix. Errors produce no suggestions.

A `[command.NAME]` table can replace a nonstandard command's entire parser model.
It has `help`, `options`, `positionals`, and `children`; arguments use the fields
in `src/odoo_completion/model.py` (`flags=[]` for positionals). Command replacements
are applied before `[[argument]]` overrides. This is also the extension point for
unsupported parser frameworks; there is no claim to introspect arbitrary Python.

## Development

```sh
uv sync
uv run ruff check .
uv run ruff format --check .
uv run pytest

ODOO_TEST_ROOT=/path/to/odoo \
ODOO_TEST_PYTHON=/path/to/venv/bin/python \
uv run pytest tests/test_odoo.py
```

Tests cover parser capture, source indexes, configuration precedence, bounded
providers, registration, reversible installation, and actual Tab insertion in
all three shells through pseudo-terminals. Database tests start and stop their
own PostgreSQL cluster on a private Unix socket. Install the server binaries to
run them; tests report a skip when binaries are unavailable. No existing Odoo
database is modified. Real-checkout tests are opt-in through the variables above.

CI configuration covers Linux/macOS shell tests and discovery against Odoo 20.0 and `master`.
The checked-in fallback records its exact upstream revision. To update it:

```sh
odoo-completion refresh --command /path/to/20.0/odoo-bin
uv run python scripts/update_snapshot.py --command /path/to/20.0/odoo-bin
```

Architecture: `probe` captures parsers in isolated processes; `discovery` assigns
semantic providers; `context` parses incomplete input; `engine` selects candidates;
`providers` and `database` resolve values; `integration` supplies native shell
adapters. Source indexes are separate from the small parser cache so ordinary
flag completion does not load the test index.

Configuration lives in `$XDG_CONFIG_HOME/odoo-completion` (default
`~/.config/odoo-completion`), caches in `$XDG_CACHE_HOME/odoo-completion` (default
`~/.cache/odoo-completion`). Deleting caches is safe; run `refresh --all` afterward.
For troubleshooting, run `doctor --json` and check the registered interpreter,
then refresh. If an old completer still wins, load this integration after it.

Original implementation: MIT. Generated Odoo metadata: see [NOTICE](NOTICE).
