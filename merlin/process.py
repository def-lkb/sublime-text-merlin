import json
import sublime
import subprocess
import os
import sys

from .helpers import fmtpos

main_protocol_version = 3


class MerlinExc(Exception):
    """ Exception returned by merlin. """

    def __init__(self, value):
        self.value = value

    def __str__(self):
        return repr(self.value)


class Failure(MerlinExc):
    """ Failure exception. """
    pass


class Error(MerlinExc):
    """ Error exception. """
    pass


class MerlinException(MerlinExc):
    """ Standard exception. """
    pass


class MerlinProcess(object):
    """
    This class launches a merlin process and send/receive commands to
    synchronise buffer, autocomplete...
    """

    def clear(self):
        self._settings = None
        self._binary_path = None
        self._last_commands = []
        self._verbosity_counter = (None, None)

    def __init__(self):
        self.clear()

    def settings(self):
        if self._settings is None:
            self._settings = sublime.load_settings("Merlin.sublime-settings")
        return self._settings

    def binary_path(self):
        """
        Return the path of the ocamlmerlin binary."
        """

        if self._binary_path is None:
            merlin_path = self.settings().get('ocamlmerlin_path')
            if merlin_path:
                self._binary_path = merlin_path
            else:
                # For Mac OS X, add the path for homebrew
                if "/usr/local/bin" not in os.environ['PATH'].split(os.pathsep):
                    os.environ['PATH'] += os.pathsep + "/usr/local/bin"
                opam_process = subprocess.Popen('opam config var bin', stdout=subprocess.PIPE, shell=True)
                opam_bin_path = opam_process.stdout.read().decode('utf-8').rstrip() + '/ocamlmerlin'

                if os.path.isfile(opam_bin_path) and os.access(opam_bin_path, os.X_OK):
                    self._binary_path = opam_bin_path
                else:
                    self._binary_path = 'ocamlmerlin'

        return self._binary_path

    def store_last_command(self, command, response, errors):
        if self._last_commands and self._last_commands[0] == (command, None, None):
            self._last_commands[0] = (command, response, errors)
        else:
            self._last_commands.insert(0, (command, response, errors))
            if len(self._last_commands) > 5:
                self._last_commands.pop()

    def track_verbosity(self, key, args):
        if key:
            if key is True:
                key = args
            if self._verbosity_counter[0] == key:
                self._verbosity_counter = (key, self._verbosity_counter[1]+1)
            else:
                self._verbosity_counter = (key, 0)
            return ["-verbosity", str(self._verbosity_counter[1])]
        else:
            return []

    def exec(self, arguments, binary_path=None, input=""):
        """ Start a merlin process. """
        try:
            if binary_path is None:
                binary_path = self.binary_path()
            command = [binary_path]
            command.extend(arguments)
            self.store_last_command(command, None, None)
            # win32 means windows, either 64 or 32 bits.
            # Note that owing to a long-standing bug in Python, stderr must be given
            # (see https://bugs.python.org/issue3905)
            if sys.platform == "win32":
                info = subprocess.STARTUPINFO()
                info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                info.wShowWindow = subprocess.SW_HIDE
                process = subprocess.Popen(
                        command,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        startupinfo=info,
                        universal_newlines=True,
                        )
            else:
                process = subprocess.Popen(
                        command,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        universal_newlines=True,
                        )
            print(command)
            (response, errors) = process.communicate(input=input)
            self.store_last_command(command, response, errors)
            return response
        except (OSError, FileNotFoundError) as e:
            print("Failed starting ocamlmerlin. Please ensure that ocamlmerlin"
                  "binary is executable.")
            raise e

    def restart(self):
        self.exec(["server", "stop-server"])
        self.clear()

    def command(self, args, binary_path=None, filename=None, extensions=None, packages=None, dot_merlins=None, input=None, other_flags=None, debug=False, build_path=None, source_path=None, track_verbosity=None):
        """
        Send a command to merlin and wait to return the results.
        Raise an exception if merlin returned an error message.
        """

        cmdline = ["server"]
        cmdline.extend(args)

        if filename:
            cmdline.extend(["-filename", filename])

        verbosity = self.track_verbosity(track_verbosity, args)
        cmdline.extend(verbosity)

        for ext in extensions or []:
            cmdline.extend(["-extension",ext])

        for pkg in packages or []:
            cmdline.extend(["-package",pkg])

        for dm in dot_merlins or []:
            cmdline.extend(["-dot-merlin", dm])

        for path in build_path or []:
            cmdline.extend(["-build-path", path])

        for path in source_path or []:
            cmdline.extend(["-source-path", path])

        if debug:
            cmdline.extend(["-log-file", "-"])

        flags = self.settings().get('ocamlmerlin_flags') or []
        cmdline.extend(flags)

        if other_flags:
            cmdline.extend(other_flags)

        result = self.exec(cmdline, binary_path=binary_path, input=input)
        print(result)
        result = json.loads(result)
        class_ = result['class']
        content = result['value']
        for msg in result['notifications']:
            print("merlin: {}".format(msg))

        if class_ == "return":
            return content
        elif class_ == "failure":
            raise Failure(content)
        elif class_ == "error":
            raise Error(content)
        elif class_ == "exception":
            raise MerlinException(content)

