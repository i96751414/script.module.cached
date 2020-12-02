import datetime
import os
import pickle
import sqlite3
from base64 import b64encode, b64decode
from functools import wraps
from hashlib import sha256

import xbmc
import xbmcaddon
import xbmcgui

ADDON_DATA = xbmc.translatePath(xbmcaddon.Addon("script.module.cached").getAddonInfo("profile"))
ADDON_NAME = xbmcaddon.Addon().getAddonInfo("name")

if not os.path.exists(ADDON_DATA):
    os.makedirs(ADDON_DATA)


def pickle_hash(obj):
    data = pickle.dumps(obj)
    h = sha256()
    h.update(data)
    return h.hexdigest()


class _BaseCache(object):
    __instance = None

    _load_func = staticmethod(pickle.loads)
    _dump_func = staticmethod(pickle.dumps)
    _hash_func = staticmethod(pickle_hash)

    @classmethod
    def get_instance(cls):
        if cls.__instance is None:
            cls.__instance = cls()
        return cls.__instance

    def get(self, key, default=None, hashed_key=False):
        if not hashed_key:
            key = self._hash_func(key)
        result = self._get(key)
        ret = default
        if result:
            data, expires = result
            if expires > datetime.datetime.utcnow():
                ret = self._process(data)
        return ret

    def set(self, key, data, expiry_time, hashed_key=False):
        if not hashed_key:
            key = self._hash_func(key)
        self._set(key, self._prepare(data), datetime.datetime.utcnow() + expiry_time)

    def _process(self, obj):
        return obj

    def _prepare(self, s):
        return s

    def _get(self, key):
        raise NotImplementedError("_get needs to be implemented")

    def _set(self, key, data, expires):
        raise NotImplementedError("_set needs to be implemented")


class MemoryCache(_BaseCache):
    def __init__(self, database=ADDON_NAME):
        self._window = xbmcgui.Window(10000)
        self._database = database + "."

    def _get(self, key):
        data = self._window.getProperty(self._database + key)
        return self._load_func(b64decode(data)) if data else None

    def _set(self, key, data, expires):
        self._window.setProperty(self._database + key, b64encode(self._dump_func((data, expires))).decode())


class Cache(_BaseCache):
    _table_name = "cached"

    def __init__(self, database=os.path.join(ADDON_DATA, ADDON_NAME + ".cached.sqlite"),
                 cleanup_interval=datetime.timedelta(minutes=15)):
        self._conn = sqlite3.connect(database, detect_types=sqlite3.PARSE_DECLTYPES)
        self._cursor = self._conn.cursor()
        self._cursor.execute(
            "CREATE TABLE IF NOT EXISTS `{}` ("
            "key TEXT UNIQUE NOT NULL, "
            "data BLOB NOT NULL, "
            "expires TIMESTAMP NOT NULL"
            ")".format(self._table_name))
        self._conn.commit()
        self._cleanup_interval = cleanup_interval
        self._last_cleanup = datetime.datetime.utcnow()
        self.clean_up()

    def _get(self, key):
        self.check_clean_up()
        self._cursor.execute("SELECT data, expires FROM `{}` WHERE key = ?".format(self._table_name), (key,))
        return self._cursor.fetchone()

    def _process(self, obj):
        return self._load_func(obj)

    def _prepare(self, s):
        return self._dump_func(s)

    def _set(self, key, data, expires):
        self.check_clean_up()
        self._cursor.execute(
            "INSERT OR REPLACE INTO `{}` (key, data, expires) VALUES(?, ?, ?)".format(self._table_name),
            (key, data, expires))
        self._conn.commit()

    def clean_up(self):
        self._cursor.execute(
            "DELETE FROM `{}` WHERE expires <= STRFTIME('%Y-%m-%d %H:%M:%f', 'NOW')".format(self._table_name))
        self._conn.commit()
        self._last_cleanup = datetime.datetime.utcnow()

    def check_clean_up(self):
        clean_up = self._last_cleanup + self._cleanup_interval < datetime.datetime.utcnow()
        if clean_up:
            self.clean_up()
        return clean_up


def cached(expiry_time, ignore_self=False, cache_type=Cache):
    def decorator(func):
        sentinel = object()
        cache = cache_type.get_instance()

        @wraps(func)
        def wrapper(*args, **kwargs):
            key_args = args[1:] if ignore_self else args
            # noinspection PyProtectedMember
            key = cache._hash_func((key_args, kwargs))
            result = cache.get(key, default=sentinel, hashed_key=True)
            if result is sentinel:
                result = func(*args, **kwargs)
                cache.set(key, result, expiry_time, hashed_key=True)

            return result

        return wrapper

    return decorator


# noinspection PyTypeChecker
def memory_cached(expiry_time, instance_method=False):
    return cached(expiry_time, instance_method, MemoryCache)
