# -*- encoding: utf-8 -*-
from __future__ import absolute_import
from __future__ import print_function

import io
import re
from glob import glob
from os.path import basename
from os.path import dirname
from os.path import join
from os.path import splitext

from setuptools import find_packages
from setuptools import setup


def read(*names, **kwargs):
    return io.open(
        join(dirname(__file__), *names),
        encoding=kwargs.get('encoding', 'utf8')
    ).read()

setup(
    name='ctmodbus',
    version=open('VERSION').read(),
    license='GPLv3',
    description='a security professional\'s swiss army knife for interacting with Modbus devices',
    long_description=open('README.md').read(),
    long_description_content_type="text/markdown",
    author='Justin Searle',
    author_email='justin@meeas.com',
    url='https://github.com/ControlThingsTools/ctmodbus',
    packages=find_packages('src'),
    package_dir={'': 'src'},
    py_modules=[splitext(basename(path))[0] for path in glob('src/*.py')],
    include_package_data=True,
    zip_safe=False,
    classifiers=[
        # complete classifier list: http://pypi.python.org/pypi?%3Aaction=list_classifiers
        'Development Status :: 5 - Production/Stable',
        'Intended Audience :: Developers',
        'Intended Audience :: Information Technology',
        'Intended Audience :: Manufacturing',
        'Intended Audience :: Other Audience',
        'Intended Audience :: Science/Research',
        'License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)',
        'Operating System :: Unix',
        'Operating System :: POSIX',
        'Operating System :: Microsoft :: Windows',
        'Programming Language :: Python :: 3',
        'Topic :: Utilities',
    ],
    keywords=[
        'Modbus', 'pentest', 'ControlThingsTools', 'ControlThingsPlatform',
    ],
    python_requires='>=3.6,<4',
    install_requires=[
        'ctui==0.7.*',
        'pyserial',
        'pymodbus',
        'tabulate'
    ],
    extras_require={
        # eg:
        #   'rst': ['docutils>=0.11'],
    },
    entry_points={
        'console_scripts': [
            'ctmodbus = ctmodbus.commands:main',
        ]
    },
)
