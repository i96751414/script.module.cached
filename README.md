# script.module.cached

[![Build Status](https://github.com/i96751414/script.module.cached/workflows/build/badge.svg)](https://github.com/i96751414/script.module.cached/actions?query=workflow%3Abuild)
[![Codacy Badge](https://app.codacy.com/project/badge/Grade/ec7ad5f1d3b3432d9df2541aec27801a)](https://www.codacy.com/gh/i96751414/script.module.cached/dashboard?utm_source=github.com&amp;utm_medium=referral&amp;utm_content=i96751414/script.module.cached&amp;utm_campaign=Badge_Grade)

A simple cache module for Kodi. It allows both file/memory caching. By default, it
uses [pickle](https://docs.python.org/3/library/pickle.html) to serialize/deserialize objects and sha256 to generate the
cache keys, however all of this can be modified. For instance, one could use json to serialize/deserialize an object and
provide a custom hashing function or even a plain key.

## Installation

This addon is made available on its [repository](https://github.com/i96751414/repository.github#installation).

Although **not recommended**, one can install the addon without installing its repository. To do so, get the
[latest release](https://github.com/i96751414/script.module.cached/releases/latest) from github.

## API

### Classes

-   **MemoryCache** - In memory cache.
-   **Cache** - File cache (using sqlite3).
-   **LoadingCache** - Loading cache which may use either `MemoryCache` or `Cache` as caching engine.

### Methods

#### MemoryCache / Cache

-   **set**(*key, data, expiry_time, hashed_key=False, identifier=""*)

    Cache `data` using `key` as the entry key and `expiry_time` as the expiry time. If `hashed_key` is true. the key is
    assumed to be hashed already. `identifier` is useful in cases where there may exist different cache entries with the
    same key.

-   **get**(*key, default=None, hashed_key=False, identifier=""*)

    Get the cached entry data. In case the entry does not exist/is expired, `default` is returned.

#### LoadingCache

-   **get**(*key*)

    Get the cached entry data. If the entry does not exist or is expired, a new one will be loaded onto cache.

## Usage

Import the addon in `addon.xml`:

```xml

<requires>
    <import addon="script.module.cached" version="0.0.1"/>
</requires>
```

### Using cached as decorator

```python
from datetime import timedelta

from cached import cached, memory_cached


@cached(timedelta(minutes=15))
def foo(*args, **kwargs):
    pass


class Bar:
    @memory_cached(timedelta(minutes=10), instance_method=True)
    def method(self, *args, **kwargs):
        pass
```

### Using cache instance

```python
from datetime import timedelta

from cached import Cache

cache = Cache.get_instance()
cache.set("foo", "bar", timedelta(minutes=15))
value = cache.get("foo")
```

Here cache is a singleton and it's instance can be obtained by calling `get_instance` method. One could also
set `hashed_key` keyword argument on both `set` and `get` functions indicating wether the key is already hashed or not
(False by default). `get` method also supports the `default` argument which refers to the value to be returned in case
the value is not cached (None by default).

### Use custom serializer/deserializer

```python
import json
from hashlib import sha256
from sqlite3 import Binary

from cached import Cache


class JsonCache(Cache):
    @staticmethod
    def _load_func(obj):
        if isinstance(obj, Binary):
            obj = str(obj)
        return json.loads(obj)

    @staticmethod
    def _dump_func(obj):
        return json.dumps(obj).encode()

    def _hash_func(self, obj):
        data = self._dump_func(obj)
        h = sha256()
        h.update(data)
        return h.hexdigest()
```

The above example shows how to use json as serializer/deserializer. Whenever one needs to use a custom
serializer/deserializer, it should be only needed to override the three functions above:
`_load_func`, `_dump_func` and `_hash_func`. The same would apply for `MemoryCache`.

### Use a LoadingCache

```python
from datetime import timedelta

from cached import LoadingCache, Cache

cache = LoadingCache(timedelta(minutes=15), lambda k: k ** 2, Cache)
cache.get(3)
```

The above example makes use of a Loading Cache. In this particular case, calling `cache.get(3)` would return `9` and
store the value in cache for future calls.