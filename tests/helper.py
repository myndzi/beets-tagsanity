# This file is part of beets.
# Copyright 2016, Thomas Scholtes.
#
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.

"""This module includes various helpers that provide fixtures, capture
information or mock the environment.

- The `control_stdin` and `capture_stdout` context managers allow one to
  interact with the user interface.

- `has_program` checks the presence of a command on the system.

- The `generate_album_info` and `generate_track_info` functions return
  fixtures to be used when mocking the autotagger.

- The `ImportSessionFixture` allows one to run importer code while
  controlling the interactions through code.

- The `TestHelper` class encapsulates various fixtures that can be set up.
"""


import sys
import os
import os.path
import shutil
import subprocess
from tempfile import mkdtemp
from contextlib import contextmanager
from io import StringIO

import beets
from beets import logging
import beets.plugins
from beets.library import Library, Item, Album
from beets import util


class LogCapture(logging.Handler):
    def __init__(self):
        logging.Handler.__init__(self)
        self.messages = []

    def emit(self, record):
        self.messages.append(str(record.msg))


@contextmanager
def capture_log(logger="beets"):
    capture = LogCapture()
    log = logging.getLogger(logger)
    log.addHandler(capture)
    try:
        yield capture.messages
    finally:
        log.removeHandler(capture)


@contextmanager
def control_stdin(input=None):
    """Sends ``input`` to stdin.

    >>> with control_stdin('yes'):
    ...     input()
    'yes'
    """
    org = sys.stdin
    sys.stdin = StringIO(input)
    try:
        yield sys.stdin
    finally:
        sys.stdin = org


@contextmanager
def capture_stdout():
    """Save stdout in a StringIO.

    >>> with capture_stdout() as output:
    ...     print('spam')
    ...
    >>> output.getvalue()
    'spam'
    """
    org = sys.stdout
    sys.stdout = capture = StringIO()
    try:
        yield sys.stdout
    finally:
        sys.stdout = org
        print(capture.getvalue())


def _convert_args(args):
    """Convert args to bytestrings for Python 2 and convert them to strings
    on Python 3.
    """
    for i, elem in enumerate(args):
        if isinstance(elem, bytes):
            args[i] = elem.decode(util.arg_encoding())

    return args


def has_program(cmd, args=["--version"]):
    """Returns `True` if `cmd` can be executed."""
    full_cmd = _convert_args([cmd] + args)
    try:
        with open(os.devnull, "wb") as devnull:
            subprocess.check_call(
                full_cmd, stderr=devnull, stdout=devnull, stdin=devnull
            )
    except OSError:
        return False
    except subprocess.CalledProcessError:
        return False
    else:
        return True


class TestHelper:
    """Helper mixin for high-level cli and plugin tests.

    This mixin provides methods to isolate beets' global state provide
    fixtures.
    """

    # TODO automate teardown through hook registration

    def setup_beets(self, disk=False):
        """Setup pristine global configuration and library for testing.

        Sets ``beets.config`` so we can safely use any functionality
        that uses the global configuration.  All paths used are
        contained in a temporary directory

        Sets the following properties on itself.

        - ``temp_dir`` Path to a temporary directory containing all
          files specific to beets

        - ``libdir`` Path to a subfolder of ``temp_dir``, containing the
          library's media files. Same as ``config['directory']``.

        - ``config`` The global configuration used by beets.

        - ``lib`` Library instance created with the settings from
          ``config``.

        Make sure you call ``teardown_beets()`` afterwards.
        """
        self.create_temp_dir()
        os.environ["BEETSDIR"] = util.py3_path(self.temp_dir)

        self.config = beets.config
        self.config.clear()
        self.config.read()

        self.config["plugins"] = []
        self.config["verbose"] = 1
        self.config["ui"]["color"] = False
        self.config["threaded"] = False

        self.libdir = os.path.join(self.temp_dir, b"libdir")
        os.mkdir(self.libdir)
        self.config["directory"] = util.py3_path(self.libdir)

        if disk:
            dbpath = util.bytestring_path(self.config["library"].as_filename())
        else:
            dbpath = ":memory:"
        self.lib = Library(dbpath, self.libdir)

    def teardown_beets(self):
        self.lib._close()
        if "BEETSDIR" in os.environ:
            del os.environ["BEETSDIR"]
        self.remove_temp_dir()
        self.config.clear()
        beets.config.read(user=False, defaults=True)

    def load_plugins(self, *plugins):
        """Load and initialize plugins by names.

        Similar setting a list of plugins in the configuration. Make
        sure you call ``unload_plugins()`` afterwards.
        """
        # FIXME this should eventually be handled by a plugin manager
        beets.config["plugins"] = plugins
        beets.plugins.load_plugins(plugins)
        beets.plugins.find_plugins()

        # Take a backup of the original _types and _queries to restore
        # when unloading.
        Item._original_types = dict(Item._types)
        Album._original_types = dict(Album._types)
        Item._types.update(beets.plugins.types(Item))
        Album._types.update(beets.plugins.types(Album))

        Item._original_queries = dict(Item._queries)
        Album._original_queries = dict(Album._queries)
        Item._queries.update(beets.plugins.named_queries(Item))
        Album._queries.update(beets.plugins.named_queries(Album))

    def unload_plugins(self):
        """Unload all plugins and remove the from the configuration."""
        # FIXME this should eventually be handled by a plugin manager
        beets.config["plugins"] = []
        beets.plugins._classes = set()
        beets.plugins._instances = {}
        Item._types = Item._original_types
        Album._types = Album._original_types
        Item._queries = Item._original_queries
        Album._queries = Album._original_queries

    # Safe file operations

    def create_temp_dir(self):
        """Create a temporary directory and assign it into
        `self.temp_dir`. Call `remove_temp_dir` later to delete it.
        """
        temp_dir = mkdtemp()
        self.temp_dir = util.bytestring_path(temp_dir)

    def remove_temp_dir(self):
        """Delete the temporary directory created by `create_temp_dir`."""
        shutil.rmtree(self.temp_dir)

    def touch(self, path, dir=None, content=""):
        """Create a file at `path` with given content.

        If `dir` is given, it is prepended to `path`. After that, if the
        path is relative, it is resolved with respect to
        `self.temp_dir`.
        """
        if dir:
            path = os.path.join(dir, path)

        if not os.path.isabs(path):
            path = os.path.join(self.temp_dir, path)

        parent = os.path.dirname(path)
        if not os.path.isdir(parent):
            os.makedirs(util.syspath(parent))

        with open(util.syspath(path), "a+") as f:
            f.write(content)
        return path
