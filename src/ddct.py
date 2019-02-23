#!/usr/bin/env python

from __future__ import (print_function, unicode_literals, division,
                        absolute_import)
"""
Datera Deployment Check Tool
"""

import argparse
import curses
import sys


import common
from common import gen_report, read_report, get_config
from common import check_plugin_table, fix_plugin_table, install_plugin_table
from checkers import run_checks, print_tags
from daemon import daemon
from fixers import run_fixes, print_fixes
from installers import run_installers

try:
    from state import get_host_state
except ImportError:
    print("Not able to import from state.py, --host-state will not be "
          "available")
    get_host_state = None

try:
    from dfs_sdk import scaffold
except ImportError:
    scaffold = None


VERSION = "v2.3.0"

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
    v2.1.0 -- Added glance checking plugin
    v2.2.0 -- Moving from ddct.json config file to universal datera config
              file.  Disabled fix/install since they're not ready yet
              --generate-config-file removed in favor of --gen-config in
              scaffold
    v2.3.0 -- Added k8s_csi_iscsi installer plugin and fixed support for
              plugin-based installers
"""


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
    common.WRAPTXT = not args.no_wrap

    if args.list_plugins:
        check_plugin_table()
        sys.exit(0)

    config = get_config()

    print("Using CONFIG:")
    scaffold.print_config()

    if args.print_tags:
        print_tags(config, plugins=args.use_plugins)
        sys.exit(0)

    if args.no_local:
        args.not_tags.append("local")
    if not args.quiet:
        print("Plugins: {}\n".format(", ".join(args.use_plugins)),
              "Tags: {}\n".format(", ".join(args.tags)),
              "Not Tags: {}\n".format(", ".join(args.not_tags)), sep='')
    if args.daemon:
        curses.wrapper(daemon, config, args)
    else:
        run_checks(config, plugins=args.use_plugins, tags=args.tags,
                   not_tags=args.not_tags)
        if args.host_state:
            get_host_state(config)
        gen_report(outfile=args.out,
                   quiet=args.quiet,
                   ojson=args.json,
                   push_data=args.push_data)


def fixer(args):
    # Global flags
    common.VERBOSE = args.verbose

    if args.print_codes:
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

    config = get_config()
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

    config = get_config()
    run_installers(config, args.use_plugins)


if __name__ == "__main__":

    top_parser = scaffold.get_argparser(add_help=False)
    kargs, rem = top_parser.parse_known_args()

    parser = argparse.ArgumentParser(parents=[top_parser])

    subparsers = parser.add_subparsers(help="Subcommands")

    version_parser = subparsers.add_parser("version", help="Show version",
                                           parents=[top_parser])
    version_parser.set_defaults(func=version)

    check_parser = subparsers.add_parser("check", help="Run checks",
                                         parents=[top_parser])
    check_parser.set_defaults(func=checker)

    # fix_parser = subparsers.add_parser("fix", help="Run fixes")
    # fix_parser.set_defaults(func=fixer)

    install_parser = subparsers.add_parser("install", help="Install things")
    install_parser.set_defaults(func=installer)

    # Version parser arguments
    version_parser.add_argument("--history", action="store_true",
                                help="Show version history")

    # Common arguments
    for p in [check_parser, install_parser]:
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
    check_parser.add_argument("-j", "--json", action="store_true",
                              help="Output json")
    check_parser.add_argument("-s", "--no-wrap", action="store_true",
                              help="Disable text wrapping in report output")
    check_parser.add_argument("-a", "--no-local", action="store_true",
                              help="Disable local checks.  This is useful for "
                                   "plugins that access resources remotely "
                                   "and the local client is not under test")
    check_parser.add_argument("-d", "--daemon", action="store_true",
                              help="Run selected checks as a daemon.  Checks "
                                   "will be run at intervals specified by -i, "
                                   "--interval")
    check_parser.add_argument("-i", "--interval", type=float, default=60 * 5,
                              help="Interval in seconds that checks should "
                                   "be run in daemon mode.")
    check_parser.add_argument("-p", "--push-data", action="store_true",
                              help="Push report data to cluster for inclusion "
                                   "in callhome")
    check_parser.add_argument("-k", "--host-state", action="store_true",
                              help="Enable host-state output during check")
    # # Fix Parser Arguments
    # fix_parser.add_argument("-i", "--in-report", help="Report file location "
    #                                                   "to read in")
    # fix_parser.add_argument("-d", "--codes", nargs="*", default=[],
    #                         help="Used for specifying codes manually")
    # fix_parser.add_argument("-p", "--print-codes", action="store_true",
    #                         help="Print out the tool's currently supported "
    #                              "fixes and codes")

    # Install Parser Arguments
    pass

    args = parser.parse_args()

    if not scaffold:
        print("Please install requirements listed in requirements.txt")
        sys.exit(1)

    if not hasattr(args, 'func'):
        args.func = none
    args.func(args)
