import csv
import git
import math
import os
import re
import repo_manifest as rm
import sys
import time

import gerrit.get_rawdata as gerrit

DATE_FORMAT = '%Y/%m/%d %H:%M:%S'
FILE_TYPE = ".*(Makefile|\.(java|jav|aidl|c|cpp|cc|h|hpp|mk|))$"

def filter_files(pattern, files):
    out = {}
    for name in files:
        if re.match(pattern, name):
            out[name] = files[name]
    return out


class ManifestSha1Comparator(object):
    def __init__(self, lmani, rmani):
        F1 = open(lmani)
        F2 = open(rmani)
        M1 = rm.RepoXmlManifest(''.join(F1.readlines()))
        M2 = rm.RepoXmlManifest(''.join(F2.readlines()))
        C = rm.ManifestComparator(M1, M2)
        self.common_changed_more = {}

        for project in C.common_changed:
            path = M1.projects[project][u'path']
            lrev = M1.projects[project][u'revision']
            rrev = M2.projects[project][u'revision']
            self.common_changed_more[project] = {u'path': path,
                                                 u'lrev': lrev, u'rrev': rrev}

    def csv_report(self):
        filename = "test.csv"
        with open(filename, 'w') as fp:
            a = csv.writer(fp)
            a.writerow(('project', 'path', 'lrev', 'rrev'))
            for project in self.common_changed_more:
                info = self.common_changed_more[project]
                path = info[u'path']
                lrev = info[u'lrev']
                rrev = info[u'rrev']
                row = (project, path, lrev, rrev)
                a.writerow(row)

