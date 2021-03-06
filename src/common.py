from __future__ import (print_function, unicode_literals, division,
                        absolute_import)

import functools
import glob
import importlib
import inspect
import io
import json
import os
import re
import subprocess
import socket
import textwrap
try:
    from StringIO import StringIO
except ImportError:
    from io import StringIO

from contextlib import contextmanager

try:
    from dfs_sdk import scaffold, ApiError
    import distro
    import ipaddress
    import paramiko
    import requests
    from tabulate import tabulate
except ImportError:
    distro = None
    ipaddress = None
    tabulate = None
    paramiko = None
    scaffold = None

# Python 2/3 compatibility
try:
    str = unicode
except NameError:
    pass

DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(DIR, "assets")
TAG_RE = re.compile(r"\d+\.\d+\.\d+")
UUID4_STR_RE = re.compile(r"[a-f0-9]{8}-?[a-f0-9]{4}-?4[a-f0-9]{3}-?[89ab]"
                          r"[a-f0-9]{3}-?[a-f0-9]{12}")

INVISIBLE = re.compile(r"\x1b\[\d+[;\d]*m|\x1b\[\d*\;\d*\;\d*m")
TMP_DIR = '/tmp/.ddct/'
FIXES_FILE = os.path.join(TMP_DIR, 'fixes_run')

UBUNTU = "ubuntu"
DEBIAN = "debian"
CENTOS = "centos"
CENTOS7 = "centos7"
CENTOS6 = "centos6"
RHEL = "rhel"

APT = "apt"
YUM = "yum"

SUPPORTED_OS_TYPES = {UBUNTU, DEBIAN, CENTOS7, CENTOS6, RHEL}


def get_config():
    api = scaffold.get_api(strict=False)
    config = scaffold.get_config()
    config['api'] = api
    access_paths = api.system.network.access_vip.get()['network_paths']
    config['vip1_ip'] = access_paths[0]['ip']
    if len(access_paths) > 1:
        config['vip2_ip'] = access_paths[1]['ip']
    return config


def get_latest_driver_version(tag_url):
    found = []
    weighted_found = []
    tags = requests.get(tag_url).json()
    for tag in tags:
        tag = tag['name'].strip("v")
        if TAG_RE.match(tag):
            found.append(tag)
    for f in found:
        # Major, minor, patch
        try:
            # Version format: M.m.p
            M, m, p = f.split(".")
            value = int(M) * 10000 + int(m) * 100 + int(p)
        except ValueError:
            # Date format: YYYY.M.d.n
            Y, M, d, n = f.split(".")
            value = int(Y) * 1000000 + int(M) * 10000 + int(d) * 100 + int(n)
        weighted_found.append((value, "v" + f))
    return sorted(weighted_found)[-1][1]


def apply_color(value_for_coloring=None, color=None):
    suffix = "\x1b[0m"
    if color == "red":
        prefix = "\x1b[31m"
    elif color == "green":
        prefix = "\x1b[32m"
    elif color == "yellow":
        prefix = "\x1b[33m"
    elif color == "cyan":
        prefix = "\x1b[36m"
    elif color == "magenta":
        prefix = "\x1b[35m"
    return "{}{}{}".format(prefix, value_for_coloring, suffix)


def strip_invisible(s):
    return re.sub(INVISIBLE, "", s)


PLUGIN_LOC = os.path.join(os.path.dirname(__file__), "plugins")
VERBOSE = False
WARNINGS = True
WRAPTXT = True


SUCCESS = apply_color("Success", color="green")
FAILURE = apply_color("FAIL", color="red")
WARNING = apply_color("WARN", color="yellow")
# FIX = apply_color("FIX {}", color="cyan")
FIX = "FIX {}"
# ISSUE = apply_color("ISSUE {}", color="magenta")
ISSUE = "ISSUE {}"


CHECK_RE = re.compile(r".*check_(.*)\.py")
CHECK_GLOB = "check_*.py"

FIX_RE = re.compile(r".*fix_(.*)\.py")
FIX_GLOB = "fix_*.py"

INSTALL_RE = re.compile(r".*install_(.*)\.py")
INSTALL_GLOB = "install_*.py"

IP_ROUTE_RE = re.compile(
    r"^(?P<net>[\w|\.|:|/]+).*dev\s(?P<iface>[\w|\.|:]+).*?$")


def _wraptxt(txt, fill):
    if WRAPTXT:
        return textwrap.fill(txt, fill)
    return txt


