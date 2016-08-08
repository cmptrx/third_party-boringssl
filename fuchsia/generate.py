#! /usr/bin/python

# Copyright 2016 The Fuchsia Authors. All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
#
#    * Redistributions of source code must retain the above copyright
# notice, this list of conditions and the following disclaimer.
#    * Redistributions in binary form must reproduce the above
# copyright notice, this list of conditions and the following disclaimer
# in the documentation and/or other materials provided with the
# distribution.
#    * Neither the name of Google Inc. nor the names of its
# contributors may be used to endorse or promote products derived from
# this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
# THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

"""Creates GN build files for Fuchsia/BoringSSL.

This module generates a number of build files not found in 'vanilla' BoringSSL
that are needed to compile, link, and package the command line bssl tool and the
BoringSSL unit tests, as well as provide the GN targets for libcrypto and libssl
for use by other Fuchsia packages.
"""

from collections import OrderedDict
import json
import os
import re
import subprocess
import sys

SCRIPT_DIR = os.path.abspath(os.path.dirname(__file__))
BSSL_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, os.pardir))
FUCHSIA_ROOT = os.path.abspath(os.path.join(BSSL_DIR, os.pardir, os.pardir))

# Enum for types of files that can be located with find_files().
SOURCE, HEADER, UNIT_TEST, TEST_SOURCE  = range(4)


def find_files(start, file_set, skip = None):
  """Locates files under a directory.

  Walks a directory tree and accumulates files that match a given FileSet.  A
  subdirectory named 'test' is always skipped; files from such a directory can
  only by returned by starting with it as the root of the directory tree.

  Args:
    start: The start of directory tree to recursively search.
    file_set: A type of file to locate. See FileSet for values.

  Returns:
    A list of paths to matching files, relative to BSSL_DIR.
  """
  exts_re = re.compile(r'\.h$' if file_set is HEADER else
                       r'\.c$|\.cc$')
  test_re = re.compile(r'_test|^example_')
  files = []
  for (path, dirnames, filenames) in os.walk(os.path.join(BSSL_DIR, start)):
    dirnames[:] = [dirname for dirname in dirnames if dirname != 'test']
    for filename in filenames:
      if exts_re.search(filename) is None:
        continue
      if not start.endswith('test') and (test_re.search(filename) is not None) != (file_set is UNIT_TEST):
        continue
      pathname = os.path.relpath(os.path.join(path, filename), BSSL_DIR)
      if skip and pathname in skip:
        continue
      if pathname in files:
        continue
      files.append(pathname)
  return files


