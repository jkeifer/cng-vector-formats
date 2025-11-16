# Exploring Cloud-Native Geospatial Formats: A Hands-on Workshop for Vector Data

Dig into geospatial vector formats—including GeoJSON, WKT/WKB, and cloud-native
GeoParquet—using Python to see in detail how vector features are stored in each
format and to understand what cloud-native means for vector data.

[Slides for the 2025-11 FOSS4G workshops are here.](https://docs.google.com/presentation/d/1iddpQ7KSaSjUpxwy3SWzptsZsQNaD0AxyrL3KRB9H0s)

Using the [docker execution
method](#running-locally-with-docker-recommended-for-local-executions) may be
the best option due to the uncertainty of conference internet quality. But
GitHub Codespaces can be a good fallback option for those that want/need a
simpler solution.

> [!WARNING]
> Codespaces has been extremely slow and unstable in testing. Using docker or
> `uv` is strongly recommended.

## Workshop Overview

Cloud-native geospatial is all the rage these days, and for good reason. As
file sizes grow, layer counts increase, and analytical methods become more
complex, the traditional download-to-the-desktop approach is quickly becoming
untenable for many applications. It's no surprise then that users are turning
to cloud-based tools to scale out their analyses, or that traditional tooling
is adopting new ways of finding and accessing data from cloud-based sources.
But as we transition away from opening whole files to now grabbing ranges of
bytes off remote servers it seems all the more important to understand exactly
how cloud-native data formats actually store data and what tools are doing to
access it.

This workshop aims to dig into how cloud-native geospatial data formats are
enabling new operational paradigms, with a particular focus on vector data
formats. Unlike its raster workshop counterpart, this workshop will be a bit
more experimental. Vector data formats tend towards greater complexity than
raster formats, so exactly how deep we get into which topics will be dependent
on the audience’s interests and the time available. Broad themes to explore
might include:

* GeoJSON: what is it, what does it represent, and how it is not cloud-native
* Well-Known Text/Binary (WKT/WKB): how these vector formats work and why they
  are important in GeoParquet
* Parquet: how does parquet store data, how geo maps into that paradigm, and
  what it takes to read some subset of data from a parquet file
* Other cloud-native formats like FlatGeobuf, PMTiles, etc.
* Practical considerations when using these formats

The content of this workshop aims to not only be theoretical: a strong goal is
to be as hands-on with these formats as possible by working with them in Python
without any specific geospatial format libraries. We’ll look at interacting
with object storage directly, to pull down files and fragments and inspect
them, to build up working understanding of what common higher-level tooling
does under the hood and abstracts away from users.

### Prerequisites

This workshop expects some familiarity with geospatial programming in Python
and a basic understanding of the vector data model and its utility. Most of the
notebook code is already provided, so any gaps in understanding don't
necessarily prohibit completing the exercises. That said, some knowledge of the
geospatial vector formats and tooling is quite helpful.

## Getting Started

The interesting contents of this repo are, primarily, the Jupyter notebooks in
the [`./notebooks`](./notebooks) directory. To facilitate easily running the
notebooks in a properly-initialized environment, a docker compose file is
provided. The project can also be run in a GitHub codespace without having to
run anything locally. Alternately, one can set up their own python environment
and run Jupyter without a dependency on docker.

Docker compose is the recommended approach if wanting to keep all services
local (due to bad internet and/or concerns about leveraging GitHub serivces).
GitHub codespaces are recommended if considering ease of use alone.

### Running locally with docker (recommended for local executions)

Using docker has the advantage of better constraining the execution
environment, which is also set up automatically with the required dependencies.

Note that the instructions below were written with a MacOS/Linux environment in
mind. Windows users will likely need to leverage WSL to access a Linux
environment to run docker.

To begin, clone this repo:

```commandline
git clone https://github.com/jkeifer/cng-vector-formats.git
cd cng-vector-formats
```

Ensure the docker daemon or an equivalent is running via whatever mechanism is
preferred (on Linux via the docker daemon or podman; on MacOS via Docker
Desktop, colima, podman, OrbStack, or others), then use `docker compose` to
`up` the project:

```commandline
docker compose up
```

This will start up the Jupyter container within docker in the foreground. If
preferring to run compose in the background, add the detach option to the
compose command via the `-d` flag.

JupyterLab will be started with no authentication, running on port 8888 (by
default; use the env var `JUPYTER_PORT` to change it if that port is already
taken on your machine). Open a web browser and browse to
[`http://127.0.0.1:8888`](http://127.0.0.1:8888) to open the JupyterLab
interface. Select a notebook from the `notebooks` directory and work through
it.

### Running locally using `uv`

This approach is less recommended as it is more subject to local environment
differences than the docker-based approaches. But it does have the benefit of
not requiring docker as a dependency. For users on Linux or MacOS that have
experience managing a python environment, this may quite honestly be the best
option.

Note that the instructions below were written with a MacOS/Linux environment in
mind. Windows users will likely need to leverage something like [git for
Windows](https://gitforwindows.org/) and the included Git BASH tool to follow
along (WSL is also likely a viable solution to get a Linux environment on a
Windows machine).

To get started, clone this repository and start up JupyterLab using `uv run`.
Users will need to have `uv` installed to use this option.

```commandline
git clone https://github.com/jkeifer/cng-vector-formats.git
cd cng-vector-formats
uv run jupyter lab
```

The `uv run jupyter lab` will create a virtual environment with a compatible
version of python, install all dependencies, then launch JupyterLab. A web
browser window should automatically be launched with this project loaded.
Select a notebook from the `notebooks` directory and work through it.

### Running in GitHub Codespaces

This method does not require any environment setup, repo cloning, or having to
execute any code locally. However, it does depend on an external, web-based
service, which may not be ideal in environments with unknown internet quality
(i.e., conferences). Codespaces also sometimes have instability or weirdness
that does not occur when executing locally. But the fact that all this option
requires is a GitHub account and a web browser means it can be a great solution
for many users.

> [!WARNING]
> Again, for this workshop, testing has proven codespaces to be unstable.

To use GitHub Codespaces, first login to GitHub. Then, browse to [the project
repo in Github](https://github.com/jkeifer/cng-vector-formats). There, click
the green `<> Code` dropdown button, select the `Codespaces` tab in the
dropdown menu, then click the button to add a new codespace from the `main`
branch.

The codespace will launch in a new browser tab, running the web version of VS
Code. The notebooks can be opened and executed directly in this interface. The
notebook kernel will need to be selected to execute code; choose the `.venv`
kernel from the existing Python Environments option.

Codespaces also have experimental JupyterLab support. For users that might want
to try this, wait for the codespace to fully initialize. Then, go back to the
repo in GitHub and open the codespaces dropdown menu (you will likely need to
refresh the page). You should see the codespace listed, and a button with three
dots `...` next to it. Click that button to open a menu with more actions for
the codespace, then select "Open in JupyterLab". Select a notebook from the
`notebooks` directory and work through it.

### Run locally using `pip` and manual virtual environments

This option is discouraged. But for users that want to use this option, they
are welcome to do so installing dependencies using the `requirements.txt` file
via pip. Leveraging a virtual environment is _strongly_ recommended.

## Untrusted Notebooks

If when running a notebook certain cell outputs (folium maps, particularly) do
not display and instead show an error about the notebook not being trusted,
press CMD+Shift+P / CTRL+Shift+P to bring up the command pallet, then type
"Trust Notebook". Select the command with that name to trust the current
notebook.

## Presentation History

### Origin

This workshop was originally created for [FOSS4G 2025](https://talks.osgeo.org/foss4g-2025/talk/MHHJE7/).

### All Workshop Presentations

| Date | Location | Slides | Notes |
| ---- | -------- | ------ | ----- |
| 2025-11-18 | [FOSS4G Auckland, NZ](https://talks.osgeo.org/foss4g-2025/talk/MHHJE7/) | [Link](https://docs.google.com/presentation/d/1iddpQ7KSaSjUpxwy3SWzptsZsQNaD0AxyrL3KRB9H0s) | Original presentation. |
