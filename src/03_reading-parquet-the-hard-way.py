# %% [markdown]
# # Reading parquet the hard way
#
# Parquet is a cloud-native data format suitable for a variety of data types, including geospatial vector data. It is often described as being "column-oriented", as opposed to row-oriented like traditional databases and vector formats (though in reality parquet is really more of a hybrid format, one not strictly columnar).
#
# The cloud-native aspect of parquet mainly comes down to two facets of its design:
#
# * file metadata is consolidated at the end of a file, and can be read entirely in at most two requests
# * the metadata contains enough information for clients to selectively read only chunks that may contain targeted rows
#
# ## Predicate pushdown
#
# This "selective reading" is done by a process called "predicate pushdown". Predicate pushdown enables clients to skip reading potentially massive amounts of data by leveraging things like chunk statistics and chunk bloom filters to restrict reads to only those chunks that _may_ potentially contain target data.
#
# Consider an example like this SQL statement:
#
# ```sql
# SELECT temperature
# FROM dataset
# WHERE
#   st_intersects(geom, AOI)
#   AND snow_cover_percent > 0
#   AND precipitation >= 10
#   AND land_cover NOT IN ("rock", "urban")
# ```
#
# Here we see the user requesting the `temperature` variable from `dataset` records that have:
#
# * a geometry intersecting the AOI
# * any snow cover
# * some significant precipitation
# * a non-impervious surface
#
# Each of these conditions is called a predicate. Predicate pushdown means using predicates to filter what chunks to read from a file, or to even filter out whole files. File and chunk statistics provide a means of identifying files and chunks that cannot possibly have a record of interest per the query predicates, and skipping those. Of those remaining, bloom filters can provide another efficient check to eliminate chunks that cannot possibly contain target records. What chunks are left are then read and filtered by the client application using the actual values prior to returning the requested data.
#
# Note the language "cannot possibly contain" is used here specifically: we never want to miss a matching record, so we use techniques that give us means of eliminating chunks with certainty that they will not contain a record of interest. These techniques come with the trade off that false positives can occur: we can rarely know that a chunk _does_ have a target record. Sometimes we then read chunks without target records, because that is the only way to ensure they do not have what we are looking for.
#
# Generally though, predicate pushdown is an effective means of eliminating a large amount of data without having to read anything but metadata.
#
# ## The exercise
#
# To get a deeper understanding of parquet and how it works, we're going to examine the [Overture Maps Buildings dataset](https://docs.overturemaps.org/guides/buildings). We will find the geometry for the building we're in for this workshop, the AUT School of Business building.
#
# This exercise is perhaps a bit contrived, because we'll start with a rough geometry for the building that we traced from aerial imagery in exercise 1, but the principles we'll be demonstrating are applicable generally for clients wanting to read from parquet, and will show how that process works in some detail. Key to the process will be a focus on using predicate pushdown with geometries, and how we can use less expensive bounding box operations to more efficiently eliminate chunks and records before turning to more expensive real-geometry comparisons.
#
# ### The `por-que` library
#
# To facilitate the learning experience, we'll use the author's custom python parquet parsing library, called `por-que`. This library is different from other, more efficient parsing libraries like `pyarrow`, in that it is designed for the educational experience. A core feature is the parsing of the entire file metadata, data page metadata, and byte structure of the file, which it exposes to users, unlike other tools that keep them hidden away as internal details.
#
# `por-que` can export the entire parsed structure to JSON, which can then be loaded, visualized, and explored with the [`ver-por-que` web application](https://teotl.dev/ver-por-que/). We'll see all of this in action through the exercise.
#
# But first, let's get some prep out of the way.
#
# ### A persistent byte cache
#
# We are going to be making a _lot_ of HTTP range requests in this exercise. Under the hood, `por-que` reads bytes through a transport library called `hctef`, which can persist every byte range it fetches to a size-bounded disk cache. With the cache enabled, re-running a cell--or recovering from a kernel crash--reads from local disk instead of hitting the network again.
#
# We configure the cache with environment variables before using `por-que`. We can also safely mark the cache immutable (skipping revalidation requests) because Overture release paths are versioned: the bytes at any given URL never change.

# %%
import os

os.environ.setdefault('HCTEF_CACHE_DIR', str(os.path.abspath('.hctef-cache')))
os.environ.setdefault('HCTEF_CACHE_MAX_BYTES', str(4 * 2**30))  # 4 GiB
os.environ.setdefault('HCTEF_CACHE_IMMUTABLE', '1')

# %% [markdown]
# Now the necessary imports.

# %%
import asyncio
import json
import time

from contextlib import AsyncExitStack
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Self
from urllib.parse import urljoin

import aiohttp

from devtools import pprint
from IPython.display import Pretty
from por_que import AsyncHttpFile, FileMetadata, ParquetFile
from shapely import (
    from_geojson as shapely_from_geojson,
    from_wkb as shapely_from_wkb,
    intersection,
)

# %% [markdown]
# We'll also define a helper function for zipping async iterators together, which we'll use later.