class Report(object):

    def __init__(self):
        self.hostname = None
        self.success = []
        self.warning = {}
        self.warning_id = {}
        self.warning_by_id = {}
        self.fix_by_id = {}
        self.failure = {}
        self.failure_id = {}
        self.failure_by_id = {}
        self.tags = {}
        self.host_state = {}

    @staticmethod
    def format_fix(fix, uid):
        # return "{}: {}".format(FIX, apply_color(fix, "magenta"))
        return "{}: {}".format(FIX, fix).format(uid)

    @staticmethod
    def format_issue(issue, uid):
        return "{}: {}".format(ISSUE, issue).format(uid)

    def add_success(self, name, tags):
        if name not in self.failure and name not in self.warning:
            self.success.append(name)
            if name not in tags:
                self.tags[name] = set()
            for tag in tags:
                self.tags[name].add(tag)

    def add_warning(self, name, reason, uid, tags, fix=None):
        reason = self.format_issue(reason, uid)
        if WARNINGS:
            if name not in self.warning:
                self.warning[name] = []
                self.warning_id[name] = []
            self.warning[name].append(reason)
            self.warning_id[name].append(uid)
            self.warning_by_id[uid] = (name, reason)
            if fix:
                self.fix_by_id[uid] = self.format_fix(fix, uid)
            if name not in tags:
                self.tags[name] = set()
            for tag in tags:
                self.tags[name].add(tag)

    def add_failure(self, name, reason, uid, tags, fix=None):
        reason = self.format_issue(reason, uid)
        if name not in self.failure:
            self.failure[name] = []
            self.failure_id[name] = []
        self.failure[name].append(reason)
        self.failure_id[name].append(uid)
        self.failure_by_id[uid] = (name, reason)
        if fix:
            self.fix_by_id[uid] = self.format_fix(fix, uid)
        if name not in tags:
            self.tags[name] = set()
        for tag in tags:
            self.tags[name].add(tag)

    def add_host_state(self, key, value):
        if not self.hostname:
            self.hostname = socket.gethostname()
        if "hostname" in self.host_state:
            self.host_state = self.hostname
        self.host_state[key] = value

    def generate(self):
        if not self.hostname:
            self.hostname = socket.gethostname()
        # try:
        #     longest = max(map(
        #         lambda x: len(x),
        #         [val for sublist in
        #             list(self.failure.values()) + list(self.warning.values())
        #             for val in sublist]))
        # except ValueError:
        #     longest = 30
        wrap = 60
        s = list(map(lambda x: (
            x,
            SUCCESS,
            "",
            "",
            "\n".join(sorted(self.tags[x]))),
            sorted(self.success)))

        w = []
        for name, wids in sorted(self.warning_id.items()):
            warnings = []
            for wid in wids:
                warnings.append(self.warning_by_id[wid][1])
                fix = self.fix_by_id.get(wid)
                if fix:
                    warnings.append(fix)
            for index, warning in enumerate(warnings):
                warnings[index] = _wraptxt(warning, wrap) + "\n"
            w.append([name,
                      WARNING,
                      "\n".join(warnings),
                      "\n".join(sorted(self.tags[name]))])
        f = []
        for name, fids in sorted(self.failure_id.items()):
            failures = []
            for fid in fids:
                failures.append(self.failure_by_id[fid][1])
                fix = self.fix_by_id.get(fid)
                if fix:
                    failures.append(fix)
            for index, failure in enumerate(failures):
                failures[index] = _wraptxt(failure, wrap)
            f.append([name,
                      FAILURE,
                      "\n".join(failures),
                      "\n".join(sorted(self.tags[name]))])

        r1 = tabulate(
            f + w + s,
            headers=["Test", "Status", "Reasons", "Tags"],
            tablefmt="grid")

        if self.host_state:
            s = []
            for k, v in self.host_state.items():
                if type(v) == dict:
                    acc1 = []
                    for a, b in sorted(v.items()):
                        if type(b) == dict:
                            acc2 = []
                            for c, d in sorted(b.items()):
                                acc2.append("  {}: {}".format(c, d))
                            b = "\n".join(acc2)
                            acc1.append("{}:\n{}".format(a, b))
                        else:
                            acc1.append("{}: {}".format(a, b))
                    v = "\n".join(acc1)
                s.append((k, v))
            r2 = tabulate(
                sorted(s),
                headers=["State", "Value"],
                tablefmt="grid")
            result = "\n".join(("HOST: {}".format(self.hostname), r1, r2))
        else:
            result = r1
        return result

    def gen_json(self):
        if not self.hostname:
            self.hostname = socket.gethostname()
        return {"host": self.hostname,
                "success": self.success,
                "warnings": self.warning_by_id,
                "failures": self.failure_by_id,
                "tags": {k: list(v) for k, v in self.tags.items()},
                "host_state": self.host_state}

    def code_list(self):
        result = []
        if WARNINGS:
            result.extend(self.warning_by_id.keys())
        result.extend(self.failure_by_id.keys())
        print(result)
        return result


