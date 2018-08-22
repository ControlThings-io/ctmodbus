# Copyright (C) 2017-2018  Justin Searle
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or any later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details at <http://www.gnu.org/licenses/>.

from argparse import ArgumentParser as Argp
from .commands import Commands
from .application import start_app
try:
    import better_exceptions
except ImportError as err:
    pass


def main():
    """Start application but allow passing of commands that create sessions"""
    start_app([])


if __name__ == '__main__':
    main()