# %%
async def azip(*iterators):
    """This is a silly zip implementation for async iterators that
    assumes equal length. Don't copy this. It's not robust."""
    _iter = iter(iterators)
    first, rest = next(_iter), list(_iter)
    async for val in first:
        yield (val, *[await anext(iterator) for iterator in rest])


# %% [markdown]
# And we'll define a bounding box model, which we will be able to use for all of the bounding box operations in this exercise. Note that we could have used an existing model from a library, but by implementing our own we can see how simple the bounding box operations are.


# %%
@dataclass(slots=True, frozen=True)
class BBox:
    xmin: int | float
    ymin: int | float
    xmax: int | float
    ymax: int | float

    def intersects(self, other: Self) -> bool:
        return (
            other.xmin < self.xmax
            and self.xmin < other.xmax
            and other.ymin < self.ymax
            and self.ymin < other.ymax
        )

    @classmethod
    def from_linestring(cls, linestring: list[list[int | float]]) -> Self:
        xmin = float('inf')
        ymin = float('inf')
        xmax = float('-inf')
        ymax = float('-inf')

        try:
            for x, y in linestring:
                xmin = min(xmin, x)
                ymin = min(ymin, y)
                xmax = max(xmax, x)
                ymax = max(ymax, y)
        except (TypeError, ValueError) as e:
            # what a non-coordinate-pair element raises when it fails to unpack
            raise ValueError('Failed to extract bbox') from e

        return cls(xmin, ymin, xmax, ymax)


# %% [markdown]
# Lastly, we'll define the geometry we'll be using for this exercise, and we'll use it with our `BBox` class to construct its bounding box. Again, this is the same polygon we delineated in exercise 1.

# %%
geom = json.loads("""{
  "coordinates": [
    [
      [
        174.76536299052356,
        -36.85325730119731
      ],
      [
        174.76501948066357,
        -36.85354934760823
      ],
      [
        174.76510987799577,
        -36.853728372411425
      ],
      [
        174.76557768418712,
        -36.85354844344181
      ],
      [
        174.76544321815658,
        -36.85331878474462
      ],
      [
        174.76536299052356,
        -36.85325730119731
      ]
    ]
  ],
  "type": "Polygon"
}""")
geom

# %%
geom_bbox = BBox.from_linestring(geom['coordinates'][0])
geom_bbox

# %% [markdown]
# ## Overture Maps parquet data
#
# Overture Maps has a number of datasets available in parquet format, including the building footprints dataset we'll be using for this exercise. All are distributed from both AWS and Azure using their respective object storage services.
#
# Overture cuts a new release of the data roughly monthly, and--importantly for us--**old releases get deleted**. Hardcoding a release path is a great way to have a notebook that stops working a few months later (ask me how I know). What we want instead is a way to discover the latest release, and the files within it, dynamically.
#
# ### The Overture STAC catalog
#
# Overture publishes a [STAC](https://stacspec.org/) catalog describing every release at `https://stac.overturemaps.org/catalog.json`. STAC (SpatioTemporal Asset Catalog) is a specification for describing geospatial data with JSON metadata; if you've used a STAC API before, note this is the other flavor: a **static catalog**, nothing but plain JSON files linked to each other, served over HTTP. There is no search endpoint--a client navigates by fetching a JSON document, inspecting its `links` array, and following `href`s of interest. That makes a static catalog itself a nice example of cloud-native thinking: it's just files, any dumb object store can host it, and the client does the work.
#
# The links use **relative** `href`s (e.g. `./2026-06-17.0/catalog.json`), so we resolve each against the URL of the document we found it in, just like a browser resolves relative links in HTML.
#
# Let's define a small helper to fetch JSON documents, then grab the root catalog and take a look.

# %%
STAC_ROOT_URL = 'https://stac.overturemaps.org/catalog.json'


async def get_json(session: aiohttp.ClientSession, url: str) -> dict:
    async with session.get(url) as response:
        response.raise_for_status()
        return await response.json()


# %%
async with aiohttp.ClientSession() as session:
    stac_root = await get_json(session, STAC_ROOT_URL)

pprint(stac_root['links'])

# %% [markdown]
# The root catalog has a `child` link per release. Notice the extra `latest` marker Overture puts on the newest release's link: that is our dynamic version pin. Let's follow it down the tree. The releases are partitioned by theme, then by type within the theme--the same `theme=buildings/type=building` hierarchy you see in the object-store paths--so from the release catalog we follow the `buildings` theme child, and from there the `building` type child, which is a STAC collection.

# %%
latest_link = next(link for link in stac_root['links'] if link.get('latest'))
latest_release_url = urljoin(STAC_ROOT_URL, latest_link['href'])
latest_release_url

# %%
async with aiohttp.ClientSession() as session:
    release_catalog = await get_json(session, latest_release_url)

    buildings_link = next(
        link
        for link in release_catalog['links']
        if link['rel'] == 'child' and link['title'] == 'buildings'
    )
    buildings_url = urljoin(latest_release_url, buildings_link['href'])
    buildings_catalog = await get_json(session, buildings_url)

    building_link = next(
        link
        for link in buildings_catalog['links']
        if link['rel'] == 'child' and link['title'] == 'building'
    )
    building_collection_url = urljoin(buildings_url, building_link['href'])
    building_collection = await get_json(session, building_collection_url)

