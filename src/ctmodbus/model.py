# Copyright (C) 2018  Justin Searle
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or any later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details at <http://www.gnu.org/licenses/>.

from datetime import datetime
from pony.orm import *

db = Database()

class Command(db.Entity):
    id = PrimaryKey(int, auto=True)
    command = Required(str)
    session = Optional('Session')
    transactions = Set('Transaction')

class Session(db.Entity):
    id = PrimaryKey(int, auto=True)
    session = Required(str)
    start = Required(datetime)
    end = Optional(datetime)
    command = Required(Command)
    transactions = Set('Transaction')

class Transaction(db.Entity):
    id = PrimaryKey(int, auto=True)
    tx = Required(str)
    rx = Required(str)
    timestamp = Required(datetime)
    session = Required(Session)
    command = Optional(Command)

class Setting(db.Entity):
    id = PrimaryKey(int, auto=True)
    name = Required(str)
    value = Required(str)
    tab = Optional(int)

class Message(db.Entity):
    id = PrimaryKey(int, auto=True)
    name = Required(str)
    description = Optional(str)
    tx = Optional(str)
    decode = Optional(str)

db.generate_mapping()
