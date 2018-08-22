#!/usr/bin/env python3
"""
Control Things Modbus, aka ctmodbus.py

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
"""

import sys
import serial
import time
from .commands import Commands
from .base import TextArea
from prompt_toolkit.application import Application
from prompt_toolkit.application.current import get_app
from prompt_toolkit.document import Document
from prompt_toolkit.filters import has_focus
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import HSplit, VSplit, Window, FloatContainer, Float
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.shortcuts.dialogs import message_dialog
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import MenuContainer, MenuItem, ProgressBar #, TextArea
from prompt_toolkit.completion import WordCompleter


class MyApplication(Application):
    session = ''
    output_format = 'mixed'


def get_statusbar_text():
    sep = '  -  '
    session = get_app().session
    if type(session) == serial.Serial:
        device = 'connected:' + session.port
    else:
        device = 'connected:None'
    output_format = 'output:' + get_app().output_format
    return sep.join([device, output_format])


# def start_app(session):
def start_app(args):
    """Text-based GUI application"""
    cmd = Commands()
    completer = WordCompleter(cmd.commands(), meta_dict=cmd.meta_dict(), ignore_case=True)
    history = InMemoryHistory()

    # Individual windows
    input_field = TextArea(
        height=1,
        prompt='ctmodbus> ',
        style='class:input-field',
        completer=completer,
        history=history)

    output_field = TextArea(
        scrollbar=True,
        style='class:output-field',
        text='')

    statusbar = Window(
        content = FormattedTextControl(get_statusbar_text),
        height=1,
        style='class:statusbar'  )

    # Organization of windows
    body = FloatContainer(
        HSplit([
            input_field,
            Window(height=1, char='-', style='class:line'),
            output_field,
            statusbar ]),
        floats=[
            Float(xcursor=True,
                  ycursor=True,
                  content=CompletionsMenu(max_height=16, scroll_offset=1)) ] )

    # Adding menus
    root_container = MenuContainer(
        body=body,
        menu_items=[],
        # menu_items=[
        #     MenuItem('Project ', children=[
        #         MenuItem('New'),
        #         MenuItem('Open'),
        #         MenuItem('Save'),
        #         MenuItem('Save as...'),
        #         MenuItem('-', disabled=True),
        #         MenuItem('Exit'),  ]),
        #     MenuItem('View ', children=[
        #         MenuItem('Split'),  ]),
        #     MenuItem('Info ', children=[
        #         MenuItem('Help'),
        #         MenuItem('About'),  ]),  ],
        floats=[
            Float(xcursor=True,
                  ycursor=True,
                  content=CompletionsMenu(max_height=16, scroll_offset=1)),  ])

    # The key bindings.
    kb = KeyBindings()

    @kb.add('space')
    def _(event):
        input_text = input_field.text
        cursor=len(input_text)
        input_updated = input_text[:cursor] + ' ' + input_text[cursor+1:]
        cursor += 1
        input_field.buffer.document = Document(
            text=input_updated, cursor_position=cursor)
        input_field.buffer.completer = WordCompleter([], ignore_case=True)

    @kb.add('enter', filter=has_focus(input_field))
    def _(event):
        # Process commands on prompt after hitting enter key
        # tx_bytes = parse_command(input_field.text, event=event)
        input_field.buffer.completer = WordCompleter(cmd.commands(), meta_dict=cmd.meta_dict(), ignore_case=True)
        if len(input_field.text) == 0:
            return
        output_text = cmd.execute(input_field.text, output_field.text, event)
        input_field.buffer.reset(append_to_history=True)

        # For commands that do not send data to modbus device
        if output_text == None:
            input_field.text = ''
            return
        # For invalid commands forcing users to correct them
        elif output_text == False:
            return
        # For invalid commands forcing users to correct them
        else:
            output_field.buffer.document = Document(
                text=output_text, cursor_position=len(output_text))
            input_field.text = ''

    @kb.add('c-c')
    def _(event):
        """Pressing Control-C will copy highlighted text to clipboard"""
        data = output_field.buffer.copy_selection()
        get_app().clipboard.set_data(data)

    @kb.add('c-p')
    def _(event):
        """Pressing Control-P will paste text from clipboard"""
        input_field.buffer.paste_clipboard_data(get_app().clipboard.get_data())

    @kb.add('c-q')
    def _(event):
        " Pressing Ctrl-Q will exit the user interface. "
        cmd.do_exit(input_field.text, output_field.text, event)

    @kb.add('c-d')
    def _(event):
        """Press Ctrl-D to start the python debugger"""
        import pdb
        pdb.set_trace()

    style = Style([
        # ('output-field', 'bg:#000000 #ffffff'),
        # ('input-field', 'bg:#000000 #ffffff'),
        ('line',        '#004400'),
        ('statusbar', 'bg:#AAAAAA')  ])

    # Run application.
    application = MyApplication(
        layout=Layout(root_container, focused_element=input_field),
        key_bindings=kb,
        style=style,
        mouse_support=True,
        full_screen=True  )
    application.run()
