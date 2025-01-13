import os
import pickle
import sqlite3
import sys
from base64 import b64encode, b64decode
from datetime import datetime, timedelta, tzinfo
from functools import wraps
from hashlib import sha256

import xbmcaddon
import xbmcgui

PY3 = sys.version_info.major >= 3
if PY3:
    from xbmcvfs import translatePath
else:
    from xbmc import translatePath

ADDON_DATA = translatePath(xbmcaddon.Addon("script.module.cached").getAddonInfo("profile"))
ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo("id")
ADDON_VERSION = ADDON.getAddonInfo("version")

if not PY3:
    ADDON_DATA = ADDON_DATA.decode("utf-8")
if not os.path.exists(ADDON_DATA):
    os.makedirs(ADDON_DATA)

# Sqlite pragmas, according to https://www.sqlite.org/pragma.html
SQLITE_SETTINGS = {
    "journal_mode": "wal",
    "auto_vacuum": "full",
    "cache_size": 8 * 1024,
    "mmap_size": 64 * 1024 * 1024,
    "synchronous": "normal",
}


class _KwdMark(object):
    pass


def make_key(args, kwargs, typed=False, kwd_mark=(_KwdMark,), fast_types=(int, str)):
    key = args
    sorted_kwargs = tuple(sorted(kwargs.items()))
    if sorted_kwargs:
        key += kwd_mark + sorted_kwargs
    if typed:
        key += tuple(type(v) for v in args)
        if sorted_kwargs:
            key += tuple(type(v) for _, v in sorted_kwargs)
    elif len(key) == 1 and type(key[0]) in fast_types:
        return key[0]
    return key


def pickle_hash(obj):
    data = pickle.dumps(obj)
    # We could also use zlib.adler32 here
    h = sha256()
    h.update(data)
    return h.hexdigest()


class UTC(tzinfo):
    _zero = timedelta(0)

    def tzname(self, dt):
        return "UTC"

    def utcoffset(self, dt):
        return self._zero

    def dst(self, dt):
        return self._zero


class _BaseCache(object):
    __instance = None

    _timezone = UTC()

    @classmethod
    def get_instance(cls):
        if cls.__instance is None:
            cls.__instance = cls()
        return cls.__instance

    def get(self, key, default=None, hashed_key=False, identifier=ADDON_VERSION):
        return self._get(self._generate_key(key, hashed_key=hashed_key, identifier=identifier), default=default)

    def set(self, key, data, ttl, hashed_key=False, identifier=ADDON_VERSION):
        return self._set(self._generate_key(key, hashed_key=hashed_key, identifier=identifier), data, ttl)

    def remove(self, key, hashed_key=False, identifier=ADDON_VERSION):
        return self._remove(self._generate_key(key, hashed_key=hashed_key, identifier=identifier))

    def close(self):
        pass

    def _generate_key(self, key, hashed_key=False, identifier=""):
        if not hashed_key:
            key = self._hash(key)
        if identifier:
            key = identifier + "." + key
        return key

    def _now(self):
        return datetime.now(self._timezone)

    @staticmethod
    def _loads(data):
        return pickle.loads(data)

    @staticmethod
    def _dumps(data):
        return pickle.dumps(data)

    @staticmethod
    def _hash(data):
        return pickle_hash(data)

    def _get(self, key, default=None):
        raise NotImplementedError("_get needs to be implemented")

    def _set(self, key, data, ttl):
        raise NotImplementedError("_set needs to be implemented")

    def _remove(self, key):
        raise NotImplementedError("_remove needs to be implemented")


class MemoryCache(_BaseCache):
    def __init__(self, database=ADDON_ID):
        self._window = xbmcgui.Window(10000)
        self._database = database

    def _generate_key(self, key, hashed_key=False, identifier=""):
        return self._database + "." + super(MemoryCache, self)._generate_key(
            key, hashed_key=hashed_key, identifier=identifier)

    def _get(self, key, default=None):
        b64_data = self._window.getProperty(key)
        if b64_data:
            data, expires = self._loads(b64decode(b64_data))
            if expires <= self._now():
                self._remove(key)
                data = default
        else:
            data = default
        return data

    def _set(self, key, data, ttl):
        self._window.setProperty(key, b64encode(self._dumps((data, self._now() + ttl))).decode())

    def _remove(self, key):
        self._window.clearProperty(key)