class MerlinView(object):
    """
    This class wraps commands local to a view/buffer
    """

    def __init__(self, process, view):
        self.process = process
        self.view = view

    def command(self, args, track_verbosity=None):
        settings = self.view.settings()
        return self.process.command(
                args,
                binary_path=settings.get("ocamlmerlin_path"),
                dot_merlins=settings.get("ocamlmerlin_dot_merlins"),
                extensions=settings.get("ocamlmerlin_extensions"),
                filename=self.view.file_name(),
                input=self.view.substr(sublime.Region(0, self.view.size())),
                other_flags=settings.get("ocamlmerlin_flags"),
                packages=settings.get("ocamlmerlin_packages"),
                build_path=settings.get("ocamlmerlin_buildpath"),
                source_path=settings.get("ocamlmerlin_sourcepath"),
                track_verbosity=track_verbosity
                )

    def complete_cursor(self, base, line, col):
        """ Return possible completions at the current cursor position. """
        with_doc = self.process.settings().get("ocamlmerlin_complete_with_doc")
        cmd = ["complete-prefix"]
        cmd.extend(["-position", fmtpos((line,col)), "-prefix", base])
        cmd.extend(["-doc", (with_doc and "y" or "n")])
        return self.command(cmd, track_verbosity=True)

    def report_errors(self):
        """
        Return all errors detected by merlin while parsing the current file.
        """
        return self.command(["errors"])

    def find_list(self):
        """ List all possible external modules to load. """
        return self.command(['findlib-list'])

    def set_packages(self, packages):
        """ Find and load external modules. """
        self.view.settings().set("ocamlmerlin_packages", packages)

    def project(self):
        """
        Returns a tuple
          (dot_merlins, failures)
        where dot_merlins is a list of loaded .merlin files
          and failures is the list of errors which occured during loading
        """
        result = self.send_query("project", "get")
        return (result['result'], result['failures'])

    # Path management
    def list_build_path(self):
        return self.view.settings().get("ocamlmerlin_buildpath") or []

    def add_build_path(self, path):
        paths = self.list_build_path()
        paths.append(path)
        self.view.settings.set("ocamlmerlin_buildpath", paths)

    def list_source_path(self):
        return self.view.settings().get("ocamlmerlin_sourcepath") or []

    def add_source_path(self, path):
        paths = self.list_source_path()
        paths.append(path)
        self.view.settings.set("ocamlmerlin_sourcepath", paths)

    # File selection
    def which_path(self, names):
        cmd = ["path-of-source"]
        for name in names:
            cmd.extend(["-file",name])
        return self.command(cmd)

    def which_with_ext(self, extensions):
        cmd = ["list-modules"]
        for ext in extensions:
            cmd.extend(["-ext",ext])
        return self.command(cmd)

    # Type information
    def type_enclosing(self, line, col):
        cmd = ["type-enclosing", "-position", fmtpos((line,col))]
        return self.command(cmd, track_verbosity=True)

    # Extensions management
    def extension_list(self):
        return self.command(["extension-list"])

    def extension_enable(self, exts):
        merlin_exts = self.view.settings().get("ocamlmerlin_extensions")
        for ext in exts:
            if not ext in merlin_exts:
                merlin_exts.append(ext)
        self.view.settings().set("ocamlmerlin_extensions", merlin_exts)

    def extension_disable(self, exts):
        merlin_exts = self.view.settings().get("ocamlmerlin_extensions")
        for ext in exts:
            if ext in merlin_exts:
                merlin_exts.remove(ext)
        self.view.settings().set("ocamlmerlin_extensions", merlin_exts)

    def locate(self, line, col, ident="", kind="mli"):
        cmd = ["locate", "-look-for", kind]
        if not (line is None or col is None):
            cmd.extend(["-prefix", ident])
        return self.command(cmd)
