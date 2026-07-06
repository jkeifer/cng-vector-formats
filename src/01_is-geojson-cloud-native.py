# %% [markdown]
# # Is GeoJSON cloud-native?
#
# In this exercise, we'll explore GeoJSON format. We'll see exactly what does or does not make it cloud native.
#
# ## Understanding GeoJSON
#
# GeoJSON is, perhaps obviously, geospatial types in JSON. GeoJSON formalizes several object models for its various types, and specifies a way of encoding geometries and their properties within those object structures. Specifically, we have two discrete object types in GeoJSON: `Geometry` and `Feature`.
#
# `Geometry` could be considered something of the most primitive type, the one on which `Feature` is built: features _have_ (optionally) a geometry. It's a composition relationship.
#
# `Feature`s compose a `Geometry` (again, optionally, as technically a geometry is not required) with attributes. Every `Feature` can optionally have an `id` attribute, a `bbox` attribute, and any other custom attributes go into a feature's `properties` member.
#
# In addition to these two discrete object types, GeoJSON also has two collection types: `FeatureCollection` and `GeometryCollection`. The former is effectively an object with an array of `Feature`s. The latter is a bit of a weirder one: it too defines an object with an array, but of `Geometry` objects. Except a `GeometryCollection` is also a valid `Geometry` type. But don't let that throw you, `GeometryCollections` aren't all that common so we won't worry about them from here on out.
#
# In all of these cases, a `type` attribute is used to specify an object is any one of these types.
#
# ### To summarize all of this
#
# #### GeoJSON types
#
# * `Feature` - has `type` (required), `geometry`, `properties`, `id` and `bbox` (all but `type` are optional)
# * `FeatureCollection` - has `type` (required), `features` (array, required), and `bbox` (optional)
# * `Geometry` - has `type`, `coordinates` (array, required), and `bbox` (optional)
# * `GeometryCollection` - has `type`, `geometries` (array, required), and `bbox` (optional)
#
# #### Key points
#
# * `bbox` is optional on any of these
# * a feature's `geometry` attribute can be null
# * the 7 geometry types: `Point`, `MultiPoint`, `LineString`, `MultiLineString`, `Polygon`, `MultiPolygon`, `GeometryCollection`
#
# ### To learn more
#
# We're not going too deep with GeoJSON. We don't need to do so to answer our question. But, if you want to learn more, GeoJSON is quite widespread and _many_ resources exist online. If I am going to call out any of them though, it would have to be the [GeoJSON RFC7946](https://datatracker.ietf.org/doc/html/rfc7946) (because you should read RFCs, they are great) and anything by Tom MacWright on the topic (in chronological order, recommended to consume in that order):
#
# * [More than you ever wanted to know about GeoJSON](https://macwright.com/2015/03/23/geojson-second-bite)
# * [Falsehoods developers believe about GeoJSON](https://macwright.com/2016/06/05/falsehoods-developers-believe-about-geojson)
# * [Everything you need to know now about RFC 7946 GeoJSON](https://macwright.com/2016/11/07/the-geojson-ietf-standard)
#
# (And [this topically-relevant bonus post that you might as well read while you're perusing his blog](https://macwright.com/2022/05/30/new-formats).)

# %% [markdown]
# ## The exercise
#
# Before we get too far, we're going to need Python's `json` module. Let's import it.

# %%
import json

# %% [markdown]
# ### Building a GeoJSON example
#
# Instead of doing this by hand, let's use an online tool like [geojson.io](https://geojson.io) or [Placemark](https://play.placemark.io/) to create a GeoJSON feature collection with one or two features in it. We can use the interface to browse to some location in the world and draw a polygon. Let's keep the polygon simple just to keep the GeoJSON length reasonable. We can also add attributes to the feature's properties in the interface.
#
# Once we have a feature collection defined, we can copy it and paste it here so we can use it for this exercise.

# %% [markdown]
# ![geojson.io example](assets/geojson_io.png)

# %%
#| scrub-note: cell0 | geojson_str = """PASTE YOUR GEOJSON FEATURE COLLECTION HERE"""
geojson_str = """{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "properties": {
        "buildingId": "WF",
        "school": "Business",
        "floorCount": 10
      },
      "geometry": {
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
      },
      "id": 0
    }
  ]
}"""

