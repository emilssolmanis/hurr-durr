from base64 import b64decode
from binascii import hexlify
from datetime import datetime, timedelta
from email.utils import parsedate as parse_last_modified
import errno
from json import loads, dumps
from operator import attrgetter
from hashlib import md5
import logging

from genericpath import exists
from os import makedirs, sep
from tornado import httpclient
from tornado import ioloop


logger = logging.getLogger(__name__)


# new_post_cb, thread_pruned_cb, img_cb
class FileHandler(object):
    def __init__(self, file_root):
        self.file_root = file_root
        try:
            makedirs(self.file_root)
        except OSError as e:
            if e.errno != errno.EEXIST:
                raise e
        self.active_threads = dict()

    def post(self, thread_id, new_post):
        if thread_id not in self.active_threads:
            thread_file_root = '%s%s%s' % (self.file_root, sep, thread_id)
            try:
                makedirs(thread_file_root)
            except OSError as e:
                if e.errno != errno.EEXIST:
                    raise e
            self.active_threads[thread_id] = []
        self.active_threads[thread_id].append(new_post)

    def pruned(self, thread_id):
        # this is necessary for the edge-case when the thread was pruned between seeing it in the main list and fetching
        # it's content json
        if thread_id in self.active_threads:
            with open('%s%s%s%s%s.json' % (self.file_root, sep, thread_id, sep, thread_id), 'w') as f:
                f.write(dumps({'posts': self.active_threads[thread_id]}))
            del self.active_threads[thread_id]

    def img(self, thread_id, filename, data):
        with open('%s%s%s%s%s' % (self.file_root, sep, thread_id, sep, filename), 'w') as f:
            f.write(data)

    def img_exists(self, thread_id, filename):
        return exists('%s%s%s%s%s' % (self.file_root, sep, thread_id, sep, filename))


class ThreadWatcher(object):
    def __init__(self, handler, board, loop, thread_id, pull_images, sampling_interval=60):
        self.loop = loop
        self.handler = handler
        self.sampling_interval = sampling_interval
        self.pull_images = pull_images
        self.client = httpclient.AsyncHTTPClient()
        self.working = True
        self.thread_id = thread_id
        self.url = 'http://a.4cdn.org/%s/res/%d.json' % (board, thread_id)
        self.downloaded_pictures = set()
        self.last_modified = datetime.now()
        self.pic_url = 'http://i.4cdn.org/%s/src/%%s' % board
        self.posts_handled = set()

    def _make_image_handler(self, filename, checksum):
        def check_image(response):
            logger.info('Got image response for %s, code: %s', filename, response.code)
            if response.code == 200:
                data = response.body
                m = md5()
                m.update(data)
                if m.hexdigest() == checksum:
                    self.handler.img(self.thread_id, filename, data)
                else:
                    logger.info('Digests don\'t match for image %s', filename)

        return check_image

    def parse_thread(self, thread):
        posts = thread['posts']
        for p in posts:
            self.handler.post(self.thread_id, p)
            if self.pull_images and 'tim' in p:
                filename = '%s%s' % (p['tim'], p['ext'])
                if filename not in self.downloaded_pictures:
                    logger.info('Pulling image %s', filename)
                    checksum = hexlify(b64decode(p['md5']))
                    remote_name = self.pic_url % filename
                    if not self.handler.img_exists(self.thread_id, filename):
                        self.client.fetch(remote_name, self._make_image_handler(filename, checksum))

    def handle(self, response):
        if response.code == 200:
            last_mod_str = response.headers['Last-Modified']
            last_mod = datetime(*parse_last_modified(last_mod_str)[:6])
            self.last_modified = last_mod

            try:
                thread = loads(response.body)
                self.parse_thread(thread)
                curr_len = len(thread['posts'])
                prev_len = len(self.posts_handled)
                logger.info('Thread %d has %d posts, had %d => %d new', self.thread_id, curr_len, prev_len,
                            curr_len - prev_len)
            except ValueError:
                logger.info('ValueError: thread unmodified')
        if not response.code == 404:
            self.loop.add_timeout(timedelta(seconds=self.sampling_interval), self.watch)
        else:
            self.handler.pruned(self.thread_id)
            self.working = False

    def watch(self):
        self.client.fetch(httpclient.HTTPRequest(self.url, if_modified_since=self.last_modified), self.handle)


class ChanWatcher(object):
    def __init__(self, handler, board, images=False, sampling_interval=60):
        self.handler = handler
        self.sampling_interval = sampling_interval
        self.images = images
        self.board = board
        self.thread_list_url = 'http://a.4cdn.org/%s/threads.json' % self.board
        self.loop = ioloop.IOLoop.instance()
        self.client = httpclient.AsyncHTTPClient()
        self.previous_threads = set()
        self.watchers = []

    def handle_threads(self, response):
        self.watchers = filter(attrgetter('working'), self.watchers)

        curr_threads = set()
        for page_obj in loads(response.body):
            # page_nr = page_obj['page']
            threads = page_obj['threads']
            for thread_obj in threads:
                thread_nr = thread_obj['no']
                curr_threads.add(thread_nr)
                # last_modified = thread_obj['last_modified']

        new_threads = curr_threads - self.previous_threads
        self.previous_threads = curr_threads
        for t in new_threads:
            watcher = ThreadWatcher(self.handler, self.board, self.loop, t, self.images)
            self.watchers.append(watcher)
            watcher.watch()

        self.loop.add_timeout(timedelta(seconds=self.sampling_interval), self.watch_threads)

    def watch_threads(self):
        self.client.fetch(self.thread_list_url, self.handle_threads)

    def start(self):
        self.watch_threads()
        self.loop.start()