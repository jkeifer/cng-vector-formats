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
| `main`     | Source: `src/*.py`, `scripts/`, config, this README               | Contributors |
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

* `notebooks/completed/NN_<name>.ipynb` — the completed notebook (Jupytext
  render of the `.py`). Keeping the completed renders under
  `notebooks/completed/` avoids colliding with the exercise notebooks and, on
  the `workshop` branch, gives a tidy "answers live here" separation.
* `notebooks/NN_<name>.ipynb` — the **exercise** notebook handed to attendees,
  produced by
  [`ipynb-scrubber`](https://pypi.org/project/ipynb-scrubber/), which clears
  designated cells and omits answer cells.
* `notes/NN_<name>.md` — notes extracted from cells tagged for note-taking.

Both generation steps are configured by `[tool.ipynb-scrubber]` in
`pyproject.toml` (input/output paths, tags) and `jupytext.toml` (the `src/` ↔
`notebooks/completed/` pairing). Static assets referenced by the notebooks
live in `notebooks/assets/` (tracked on `main`; the generator copies them
along with the notebooks).

### Editing

Edit `src/NN_<name>.py` directly, or edit a completed notebook in Jupyter and
sync it back to the `.py`:

```commandline
# after editing a notebook in Jupyter, sync it back to src/:
uv run jupytext --sync src/*.py
```

## Building & publishing

Two small, composable scripts handle staging content onto the `workshop`
branch. The generic `worktree.py` prepares (or reuses) a worktree for a branch;
you then generate content into it, review, and commit yourself. Nothing is
committed or pushed automatically.

```commandline
# 1. Check out the workshop branch as a worktree at ./workshop
uv run scripts/worktree.py workshop

# 2. Generate the notebooks + notes into that worktree
uv run scripts/generate_notebooks.py --output-dir ./workshop

# 3. Review, then commit/push from the worktree
cd workshop
git add -A && git commit -m "Update notebooks" && git push
```

`generate_notebooks.py` defaults `--output-dir` to the repo root, so a bare
`uv run scripts/generate_notebooks.py` regenerates the notebooks in place
(handy for a quick local check). The generated notebooks are gitignored on
`main`.

The `workshop` branch maintains its **own** participant-facing README, notes,
and runtime environment (a trimmed `pyproject.toml` with runtime deps only,
plus its `uv.lock`, Dockerfile, `compose.yml`, and `.devcontainer`). Those are
edited on the `workshop` branch, not copied from `main`; the stage script only
writes the notebooks and notes.

## Development environment

```commandline
uv sync
```

installs everything, including the dev tooling (Jupytext, ipynb-scrubber). Run
Jupyter with `uv run jupyter lab`.

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
uv run scripts/generate_notebooks.py
uv run jupyter execute notebooks/completed/NN_<name>.ipynb   # for each of 01, 02, 03
```

## Presentation History

Keep this table in sync with the copy in the `workshop` branch README.

### Origin

This workshop was originally created for [FOSS4G 2025](https://talks.osgeo.org/foss4g-2025/talk/MHHJE7/).

### All Workshop Presentations

| Date | Location | Slides | Notes |
| ---- | -------- | ------ | ----- |
| 2025-11-18 | [FOSS4G Auckland, NZ](https://talks.osgeo.org/foss4g-2025/talk/MHHJE7/) | [Link](https://docs.google.com/presentation/d/1iddpQ7KSaSjUpxwy3SWzptsZsQNaD0AxyrL3KRB9H0s) | Original presentation. |
