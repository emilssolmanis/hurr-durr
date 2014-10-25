# What is this?

A streaming async API to 4chan boards. You create a handler class, implement some callbacks and get informed when new
posts and images arrive in threads. There's a bundled `FileHandler` that saves content to the file system.

# How?

The bundled executable called `hurr-durr` is a scraper. You use it as

    hurr-durr --directory /tmp/4chan --board b

There's an optional `-i` flag to also download the images and a `-v` flag to see logging information. All this is also
available via the `-h` flag.

As for the API part, the main entry point is `hurr_durr.ChanWatcher`. You have to implement a handler class and then
do something along the lines of

```python
from hurr_durr import FileHandler, ChanWatcher

watcher = ChanWatcher(FileHandler('/tmp/4chan/b'), 'b', images=True)
watcher.start()
```

The only handler currently bundled is a `FileHandler` which saves content to disk. To implement your own handler,
you need to create a class inheriting from `Handler`, containing 4 methods:

 * `post(thread_id, new_post)` -- gets called when a new post is made in a thread
 * `pruned(thread_id)` -- gets called when a thread is pruned from 4chan
 * `img(thread_id, filename, data)` -- gets called with downloaded image data, only relevant if images are downloaded
 * `download_img(thread_id, filename)` -- gets called to check if a particular image should be downloaded, only relevant
    if images are downloaded

# Installing

It's in PyPI, just use pip

    pip install hurr-durr

# Why?

Because I needed a 4chan scraper, everything else sucked, and I wanted to give Tornado a ride around the block.

# License

 Copyright 2014 Emils Solmanis

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.