# %%
#| scrub-note: cell1
geojson = json.loads(geojson_str)
geojson

# %% [markdown]
# <!-- scrub-omit -->
# ### A few things to notice
#
# This GeoJSON is not large. As a string it is only 910 bytes long. Cloud-native concerns don't even begin to come into play with this example, it's just not big enough for us to have to worry about read inefficiencies.
#
# But notice the length of each point: a point coordinate pair like `[174.76510987799577,-36.853728372411425],` is 41 bytes, and that's removing all whitespace from consideration. Imagine I did a better job tracing the building, we could have 16 points instead of just 6. Or 49 if I had followed the zigzags. Or even more if I tried to follow the apparent radius of the building corner...
#
# Imagine then we extend this feature collection so it contains similar geometries for all buildings in Auckland. Or New Zealand's North Island. Or all of Oceania.
#
# We start to see a potential problem...

# %% [markdown]
# ### Examining GeoJSON's "cloud nativeness"
#
# The core tenet of cloud native data formats is the ability to selectively read what we want out of them using metadata that gives a means of indexing into the data format. Perhaps immediately we can see a problem: what metadata do we have? But before we get there, let's see what we can do with our GeoJSON string.
#
# Notably, a large scale production dataset would be unlikely to contain whitespace (as it just wastes bytes), so let's dump our parsed json to a string and use that "dewhitespaced" version for this portion of the exercise.

# %%
condensed = json.dumps(geojson, separators=(',', ':'))
condensed

# %% [markdown]
# So what can we selectively parse out of this? Can we take just a slice from the beginning or end?

# %%
#| scrub-note: cell2
len(condensed)

# %% tags=["raises-exception"]
#| scrub-note: cell3
json.loads(condensed[:200])

# %% tags=["raises-exception"]
#| scrub-note: cell4
json.loads(condensed[200:])

# %% [markdown]
# JSON is not a streamable format! You can't parse any of it without parsing all of it. At least not naively. Maybe if we try to just parse the `Feature` object?
#
# How do we do that? I guess maybe we could find the first `[` and the last `]` and then use those indices to inform our slice?

# %%
first_bracket_index = condensed.find('[')
last_bracket_index = len(condensed) - 1 - condensed[::-1].find(']')
substring = condensed[first_bracket_index + 1 : last_bracket_index]
substring

# %%
#| scrub-note: cell5
json.loads(substring)

# %% [markdown]
# Woah, cool, that worked! So we _can_ selectively read GeoJSON to extract just what we want, right?
#
# Well, yes, maybe. But look at what we had to do to make this work. We had to use our knowledge of the structure of the GeoJSON feature collection in the original string to know that we in fact did have a feature collection from which we could read a feature. And that we had only one feature to read: using this character finding strategy is only effective with a single feature, and would break down if we added any more. Then we had to have _the whole GeoJSON string_ to be able to find those slice indices to finally be able to say which part of the GeoJSON we really wanted, to just read that part out and parse it.
#
# Phew. That's a lot. And it required all the data to do it.
#
# ### So is GeoJSON cloud-native?
#
# No.
#
# This exercise confirms it. Sure, it is theoretically possible we could build an index into a GeoJSON file, to be able to read it in pieces, feature by feature. We could consider this new theoretical index like kerchunk but for vectors. We'd have to index the various attributes of our features and have a way to search on them to figure out what byte ranges we would need to read to get those features out of the larger GeoJSON feature collection in object storage. This is starting to get complex...
#
# But GeoJSON itself does not provide this. There's no metadata in the file itself that tells us how to do this selective reading. The idea above even points out that if we did have start and end offsets for each feature we'd still not know which of those we'd want to read without some higher level of attribute index layered on top. Again, nothing like that is in GeoJSON.
#
# As a data interchange format, like a request or response format for an HTTP API, it makes perfect sense not to include such indexing in GeoJSON. Of course, as a data interchange format its lack of streamability is a problem, but that's orthogonal to our cloud-native concerns here (not to say that it can't be hackily streamed using things like [geojson-stream](https://github.com/node-geojson/geojson-stream); of course it's also worth mentioning [GeoJSONSeq](https://stevage.github.io/ndgeojson/), a new-line delimited format for streaming features).
