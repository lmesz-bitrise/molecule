#  Copyright (c) 2015-2018 Cisco Systems, Inc.
#
#  Permission is hereby granted, free of charge, to any person obtaining a copy
#  of this software and associated documentation files (the "Software"), to
#  deal in the Software without restriction, including without limitation the
#  rights to use, copy, modify, merge, publish, distribute, sublicense, and/or
#  sell copies of the Software, and to permit persons to whom the Software is
#  furnished to do so, subject to the following conditions:
#
#  The above copyright notice and this permission notice shall be included in
#  all copies or substantial portions of the Software.
#
#  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#  IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#  FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#  AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#  LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
#  FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
"""Molecule Utils Module."""

from __future__ import print_function

import contextlib
import fnmatch
import os
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache  # noqa
from subprocess import CompletedProcess
from typing import Any, Dict, List, Optional, Union

import colorama
import jinja2
import yaml
from rich.syntax import Syntax
from subprocess_tee import run

from molecule.console import console
from molecule.constants import MOLECULE_HEADER
from molecule.logger import get_logger

LOG = get_logger(__name__)


class SafeDumper(yaml.SafeDumper):
    """SafeDumper YAML Class."""

    def increase_indent(self, flow=False, indentless=False):
        return super(SafeDumper, self).increase_indent(flow, False)


def print_debug(title: str, data: str) -> None:
    """Print debug information."""
    title = "DEBUG: {}".format(title)
    title_list = [
        colorama.Back.WHITE,
        colorama.Style.BRIGHT,
        colorama.Fore.BLACK,
        title,
        colorama.Fore.RESET,
        colorama.Back.RESET,
        colorama.Style.RESET_ALL,
    ]
    print("".join(title_list))
    data_list = [
        colorama.Fore.BLACK,
        colorama.Style.BRIGHT,
        data,
        colorama.Style.RESET_ALL,
        colorama.Fore.RESET,
    ]
    print("".join(data_list))


def print_environment_vars(env: Optional[Dict[str, str]]) -> None:
    """
    Print ``Ansible`` and ``Molecule`` environment variables and returns None.

    :param env: A dict containing the shell's environment as collected by
    ``os.environ``.
    :return: None
    """
    if env:
        ansible_env = {k: v for (k, v) in env.items() if "ANSIBLE_" in k}
        print_debug("ANSIBLE ENVIRONMENT", safe_dump(ansible_env))

        molecule_env = {k: v for (k, v) in env.items() if "MOLECULE_" in k}
        print_debug("MOLECULE ENVIRONMENT", safe_dump(molecule_env))

        combined_env = ansible_env.copy()
        combined_env.update(molecule_env)
        print_debug(
            "SHELL REPLAY",
            " ".join(["{}={}".format(k, v) for (k, v) in sorted(combined_env.items())]),
        )
        print()


def sysexit(code: int = 1) -> None:
    """Perform a system exit with given code, default 1."""
    sys.exit(code)


def sysexit_with_message(
    msg: str, code: int = 1, detail: Optional[Dict] = None
) -> None:
    """Exit with an error message."""
    # detail is usually a multi-line string which is not suitable for normal
    # logger.
    if detail:
        if isinstance(detail, dict):
            detail_str = safe_dump(detail)
        else:
            detail_str = str(detail)
        print(detail_str)
    LOG.critical(msg)
    sysexit(code)


def run_command(cmd, env=None, debug=False, echo=False) -> CompletedProcess:
    """
    Execute the given command and returns None.

    :param cmd: :
        - a string or list of strings (similar to subprocess.run)
        - a BakedCommand object (
    :param debug: An optional bool to toggle debug output.
    :return: ``sh`` object
    """
    args = []
    stdout = None
    stderr = None
    if cmd.__class__.__name__ == "Command":
        raise RuntimeError(
            "Molecule 3.2.0 dropped use of sh library, update plugin code to use new API. "
            "See https://github.com/ansible-community/molecule/issues/2678"
        )
    elif cmd.__class__.__name__ == "BakedCommand":
        env = cmd.env if not env else cmd.env.copy().update(env)
        args = cmd.cmd
        stdout = cmd.stdout
        stderr = cmd.stderr
    else:
        args = cmd

    if debug:
        print_environment_vars(env)

    return run(args, env=env, stdout=stdout, stderr=stderr, echo=echo or debug)