report = Report()
fixes_run = set()


def reset_checks():
    global report
    report = Report()


def idempotent(fix):
    @functools.wraps(fix)
    def _wrapper():
        if fix.__name__ in fixes_run:
            return
        fix()
        fixes_run.add(fix.__name__)

    return _wrapper


def load_run_fixes():
    with io.open(FIXES_FILE, 'r') as f:
        for fix in json.loads(f.read()):
            fixes_run.add(fix)


def save_run_fixes():
    j = json.dumps(list(fixes_run))
    with io.open(FIXES_FILE, 'w+') as f:
        f.write(j)


def check(test_name, *tags):
    """
    Decorator to be used for checks that automatically calls sf() at the
    end of the check.

    NOTE: This should always be the outermost decorator due to
          non-kosher behavior that *should* make our lives easier

    Usage:
        @check("Test Name")
        def my_tests():
            if not some_condition:
                ff("We failed!")


    Which is equivalent to:
        def my_tests():
            name = "Test Name"
            if not some_condition:
                ff(name, "We Failed!")
            sf(name)
    """
    def _outer(func):
        @functools.wraps(func)
        def _inner_check_func(*args, **kwargs):
            tname = test_name  # noqa
            ttags = tags  # noqa
            result = func(*args, **kwargs)
            sf()
            return result
        _inner_check_func._tags = tags
        return _inner_check_func
    return _outer


def load_plugins(regex, globx):
    found = {}
    RE = re.compile(regex)
    path = glob.glob(os.path.join(PLUGIN_LOC, globx))
    for file in path:
        name = RE.match(file).groups(1)[0]
        mod = importlib.import_module("plugins." + os.path.basename(file)[:-3])
        found[name] = mod
    return found


def check_load():
    return load_plugins(CHECK_RE, CHECK_GLOB)


def fix_load():
    return load_plugins(FIX_RE, FIX_GLOB)


def install_load():
    return load_plugins(INSTALL_RE, INSTALL_GLOB)


def check_plugin_table():
    checks = map(lambda x: [x], check_load())
    print(tabulate(checks, headers=["Check Plugins"], tablefmt="grid"))


def fix_plugin_table():
    fixes = map(lambda x: [x], fix_load())
    print(tabulate(fixes, headers=["Fix Plugins"], tablefmt="grid"))


def install_plugin_table():
    installs = map(lambda x: [x], install_load())
    print(tabulate(installs, headers=["Install Plugins"], tablefmt="grid"))


def parse_mconf(data):

    def _helper(lines):
        result = []
        for line in lines:
            line = line.strip()
            line = line.split()
            if not line or len(line) < 1 or line[0].startswith("#"):
                continue
            elif line[-1] == "{":
                result.append([line[0], _helper(lines)])
                continue
            elif line[-1] == "}":
                break
            result.append([line[0], " ".join(line[1:]).strip("\"'")])
        return result

    return _helper(iter(data.splitlines()))


def get_pkg_manager():
    if exe_check("which apt-get > /dev/null 2>&1", err=False):
        return APT
    if exe_check("which yum > /dev/null 2>&1", err=False):
        return YUM


def get_os():
    did = distro.id()
    if did == CENTOS:
        version = distro.version()
        if version.startswith("7"):
            return CENTOS7
        elif version.startswith("6"):
            return CENTOS6
    return did


def _lookup_vars():
    name = None
    for frame in inspect.stack():
        if frame[3] == "_inner_check_func":
            name = frame[0].f_locals['test_name']
            tags = frame[0].f_locals['tags']
            break
    if not name:
        raise ValueError("Couldn't find test_name in frame stack")
    return name, tags


# Success Func
def sf():
    name, tags = _lookup_vars()
    report.add_success(name, tags)


