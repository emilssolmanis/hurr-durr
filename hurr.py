from tornado import ioloop, httpclient
from datetime import timedelta
from random import randint, random
from json import loads


def get_new_threads():
    threads = set(randint(0, 666) for _ in range(randint(1, 3)))
    print 'Got threads %s' % threads
    return threads


class ThreadWatcher(object):
    def __init__(self, loop, thread_id):
        self.loop = loop
        self.thread_id = thread_id
        self.watcher = None

    def watch(self):
        print 'Watching %s' % self.thread_id
        if random() < 0.2:
            print 'Stopping %s' % self.thread_id
            self.watcher.stop()

    def start(self):
        watcher = ioloop.PeriodicCallback(self.watch, 1500, self.loop)
        self.watcher = watcher
        self.watcher.start()


class ChanWatcher(object):
    def __init__(self, loop):
        self.loop = loop
        self.client = httpclient.AsyncHTTPClient()

    def handle_threads(self, response):
        for page_obj in loads(response.body):
            page = page_obj['page']
            threads = page_obj['threads']
            for thread_obj in threads:
                thread_nr = thread_obj['no']
                last_modified = thread_obj['last_modified']
        self.loop.add_timeout(timedelta(seconds=10), self.watch_threads)

    def watch_threads(self):
        self.client.fetch('http://a.4cdn.org/b/threads.json', self.handle_threads)

    def start(self):
        self.loop.add_timeout(timedelta(seconds=2), self.watch_threads)
        self.loop.start()


def main():
    watcher = ChanWatcher(ioloop.IOLoop.instance())
    watcher.start()


if __name__ == '__main__':
    main()