release_catalog['id']

# %% [markdown]
# The `building` collection has an `item` link for every parquet file in the dataset. How many are there?

# %%
item_links = [link for link in building_collection['links'] if link['rel'] == 'item']
len(item_links)

# %% [markdown]
# Wow, that's a lot of files! But it is not unexpected: this is a worldwide building footprints dataset, so it has _a lot_ of records (we'll see exactly how many in a bit). To make it more efficient to access a subset of the dataset, Overture partitions the rows into files around 1 GB in size. So we have a ton of data here, how will we ever find the record for which we are searching?
#
# First we need the item documents themselves: one small JSON file per parquet file. Fetching hundreds of documents one at a time would be painfully slow--each request would wait for the previous one to finish, paying the full network round trip every time. Instead we can create all the fetch coroutines up front and run them concurrently with `asyncio.gather`, so the round trips overlap. Keep this pattern in mind; we'll use it again shortly for something much bigger.

# %%
async with aiohttp.ClientSession() as session:
    items = await asyncio.gather(
        *[
            get_json(session, urljoin(building_collection_url, link['href']))
            for link in item_links
        ],
    )

pprint(items[0])

# %% [markdown]
# Each item describes one parquet file: where it lives (the `assets`, with an HTTPS URL for each of AWS and Azure), plus some properties about it, and even the bounding box of everything in the file (hold that thought--we'll come back to it). We'll read from AWS; let's pull out the HTTPS URL for every file.

# %%
parquet_urls = [item['assets']['aws']['href'] for item in items]
parquet_urls[:3]


# %% [markdown]
# ## Loading one of these files using `por-que`
#
# `por-que` exposes three key classes, each of which we'll be using throughout the rest of this exercise:
#
# * `AsyncHttpFile`
# * `FileMetadata`
# * `ParquetFile`
#
# The first of these, `AsyncHttpFile`, is a helper class that can open an HTTP(S) URL and expose it as a readable filelike object. We need this to allow the other two classes to do their parsing of the parquet files over HTTP.
#
# `FileMetadata` is a class that represents the block of metadata at the end of a parquet file. This metadata includes both file level information, like the schema, and chunk level metadata via row groups and their column chunks. Passing a readable filelike object into `FileMetadata.from_reader()` will parse the metadata object from said file.
#
# `ParquetFile` is a class that represents the entire physical and logical structure of a parquet file. This includes `FileMetadata`, but also all data page locations and metadata. `ParquetFile` and its nested `DataPage` objects allow reading data from the file. `ParquetFile.from_reader()`, similar to above, will parse the full structure and metadata from a passed in readable filelike object.
#
# Let's see how we can use `AsyncHttpFile` with `ParquetFile` and some of what the latter exposes. Note that creating the `ParquetFile` instances has to make many random reads within the file, so this is not a fast process, especially over the network (though thanks to the byte cache we set up at the top, re-running it is nearly instant).
#
# Because these parses can take a while, `por-que` accepts a `progress` callback: it calls the function with the current phase of the parse and how far along it is. We can use that with an updating IPython display to get a live one-line status without spewing output. Let's make a small factory so every slow parse in this notebook can have its own status line (the time-based throttle just keeps us from flooding the kernel's messaging when the parse is fast).


# %%
def parquet_progress():
    status = display(Pretty('starting...'), display_id=True)
    last = 0.0

    def callback(phase, done, total):
        nonlocal last
        now = time.monotonic()
        if done < total and now - last < 0.2:
            return
        last = now
        status.update(Pretty(f'{phase}: {done:_} of {total:_}'))

    return callback


# %%
async with AsyncHttpFile(parquet_urls[0]) as hf:
    pf = await ParquetFile.from_reader(
        hf,
        parquet_urls[0],
        progress=parquet_progress(),
    )


# %%
pprint(pf.metadata.schema_root)

# %%
pprint(pf.metadata.row_groups[0])

# %% [markdown]
# ### Visualizing the `ParquetFile` structure
#
# We can dump our `ParquetFile` model instance to JSON, and then we can load that into a static web application called [ver-por-que](https://teotl.dev/ver-por-que). The app will show the structure via an interactive visualization.
#
# So let's first write our JSON file:

# %%
Path('./buildings.parquet.json').write_text(pf.to_json())

# %% [markdown]
# Now, download the json file (right-click on the file in the file explorer sidebar), then browse to [ver-por-que](https://teotl.dev/ver-por-que) and load the JSON file.
#
# Key things to notice:
#
# * how data page region is logically organized into row groups and column chunks, but all the row group and column chunk information comes from the file metadata
# * the schema is not a flat set of columns: it has nested data structures, like the bbox columns
# * the general layout of the file bytes

# %% [markdown]
# ### File-level geo metadata
#
# Another thing to note is that the parquet specification does not have file-level statistics or bloom filters--such information is available (optionally) at the column chunk (and sometimes data page) level, but not the file level.
#
# To facilitate more performant reading by allowing filtering at the file level, convention dictates writing geospatial metadata to the top-level of the file using the flexible "key/value" metadata in the file metadata structure. This geospatial metadata is written in JSON format, and includes the bounding box around all geometries in the file.
#
# We can view that metadata like so:

