"""
Control Things Modbus, aka ctmodbus.py

# Copyright (C) 2019  Justin Searle
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or any later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details at <http://www.gnu.org/licenses/>.
"""

class Loops(object):
    '''Object that contains and calculates a list of range parameters'''
    from sys import maxsize

    def __init__(self, csr=None, minimum=-maxsize, maximum=maxsize):
        assert (isinstance(csr, str) or csr == None), 'csr must be a string'
        self.csr = csr or None
        self.loops = []
        self.length = 0
        self.enum_length = 0
        if csr:
            self._from_int_csr(csr, minimum, maximum)

    def __repr__(self):
        return repr(self.loops)

    def __len__(self):
        return self.length

    def __iter__(self):
        for loop in self.loops:
            yield loop

    def max_count(self, max_count):
        assert (isinstance(max_count, int)), 'max_count must be int'
        for loop in self.loops:
            for i in range(0, loop['count'], max_count):
                start, stop, count = loop.values()
                yield {'start': start + i,
                       'stop': min(start + max_count + i, stop),
                       'count': min(max_count, count - i) }

    def append(self, start, stop=None, count=None):
        """Append a new loop"""
        assert (isinstance(start, int)), 'start must be an int'
        assert (stop or count), 'must set stop or count'
        if stop and not count:
            count = stop - start + 1
        elif count and not stop:
            stop = start + count - 1
        assert (count == stop - start + 1), 'count must equal stop - start + 1'
        self.loops.append({'start':start, 'stop':stop, 'count':count})
        self.length += 1
        self.enum_length += count

    def enum(self, func=None):
        """Use ranges to enumerate every increment"""
        for loop in self.loops:
            for x in range(loop['start'], loop['stop']):
                if func:
                    yield func(x)
                else:
                    yield x

    def _from_int_csr(self, csr, minimum, maximum):
        """Converts comma separated int ranges to range() functions"""
        assert (isinstance(csr, str)), 'csr must be a string like "1-5,10,13-15"'
        assert (isinstance(minimum, int)), 'minimum must be int'
        self.minimum = minimum
        assert (isinstance(maximum, int)), 'maximum must be int'
        self.maximum = maximum
        parts = csr.split(',')
        for single_or_range in parts:
            if single_or_range.isdigit():
                single = int(single_or_range)
                assert (minimum <= single <= maximum), '{} is not between {} and {}'.format(single, minimum, maximum)
                self.loops.append({'start':single, 'stop':single+1, 'count':1})
                self.length += 1
                self.enum_length += 1
            else:
                a_range = single_or_range.split('-')
                assert (len(a_range) == 2), '{} is not a valid range'.format(a_range)
                start, stop = a_range
                assert (start.isdigit() and stop.isdigit()), '{} and {} must be integers'.format(start, stop)
                start, stop = int(start), int(stop)
                assert (minimum <= start <= maximum), '{} is not between {} and {}'.format(start, minimum, maximum)
                assert (minimum <= stop <= maximum), '{} is not between {} and {}'.format(stop, minimum, maximum)
                assert (start < stop), '{} must be less than {}'.format(start, stop)
                count = stop - start + 1
                self.loops.append({'start':start, 'stop':stop+1, 'count':count})
                self.length += 1
                self.enum_length += count
