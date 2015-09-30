#!/usr/bin/env python

import sys
import glob
import subprocess
import argparse
import re

# sorry for ugly code :(

class Package(object):

    @classmethod
    def get_version_from_filename(cls, filename):
        m = re.search('_(.*)\.deb', filename)
        if m is None:
            return None
        return m.group(1)

    @classmethod
    def extract_requests_from_debian_depends(cls, depends):
        result = []
        if depends is None:
            return result

        chunks = re.split(',\s+', depends)
        for chunk in chunks:
            package_and_version = re.split('\s+', chunk, 1)
            package = package_and_version[0]
            if package.rstrip() == '':
                continue
            version = None
            if len(package_and_version) > 1: 
                version = package_and_version[1]
                version = version.rstrip()
                m = re.search('^\s*\(.*?\s*(\d+(\.\d+)*)\s*\)\s*$', version)
                if m is None:
                    version = None
                else:
                    version = m.group(1)
            result.append(Package(package, version))
        return result

    @classmethod
    def compare_version(cls, x, y):
        if x is None and y is None:
            return 0
        if x is None:
            return -1 
        if y is None:
            return 1

        xx = map(lambda z: int(z), x.split('.'))
        yy = map(lambda z: int(z), y.split('.'))
        for i in xrange(0, min(len(xx), len(yy))):
            if xx[i] > yy[i]:
                return 1
            if xx[i] < yy[i]:
                return -1 
        return 0


    def __init__(self, name, version, filename=None, ignore=None, parents=None):
        self.name = name
        self.filename = filename
        self.version = version
        self.ignore = ignore
        self.parents = parents
        self.is_python = re.match(r'^python-(.*?)$', name) is not None 

    def __str__(self):
        return self.name + '_' + str(self.version)
        
    def fpm_arguments(self):
        if not self.is_python:
            return ["echo", "not a python package"]

        result = ["fpm", "-s", "python", "-f", "-t", "deb"]
        if self.version is not None:
            result.append("-v")
            result.append(self.version)
        fpm_name = re.sub('^python-', '', self.name)
        result.append(fpm_name)
        return result

def get_package_version(filename):
    m = re.search('_(.*)\.deb', filename)
    if m is None:
        return None
    return m.group(1)

def generate_packages_first_pass(package, ignore):
    result = {}
    to_go = {}
    to_go[package.name] = package

    while len(to_go) > 0:
        print "%i to go %i processed" % (len(to_go), len(result))

        _, package = to_go.popitem()
        print "processing '%s'" % (str(package))
        
        if not package.is_python:
            continue

        subprocess.call(package.fpm_arguments())

        files = glob.glob("%s_*.deb" % (package.name))

        if (len(files) != 1):
            print "Something wrong, we have several files %s" % (files)
            continue

        package.filename = files[0]

        result[package.name] = package

        depends = subprocess.Popen(["dpkg", "-f", package.filename, "Depends"], stdout=subprocess.PIPE).stdout.read()
        parents = Package.extract_requests_from_debian_depends(depends)
        for parent in parents:
            if parent.name in ignore:
                continue
            if parent.name in result and Package.compare_version(result[parent.name].version, parent.version) > 0:
                continue
            if parent.name in to_go and Package.compare_version(to_go[parent.name].version, parent.version) > 0:
                continue
            to_go[parent.name] = parent
    print result
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--package', help='package name', required=True)
    parser.add_argument('--version', help='required package version', default=None, required=True)
    parser.add_argument('--ignore', help='ignore packages', type=str, nargs='*')
    args = parser.parse_args()
    packages = generate_packages_first_pass(Package(args.package, args.version, ignore=args.ignore), set(args.ignore or []))
    #subprocess.call(["fpm", "--no-depends", "-s", "python", "-f", "-t", "deb", package])

if __name__ == '__main__':
    main()