# %%
json.loads(
    next(kv for kv in pf.metadata.key_value_metadata if kv.key == 'geo').value,
)

# %% [markdown]
# ## Filtering files
#
# Now that we know how to determine the bounding box for a file's geometries, we can take a first pass at eliminating data we'll need to read by finding only those files that have a bounding box that intersects our geometry's bounding box.
#
# ### Reading the metadata for all files
#
# Above, we read the geospatial metadata for a file, but we need to do it for all files. Reading the metadata can be slow due to network round trips and latency. To make reading the metadata across all files possible in a somewhat reasonable amount of time we can leverage parallelism (the same `asyncio.gather` pattern we used for the STAC items), but that comes at the cost of code complexity.
#
# In essence, the code below is creating an `AsyncHttpFile` instance for every file in our list. We open each of those instances within a context manager, so they will be automatically closed once we leave this context. With each of those `AsyncHttpFile` instances we can create a corresponding `FileMetadata` instance via an async function call. We put all those async calls into a list, so we can use `asyncio.gather` to run them in parallel, and we `await` the completion of the gather to get all the produced `FileMetadata` instances. Again, parallelism allows us to make many HTTP requests for the data at once, instead of having to wait as we would when running requests serially.
#
# These `FileMetadata` instances we zip up with the corresponding URLs, and we use the resulting tuples to construct a dictionary keyed on the file URL. This gives us a mapping of a file's URL to its `FileMetadata` instance.
#
# We'll also collect and output the total number of bytes in this dataset summed across all files.
#
# Two important tricks make this workable at this scale:
#
# * **Column projection.** A full parse of one of these footers retains roughly 24 MB of parsed metadata per file--multiply by every file in the dataset and the kernel dies. But the filtering stages ahead only need the four bbox columns, and `FileMetadata.from_reader()` accepts a `columns=` projection that skips parsing all the column-chunk metadata we don't care about, retaining ~10x less memory (the schema and the key/value `geo` metadata always parse fully, so our file-level bboxes are unaffected).
# * **A parsed-metadata cache.** The network bytes are already covered by the disk cache, but the parse itself is CPU-bound and takes a few minutes for the whole dataset. So immediately after building `fms`, we persist it to `fms.json`; the guard in the cell below reloads it, making a re-run (or a crash recovery) cost seconds instead of minutes. The dump format can change between `por-que` versions, so we store the version alongside and ignore the cache on mismatch.
#
# And since this is the longest-running cell in the notebook, we'll keep ourselves sane with a live progress line: here `por-que`'s per-file progress callback is the wrong granularity (hundreds of files parsing concurrently), so instead we wrap each file's parse in a small coroutine that bumps a completed-files counter as it finishes.

# %%
BBOX_COLS = ['bbox.xmin', 'bbox.ymin', 'bbox.xmax', 'bbox.ymax']
FMS_CACHE = Path('fms.json')
POR_QUE_VERSION = version('por-que')

fms: dict[str, FileMetadata] = {}
total_bytes = 0
if FMS_CACHE.exists():
    cached = json.loads(FMS_CACHE.read_text())
    if cached['por_que_version'] == POR_QUE_VERSION:
        fms = {
            url: FileMetadata.model_validate(dump)
            for url, dump in cached['fms'].items()
        }
        total_bytes = cached['total_bytes']

len(fms)

# %%
if not fms:
    scanned = 0
    scan_progress = display(
        Pretty(f'{scanned} of {len(parquet_urls)} files scanned'),
        display_id=True,
    )

    async def scan_file(f):
        global scanned
        fm = await FileMetadata.from_reader(f, columns=BBOX_COLS)
        scanned += 1
        scan_progress.update(
            Pretty(f'{scanned} of {len(parquet_urls)} files scanned'),
        )
        return fm

    fm_tasks = []
    async with AsyncExitStack() as stack:
        for url in parquet_urls:
            f = await stack.enter_async_context(AsyncHttpFile(url))
            total_bytes += f.size
            fm_tasks.append(asyncio.create_task(scan_file(f)))
        fms = dict(zip(parquet_urls, await asyncio.gather(*fm_tasks)))

    FMS_CACHE.write_text(
        json.dumps(
            {
                'por_que_version': POR_QUE_VERSION,
                'total_bytes': total_bytes,
                'fms': {
                    url: json.loads(fm.model_dump_json()) for url, fm in fms.items()
                },
            },
        ),
    )

print(f'{total_bytes:_}')

# %% [markdown]
# Let's also see how many rows we have in this dataset across all the files.

# %%
total_rows = 0
for fm in fms.values():
    total_rows += fm.row_count

print(f'{total_rows:_}')

# %% [markdown]
# As a sanity check: the STAC items reported row counts too. Do the catalog and the file metadata agree?

# %%
total_rows == sum(item['properties']['num_rows'] for item in items)

