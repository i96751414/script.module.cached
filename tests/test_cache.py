import datetime
import os
import shutil
import sys
import time
from unittest import TestCase

try:
    from unittest.mock import Mock
except ImportError:
    from mock import Mock

DATA_FOLDER = "test_data"
DATABASE_NAME = "test_database"


def kodi_mocks():
    # noinspection PyPep8Naming
    class WindowMock(object):
        def __init__(self):
            self._cache = {}

        def getProperty(self, key):
            return self._cache.get(key, "")

        def setProperty(self, key, value):
            self._cache[key] = value

    xbmc = Mock()
    xbmc.translatePath.return_value = DATA_FOLDER
    xbmcaddon = Mock()
    xbmcaddon.Addon().getAddonInfo.return_value = DATABASE_NAME
    xbmcgui = Mock()
    xbmcgui.Window.return_value = WindowMock()
    return {"xbmc": xbmc, "xbmcaddon": xbmcaddon, "xbmcgui": xbmcgui}


sys.modules.update(kodi_mocks())
from lib.cached import Cache, MemoryCache, _BaseCache  # noqa


def with_values(*values):
    def decorator(func):
        def wrapper(self):
            for value in values:
                func(self, value)

        return wrapper

    return decorator


class CacheTestCase(TestCase):
    @classmethod
    def tearDownClass(cls):
        if os.path.exists(DATA_FOLDER):
            shutil.rmtree(DATA_FOLDER)

    def test_singleton(self):
        for clazz in (MemoryCache, Cache, _BaseCache):
            self.assertIs(clazz.get_instance(), clazz.get_instance())
            self.assertIsNot(clazz.get_instance(), clazz())
        self.assertIsNot(Cache.get_instance(), _BaseCache.get_instance())
        self.assertIsNot(Cache.get_instance(), MemoryCache.get_instance())
        self.assertIsNot(_BaseCache.get_instance(), MemoryCache.get_instance())

    @with_values(Cache, MemoryCache)
    def test_expiry_time(self, clazz):
        cache = clazz(os.path.join(DATA_FOLDER, "test_expiry_time.sqlite"))
        key, value = "key", "value"
        cache.set(key, value, datetime.timedelta(milliseconds=500))
        start = time.time()
        self.assertEqual(value, cache.get(key))
        self.wait(0.4, start)
        self.assertEqual(value, cache.get(key))
        self.wait(0.5, start)
        self.assertEqual(None, cache.get(key))

    def test_clean_up(self):
        key, value = "key", "value"
        cache = Cache(os.path.join(DATA_FOLDER, "test_clean_up.sqlite"),
                      cleanup_interval=datetime.timedelta(milliseconds=500))
        start = time.time()
        cache.set(key, value, datetime.timedelta(milliseconds=100))
        self.assertFalse(cache.check_clean_up())
        self.assertEqual(1, self.count(cache, key))
        self.wait(0.4, start)
        self.assertFalse(cache.check_clean_up())
        self.assertEqual(1, self.count(cache, key))
        self.wait(0.5, start)
        self.assertTrue(cache.check_clean_up())
        self.assertEqual(0, self.count(cache, key))

    @with_values(Cache, MemoryCache)
    def test_cache(self, clazz):
        data = (1, "1", 1.1, True, None, {1}, frozenset([1]), [1], (1,), {1: 2, "1": "2"}, datetime.datetime.now())
        expiry = datetime.timedelta(minutes=15)
        cache = clazz(os.path.join(DATA_FOLDER, "test_cache.sqlite"))
        for key in data:
            for value in data:
                cache.set(key, value, expiry)
                self.assertEqual(value, cache.get(key))

    @staticmethod
    def count(cache, key):
        cache._cursor.execute(
            "SELECT COUNT(*) FROM `{}` WHERE key = ?".format(cache._table_name), (cache._hash_func(key),))
        return cache._cursor.fetchone()[0]

    @staticmethod
    def wait(delay, start_time=None):
        if start_time is None:
            start_time = time.time()
        while time.time() - start_time < delay:
            pass
