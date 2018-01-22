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
from common import ff, sf, gen_report, read_report
from validators import client_check, connection_check
from check_drivers import check_drivers

VERSION = "v1.0.1"

VERSION_HISTORY = """
    v1.0.0 -- Initial version
    v1.0.1 -- Additional multipath.conf checks, Check IDs, tool versioning
    v1.0.2 -- Added report reading and file output
"""


CONFIG = {"mgmt_ip": "1.1.1.1",
          "vip1_ip": "10.0.1.1",
          "vip2_ip": "10.0.2.1",
          "username": "admin",
          "password": "password",
          "cinder-volume": {
              "version": "2.7.2",
              "location": None}}

GEN_CONFIG_FILE = "ddct.json"
DEFAULT_CONFIG_FILE = ".ddct.json"


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


def main(args):
    if args.version:
        print("Datera Deployment Check Tool (DDCT) version: ", VERSION)
        sys.exit(0)
    common.VERBOSE = args.verbose
    common.WARNINGS = not args.disable_warnings
    if not common.tabulate:
        print("Please install requirements listed in requirements.txt")
        sys.exit(1)
    # Generate or load config file
    if args.generate_config_file:
        generate_config_file()
        return 0
    elif args.config_file:
        if not os.path.exists(args.config_file):
            raise EnvironmentError(
                "Config file {} not found".format(args.config_file))
        with io.open(args.config_file, "r") as f:
            config = json.load(f)
    elif os.path.exists(DEFAULT_CONFIG_FILE):
        with io.open(DEFAULT_CONFIG_FILE, "r") as f:
            config = json.load(f)
    else:
        print("No config file found.\nMust either have a {} file in current "
              "directory or manually specify config file via '-c' flag. "
              "\nA sample config file can be generated with the '-g' flag."
              "".format(
                  DEFAULT_CONFIG_FILE))
        return ff("CONFIG", "Missing config file")

    sf("CONFIG")

    if args.in_report:
        print(read_report(args.in_report).generate())
        sys.exit(0)

    client_check(config)
    connection_check(config)
    if not args.no_drivers:
        check_drivers(config)
    gen_report(outfile=args.out, quiet=args.quiet)


if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument("-g", "--generate-config-file", action="store_true",
                        help="Generate config file example")
    parser.add_argument("-c", "--config-file",
                        help="Config file location")
    parser.add_argument("-n", "--no-drivers", action="store_true",
                        help="Disable driver checks")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Enables verbose output")
    parser.add_argument("-w", "--disable-warnings", action="store_true",
                        help="Disables showing warnings in output")
    parser.add_argument("-o", "--out", help="Output file.  Will still print "
                                            "to stdout unless -q option is "
                                            "provided")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="No output to stdout")
    parser.add_argument("-i", "--in-report", help="Report file location to "
                                                  "read in")
    parser.add_argument("--version", action="store_true",
                        help="Print DDCT version")
    args = parser.parse_args()
    sys.exit(main(args))