# %% [markdown]
# ### Finding intersecting files by their bounding boxes
#
# We can iterate through our file URLs and their `FileMetadata` instances to build a `BBox` for each from the geospatial metadata. We do the same `json.loads()` call on the key/value metadata entry with the `geo` key that we saw above; from the resulting dictionary we can build a `BBox` from the `['columns']['geometry']['bbox']` fields.
#
# Once we have a file's `BBox`, we can check for an intersection with our geometry's `BBox` and note where we find one. At the end we will have a list of the URLs for all files that are worthy of a closer look. Any that get filtered out we can know with certainty do not contain rows of interest, so we can safely disregard them.

# %%
urls_that_intersect = []
for fm_url, fm in fms.items():
    kv_metadata = json.loads(
        next(kv for kv in fm.key_value_metadata if kv.key == 'geo').value,
    )
    bbox = BBox(*kv_metadata['columns']['geometry']['bbox'])
    if bbox.intersects(geom_bbox):
        print(bbox)
        urls_that_intersect.append(fm_url)

print(geom_bbox)
urls_that_intersect

# %% [markdown]
# ### An aside: catalog-level vs file-level metadata
#
# Remember the bounding box on each STAC item? That is the exact same information we just extracted from each file's `geo` key/value metadata--but hoisted up to the catalog level, available _before touching a single parquet footer_. A client that trusts the catalog could have done this file-level filtering step from the item documents alone:

# %%
stac_urls_that_intersect = [
    item['assets']['aws']['href']
    for item in items
    if BBox(*item['bbox']).intersects(geom_bbox)
]
stac_urls_that_intersect == urls_that_intersect

# %% [markdown]
# This is a recurring cloud-native pattern: each level of metadata exists to save you from reading the level below it. The catalog saves you the footers; the footers will save us from reading most of the data pages. (It's also a handy escape hatch: if the metadata scan above is intolerably slow on conference wifi, you could filter with the STAC bboxes first and run the scan over just the intersecting files.)
#
# Speaking of saving: now that we know which few files matter, there is no reason to keep metadata for hundreds of files we've ruled out sitting in memory. Let's drop everything else.

# %%
fms = {url: fms[url] for url in urls_that_intersect}
len(fms)

# %% [markdown]
# ## Finding intersecting row groups
#
# We've successfully filtered down the file set to a much smaller number, but we can still filter the data we need to read even further. To do so, we can perform the same bounding box filtering we did at the file level, but at the row group level using the column chunk statistics across our bounding box columns.
#
# Let's walk through this process for one file, and once we see how that process comes together we can create a single routine to perform the checks across each file in our filtered set.
#
# To begin, we'll grab the `FileMetadata` instance for one of our matching URLs. From that we can start looking into the logical structures of the file, the row groups and column chunks.

# %%
fm = fms[urls_that_intersect[0]]

# %%
bbox_min_cc0 = fm.row_groups[0].column_chunks['bbox.xmin']
pprint(bbox_min_cc0)

# %% [markdown]
# We see the structure of the file starting to take shape:
#
# * Files have rows split up into row groups
# * Files have columns, but these are not accessed directly
# * Row groups have a column chunk for each column in the file
#
# Parquet is not truly column-oriented! It is column oriented within row groups, but within a file the organization is something of a hybrid between column and row-orientation.
#
# What does this mean for us? We cannot just read a column. But that's okay, because if we identify column chunks that might contain data we're looking for then we can identify what row groups definitely don't have records we want, and we have a means of filtering down the data we need to read.
#
# But how do we do this? We can use the column chunk statistics. Specifically the min and max values.

# %%
bbox_min_cc0.statistics.min_value

# %%
bbox_min_cc0.statistics.max_value

# %% [markdown]
# These values aren't super helpful looking, are they? What do they even mean?
#
# To understand how to interpret these raw bytes, we need to do two things:
#
# * Convert them to the column's physical type
# * Convert the physical type value to the column's logical type
#
# To get the type information for a column, we can use the `FileMetadata`'s schema. To make it easier to access the specific schema element for this column, each column chunk has a link to its schema element in its metadata.

# %%
schema = bbox_min_cc0.metadata.schema_element
schema

# %% [markdown]
# We can explicitly get the physical and logical types from this schema element (which are also contained in its string representation above):

# %%
schema.type

# %%
schema.get_logical_type()

# %% [markdown]
# In this case, we get a fairly expected answer: the physical type of bounding box coordinates is float, and no additional logical type conversion need happen to use the float values (logical types are super useful in other cases, like telling us a bytes physical type column is a geometry, or encoding other special types like decimals, datetimes, JSON, etc.).
#
# With this type information we can convert our raw bytes values into something more useful. In fact, the schema element has conversion helper methods on it for just this purpose:

# %%
schema.physical_to_logical_type(
    schema.bytes_to_physical_type(bbox_min_cc0.statistics.max_value)
)

# %% [markdown]
# What's more, the statistics object itself can convert the min and max values for us (using these same convenience methods under the covers):

# %%
{
    'min_value': bbox_min_cc0.statistics.converted_min_value,
    'max_value': bbox_min_cc0.statistics.converted_max_value,
}


