#!/usr/bin/env python

import sys
import glob
import subprocess
import argparse
import re
import os

# sorry for ugly code :(

class BuildPackageExcpetion(RuntimeError):
    pass

class Package(object):

    @classmethod
    def get_version_from_filename(cls, filename):
        m = re.search('_(.*)\.deb', filename)
        if m is None:
            return None
        return m.group(1)

    def get_dpkg_info(self):
        if self.filename is None:
            return ''
        with open(os.devnull, "w") as fnull:
            return subprocess.Popen(["dpkg", "-f", self.filename], stdout=subprocess.PIPE, stderr=fnull).stdout.read()
        return ''


    def extract_requests_from_debian_depends(self):
        result = []

        depends = self.get_dpkg_info() 

        m = re.search('Depends: (.*?)\n', depends, re.S)
        if m is None:
            return result

        depends = m.group(1)

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
                m = re.search('^\s*\(.*?\s*(\d+(\.\d+)*)(-\d+)?\s*\)\s*$', version)
                if m is None:
                    if version is not None and version != '':
                        self.broken_dependency_number = True
                    version = None
                else:
                    version = m.group(1)
            result.append(Package(package, version))
        return result

    def get_cached_version(self):
        output = subprocess.Popen(["apt-cache", "policy", self.name], stdout=subprocess.PIPE).stdout.read()
        m = re.search('Candidate:\s+(\d+(\.\d+)*)', output, re.S)
        if m is None:
            return None
        return m.group(1)

    def guess_version_from_filename(self):
        info = self.get_dpkg_info()
        m = re.search('Version: (.*?)\n', info, re.S)
        if m is None:
            return
        self.version = m.group(1)

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


    def __init__(self, name, version, filename=None, ignore=None, parents=None, broken=False):
        self.name = name
        self.filename = filename
        self.version = version
        self.ignore = ignore
        self.parents = parents
        self.broken = broken
        self.broken_dependency_number = False
        self.system_version = self.get_cached_version()
        self.exists_in_system = self.system_version is not None and self.compare_version(self.system_version, self.version) >= 0
        self.is_python = re.match(r'^python-(.*?)$', name) is not None 
        self.parents = []

    def __str__(self):
        if self.version is not None:
            return self.name + '_' + str(self.version)
        else:
            return self.name
        
    def fpm_build(self, dependencies=None):
        if not self.is_python:
            return

        args = ["fpm", "-s", "python", "-f", "-t", "deb"]

        if self.version is not None:
            args.append("-v")
            args.append(self.version)
        fpm_name = re.sub('^python-', '', self.name)

        if dependencies is not None:
            args.append('--no-auto-depends')
            for dep in dependencies:
                args.append('-d')
                if dep[1] is None:
                    args.append(dep[0])
                else:
                    args.append("%s >= %s" % (dep[0], dep[1]))

        args.append(fpm_name)

        with open(os.devnull, "w") as fnull:
            try:
                subprocess.check_output(args, stdout=subprocess.PIPE, stderr=fnull)
            except subprocess.CalledProcessError, e:
                raise BuildPackageExcpetion(e.otupt)
        return


def get_package_version(filename):
    m = re.search('_(.*)\.deb', filename)
    if m is None:
        return None
    return m.group(1)

def generate_packages_first_pass(package, args):
    result = {}
    to_go = {}
    to_go[package.name] = package

    while len(to_go) > 0:
        #print "%i to go %i processed" % (len(to_go), len(result))

        _, package = to_go.popitem()
        result[package.name] = package
        print "processing %s" % (str(package))

        if package.exists_in_system and not args.force_package_build_over_system:
            continue
        
        if not package.is_python:
            continue

        files = glob.glob("%s_*.deb" % (package.name))
        if len(files) == 0 or args.rebuild_existing_package:
            try:
                package.fpm_build()
            except BuildPackageExcpetion, e:
                print "\tFAIL\n\t%s" % (e.message)
                package.broken = True
                continue
            files = glob.glob("%s_*.deb" % (package.name))

        if (len(files) != 1):
            print "internal error: there should be only one '%s_*.deb' file" % (package.name)
            print "try to delete all *.deb files and restart script"
            sys.exit(1)

        package.filename = files[0]
        if package.version is None:
            package.guess_version_from_filename()

        parents = package.extract_requests_from_debian_depends()
        package.parents = parents
        for parent in parents:
            if parent.name in result and Package.compare_version(result[parent.name].version, parent.version) > 0:
                continue
            if parent.name in to_go and Package.compare_version(to_go[parent.name].version, parent.version) > 0:
                continue
            to_go[parent.name] = parent
    return result

def optimistic_fix_packages(packages):
    result = {} 
    totaly_broken_packages = set() 
    version_broken_packages = set() 
    for key, package in packages.iteritems():
        if not package.broken:
            continue
        if package.system_version is not None:
            print "%s has version problems, remove it's version from dependencies" % (str(package))
            version_broken_packages.add(package.name)
        else:
            print "%s failed to build, remove it from dependencies completely" % (str(package))
            totaly_broken_packages.add(package.name)

    if len(totaly_broken_packages) + len(version_broken_packages) == 0:
        return

    # ok we have some broken packages in dependencies, so let's remove them
    for key, package in packages.iteritems():
        dependencies = []
        need_rebuild = False


        if package.broken:
            continue

        if package.broken_dependency_number:
            need_rebuild = True

        for parent in package.parents:
            if parent.name in totaly_broken_packages:
                need_rebuild = True
                continue
            if parent.name in version_broken_packages:
                need_rebuild = True
                dependencies.append([parent.name, parent.system_version])
            else:
                dependencies.append([parent.name, parent.version])

        if not need_rebuild:
            continue

        print "rebuilding %s" % (str(package))
        package.fpm_build(dependencies=dependencies)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--package', help='package name', required=True)
    parser.add_argument('--version', help='required package version', default=None, required=True)
    parser.add_argument('--force-package-build-over-system', action='store_true')
    parser.add_argument('--optimistic-ignore-broken-packages', action='store_true')
    parser.add_argument('--rebuild-existing-package', action='store_true')
    args = parser.parse_args()
    packages = generate_packages_first_pass(Package(args.package, args.version), args)
    if args.optimistic_ignore_broken_packages:
        optimistic_fix_packages(packages)

if __name__ == '__main__':
    main()