# Fail Func
def ff(reasons, uid, fix=None):
    name, tags = _lookup_vars()
    if type(reasons) not in (list, tuple):
        report.add_failure(name, reasons, uid, tags, fix=fix)
        return
    report.add_failure(name, "\n".join(reasons), uid, tags, fix=fix)


# Warn Func
def wf(reasons, uid, fix=None):
    name, tags = _lookup_vars()
    if type(reasons) not in (list, tuple):
        report.add_warning(name, reasons, uid, tags, fix=fix)
        return
    report.add_warning(name, "\n".join(reasons), uid, tags, fix=fix)


def hs(k, v):
    report.add_host_state(k, v)


def gen_report(outfile=None, quiet=False, ojson=False, push_data=False):

    def _writer(results, out):
        try:
            with io.open(out, 'w+') as f:
                f.write(results)
                f.write("\n")
        except TypeError:
            out.write(results)
            out.write("\n")

    if ojson:
        results = report.gen_json()
    else:
        results = report.generate()

    if push_data:
        print("Pushing results to cluster")
        config = get_config()
        api = config['api']
        s = StringIO()
        _writer(json.dumps(report.gen_json(), indent=4), s)
        s.seek(0)
        files = {'file': ('ddct-results.txt', s)}
        try:
            api.logs_upload.upload(files=files, ecosystem='python-sdk')
        except ApiError:
            api.logs_upload.upload(files=files, ecosystem='openstack')
        print("Results uploaded successfully")
    if outfile:
        _writer(results, outfile)
    if ojson and not quiet:
        print(json.dumps(results, indent=4))
    elif not quiet:
        print(results)


def read_report(infile):
    in_report = Report()
    with io.open(infile, 'r') as f:
        header_skip = True
        prevr = None
        prevt = None
        for line in f:
            if "|" not in line:
                continue
            elif header_skip:
                header_skip = False
                continue
            test, result, reason, uid, tags = list(
                map(lambda x: x.strip(), line.split("|")))[1:-1]
            print(test, result, reason, uid, tags, sep=", ")
            if result == "":
                result = prevr
                test = prevt
            if result == FAILURE:
                in_report.add_failure(test, reason, uid, tags.split())
            elif result == WARNING:
                in_report.add_warning(test, reason, uid, tags.split())
            elif result == SUCCESS:
                in_report.add_success(test, tags.split())
            prevr = result
            prevt = test
    return in_report


def vprint(*args, **kwargs):
    if VERBOSE:
        print(*args, **kwargs)


@contextmanager
def verbose():
    global VERBOSE
    old = VERBOSE
    VERBOSE = True
    try:
        yield
    finally:
        VERBOSE = old


def exe(cmd):
    vprint("Running cmd:", cmd)
    return subprocess.check_output(cmd, shell=True).decode("utf-8")


def exe_check(cmd, err=False):
    try:
        vprint(exe(cmd))
        if err:
            return False
        return True
    except subprocess.CalledProcessError:
        if not err:
            return False
        return True


def cluster_cmd(cmd, config, fail_ok=False):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(
        paramiko.AutoAddPolicy())
    if config.get('cluster_root_keyfile'):
        ssh.connect(hostname=config['mgmt_ip'],
                    username='root',
                    banner_timeout=60,
                    pkey=config.get('cluster_root_keyfile'))
    elif config.get('cluster_root_password'):
        ssh.connect(hostname=config['mgmt_ip'],
                    username='root',
                    password=config.get('cluster_root_password'),
                    banner_timeout=60)
    else:
        raise ValueError("Missing cluster_root_keyfile or "
                         "cluster_root_password for this test")
    msg = "Executing command: {} on Cluster".format(cmd)
    vprint(msg)
    _, stdout, stderr = ssh.exec_command(cmd)
    exit_status = stdout.channel.recv_exit_status()
    result = None
    if int(exit_status) == 0:
        result = stdout.read()
    elif fail_ok:
        result = stderr.read()
    else:
        raise EnvironmentError(
            "Nonzero return code: {} stderr: {}".format(
                exit_status,
                stderr.read()))
    return result


def is_l3(config):
    api = config['api']
    return api.system.get()['l3_enabled']


def parse_route_table():
    results = []
    data = exe("ip route show")
    for line in data.splitlines():
        match = IP_ROUTE_RE.match(line)
        if match:
            try:
                net = ipaddress.ip_network(str(match.group("net")))
            except ValueError:
                continue
            results.append((net, match.group("iface")))
    return results