# %% [markdown]
# Now that we can get these min/max statistics in a useful form, we can build up a bounding box for each row group. Let's make a function to construct a `BBox` instance for a given row group:


# %%
def get_rg_bbox(row_group) -> BBox:
    return BBox(
        row_group.column_chunks['bbox.xmin'].statistics.converted_min_value,
        row_group.column_chunks['bbox.ymin'].statistics.converted_min_value,
        row_group.column_chunks['bbox.xmax'].statistics.converted_max_value,
        row_group.column_chunks['bbox.ymax'].statistics.converted_max_value,
    )


# %% [markdown]
# We can try it out and see what we get:

# %%
get_rg_bbox(fm.row_groups[0])

# %% [markdown]
# Cool, that works! Let's run it on every row group of our `FileMetadata` instance and check for any intersections

# %%
intersecting_rgs = [rg for rg in fm.row_groups if get_rg_bbox(rg).intersects(geom_bbox)]
len(intersecting_rgs)

# %% [markdown]
# Look at that! We've successfully filtered down the rows we need to be concerned about significantly, _and we haven't even read any data yet_.
#
# Can we keep using metadata to filter further? Like, does the geometry column have metadata that could be used in a similar manner? Our projected `FileMetadata` instances only retained the bbox column chunks, but we still have the full `ParquetFile` we parsed at the start of the exercise, so let's look at its `geometry` column chunk metadata.

# %%
pprint(pf.metadata.row_groups[0].column_chunks['geometry'])

# %% [markdown]
# Hmm, that's not super helpful looking. It might be time to say we've done as much as we can without reading data, and start fetching rows.

# %% [markdown]
# ## Reading and filtering rows
#
# To read rows we need to get full `ParquetFile` instances for our intersecting files. Once we have a `ParquetFile` instance, we can read its column chunks.
#
# We're going to need a `ParquetFile` instance per intersecting file. Because instantiating them is a time consuming operation, let's instantiate them all in parallel here, building them up into a dictionary keyed on the file URL. Like the earlier `FileMetadata` scan, we pass a `columns=` projection so `por-que` only materializes the physical structure for the handful of columns we will actually read--the bbox columns for filtering, plus `names.primary` and `geometry` for the final lookups--which makes this parse dramatically faster than a full-file scan. Then we can just grab one of them to use for the rest of this section as we prove out our process (making sure it is for the same file as the `FileMetadata` instance we were using above).

# %%
SEARCH_COLS = [*BBOX_COLS, 'names.primary', 'geometry']

pf_tasks = []
async with AsyncExitStack() as stack:
    for url in urls_that_intersect:
        f = await stack.enter_async_context(AsyncHttpFile(url))
        pf_tasks.append(
            asyncio.create_task(
                ParquetFile.from_reader(
                    f,
                    url,
                    columns=SEARCH_COLS,
                    progress=parquet_progress(),
                ),
            ),
        )
    pfs = dict(zip(urls_that_intersect, await asyncio.gather(*pf_tasks)))

pf = pfs[urls_that_intersect[0]]

# %% [markdown]
# With a `ParquetFile` instance, we can find all four of the `bbox` column chunks in one of our intersected row groups. We do this by iterating through all column chunks in the file, keeping those that are part of our intersected row group index (given by that row group's `ordinal` property) that have a schema path starting with `bbox`. The column chunks we collect here we'll put into a dictionary, keyed on the column chunk path in the schema (e.g., `bbox.min`).

# %%
bbox_chunks = {
    cc.path_in_schema: cc
    for cc in pf.column_chunks
    if cc.row_group == intersecting_rgs[0].ordinal
    and cc.path_in_schema.startswith('bbox')
}
bbox_chunks.keys()

# %% [markdown]
# Now that we have identified the relevant column chunks and inspected what they are, let's take a closer look at one to see other metadata it has.

# %%
pprint(bbox_chunks['bbox.xmin'])


# %% [markdown]
# We see from the above that the name of the type for our column chunk instances is `PhysicalColumnChunk`. That's because these column chunks are not the column chunk metadata in the file metadata, but are instead representative of all the physical byte ranges in the file that make up this "column chunk" abstraction within the file. This includes the column chunk metadata from the file metadata, any indices in the file metadata (column index or offset index), any dictionary page, or, most prominently, the data pages that store the data for the column chunk.
#
# As a result, this `PhysicalColumnChunk` type has a method `parse_all_data_pages()`, which we can use to read all data pages in the column chunk and parse the data values from them. A dictionary page, if present, will also be read so the data pages can be correctly decompressed.
#
# Let's use `parse_all_data_pages()` with each of our bbox chunks to get all the bbox values for our target row group. We have to have a readable filelike object to pass in because we need to read file data, so we'll use the `AsyncHttpFile` class again and pass in an open instance of that class. The data values we read we'll zip together into a four-tuple like `(xmin, ymin, xmax, ymax)`; this tuple provides us a data structure we can use to instantiate `BBox` instances for each row in a later step.

