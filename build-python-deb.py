#!/usr/bin/env python

import sys
import glob
import subprocess
import re

# sorry for ugly code :(

def main():
    processed_packages = set()
    packages_to_process = set()
    packages_to_process.add(sys.argv[1])

    while len(packages_to_process) > 0:
        print "%i to go %i processed" % (len(packages_to_process), len(processed_packages))

        package = packages_to_process.pop()
        print "processing '%s'" % (package)

        processed_packages.add(package)
        subprocess.call(["fpm", "-s", "python", "-f", "-t", "deb", package])

        files = glob.glob("python-%s_*.deb" % (package))

        if (len(files) != 1):
            print "Something wrong, we have several files %s" % (files)
            continue

        files = files[0]
        depends = subprocess.Popen(["dpkg", "-f", files, "Depends"], stdout=subprocess.PIPE).stdout.read()
        if depends:
            chunks = re.split(',\s+', depends)
            for chunk in chunks:
                parent_package = re.split('\s+', chunk, 1)[0]
                m = re.match(r'^python-(.*?)$', parent_package)
                if m is not None and m.group(1) not in processed_packages:
                    packages_to_process.add(m.group(1))

        # NOTE use this crutch to avoid version conflicts
        subprocess.call(["fpm", "--no-depends", "-s", "python", "-f", "-t", "deb", package])


if __name__ == '__main__':
    main()
