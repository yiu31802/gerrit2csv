import csv
import git
import os
import re
import repo_manifest as rm

FILE_JAVA = ".*\.(java|jav|aidl)$"
FILE_MAKE = ".*(Makefile|\.mk)$"
FILE_CPP = ".*\.(c|cpp|cc|h|hpp)$"
FILE_ANDROIDXML = ".*AndroidManifest\.xml$"

def file_len(fname):
    with open(fname) as f:
        for i, l in enumerate(f):
            pass
    try:
        return i + 1
    except UnboundLocalError:
        return 0

class RepoSnapshots(object):
    def __init__(self, manifest, repo_path="."):
        F = open(manifest)
        M = rm.RepoXmlManifest(''.join(F.readlines()))
        self.Repo = {}
        notfound = 0
        for project in M.projects:
            rev = M.projects[project]['revision']
            project_path = M.projects[project]['path']
            path = os.path.join(repo_path, project_path)
            if os.path.exists(path):
                self.Repo[project] = {}
                self.Repo[project]['Git'] = git.Git(path)
                self.Repo[project]['path'] = path
                self.Repo[project]['revision'] = rev
            else:
                notfound += 1
        print "%d/%d projects found in %s/" % (len(self.Repo), len(M.projects), repo_path)

    def checkout(self):
        for project in self.Repo:
            rev = self.Repo[project]['revision']
            self.Repo[project]['Git'].checkout(rev)

    def measure_files(self, exclude_dir=".git", filename="test.csv"):
        with open(filename, 'w') as fp:
            a = csv.writer(fp)
            a.writerow(('project', 'rev', 'n_java', 'n_make', 'n_cpp',
			'n_androidxml', 'l_java', 'l_make', 'l_cpp'))
            for project in self.Repo:
                path = self.Repo[project]['path']
                n_java = 0
                n_make = 0
                n_cpp = 0
                n_androidxml = 0
                l_java = 0
                l_make = 0
                l_cpp = 0
                for r,d,files in os.walk(path):
                    for f in files:
                        if not exclude_dir in r:
                            if re.match(FILE_JAVA, f):
                                n_java += 1
                                l_java += file_len(os.path.join(r, f))
                            elif re.match(FILE_MAKE, f):
                                n_make += 1
                                l_make += file_len(os.path.join(r, f))
                            elif re.match(FILE_CPP, f):
                                n_cpp += 1
                                l_cpp += file_len(os.path.join(r, f))
                            elif re.match(FILE_ANDROIDXML, f):
                                n_androidxml += 1
                rev = self.Repo[project]['revision'][0:7]
                row = (project, rev, n_java, n_make, n_cpp, n_androidxml,
                       l_java, l_make, l_cpp)
                a.writerow(row)