# %%
async with AsyncHttpFile(urls_that_intersect[0]) as hf:
    bbox_tuples = [
        bbox_tuple
        async for bbox_tuple in azip(
            bbox_chunks['bbox.xmin'].parse_all_data_pages(hf),
            bbox_chunks['bbox.ymin'].parse_all_data_pages(hf),
            bbox_chunks['bbox.xmax'].parse_all_data_pages(hf),
            bbox_chunks['bbox.ymax'].parse_all_data_pages(hf),
        )
    ]


# %% [markdown]
# Let's take a look at what the first four rows look like.

# %%
bbox_tuples[:4]

# %% [markdown]
# This result, it might be unexpected. Each data value we see is a three-tuple like `(float, int, int)`. The float values, if not obviously, are our actual data values. The integer values are the definition and repetition levels for each value.
#
# Exactly what the definition and repetition levels are and how they work is outside the scope of this exercise; the short version is they are used in reconstructing nested types like maps, arrays, and structs, by providing the necessary state to determine when and where within a data tree to end/start a data structure or insert nulls. To learn more about how this works, review the three-part blog post series on the Apache Arrow blog ([part 1](https://arrow.apache.org/blog/2022/10/05/arrow-parquet-encoding-part-1/), [part 2](https://arrow.apache.org/blog/2022/10/08/arrow-parquet-encoding-part-2/), and [part 3](https://arrow.apache.org/blog/2022/10/17/arrow-parquet-encoding-part-3/)) or dig into the `por_que.structuring` code.
#
# For now, just note that for our purposes we only need the first element of these tuples, which we can get using something like the generator expression `(i[0] for i in bbox_tuple)`. Let's use that when iterating through each of our bbox tuples, constructing a `BBox` instance from each tuple's extracted values and checking the intersection with our geometry's `BBox` instance. We'll print out the index of each row that intersects, if any.

# %%
for row_index, bbox_tuple in enumerate(bbox_tuples):
    if BBox(*(i[0] for i in bbox_tuple)).intersects(geom_bbox):
        print(row_index)


# %% [markdown]
# Now we have all the steps we need to identify rows that intersect our search bounding box. Let's put all these steps together so we can iterate through all the intersecting URLs and find any and all rows with intersecting bounding boxes!

# %% [markdown]
# ## Putting this all together
#
# Let's make a function that, given a `ParquetFile` instance, will search for intersecting row group bounding boxes, then search those row groups for rows with intersecting bounding boxes.


# %%
async def find_intersecting_rows(pf: ParquetFile) -> dict[int, list[int]]:
    matched_rows = {}
    async with AsyncHttpFile(pf.source) as hf:
        for rg in pf.metadata.row_groups:
            if not get_rg_bbox(rg).intersects(geom_bbox):
                continue

            bbox_chunks = {
                cc.path_in_schema: cc
                for cc in pf.column_chunks
                if cc.row_group == rg.ordinal and cc.path_in_schema.startswith('bbox')
            }

            bbox_tuples = [
                bbox_tuple
                async for bbox_tuple in azip(
                    bbox_chunks['bbox.xmin'].parse_all_data_pages(hf),
                    bbox_chunks['bbox.ymin'].parse_all_data_pages(hf),
                    bbox_chunks['bbox.xmax'].parse_all_data_pages(hf),
                    bbox_chunks['bbox.ymax'].parse_all_data_pages(hf),
                )
            ]

            for row_index, bbox_tuple in enumerate(bbox_tuples):
                if BBox(*(i[0] for i in bbox_tuple)).intersects(geom_bbox):
                    try:
                        matched_rows[rg.ordinal].append(row_index)
                    except KeyError:
                        matched_rows[rg.ordinal] = [row_index]

    return matched_rows


# %% [markdown]
# Now let's use our `find_intersecting_rows` function on each of our intersecting `ParquetFile` instances. We'll track the outputs in a nested dictionary structure mapping file URL to row group index to intersected row indices.

# %%
matched_rows: dict[str, dict[int, list[int]]] = dict(
    zip(
        urls_that_intersect,
        await asyncio.gather(
            *[asyncio.create_task(find_intersecting_rows(pf)) for pf in pfs.values()]
        ),
    )
)
matched_rows

# %% [markdown]
# As only one row group in one file had intersections, let's extract the key bits of information here out into discrete variables, to keep the following code simpler. Specifically, we'll define vars for the file URL, the row group index, and the intersected row indices.

# %%
file_url, row_group_index, row_indices = next(
    (url, k, v) for url, d in matched_rows.items() if d for k, v in d.items()
)
file_url, row_group_index, row_indices

# %% [markdown]
# ## Reading data for the intersecting rows
#
# ### A simple string column
#
# We can use the row group index and row indices to read other column chunks that contain other data for the rows. Let's take a look at how that works with the `names.primary` column, to see if that provides any insight into the intersected rows.
#
# To do this, we need to first find the column chunk for this `names.primary` column that is within our target row group. We can iterate through the target `ParquetFile`'s column chunks until we find the one that matches.

# %%
for cc in pfs[file_url].column_chunks:
    if cc.row_group == row_group_index and cc.path_in_schema == 'names.primary':
        primary_name_chunk = cc
        break

