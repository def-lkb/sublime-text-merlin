import functools
import subprocess
import os

import sublime


def fmtpos(arg):
    if arg is None:
        return "end"
    elif isinstance(arg, dict):
        line = arg['line']
        col = arg['col']
    elif isinstance(arg, tuple) or isinstance(arg, list):
        (line, col) = arg
    else:
        raise ValueError("fmtpos takes None, (line,col) or { 'line' : _, 'col' : _ }")
    return "{0}:{1}".format(line, col)

def is_ocaml(view):
    """
    Check if the current view is an OCaml source code.
    """

    matcher = 'source.ocaml'
    location = view.sel()[0].begin()
    return view.match_selector(location, matcher)


def only_ocaml(func):
    """
    Execute the given function if we are in an OCaml source code only.
    """

    @functools.wraps(func)
    def wrapper(self, view, *args, **kwargs):
        if is_ocaml(view):
            return func(self, view, *args, **kwargs)

    return wrapper


def merlin_pos(view, pos):
    """
    Convert a position returned by Merlin to a Sublime text point.
    Sublime uses character positions and starts each file at line 0.
    """

    return view.text_point(pos['line'] - 1, pos['col'])


def clean_whitespace(text):
    """
    Replace sequence of whitespaces by a single space
    """

    return ' '.join(text.split())
