import os
import random
import shutil
import string
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta, datetime
from unittest import TestCase

try:
    from unittest.mock import Mock, MagicMock
except ImportError:
    from mock import Mock, MagicMock

DATA_FOLDER = "test_data"
DATABASE_NAME = "test_database"
VERSION = "1.0.0"


def kodi_mocks():
    # noinspection PyPep8Naming
    class WindowMock(object):
        def __init__(self):
            self.cache = {}
            self.cleared_properties = set()

        def getProperty(self, key):
            return self.cache.get(key, "")

        def setProperty(self, key, value):
            self.cache[key] = value

        def clearProperty(self, key):
            self.cleared_properties.add(key)

    def get_addon_info(attr):
        if attr == "version":
            return VERSION
        elif attr == "id":
            return DATABASE_NAME
        elif attr == "profile":
            return DATA_FOLDER
        else:
            raise ValueError("Unexpected value: {}".format(attr))

    xbmc = Mock()
    xbmc.translatePath = MagicMock(side_effect=lambda v: v)
    xbmcaddon = Mock()
    addon = xbmcaddon.Addon()
    addon.getAddonInfo = MagicMock(side_effect=get_addon_info)
    xbmcgui = Mock()
    xbmcgui.Window.return_value = WindowMock()

    return {"xbmc": xbmc, "xbmcaddon": xbmcaddon, "xbmcgui": xbmcgui, "xbmcvfs": xbmc}


sys.modules.update(kodi_mocks())
from lib.cached import Cache, MemoryCache, _BaseCache, cached, LoadingCache  # noqa


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
        Cache.get_instance().close()
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
        cache.set(key, value, timedelta(milliseconds=500))
        start = time.time()
        self.assertEqual(value, cache.get(key))
        self.wait(0.4, start)
        self.assertEqual(value, cache.get(key))
        self.wait(0.5, start)
        self.assertEqual(None, cache.get(key))

    def test_clean_up(self):
        key, value = "key", "value"
        cache = Cache(os.path.join(DATA_FOLDER, "test_clean_up.sqlite"), cleanup_interval=timedelta(milliseconds=500))
        start = time.time()
        cache.set(key, value, timedelta(milliseconds=100))
        self.assertFalse(cache.check_clean_up())
        self.assertEqual(1, self.count(cache, key))
        self.wait(0.4, start)
        self.assertFalse(cache.check_clean_up())
        self.assertEqual(1, self.count(cache, key))
        self.wait(0.5, start)
        self.assertTrue(cache.check_clean_up())
        self.assertEqual(0, self.count(cache, key))

    def test_clear(self):
        key, value = "key", "value"
        cache = Cache(os.path.join(DATA_FOLDER, "test_clear.sqlite"))
        cache.set(key, value, timedelta(milliseconds=100))
        self.assertEqual(1, self.count(cache, key))
        cache.clear()
        self.assertEqual(0, self.count(cache, key))

    @with_values(Cache, MemoryCache)
    def test_cache(self, clazz):
        data = (1, "1", 1.1, True, None, {1, 3, 2, 4}, frozenset([1, 3, 2, 4]), [1, 3, 2, 4], (1, 3, 2, 4),
                {1: 2, "1": "2", (1, 3, 2, 4): 1 + 1.4j}, 1 + 1.4j, datetime.now())
        expiry = timedelta(minutes=15)
        cache = clazz(os.path.join(DATA_FOLDER, "test_cache.sqlite"))
        for key in data:
            for value in data:
                cache.set(key, value, expiry)
                self.assertEqual(value, cache.get(key))

    def test_cache_version(self):
        cache = Cache(os.path.join(DATA_FOLDER, "test_cache_version.sqlite"))
        cache2 = Cache(os.path.join(DATA_FOLDER, "test_cache_version.sqlite"))
        self.assertEqual(0, cache.version)
        self.assertEqual(0, cache2.version)
        version = 100
        cache._set_version(version)
        self.assertEqual(version, cache.version)
        self.assertEqual(version, cache2.version)

    @with_values(Cache, MemoryCache)
    def test_identifier(self, clazz):
        key = "key"
        expiry = timedelta(minutes=15)
        cache = clazz(os.path.join(DATA_FOLDER, "test_identifier.sqlite"))
        for i in range(5):
            identifier = "id{}".format(i)
            cache.set(key, identifier, expiry, identifier=identifier)
            self.assertEqual(identifier, cache.get(key, identifier=identifier))

    @with_values(Cache, MemoryCache)
    def test_decorator(self, clazz):
        return_value = 123456
        func_duration = 0.1
        args = (object(),)
        kwargs = {"kw": object()}

        @cached(timedelta(seconds=func_duration * 2), cache_type=clazz)
        def func(*_, **__):
            time.sleep(func_duration)
            return return_value

        class Test(object):
            @staticmethod
            @cached(timedelta(seconds=func_duration * 2), cache_type=clazz)
            def static_func(*_, **__):
                time.sleep(func_duration)
                return return_value

            @cached(timedelta(seconds=func_duration * 2), instance_method=True, cache_type=clazz)
            def func(self, *_, **__):
                time.sleep(func_duration)
                return return_value

        for i, f in enumerate((func, Test().static_func, Test().func)):
            start_time = time.time()
            self.assertEqual(return_value, f(i, *args, **kwargs))
            self.assertTrue(time.time() - start_time >= func_duration)
            start_time = time.time()
            self.assertEqual(return_value, f(i, *args, **kwargs))
            self.assertTrue(time.time() - start_time < func_duration)

    def test_threaded_cache(self):
        cleanup_interval = timedelta(milliseconds=200)
        expiration = timedelta(seconds=2)
        cache = Cache(os.path.join(DATA_FOLDER, "test_threaded_cache.sqlite"), cleanup_interval=cleanup_interval)

        def target(key, value):
            cache.set(key, value, expiration)
            self.assertEqual(value, cache.get(key))

        with ThreadPoolExecutor(20) as pool:
            futures = [pool.submit(target, self.random_string(20), self.random_string(500)) for _ in range(1000)]
            for result in futures:
                result.result()

    @with_values(Cache, MemoryCache)
    def test_loading_cache(self, clazz):
        key, value = "key", "value"
        func_duration = 0.1

        def loader(k):
            self.assertEqual(key, k)
            time.sleep(func_duration)
            return value

        cache = LoadingCache(timedelta(minutes=15), loader, clazz,
                             os.path.join(DATA_FOLDER, "test_loading_cache.sqlite"))

        start_time = time.time()
        self.assertEqual(value, cache.get(key))
        self.assertTrue(time.time() - start_time >= func_duration)
        start_time = time.time()
        self.assertEqual(value, cache.get(key))
        self.assertTrue(time.time() - start_time < func_duration)

    @staticmethod
    def random_string(length):
        return "".join(random.choice(string.printable) for _ in range(length))

    @staticmethod
    def count(cache, key):
        return cache._conn.execute(
            "SELECT COUNT(*) FROM `cached` WHERE key = ?",
            (cache._generate_key(key, identifier=VERSION),)).fetchone()[0]

    @staticmethod
    def wait(delay, start_time=None):
        if start_time is None:
            start_time = time.time()
        while time.time() - start_time < delay:
            pass
