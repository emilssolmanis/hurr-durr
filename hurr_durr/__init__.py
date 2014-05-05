from base64 import b64decode
from binascii import hexlify
from datetime import datetime, timedelta
import time
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
__version__ = '0.1.0'


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

        self._file_root = file_root

        try:
            makedirs(self._file_root)
        except OSError as e:
            if e.errno != errno.EEXIST:
                raise e

        self._active_threads = dict()
        self._thread_roots = dict()

    @staticmethod
    def _get_date_string():
        return time.strftime('%Y%m%d')

    def _get_thread_root(self, thread_id):
        if thread_id not in self._thread_roots:
            return '{file_root}{sep}{date}{sep}{thread_id}'.format(
                file_root=self._file_root,
                thread_id=thread_id,
                date=self._get_date_string(),
                sep=sep
            )
        else:
            return self._thread_roots[thread_id]

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
        if thread_id not in self._active_threads:
            thread_file_root = self._get_thread_root(thread_id)
            try:
                makedirs(thread_file_root)
            except OSError as e:
                if e.errno != errno.EEXIST:
                    raise e
            self._active_threads[thread_id] = []
            self._thread_roots[thread_id] = thread_file_root
        self._active_threads[thread_id].append(new_post)

    def pruned(self, thread_id):
        """Handles thread pruning, writes content to JSON on disk.

        thread_id -- the thread ID that was pruned from 4chan
        """
        # this is necessary for the edge-case when the thread was pruned between seeing it in the main list and fetching
        # it's content json
        if thread_id in self._active_threads:
            filename = '{thread_root}{sep}{thread_id}.json'.format(
                thread_root=self._get_thread_root(thread_id),
                thread_id=thread_id,
                sep=sep
            )
            with open(filename, 'w') as f:
                f.write(dumps({'posts': self._active_threads[thread_id]}))
            del self._active_threads[thread_id]
            del self._thread_roots[thread_id]

    def img(self, thread_id, filename, data):
        """Handles image downloads, writes content to disk in thread_id directory.

        thread_id -- ID of thread in which image was posted
        filename -- the image's filename with extensions
        data -- bytes, image content
        """
        full_filename = '{thread_root}{sep}{img_filename}'.format(
            thread_root=self._get_thread_root(thread_id),
            img_filename=filename,
            sep=sep
        )
        with open(full_filename, 'w') as f:
            f.write(data)

    def download_img(self, thread_id, filename):
        """Checks whether the image already exists.

        Needed to avoid downloading the same image multiple times. Prime use-case is resumed operation.

        thread_id -- the thread ID for thread containing the image
        filename -- the image's file name
        """
        return exists('{file_root}{sep}{thread_id}{sep}{filename}'.format(
            file_root=self._file_root,
            thread_id=thread_id,
            filename=filename,
            sep=sep
        ))


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
        self._loop = loop
        self._handler = handler
        self._sampling_interval = sampling_interval
        self._pull_images = pull_images
        self._client = httpclient.AsyncHTTPClient()
        self._thread_id = thread_id
        self._url = 'http://a.4cdn.org/{board}/thread/{thread_id}.json'.format(board=board, thread_id=thread_id)
        self._downloaded_pictures = set()
        self._last_modified = datetime.now()
        self._pic_url = 'http://i.4cdn.org/{board}/{{pic_filename}}'.format(board=board)
        self._posts_handled = set()

        self.working = True

    def _make_image_handler(self, filename, checksum):
        def check_image(response):
            logger.info('Got image response for %s, code: %s', filename, response.code)
            if response.code == 200:
                data = response.body
                m = md5()
                m.update(data)
                if m.hexdigest() == checksum:
                    self._handler.img(self._thread_id, filename, data)
                else:
                    logger.info('Digests don\'t match for image %s', filename)

        return check_image

    def _parse_thread(self, thread):
        posts = thread['posts']
        for p in filter(lambda post: post['no'] not in self._posts_handled, posts):
            self._handler.post(self._thread_id, p)
            self._posts_handled.add(p['no'])
            if self._pull_images and 'tim' in p:
                filename = '{filename}{extension}'.format(filename=p['tim'], extension=p['ext'])
                if filename not in self._downloaded_pictures:
                    checksum = hexlify(b64decode(p['md5']))
                    remote_name = self._pic_url.format(pic_filename=filename)
                    if not self._handler.download_img(self._thread_id, filename):
                        logger.info('Pulling image %s', filename)
                        self._client.fetch(remote_name, self._make_image_handler(filename, checksum))

    def _handle(self, response):
        if response.code == 200:
            last_mod_str = response.headers['Last-Modified']
            last_mod = datetime(*parse_last_modified(last_mod_str)[:6])
            self._last_modified = last_mod

            try:
                thread = loads(response.body)
                curr_len = len(thread['posts'])
                prev_len = len(self._posts_handled)
                self._parse_thread(thread)
                logger.info('Thread %d has %d posts, had %d => %d new', self._thread_id, curr_len, prev_len,
                            curr_len - prev_len)
            except ValueError:
                logger.info('ValueError: thread unmodified')
        if not response.code == 404:
            self._loop.add_timeout(timedelta(seconds=self._sampling_interval), self.watch)
        else:
            self._handler.pruned(self._thread_id)
            self.working = False

    def watch(self):
        """Starts watching the thread this watcher is bound to."""
        self._client.fetch(httpclient.HTTPRequest(self._url, if_modified_since=self._last_modified), self._handle)


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
        self._handler = handler
        self._sampling_interval = sampling_interval
        self._images = images
        self._board = board
        self._thread_list_url = 'http://a.4cdn.org/{board}/threads.json'.format(board=self._board)
        self._loop = ioloop.IOLoop.instance()
        self._client = httpclient.AsyncHTTPClient()
        self._previous_threads = set()
        self._watchers = []

    def _handle_threads(self, response):
        self._watchers = filter(attrgetter('working'), self._watchers)

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

                new_threads = curr_threads - self._previous_threads
                self._previous_threads = curr_threads
                for t in new_threads:
                    watcher = ThreadWatcher(self._handler, self._board, self._loop, t, self._images)
                    self._watchers.append(watcher)
                    watcher.watch()
            except ValueError:
                logger.info('Failed to parse thread list JSON response')

        self._loop.add_timeout(timedelta(seconds=self._sampling_interval), self._watch_threads)

    def _watch_threads(self):
        self._client.fetch(self._thread_list_url, self._handle_threads)

    def start(self):
        """Starts watching the board this watcher is bound to."""
        self._watch_threads()
        self._loop.start()