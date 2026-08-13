# cng-vector-formats — Contributor Guide

> [!IMPORTANT]
> This is the **source/development branch** for *Exploring Cloud-Native
> Geospatial Formats: A Hands-on Workshop for Vector Data*. If you are here to
> **take the workshop**, you want the
> [`workshop` branch](https://github.com/jkeifer/cng-vector-formats/tree/workshop)
> instead: it contains the ready-to-run notebooks and setup instructions.

This document is for people editing the workshop content.

## About the workshop

The workshop digs into geospatial vector formats—including GeoJSON, WKT/WKB,
and cloud-native GeoParquet—using Python to see in detail how vector features
are stored in each format and to understand what cloud-native means for vector
data. A strong goal is to be as hands-on with these formats as possible by
working with them in Python without any specific geospatial format libraries,
building up a working understanding of what common higher-level tooling does
under the hood.

[Slides for the 2025-11 FOSS4G workshop are here.](https://docs.google.com/presentation/d/1iddpQ7KSaSjUpxwy3SWzptsZsQNaD0AxyrL3KRB9H0s)

## Repository model

The workshop is authored here on `main` and published to a long-lived
`workshop` branch. Keeping generated artifacts off `main` keeps its history
clean and diffable.

| Branch     | Contents                                                         | Audience     |
| ---------- | ---------------------------------------------------------------- | ------------ |
| `main`     | Source: `src/*.py`, the location model, config, this README       | Contributors |
| `workshop` | Runnable notebooks + participant README, notes, run env           | Participants |

Notebooks are **never committed on `main`** — they are generated on demand into
a worktree of the `workshop` branch and committed there.

Pull requests should target `main`. Note that once `workshop` becomes the
repository's default branch, GitHub will default new PRs to target `workshop` —
retarget them to `main`.

## Notebook sources

The source of truth for each notebook is a
[Jupytext](https://jupytext.readthedocs.io/) `py:percent` file under `src/`:

* `src/NN_<name>.py` — the full, working notebook, as readable Python with
  `# %%` cell markers (clean diffs, no JSON noise, no cell outputs). Each file
  is named for its exercise:
  * `src/01_is-geojson-cloud-native.py` — GeoJSON and why it isn't cloud-native
  * `src/02_the-well-knowns.py` — WKT/WKB by hand
  * `src/03_reading-parquet-the-hard-way.py` — parquet/GeoParquet over HTTP
    byte ranges, discovering the latest Overture Maps release via their static
    STAC catalog

From each `src/` file we generate:

* `notebooks-completed/NN_<name>.ipynb` — the completed notebook (Jupytext
  render of the `.py`). Keeping the completed renders under
  `notebooks-completed/` avoids colliding with the exercise notebooks and, on
  the `workshop` branch, gives a tidy "answers live here" separation. It is a
  *sibling* of `notebooks/`, not a child, so one relative asset reference
  resolves from both.
* `notebooks/NN_<name>.ipynb` — the **exercise** notebook handed to attendees,
  produced by
  [`ipynb-scrubber`](https://pypi.org/project/ipynb-scrubber/), which clears
  designated cells and omits answer cells.
* `notes/NN_<name>.md` — notes extracted from cells tagged for note-taking.

Both generation steps are configured in `pyproject.toml`, by
`[tool.ipynb-scrubber]` (input/output paths, tags) and `[tool.jupytext]` (the
`src/` ↔ `notebooks-completed/` pairing). Static assets referenced by the
notebooks live in `notebook-assets/`, alongside the two notebook directories
rather than inside either, so that `../notebook-assets/...` means the same
thing from each. Like the notebooks, they are build output and are **not**
committed on `main`; run `uv run workshopify render` after cloning. They are derived from
the recorded location the same way the rendered values are: the context module's
`ASSETS` map names each one and its source, `render`/`set` place them, and
`check` verifies them. Because an asset already publishes itself,
`notebook-assets/` must *not* also appear in `[tool.workshopify.build] include`
— one published path may have only one source, and the build rejects a
duplicate outright.

### Changing the workshop location

Every exercise is built around one building. It lives in `locations/`, one
TOML file per location, holding the FeatureCollection exactly as pasted from
geojson.io plus the names the prose uses. Everything else — the WKT, the
ring points, the byte counts, the size ratio — is derived.

    uv run workshopify set location hiroshima

That rewrites `src/*.py`, copies the location's screenshot to
`notebook-assets/geojson_io.png`, and records the new slug in
`[tool.workshopify.params]`. It verifies every site it is about to change is present
exactly once first, so a hand-edited source aborts the run rather than being
half-rewritten. `uv run workshopify check` runs that verification alone, reporting
stale rendered values or assets, and runs in CI.

Afterwards, regenerate and **execute notebook 03**: the script cannot know
whether the new building is actually found in Overture, or how many row groups
match. That needs a real run.

To add a location, copy `locations/auckland.toml` to `locations/<slug>.toml`
and drop its geojson.io screenshot in `locations/` alongside it. The file name's
stem is the slug. Six keys are required, all of them:

| Key                  | What it is                                                                     |
| -------------------- | ------------------------------------------------------------------------------ |
| `building_name`      | The building, as exercise 3's prose names it                                    |
| `city`               | Fills "all buildings in *city*"                                                 |
| `region`             | The next step out — "Or *region*"                                               |
| `macro`              | The step out from there — "Or all of *macro*"                                   |
| `screenshot`         | The geojson.io screenshot, relative to `locations/` (or an absolute path)       |
| `feature_collection` | The FeatureCollection, pasted verbatim from geojson.io, in a `'''` TOML string  |

The collection must hold exactly one feature whose geometry is a `Polygon`
with a single ring — one building, no holes, no MultiPolygon. Loading rejects
anything else, since the exercises hand-encode that one ring. Everything else
is derived, so nothing else needs writing down.

### Editing

Edit `src/NN_<name>.py` directly, or edit a completed notebook in Jupyter and
sync it back to the `.py`:

```commandline
# after editing a notebook in Jupyter, sync it back to src/:
uv run jupytext --sync src/*.py
```

## Publishing to the `workshop` branch

The `workshop` branch is a pure build artifact — every file on it is
reproducible from `main`, so a publish replaces the tree rather than
merging into it.

    uv run workshopify build

That assembles the complete published tree into the `workshop` worktree:
the files named by `[tool.workshopify.build] include`, the `static/` overlay,
the generated notebooks and notes, the declared assets, and a
`pyproject.toml`/`uv.lock` derived from main's (dev tooling and the
`[tool.workshopify]` tables stripped). Nothing is committed or
pushed automatically — review and publish yourself:

```commandline
uv run workshopify build
git -C workshop status                     # review
git -C workshop add -A
PREK_ALLOW_NO_CONFIG=1 git -C workshop commit -m "Update notebooks"
git -C workshop push
```

`PREK_ALLOW_NO_CONFIG=1` on the commit is required, not optional. Git
keeps a single `.git/hooks` directory shared by every worktree of a
repository, so the `prek` pre-commit hook installed for contributor work
also fires inside `workshop`. That branch deliberately carries no
`.pre-commit-config.yaml` — it is a build artifact, and contributor lint
config is not part of what participants receive — so the hook would abort
the commit with `No prek.toml or .pre-commit-config.yaml found`. The
variable lets the hook no-op on its own terms, which is preferable to
`--no-verify` (that would disable hook execution wholesale). Do not
"fix" this by adding a pre-commit config to the `workshop` branch: the
build would drop it on the next publish anyway, since the branch only
ever contains what `workshopify build` writes.

The build only writes. If a file was renamed or dropped, its old copy
stays on the branch — and since it is unchanged, `git status` there says
nothing at all, so the build reports every tracked file it did not write.
`--clean` removes those, by `git rm`-ing all tracked files before
building. Ignored files deliberately survive that: the worktree holds a
multi-gigabyte `.hctef-cache` that notebook 03 would otherwise refetch.

Both modes refuse to run if the worktree has uncommitted changes, since
those may be notebook edits made in Jupyter that are not yet synced back
to `src/`. `--overwrite-dirty` proceeds anyway; what that costs depends on
the mode. The default build overwrites only the files it writes, so
unrelated dirty files survive; `--clean` deletes every tracked file first,
modifications included.

## Development environment

```commandline
uv sync
```

installs everything, including the dev tooling (Jupytext, ipynb-scrubber). Run
Jupyter with `uv run jupyter lab`.

The `workshopify` commands used throughout this guide come from
[workshopify](https://github.com/jkeifer/workshopify), a separate package
released to PyPI and pinned in the dev dependency group. It holds all the
generic build machinery; what is specific to this workshop lives in the
`[tool.workshopify]` tables of `pyproject.toml` and in `scripts/`.

After syncing, install the git hooks with `uv run prek install`. The hooks run
ruff lint and format, with the tools coming from the dev dependency group; run
them manually with `uv run prek run --all-files`.

## Checks / CI

CI (`.github/workflows/ci.yml`) runs on pull requests and on pushes to `main`.
It runs the prek hooks, then generates all notebooks from `src/` and executes
each completed notebook end to end. Notebook 03 reads live Overture Maps
parquet over HTTP (no credentials needed); its hctef byte cache is persisted
between runs with `actions/cache`, so reruns skip most of the network I/O. The
local equivalents:

```commandline
uv run prek run --all-files
uv run workshopify generate
uv run jupyter execute notebooks-completed/NN_<name>.ipynb   # for each of 01, 02, 03
```

## Presentation History

Keep this table in sync with the copy in the `workshop` branch README.

### Origin

This workshop was originally created for [FOSS4G 2025](https://talks.osgeo.org/foss4g-2025/talk/MHHJE7/).

### All Workshop Presentations

| Date | Location | Slides | Notes |
| ---- | -------- | ------ | ----- |
| 2025-11-18 | [FOSS4G Auckland, NZ](https://talks.osgeo.org/foss4g-2025/talk/MHHJE7/) | [Link](https://docs.google.com/presentation/d/1iddpQ7KSaSjUpxwy3SWzptsZsQNaD0AxyrL3KRB9H0s) | Original presentation. |
