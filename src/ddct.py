#!/usr/bin/env python

from __future__ import (print_function, unicode_literals, division,
                        absolute_import)
"""
Datera Deployment Check Tool
"""

import argparse
import io
import json
import os
import sys


import common
from common import ff, gen_report, read_report, check
from common import check_plugin_table, fix_plugin_table, install_plugin_table
from checkers import load_checks, print_tags
from fixers import run_fixes, print_fixes
from installers import run_installers

try:
    from dfs_sdk import get_api
except ImportError:
    get_api = None


VERSION = "v2.0.0"

VERSION_HISTORY = """
    v1.0.0 -- Initial version
    v1.0.1 -- Additional multipath.conf checks, Check IDs, tool versioning
    v1.0.2 -- Added report reading and file output
    v1.1.0 -- Adding support for running fixes based on report codes
    v1.2.0 -- Adding plugin support, moving cinder-volume to plugins
    v1.3.0 -- Created "check" decorator and changing wf/ff function signatures
    v1.4.0 -- Changed ddct.py to ddct
    v1.5.0 -- Adding tagging support for checks
    v1.5.1 -- Added simple UDEV and ISCSI checks
    v1.6.0 -- New installation method, moved ddct to ddct.py so ddct can be
              autogenerated
    v2.0.0 -- New argument parser with subparsers.  Added installer options
"""


CONFIG = {"mgmt_ip": "1.1.1.1",
          "vip1_ip": "10.0.1.1",
          "vip2_ip": "10.0.2.1",
          "username": "admin",
          "password": "password",
          "cluster_root_password": None,
          "cluster_root_keyfile": None}

GEN_CONFIG_FILE = "ddct.json"
# DEFAULT_CONFIG_FILE = ".ddct.json"


def get_config(args):
    config = check_config(args)
    if not config:
        print("No valid config found")
        sys.exit(1)
    config['api'] = get_api(
        config['mgmt_ip'], config['username'], config['password'], "v2.2")
    return config


def generate_config_file():
    print("Generating example config file: {}".format(GEN_CONFIG_FILE))
    with io.open(GEN_CONFIG_FILE, "w+") as f:
        try:
            json.dump(CONFIG, f, indent=4, sort_keys=True)
        except TypeError:
            # Python 2 compatibility
            f.write(json.dumps(CONFIG, indent=4, sort_keys=True).decode(
                'utf-8'))
        sys.exit(0)


@check("CONFIG")
def check_config(args):
    config = None
    if not os.path.exists(args.config_file):
        print("No config file found at {}. A sample config file can be "
              "generated with the '-g' flag.".format(args.config_file))
        return ff("Missing config file", "1909B3B0")
    try:
        with io.open(args.config_file, "r") as f:
            config = json.load(f)
    except json.decoder.JSONDecodeError as e:
        print(e)
        return ff("Invalid config file: {}".format(e), "55DCEF2D")
    return config


def version(args):
    if args.history:
        print(VERSION_HISTORY)
    print("Datera Deployment Check Tool (DDCT) version: ", VERSION)


def none(args):
    return


def checker(args):
    # Global flags
    common.VERBOSE = args.verbose
    common.WARNINGS = not args.disable_warnings

    if args.list_plugins:
        check_plugin_table()
        sys.exit(0)

    config = get_config(args)
    if args.print_tags:
        print_tags(config, plugins=args.use_plugins)
        sys.exit(0)

    if not args.quiet:
        print("Plugins: {}\n".format(", ".join(args.use_plugins)),
              "Tags: {}\n".format(", ".join(args.tags)),
              "Not Tags: {}\n".format(", ".join(args.not_tags)), sep='')
    load_checks(config, plugins=args.use_plugins, tags=args.tags,
                not_tags=args.not_tags)
    gen_report(outfile=args.out, quiet=args.quiet)


def fixer(args):
    # Global flags
    common.VERBOSE = args.verbose

    if args.print:
        print_fixes(args.use_plugins)
        sys.exit(0)

    if args.list_plugins:
        fix_plugin_table()
        sys.exit(0)

    report = None
    if args.in_report:
        report = read_report(args.in_report)

    codes = args.codes
    if report and not codes:
        codes = report.code_list()

    if not codes:
        print("No codes or report provided, not sure which fixes to run")
        sys.exit(1)

    config = get_config(args)
    run_fixes(codes, config, plugins=args.use_plugins)


def installer(args):
    # Global flags
    common.VERBOSE = args.verbose

    if args.list_plugins:
        install_plugin_table()
        sys.exit(0)

    if not args.use_plugins:
        print("At least one plugin must be specified via '-u'")
        sys.exit(1)

    config = get_config(args)
    run_installers(config, args.use_plugins)


if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument("-g", "--generate-config-file", action="store_true",
                        help="Generate config file example")

    kargs = parser.parse_known_args()[0]
    if kargs.generate_config_file:
        generate_config_file()
        sys.exit(0)

    subparsers = parser.add_subparsers(
            title="Subcommands")

    version_parser = subparsers.add_parser("version", help="Show version")
    version_parser.set_defaults(func=version)

    check_parser = subparsers.add_parser("check", help="Run checks")
    check_parser.set_defaults(func=checker)

    fix_parser = subparsers.add_parser("fix", help="Run fixes")
    fix_parser.set_defaults(func=fixer)

    install_parser = subparsers.add_parser("install", help="Install drivers")
    install_parser.set_defaults(func=installer)

    # Version parser arguments
    version_parser.add_argument("--history", action="store_true",
                                help="Show version history")

    # Common arguments
    for p in [check_parser, fix_parser, install_parser]:
        p.add_argument("config_file", help="Config file location")
        p.add_argument("-g", "--generate-config-file", action="store_true",
                       help="Generate config file example")
        p.add_argument("-v", "--verbose", action="store_true",
                       help="Enables verbose output")
        p.add_argument("-o", "--out", help="Output file.Will still print to "
                                           "stdout unless -q option is "
                                           "provided")
        p.add_argument("-q", "--quiet", action="store_true",
                       help="No output to stdout")
        p.add_argument("-u", "--use-plugins", nargs="*", default=[],
                       help="Accepts a space separated list of plugins")
        p.add_argument("-l", "--list-plugins", action="store_true",
                       help="List available plugins")

    # Check Parser Arguments
    check_parser.add_argument("-w", "--disable-warnings", action="store_true",
                              help="Disables showing warnings in output")
    check_parser.add_argument("-t", "--tags", nargs="*", default=[],
                              help="Accepts a space separated list of tags.  "
                              "These tags are used to select checks matching "
                              "the tag")
    check_parser.add_argument("-n", "--not-tags", nargs="*", default=[],
                              help="Accepts as space separated list of tags.  "
                                   "These tags are used to deselect checks "
                                   "matching the tag, this takes precedence "
                                   "over '--tags'")
    check_parser.add_argument("-b", "--print-tags", action="store_true",
                              help="Print available tags.  Only prints tags "
                                   "for plugins loaded with '-u' as well as "
                                   "generally available tags")

    # Fix Parser Arguments
    fix_parser.add_argument("-i", "--in-report", help="Report file location "
                                                      "to read in")
    fix_parser.add_argument("-d", "--codes", nargs="*", default=[],
                            help="Used for specifying codes manually")
    fix_parser.add_argument("-p", "--print", action="store_true",
                            help="Print out the tool's currently supported "
                                 "fixes and codes")

    # Install Parser Arguments
    pass

    args = parser.parse_args()

    if not get_api:
        print("Please install requirements listed in requirements.txt")
        sys.exit(1)

    if not hasattr(args, 'func'):
        args.func = none
    args.func(args)
