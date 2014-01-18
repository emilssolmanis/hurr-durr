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
from os import makedirs
from tornado import httpclient
from tornado import ioloop

logger = logging.getLogger(__name__)


# new_post_cb, thread_pruned_cb, img_cb
class FileHandler(object):
    def __init__(self, file_root):
        self.file_root = file_root

    def post(self):
        pass

    def pruned(self):
        pass

    def img(self):
        pass


class ThreadWatcher(object):
    def __init__(self, file_root, board, loop, thread_id, pull_images):
        self.file_root = '%s/%s' % (file_root, thread_id)
        try:
            makedirs(self.file_root)
        except OSError as e:
            if e.errno != errno.EEXIST:
                raise e
        self.loop = loop
        self.pull_images = pull_images
        self.client = httpclient.AsyncHTTPClient()
        self.working = True
        self.thread_id = thread_id
        self.url = 'http://a.4cdn.org/%s/res/%d.json' % (board, thread_id)
        self.downloaded_pictures = set()
        self.last_modified = datetime.now()
        self.pic_url = 'http://i.4cdn.org/%s/src/%%s' % board
        self.previous_thread = {'posts': []}

    def make_image_handler(self, local_filename, filename, checksum):
        def write_image(response):
            logger.info('Got image response, code: %s', response.code)
            if response.code == 200:
                data = response.body
                m = md5()
                m.update(data)
                if m.hexdigest() == checksum:
                    with open(local_filename, 'w') as f:
                        f.write(data)
                    self.downloaded_pictures.add(filename)
                else:
                    logger.info('Digests don\'t match for image %s', filename)

        return write_image

    def parse_thread(self, thread):
        if self.pull_images:
            for p in thread['posts']:
                if 'tim' in p:
                    filename = str(p['tim']) + p['ext']
                    if filename not in self.downloaded_pictures:
                        logger.info('Pulling image %s', filename)
                        checksum = hexlify(b64decode(p['md5']))
                        remote_name = self.pic_url % filename
                        local_filename = '%s/%s' % (self.file_root, filename)
                        if not exists(local_filename):
                            self.client.fetch(remote_name, self.make_image_handler(local_filename, filename, checksum))

    def handle(self, response):
        if response.code == 200:
            last_mod_str = response.headers['Last-Modified']
            last_mod = datetime(*parse_last_modified(last_mod_str)[:6])
            self.last_modified = last_mod

            try:
                thread = loads(response.body)
                self.parse_thread(thread)
                curr_len = len(thread['posts'])
                prev_len = len(self.previous_thread['posts'])
                logger.info('Thread %d has %d posts, had %d => %d new', self.thread_id, curr_len, prev_len,
                            curr_len - prev_len)
                self.previous_thread = thread
            except ValueError:
                logger.info('ValueError: thread unmodified')
        if not response.code == 404:
            self.loop.add_timeout(timedelta(seconds=60), self.watch)
        else:
            with open('%s/%s.json' % (self.file_root, self.thread_id), 'w') as f:
                f.write(dumps(self.previous_thread))
            self.working = False

    def watch(self):
        self.client.fetch(httpclient.HTTPRequest(self.url, if_modified_since=self.last_modified), self.handle)


class ChanWatcher(object):
    def __init__(self, file_root, board, images):
        try:
            makedirs(file_root)
        except OSError as e:
            if e.errno != errno.EEXIST:
                raise e
        self.file_root = file_root
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
            watcher = ThreadWatcher(self.file_root, self.board, self.loop, t, self.images)
            self.watchers.append(watcher)
            watcher.watch()

        self.loop.add_timeout(timedelta(seconds=60), self.watch_threads)

    def watch_threads(self):
        self.client.fetch(self.thread_list_url, self.handle_threads)

    def start(self):
        self.watch_threads()
        self.loop.start()