def os_walk(directory, pattern, excludes=[]):
    """Navigate recursively and retried files based on pattern."""
    for root, dirs, files in os.walk(directory, topdown=True):
        dirs[:] = [d for d in dirs if d not in excludes]
        for basename in files:
            if fnmatch.fnmatch(basename, pattern):
                filename = os.path.join(root, basename)

                yield filename


def render_template(template, **kwargs):
    """Render a jinaj2 template."""
    t = jinja2.Environment()
    t = t.from_string(template)

    return t.render(kwargs)


def write_file(filename, content):
    """
    Write a file with the given filename and content and returns None.

    :param filename: A string containing the target filename.
    :param content: A string containing the data to be written.
    :return: None
    """
    with open_file(filename, "w") as f:
        f.write(content)

    file_prepender(filename)


def molecule_prepender(content):
    """Return molecule identification header."""
    return MOLECULE_HEADER + "\n\n" + content


def file_prepender(filename):
    """
    Prepend an informational header on files managed by Molecule and returns \
    None.

    :param filename: A string containing the target filename.
    :return: None
    """
    with open_file(filename, "r+") as f:
        content = f.read()
        f.seek(0, 0)
        f.write(molecule_prepender(content))


def safe_dump(data: Any) -> str:
    """
    Dump the provided data to a YAML document and returns a string.

    :param data: A string containing an absolute path to the file to parse.
    :return: str
    """
    # TODO(retr0h): Do we need to encode?
    # yaml.dump(data) produces the document as a str object in both python
    # 2 and 3.
    return yaml.dump(
        data, Dumper=SafeDumper, default_flow_style=False, explicit_start=True
    )


def safe_load(string) -> Dict:
    """
    Parse the provided string returns a dict.

    :param string: A string to be parsed.
    :return: dict
    """
    try:
        return yaml.safe_load(string) or {}
    except yaml.scanner.ScannerError as e:
        sysexit_with_message(str(e))
    return {}


def safe_load_file(filename):
    """
    Parse the provided YAML file and returns a dict.

    :param filename: A string containing an absolute path to the file to parse.
    :return: dict
    """
    with open_file(filename) as stream:
        return safe_load(stream)


@contextlib.contextmanager
def open_file(filename, mode="r"):
    """
    Open the provide file safely and returns a file type.

    :param filename: A string containing an absolute path to the file to open.
    :param mode: A string describing the way in which the file will be used.
    :return: file type
    """
    with open(filename, mode) as stream:
        yield stream


def instance_with_scenario_name(instance_name, scenario_name):
    """Format instance name that includes scenario."""
    return "{}-{}".format(instance_name, scenario_name)


def strip_ansi_escape(data):
    """Remove all ANSI escapes from string or bytes.

    If bytes is passed instead of string, it will be converted to string
    using UTF-8.
    """
    if isinstance(data, bytes):
        data = data.decode("utf-8")

    return re.sub(r"\x1b[^m]*m", "", data)


def strip_ansi_color(data):
    """Remove ANSI colors from string or bytes."""
    if isinstance(data, bytes):
        data = data.decode("utf-8")

    # Taken from tabulate
    invisible_codes = re.compile(r"\x1b\[\d*m")

    return re.sub(invisible_codes, "", data)


def verbose_flag(options):
    """Return computed verbosity flag."""
    verbose = "v"
    verbose_flag = []
    for i in range(0, 3):
        if options.get(verbose):
            verbose_flag = ["-{}".format(verbose)]
            del options[verbose]
            if options.get("verbose"):
                del options["verbose"]
            break
        verbose = verbose + "v"

    return verbose_flag


def filter_verbose_permutation(options):
    """Clean verbose information."""
    return {k: options[k] for k in options if not re.match("^[v]+$", k)}


def title(word):
    """Format title."""
    return " ".join(x.capitalize() or "_" for x in word.split("_"))


def abs_path(path):
    """Return absolute path."""
    if path:
        return os.path.abspath(path)


def camelize(string):
    """Format string as camel-case."""
    # NOTE(retr0h): Taken from jpvanhal/inflection
    # https://github.com/jpvanhal/inflection
    return re.sub(r"(?:^|_)(.)", lambda m: m.group(1).upper(), string)


