#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from setuptools import setup

setup(
    name="beets-tagsanity",
    version="0.1",
    description="beets plugin to sanely romanize metadata in tags AND paths",
    long_description=open("README.md").read(),
    author="Kris Reeves",
    author_email="",
    url="https://github.com/myndzi/beets-tagsanity",
    license="MIT",
    platforms="ALL",
    packages=["beetsplug"],
    install_requires=[
        "beets>=1.6.0",
        "unihandecode==v0.9.0b1",
        "regex",
        "confuse>=1.0.0",
    ],
)