class FuchsiaBuilder(object):
  """FuchsiaBuilder generates test related GN build files.

  FuchsiaBuilder outputs GN build files for Fuchsia/BoringSSL consistent with
  the current source tree and with 'util/all_test.json'
  """

  def __init__(self):
    self._test_names = []
    self._data_files = []


  def generate_code(self, workdir, stem):
    """Generates source files.

    Iterates through the list of generated source files and invokes a generator
    for each.
    """
    cwd = os.path.join(BSSL_DIR, workdir)
    out = os.path.join(cwd, '%s.c' % stem)
    gen = os.path.join(cwd, '%s_generate.go' % stem)
    with open(out, 'w') as c:
      subprocess.check_call(['go', 'run', gen], cwd=cwd, stdout=c)
    print 'Generated //' + os.path.relpath(out, FUCHSIA_ROOT)


  def generate_test_spec(self):
    """Parses tests from a JSON file.

    Reads a JSON file and records test names, test data files, and other
    arguments for the available unit tests in BoringSSL.  The JSON file should
    contain a list of lists, where each of those lists has between 1 and 3
    elements.
    """
    test_spec = os.path.join('fuchsia', 'test.spec')
    self._data_files.append(test_spec)
    all_tests = os.path.join(BSSL_DIR, 'util', 'all_tests.json')
    test_spec = os.path.join(BSSL_DIR, test_spec)
    with open(all_tests, 'r') as tests:
      with open(test_spec, 'w') as out:
        for test in json.load(tests):
          if test[0].startswith('decrepit/'):
            continue
          test_name = os.path.basename(test[0])
          out.write('/boot/test/boringssl/%s' % test_name)
          if test_name not in self._test_names:
            self._test_names.append(test_name)
          if len(test) == 3:
            out.write(' ' + test[1])
          if len(test) > 1:
            out.write(' /boot/test/boringssl/data/%s' % os.path.basename(test[-1]))
            self._data_files.append(test[-1])
          out.write('\n')
    print 'Generated //' + os.path.relpath(test_spec, FUCHSIA_ROOT)


  def generate_gn(self):
    """Generate the GN build file for Fuchsia/BoringSSL.

    Takes a template and examines it for places to insert list of files as
    specified by the config, and writes out the resulting GN file.

    Args:
      config: Path to a GN template file.
      output: Path to the GN file to output.
    """
    generate_re = re.compile(r'(\s*)#\s*GENERATE\s*(\w+)')
    todo_re = re.compile(r'\s*#\s*TODO')
    build_template = os.path.join(BSSL_DIR, 'fuchsia', 'BUILD_template.gn')
    build_gn = os.path.join(BSSL_DIR, 'BUILD.gn')
    file_path = os.path.relpath(__file__, BSSL_DIR)
    with open(build_template, 'r') as template:
      with open(build_gn, 'w') as out:
        for line in template:
          if re.search(todo_re, line):
            continue
          match = re.search(generate_re, line)
          if not match:
            out.write(line)
            continue
          what = match.group(2)
          if what == 'comment':
            out.write('# This file was generated by %s.' % file_path)
            out.write(' Do not edit manually.\n')
          elif what == 'boringssl_sources':
            self._generate_sources(out, [ 'crypto', 'ssl' ])
          elif what == 'bssl_sources':
            self._generate_sources(out, [ 'tool' ])
          elif what == 'test_support_sources':
            self._generate_sources(out, [ 'crypto/test' ], [ 'crypto/test', 'ssl/test' ])
          elif what == 'unit_tests':
            self._generate_tests(out, [ 'crypto', 'ssl' ])
          else:
            print 'Failed to parse GN template, unknown reference "%s"' % (what)
    print 'Generated //' + os.path.relpath(build_gn, FUCHSIA_ROOT)


  def generate_module(self):
    """Generates a module file that can be passed to '//packages/gn/gen.py'.

    Creates a JSON file that can be consumed by '//packages/gn/gen.py' to
    produce module build files for Ninja.  This JSON file maps GN targets within
    //third_party/boringssl to files to be included in the extra bootfs that can
    be passed when booting magenta.

    Args:
      output: Path to the GN file to output.
    """
    output = os.path.join(FUCHSIA_ROOT, 'packages', 'gn', 'boringssl')
    # Gather labels.
    labels = []
    labels.append('//third_party/boringssl:bssl')
    labels.append('//third_party/boringssl:boringssl_tests')
    # Gather binaries.
    binaries = []
    binaries.append({'binary': 'bssl', 'bootfs_path': 'bin/bssl'})
    for name in self._test_names:
      binaries.append({'binary': name, 'bootfs_path': 'test/boringssl/' + name})
    # Gather resources.
    resources = []
    path = os.path.relpath(BSSL_DIR, FUCHSIA_ROOT)
    for file in self._data_files:
      resources.append(
          {'file': '%s/%s' % (path, file),
           'bootfs_path': 'test/boringssl/data/%s' % os.path.basename(file)})
    # Output JSON module file.
    odict = OrderedDict()
    odict['labels'] = labels
    odict['binaries'] = binaries
    odict['resources'] = resources
    with open(output, 'w') as out:
      json.dump(odict, out, indent=4, separators=(',', ': '))
      out.write('\n')
    print 'Generated //' + os.path.relpath(output, FUCHSIA_ROOT)

  def _generate_sources(self, out, paths, headers = None):
    """Generates a source list and writes it out to the GN file.

    Reads lists of directories for each of the file set types except UNIT_TEST
    and calls find_files to build a list of files to insert into the GN file
    being generated.

    Args:
      out: The GN file being generated.
      what: The name of the config item to generate sources for.
    """
    files = []
    for path in paths:
      files += find_files(path, SOURCE)
    if headers:
      for path in headers:
        files += find_files(path, HEADER)
    for file in sorted(files):
      out.write('    "%s",\n' % file)


  def _generate_tests(self, out, paths):
    tests = {}
    for path in paths:
      for test in find_files(path, UNIT_TEST):
        name = os.path.splitext(os.path.basename(test))[0]
        if name not in self._test_names:
          print 'Warning: %s does not have a corresponding JSON element.' % name
        tests[name] = test
    names = OrderedDict(sorted(tests.items()))
    for name, test in names.items():
        out.write('unit_test("%s") {\n' % name)
        out.write('  sources = [ "%s" ]\n' % test)
        out.write('}\n\n')
    out.write('group("boringssl_tests") {\n')
    out.write('  testonly = true\n')
    out.write('  deps = [\n')
    for name, test in names.items():
      out.write('    ":%s",\n' % name)
    out.write('  ]\n}\n')


def main():
  """Creates GN build files for Fuchsia/BoringSSL.

  This is the main method of this module, and invokes each of the other
  'generate' and 'write' methods to create the build files needed to compile,
  link, and package the command line bssl tool and the BoringSSL unit tests.

  Returns:
    An integer indicating success (zero) or failure (non-zero).
  """
  fb = FuchsiaBuilder()
  fb.generate_code(os.path.join('crypto', 'err'), 'err_data')
  fb.generate_test_spec()
  fb.generate_gn()
  fb.generate_module()
  print '\nAll BoringSSL/Fuchsia build files generated.'
  return 0


if __name__ == '__main__':
  sys.exit(main())