def underscore(string):
    """Format string to underlined notation."""
    # NOTE(retr0h): Taken from jpvanhal/inflection
    # https://github.com/jpvanhal/inflection
    string = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", string)
    string = re.sub(r"([a-z\d])([A-Z])", r"\1_\2", string)
    string = string.replace("-", "_")

    return string.lower()


def merge_dicts(a, b):
    """
    Merge the values of b into a and returns a new dict.

    This function uses the same algorithm as Ansible's `combine(recursive=True)` filter.

    :param a: the target dictionary
    :param b: the dictionary to import
    :return: dict
    """
    result = a.copy()

    for k, v in b.items():
        if k in a and isinstance(a[k], Mapping) and isinstance(v, Mapping):
            result[k] = merge_dicts(a[k], v)
        else:
            result[k] = v

    return result


def validate_parallel_cmd_args(cmd_args):
    """Prevents use of options incompatible with parallel mode."""
    if cmd_args.get("parallel") and cmd_args.get("destroy") == "never":
        msg = 'Combining "--parallel" and "--destroy=never" is not supported'
        sysexit_with_message(msg)


def _parallelize_platforms(config, run_uuid):
    def parallelize(platform):
        platform["name"] = "{}-{}".format(platform["name"], run_uuid)
        return platform

    return [parallelize(platform) for platform in config["platforms"]]


def find_vcs_root(test, dirs=(".git", ".hg", ".svn"), default=None) -> str:
    """Return current repository root directory."""
    prev, test = None, os.path.abspath(test)
    while prev != test:
        if any(os.path.isdir(os.path.join(test, d)) for d in dirs):
            return test
        prev, test = test, os.path.abspath(os.path.join(test, os.pardir))
    return default


def lookup_config_file(filename: str) -> str:
    """Return config file PATH."""
    for path in [find_vcs_root(os.getcwd(), default="~"), "~"]:
        f = os.path.expanduser("%s/%s" % (path, filename))
        if os.path.isfile(f):
            LOG.info("Found config file %s", f)
            return f
    return f


def boolean(value: Any, strict=True) -> bool:
    """Evaluate any object as boolean matching ansible behavior."""
    # Based on https://github.com/ansible/ansible/blob/devel/lib/ansible/module_utils/parsing/convert_bool.py

    BOOLEANS_TRUE = frozenset(("y", "yes", "on", "1", "true", "t", 1, 1.0, True))
    BOOLEANS_FALSE = frozenset(("n", "no", "off", "0", "false", "f", 0, 0.0, False))
    BOOLEANS = BOOLEANS_TRUE.union(BOOLEANS_FALSE)

    if isinstance(value, bool):
        return value

    normalized_value = value
    if isinstance(value, (str, bytes)):
        normalized_value = str(value).lower().strip()

    if normalized_value in BOOLEANS_TRUE:
        return True
    elif normalized_value in BOOLEANS_FALSE or not strict:
        return False

    raise TypeError(
        "The value '%s' is not a valid boolean.  Valid booleans include: %s"
        % (str(value), ", ".join(repr(i) for i in BOOLEANS))
    )


@dataclass
class BakedCommand:
    """Define a subprocess command to be executed."""

    cmd: Union[str, List[str]]
    env: Optional[Dict]
    cwd: Optional[str] = None
    stdout: Any = None
    stderr: Any = None


def dict2args(data: Dict) -> List[str]:
    """Convert a dictionary of options to command like arguments."""
    result = []
    # keep sorting in order to achieve a predictable behavior
    for k, v in sorted(data.items()):
        if v is not False:
            prefix = "-" if len(k) == 1 else "--"
            result.append(f"{prefix}{k}".replace("_", "-"))
            if v is not True:
                # { foo: True } should produce --foo without any values
                result.append(v)
    return result


def bool2args(data: bool) -> List[str]:
    """Convert a boolean value to command line argument (flag)."""
    return []


def print_as_yaml(data: Any) -> None:
    """Render python object as yaml on console."""
    result = Syntax(safe_dump(data), "yaml")
    console.print(result)


def chomp(text: str) -> str:
    """Remove any training spaces from string."""
    return "\n".join([x.rstrip() for x in text.splitlines()])
