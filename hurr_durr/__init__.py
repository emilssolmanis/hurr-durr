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

__all__ = ['FileHandler', 'ChanWatcher']


class FileHandler(object):
    """ Handler that writes things to the file system.

    Threads are purged to disk when they get pruned from 4chan and held in-memory before they are.

    The directory structure is root/thread_id/[thread_id.json | thread images].
    """
    def __init__(self, file_root):
        """Makes a new FileHandler

        file_root -- the directory to which data will be purged. If it does not exist, it will be created.
        """
        if file_root.endswith(sep):
            file_root = file_root[:len(sep)]

        self.file_root = file_root

        try:
            makedirs(self.file_root)
        except OSError as e:
            if e.errno != errno.EEXIST:
                raise e
        self.active_threads = dict()

    def post(self, thread_id, new_post):
        """Handle a new post.

        thread_id -- the thread's ID
        new_post -- the new post dict that has just arrived. Check 4chan API (https://github.com/4chan/4chan-API)
            for full possible contents, but most notable keys are
            no : post number
            resto : number of post that this post is a response to
            time : a UNIX timestamp of post's time
            com : the text, contains escaped HTML
        """
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
        """Handles thread pruning, writes content to JSON on disk.

        thread_id -- the thread ID that was pruned from 4chan
        """
        # this is necessary for the edge-case when the thread was pruned between seeing it in the main list and fetching
        # it's content json
        if thread_id in self.active_threads:
            with open('%s%s%s%s%s.json' % (self.file_root, sep, thread_id, sep, thread_id), 'w') as f:
                f.write(dumps({'posts': self.active_threads[thread_id]}))
            del self.active_threads[thread_id]

    def img(self, thread_id, filename, data):
        """Handles image downloads, writes content to disk in thread_id directory.

        thread_id -- ID of thread in which image was posted
        filename -- the image's filename with extensions
        data -- bytes, image content
        """
        with open('%s%s%s%s%s' % (self.file_root, sep, thread_id, sep, filename), 'w') as f:
            f.write(data)

    def download_img(self, thread_id, filename):
        """Checks whether the image already exists.

        Needed to avoid downloading the same image multiple times. Prime use-case is resumed operation.

        thread_id -- the thread ID for thread containing the image
        filename -- the image's file name
        """
        return exists('%s%s%s%s%s' % (self.file_root, sep, thread_id, sep, filename))


class ThreadWatcher(object):
    """Watcher implementation for single thread.

    Polls the API for updates and calls the handler with new content. Stops polling when a 404 status code is returned
    from the API for this thread.
    """
    def __init__(self, handler, board, loop, thread_id, pull_images, sampling_interval=60):
        """Constructs a new ThreadWatcher.

        handler -- a handler instance, see ChanWatcher's doc for requirements
        board -- the board to watch, e.g., 'b'
        loop -- a tornado IOLoop instance
        thread_id -- the thread ID to watch
        pull_images -- boolean, whether to download images encountered in thread
        sampling_interval -- seconds between each poll. Defaults to 60. Shorter intervals result in more precise
            samples, but consume bandwidth and m00t has 4chan running on fumes as is. Do not abuse.
        """
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

    def _parse_thread(self, thread):
        posts = thread['posts']
        for p in filter(lambda post: post['no'] not in self.posts_handled, posts):
            self.handler.post(self.thread_id, p)
            self.posts_handled.add(p['no'])
            if self.pull_images and 'tim' in p:
                filename = '%s%s' % (p['tim'], p['ext'])
                if filename not in self.downloaded_pictures:
                    checksum = hexlify(b64decode(p['md5']))
                    remote_name = self.pic_url % filename
                    if not self.handler.download_img(self.thread_id, filename):
                        logger.info('Pulling image %s', filename)
                        self.client.fetch(remote_name, self._make_image_handler(filename, checksum))

    def _handle(self, response):
        if response.code == 200:
            last_mod_str = response.headers['Last-Modified']
            last_mod = datetime(*parse_last_modified(last_mod_str)[:6])
            self.last_modified = last_mod

            try:
                thread = loads(response.body)
                curr_len = len(thread['posts'])
                prev_len = len(self.posts_handled)
                self._parse_thread(thread)
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
        """Starts watching the thread this watcher is bound to."""
        self.client.fetch(httpclient.HTTPRequest(self.url, if_modified_since=self.last_modified), self._handle)


class ChanWatcher(object):
    """Watcher implementation for a 4chan board.

    Polls the board for threads and spawns ThreadWatcher's for each new thread detected.
    """
    def __init__(self, handler, board, images=False, sampling_interval=60):
        """Constructs a new watcher.

        handler -- a handler instance. Handler classes need to implement
                post(thread_id, new_post) - called for new posts
                pruned(thread_id) - called when a thread gets pruned
                img(thread_id, filename, data) - called when an image is downloaded
                bool download_img(thread_id, filename) - called to check whether a particular image should be fetched
            Check the FileHandler class for more info.
        board -- the name of the board to watch, e.g., 'b'
        images -- whether to fetch images. If False, the handler can avoid implementing img() and download_img()
        sampling_interval -- seconds between each poll. Defaults to 60. Shorter intervals result in more precise
            samples, but consume bandwidth and m00t has 4chan running on fumes as is. Do not abuse.
        """
        self.handler = handler
        self.sampling_interval = sampling_interval
        self.images = images
        self.board = board
        self.thread_list_url = 'http://a.4cdn.org/%s/threads.json' % self.board
        self.loop = ioloop.IOLoop.instance()
        self.client = httpclient.AsyncHTTPClient()
        self.previous_threads = set()
        self.watchers = []

    def _handle_threads(self, response):
        self.watchers = filter(attrgetter('working'), self.watchers)

        if response.code == 200:
            try:
                pages = loads(response.body)
                curr_threads = set()
                for page_obj in pages:
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
            except ValueError:
                logger.info('Failed to parse thread list JSON response')

        self.loop.add_timeout(timedelta(seconds=self.sampling_interval), self._watch_threads)

    def _watch_threads(self):
        self.client.fetch(self.thread_list_url, self._handle_threads)

    def start(self):
        """Starts watching the board this watcher is bound to."""
        self._watch_threads()
        self.loop.start()