class Cache(_BaseCache):
    def __init__(self, database=os.path.join(ADDON_DATA, ADDON_ID + ".cached.sqlite"),
                 cleanup_interval=timedelta(minutes=15)):
        self._conn = sqlite3.connect(
            database, detect_types=sqlite3.PARSE_DECLTYPES, isolation_level=None, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS `cached` ("
            "key TEXT PRIMARY KEY NOT NULL, "
            "data BLOB NOT NULL, "
            "expires TEXT NOT NULL"
            ")")
        # self._conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS key_idx ON `{}` (key)'.format(self._table_name))
        for k, v in SQLITE_SETTINGS.items():
            self._conn.execute("PRAGMA {}={}".format(k, v))
        self._cleanup_interval = cleanup_interval
        self._last_cleanup = self._now()
        self.clean_up()

    def _get(self, key, default=None):
        self.check_clean_up()
        row = self._conn.execute(
            "SELECT data FROM `cached` WHERE key = ? AND expires > STRFTIME('%Y-%m-%d %H:%M:%f', 'NOW')",
            (key,)).fetchone()
        return default if row is None else self._loads(row[0])

    def _set(self, key, data, ttl):
        self.check_clean_up()
        self._conn.execute(
            "INSERT OR REPLACE INTO `cached` (key, data, expires) "
            "VALUES(?, ?, STRFTIME('%Y-%m-%d %H:%M:%f', 'NOW', ?))",
            (key, sqlite3.Binary(self._dumps(data)), "+{:.3f} seconds".format(ttl.total_seconds())))

    def _remove(self, key):
        self.check_clean_up()
        self._conn.execute("DELETE FROM `cached` WHERE key = ?", (key,))

    def _set_version(self, version):
        self._conn.execute("PRAGMA user_version={}".format(version))

    @property
    def version(self):
        return self._conn.execute("PRAGMA user_version").fetchone()[0]

    @property
    def needs_cleanup(self):
        return self._last_cleanup + self._cleanup_interval < self._now()

    def clean_up(self):
        self._conn.execute(
            "DELETE FROM `cached` WHERE expires <= STRFTIME('%Y-%m-%d %H:%M:%f', 'NOW')")
        self._last_cleanup = self._now()

    def check_clean_up(self):
        clean_up = self.needs_cleanup
        if clean_up:
            self.clean_up()
        return clean_up

    def clear(self):
        self._conn.execute("DELETE FROM `cached`")
        self._last_cleanup = self._now()

    def close(self):
        self._conn.close()


class LoadingCache(object):
    def __init__(self, ttl, loader, cache_type, *args, **kwargs):
        self._ttl = ttl
        self._loader = loader
        self._identifier = kwargs.pop("identifier", ADDON_VERSION)
        self._cache = cache_type(*args, **kwargs)
        self._sentinel = object()

    def get(self, *args, **kwargs):
        key = make_key(args, kwargs)
        data = self._cache.get(key, default=self._sentinel, identifier=self._identifier)
        if data is self._sentinel:
            data = self._loader(*args, **kwargs)
            self._cache.set(key, data, self._ttl, identifier=self._identifier)
        return data

    def close(self):
        self._cache.close()


def cached(ttl, instance_method=False, identifier=ADDON_VERSION, cache_type=Cache):
    def decorator(func):
        sentinel = object()
        cache = cache_type.get_instance()

        @wraps(func)
        def wrapper(*args, **kwargs):
            if instance_method:
                key_args = args[1:]
                func_name = args[0].__class__.__name__ + "." + func.__name__
            else:
                key_args = args
                func_name = func.__name__

            key = make_key((func_name, *key_args), kwargs)
            result = cache.get(key, default=sentinel, identifier=identifier)
            if result is sentinel:
                result = func(*args, **kwargs)
                cache.set(key, result, ttl, identifier=identifier)

            return result

        return wrapper

    return decorator


# noinspection PyTypeChecker
def memory_cached(ttl, instance_method=False, identifier=ADDON_VERSION):
    return cached(ttl, instance_method=instance_method, identifier=identifier, cache_type=MemoryCache)