pprint(primary_name_chunk)


# %% [markdown]
# With the column chunk identified, we can parse all its data pages to get all its rows.

# %%
async with AsyncHttpFile(file_url) as hf:
    name_rows = [name async for name in primary_name_chunk.parse_all_data_pages(hf)]


# %% [markdown]
# Now it's simply a matter of grabbing each row with our target row indices.

# %%
for row in row_indices:
    print(name_rows[row])

# %% [markdown]
# Easy yeah?
#
# ### Reading the geometries
#
# We can do this same process again to get access to the target row geometries. So let's do that, starting again by finding the column chunk for the `geometry` column in our target row group.

# %%
for cc in pfs[file_url].column_chunks:
    if cc.row_group == row_group_index and cc.path_in_schema == 'geometry':
        geom_chunk = cc
        break

pprint(geom_chunk)


# %% [markdown]
# Now we can read the rows from the column chunk. This time we'll combine that operation with the row filtering as well, so we just collect our target geometries. Let's also print those out and see what they look like.

# %%
async with AsyncHttpFile(file_url) as hf:
    geom_rows = [
        [geom async for geom in geom_chunk.parse_all_data_pages(hf)][i]
        for i in row_indices
    ]
geom_rows

# %% [markdown]
# That doesn't look too useful, does it?
#
# The type for this column is `BYTE_ARRAY`, and we have no logical type specified in the schema for this column. The addition of parquet `GEOMETRY` and `GEOGRAPHY` logical types is [really fairly recent](https://github.com/apache/parquet-format/pull/240). It appears this file does not use either of those types, but instead relies on the older geoparquet specification that defines the convention of encoding geometries in `BYTE_ARRAY` format with no logical type.
#
# In fact, if we go back to the file metadata and the geospatial key/value metadata, we can see where this encoding was specified:

# %%
json.loads(
    next(
        kv for kv in pfs[file_url].metadata.key_value_metadata if kv.key == 'geo'
    ).value,
)

# %% [markdown]
# The `geometry` column we see here is encoded as WKB! Let's take a second look at the values in hex format and see if WKB seems a reasonable interpretation of these byte values. We have to extract just the value from our `(value, definition, repetition)` tuples though, so we'll do that first.

# %%
geoms = [row[0] for row in geom_rows]
for _geom in geoms:
    print(_geom.hex())

# %% [markdown]
# What do you think? Do these look like they could be WKB values?
#
# We can use the `from_wkb()` function from shapely to parse these values into geometries, if indeed they are valid. That function is imported here as `shapely_from_wkb()`; let's try it out! We'll collect all the resulting shapes in a dictionary keyed on the row index.

# %%
shapely_geoms = {}
for index, _geom in zip(row_indices, geoms):
    shapely_geom = shapely_from_wkb(_geom)
    shapely_geoms[index] = shapely_geom
    display(shapely_geom)

# %% [markdown]
# Hmm, interesting. It may or may not be obvious which of these is our building of interest, but either way let's treat this as a problem to solve robustly. We've done really inexpensive bounding box comparisons up until now to filter down the set of possibilities as cheaply as possible. Now that we have some actual contenders, we should switch to the more expensive comparison of the geometries themselves.
#
# To facilitate this comparison, let's also load our geometry into shapely.

# %%
our_geom = shapely_from_geojson(json.dumps(geom))
display(our_geom)

# %% [markdown]
# With shapely geometries on either side, we can find all geometries that intersect our geometry.

# %%
for _geom in shapely_geoms.values():
    if _geom.intersects(our_geom):
        display(_geom)

# %% [markdown]
# Hmm, well, we've narrowed it down. But still, we need to do better. How can we estimate similarity? Perhaps if we calculate the actual intersection as a geometry, we could measure its area? The larger the intersecting area, the more likely the geometry is our target building? After all, we might expect some overlaps around the edges that could cause intersecting slivers, but we should not have buildings overlapping in the Overture dataset.
#
# So let's try that out and see what happens.

# %%
max_intersection_area = 0
max_intersecting_geom = None
max_intersecting_index = None

for index, _geom in shapely_geoms.items():
    area = intersection(_geom, our_geom).area
    if area > max_intersection_area:
        max_intersection_area = area
        max_intersecting_geom = _geom
        max_intersecting_index = index

display(max_intersecting_geom)
print(
    f'The row that most intersects our geometry is {max_intersecting_index} of row group {row_group_index} in {file_url}'
)

# %% [markdown]
# Look at that! We've narrowed it down to a single row. Does this look like it is the right row?
#
# ## Questions
#
# * How effective was parquet's support for predicate pushdown in our search? Can the access efficiency be quantified for this particular scenario?
# * Using what you learned through this exercise, can you classify what types of problems parquet supports well?
# * What about what parquet would be bad at? What are the trade-offs of parquet? What might be done to mitigate its trade-offs? What cannot be mitigated?
# * Is parquet a true cloud-native format? Some argue that it is not. Can you make a case for why it is? What about why it might not be?
# * What would it take to write a generic client for this access pattern? What about others? What would it take to make a truly general purpose query engine for parquet?