class RepoCommits(object):
    def __init__(self, common_changed_more, repo_path="."):
        self.commits = {}
        notfound = 0
        for project in common_changed_more.keys():
            path = common_changed_more[project]['path']
            lrev = common_changed_more[project]['lrev']
            rrev = common_changed_more[project]['rrev']
            try:
                G = git.Repo(os.path.join(repo_path, path))
                self.commits[project] = list(G.iter_commits(lrev + ".." + rrev))
            except git.exc.NoSuchPathError:
                notfound += 1
                pass
        print "%d/%d projects found in %s/" % (len(self.commits), len(common_changed_more),
                                               repo_path)

    def count_commits(self):
        l = 0
        for project in self.commits:
            l += len(self.commits[project])
        return l

    def count_git_changes(self):
        l = 0
        for project in self.git_changes:
            l += len(self.git_changes[project])
        return l


    def init_gerrit_changes(self, exclude_merge=True, include_domain="sony"):
        self.gerrit_changes = []
        for project in self.commits:
            for c in self.commits[project]:
                try:
                    is_merge = len(c.parents) is 2
                    if is_merge and exclude_merge:
                        continue
                    else:
                        hexsha = c.hexsha
                        domain = re.sub(pattern="^.*@",
                                        repl="", string=c.author.email)
                        if include_domain in domain:
                            self.gerrit_changes.append(hexsha)
                except LookupError:
                    print "Warning: Encoding issue"
                    pass

    def get_gerrit_changes(self, nmax=75):
        n = len(self.gerrit_changes)  # n = d*nmax+r
        d = n / nmax
        r = n % nmax
        C = None
        i_end = 0
        for i in range(d):
            i_start = i * nmax
            i_end = (i + 1) * nmax
            B = gerrit.Base(numbers=self.gerrit_changes[i_start:i_end],
                            dst="result-gerrit")
            if C:
                C.merge(gerrit.Changes(B))
            else:
                C = gerrit.Changes(B)
            print i_start, i_end
        if r is not 0:
            i_start = i_end
            i_end = i_end + r
            B = gerrit.Base(numbers=self.gerrit_changes[i_start:i_end],
                            dst="result-gerrit")
            if C:
                C.merge(gerrit.Changes(B))
            else:
                C = gerrit.Changes(B)
        self.Changes = C
        print "Total: %d" % n
        print "Found: %d" % len(self.Changes.data)

    def init_git_changes(self, exclude_merge=True, filetype=FILE_TYPE):
        self.git_changes = {}
        progress = 0
        num_merge = 0
        for project in self.commits:
            self.git_changes[project] = []
            for c in self.commits[project]:
                progress += 1
                print "%d, %s (%s) " % (progress, c.hexsha[0:7], project)
                try:
                    is_merge = len(c.parents) is 2
                    num_merge += is_merge
                    filtered_files = filter_files(filetype, c.stats.files)
                    if is_merge and exclude_merge:
                        continue
                    nol = 0
                    nof = 0
                    ent = 0.0 # Shannon entropy

                    for f in filtered_files:
                        nol += filtered_files[f]['lines']
                        nof += 1
                    for f in filtered_files:  # Entropy calculation
                        p = 1.0 * filtered_files[f]['lines'] / nol
                        ent += -1.0 * p * math.log(p, 2)
                    if ent != 0.0:
                        ent = ent / math.log(nof, 2)  # Normalization
                    N = len(filtered_files)
                    self.git_changes[project].append(
                                        {'hexsha': c.hexsha,
                                        'merge': is_merge,
                                        'author': c.author.email,
                                        'authored_date': c.authored_date,
                                        'committer': c.committer.email,
                                        'committed_date': c.committed_date,
                                        'files': nof,
                                        'lines': nol,
                                        'entropy': ent,
                                        'message': c.message
                                        })
                except LookupError:
                    print "Warning: Encoding issue"
                    pass
            if len(self.git_changes[project]) is 0:
                del self.git_changes[project]
        print "Total: %d" % progress
        print "Merge: %d" % num_merge

    def measure_git(self, filename="test.csv"):
        with open(filename, 'w') as fp:
            a = csv.writer(fp)
            a.writerow(('project', 'hexsha', 'merge', 'author', 'authored_date',
                        'committer', 'committed_date', 'files', 'lines',
                        'entropy', 'message'))
            for project in self.git_changes:
                for c in self.git_changes[project]:
                    ad = time.strftime(DATE_FORMAT,
                                       time.gmtime(c['authored_date']))
                    cd = time.strftime(DATE_FORMAT,
                                       time.gmtime(c['committed_date']))
                    message = unicode(c['message']).encode("utf-8")
                    row = (project, c['hexsha'], c['merge'], c['author'], ad,
                           c['committer'], cd, c['files'], c['lines'],
                           c['entropy'], message)
                    a.writerow(row)

    def init_git_files(self, exclude_merge=True, filetype=".*"):
        self.git_files = {}
        progress = 0
        num_merge = 0
        for project in self.commits:
            self.git_files[project] = []
            for c in self.commits[project]:
                progress += 1
                print "%d, %s (%s) " % (progress, c.hexsha[0:7], project)
                try:
                    is_merge = len(c.parents) is 2
                    num_merge += is_merge
                    filtered_files = filter_files(filetype, c.stats.files)
                    if is_merge and exclude_merge:
                        continue

                    for f in filtered_files:
                        deletions = filtered_files[f]['deletions']
                        insertions = filtered_files[f]['insertions']
                        lines = filtered_files[f]['lines']
                        self.git_files[project].append(
                                        {'hexsha': c.hexsha,
                                         'file': f,
                                         'deletions': deletions,
                                         'lines': lines,
                                         'insertions': insertions
                                        })
                except LookupError:
                    print "Warning: Encoding issue"
                    pass
        print "Total: %d" % progress
        print "Merge: %d" % num_merge

    def measure_files(self, filename="test.csv"):
        with open(filename, 'w') as fp:
            a = csv.writer(fp)
            a.writerow(('hexsha', 'file', 'lines', 'insertions', 'deletions'))
            for project in self.git_files:
                for f in self.git_files[project]:
                    row = (f['hexsha'], f['file'], f['lines'],
                           f['insertions'], f['deletions'])
                    a.writerow(row)


    def summarize_git_changes(self):
        self.git_summary = {}
        for project in self.git_changes:
            noc = len(self.git_changes[project])  # commit
            authors = []
            nol = 0
            nof = 0
            for c in self.git_changes[project]:
                nol += c['lines']
                nof += c['files']
                authors.append(c['author'])
            noa = len(set(authors))
            self.git_summary[project] = {'noc': noc, 'nof': nof,
                                         'nol': nol, 'noa': noa}
    def print_summary(self):
        for project in self.git_summary:
            print "===== %s =====" % project
            print self.git_summary[project]