#!/bin/bash
# Build script for rocky-snapshot-manager RPM

set -e

VERSION=1.0
NAME=rocky-snapshot-manager

# Create rpmbuild directories
mkdir -p ~/rpmbuild/{BUILD,RPMS,SOURCES,SPECS,SRPMS}

# Copy spec file
cp ${NAME}.spec ~/rpmbuild/SPECS/

# Create source tarball with proper directory structure
mkdir -p tmp/${NAME}-${VERSION}
cp snapshot_manager.py README.md LICENSE tmp/${NAME}-${VERSION}/
tar -czf ~/rpmbuild/SOURCES/${NAME}-${VERSION}.tar.gz -C tmp ${NAME}-${VERSION}
rm -rf tmp

# Build the RPM
rpmbuild -ba ~/rpmbuild/SPECS/${NAME}.spec

echo "RPM built successfully. Check ~/rpmbuild/RPMS/noarch/ for the package."