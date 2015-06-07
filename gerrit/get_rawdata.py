""" Get data from Gerrit and export it to CSV."""

from datetime import datetime
from pygerrit.rest import auth
from pygerrit import rest
from requests.exceptions import HTTPError
import re
import csv
import os

SOMCGR = "http://review.sonyericsson.net"
REVMSG_ABANDONED = "Abandoned"
REVMSG_MERGED = "Change has been successfully merged into the git repository."
REVMSG_PUSHED = "Change has been successfully pushed."
REVMSG_UPDATE_MSG = "Patch Set %d: Commit message was updated"
REVMSG_REBASED = "Patch Set %d: Patch Set %d was rebased"
REVMSG_REVERTED = "Reverted\n\nThis patchset was reverted in change: "
REVMSG_UPLOADED = 'Uploaded patch set %d.'
COMMSG_CHERRY = "(cherry picked from commit "
COMMSG_REVERT = "This reverts commit "


def rm_slashes(string):
    """Replace "/" by "%2F" and return String."""
    return "%2F".join(string.split("/"))


def add_slashes(string):
    """Replace "%2F" by "/" and return String."""
    return "/".join(string.split("%2F"))

def rm_quotes(string):
    """Replace '"' by '``' and return String."""
    return re.sub(string=string, pattern='"', repl='``')


class Base(object):

    """Class to hold basic query input data."""

    def __init__(self, project=None, branch=None, numbers=None, \
                 dst=None, url=SOMCGR):
        if (numbers is not None and project is None and branch is None):
            pass
        elif (numbers is None and project is not None and branch is not None):
            pass
        else:
            raise Exception("Parameter combination is wrong.")
        self.project = project
        self.branch = branch
        self.numbers = numbers

        if dst is not None:
            self.dst = dst
        else:
            self.dst = "result-dir"

        try:
            os.makedirs(self.dst)
        except OSError:
            pass #raise Exception("Default path %s already exists." % project)
        self.a = auth.HTTPDigestAuthFromNetrc(url)
        self.req = rest.GerritRestAPI(url, verify=False, auth=self.a)


class Changes(object):

    """Class to encapsulate data collected from change endpoints."""

    def __init__(self, base, status=None, file_base = None):
        self.base = base
        self.status = status
        if file_base is None:
            file_base = datetime.now().strftime('%Y-%m%d-%H%M-%S')
        self.file_base = file_base
        if base.numbers is None:
            query = "changes/?q=project:%s+branch:%s" % (base.project, base.branch)
            if status is not None:
                query += "+status:%s" % status
        else:
            numbers = [str(x) for x in base.numbers]
            query = "changes/?q=%s" % ("+OR+".join(numbers))
        query += "&o=ALL_REVISIONS&o=ALL_COMMITS&o=ALL_FILES&o=MESSAGES"

	self.data = base.req.get(query)

    def merge(self, changes):
        """Merge another Changes instance."""
        if type(changes) != type(self):
            raise Exception("wrong input")
        self.data += changes.data

    def changes_csv(self):
        """Export Changes data in CSV."""
        filename = self.file_base + "-changes.csv"
        path = os.path.join(self.base.dst, filename)
        with open(path, 'w') as fp:
            a = csv.writer(fp)
            a.writerow(('number', 'change_id', 'current_revision',
                        'project', 'branch',
                        'num_patches', 'date_created',
                        'date_closed', 'closed_by', 'created_by',
                        'reverted_by'))
            for c in self.data:
                try:
                    current_revision = c['current_revision']
                except KeyError:
                    current_revision = c['revisions'].keys()[-1]
                details = c['revisions'][current_revision]
                closed_by = ''
                date_closed = ''
                reverted_by = ''
                review_messages = c['messages']
                for msg in review_messages:
                    if REVMSG_ABANDONED in msg['message']:
                        closed_by = 'abandoned'
                        date_closed = msg['date']
                        break
                    elif REVMSG_MERGED in msg['message']:
                        closed_by = 'merged'
                        date_closed = msg['date']
                        break
                    elif REVMSG_PUSHED in msg['message']:
                        closed_by = 'pushed'
                        date_closed = msg['date']
                        break

                for msg in review_messages:
                    if REVMSG_REVERTED in msg['message']:
                        revert_id = re.match('(.*)\n\n.*(I[a-f0-9]{40}$)',
                                            msg['message']).groups()[1]
                        reverted_by = revert_id
                        break

                created_by = ''
                commit_message = details['commit']['message']
                if COMMSG_CHERRY in commit_message:
                    created_by = 'cherry-pick'
                elif COMMSG_REVERT in commit_message:
                    created_by = 'revert'

                row = (c['_number'], c['change_id'], current_revision,
                       c['project'], c['branch'],
                       details['_number'], c['created'],
                       date_closed, closed_by, created_by,
                       reverted_by)
                try:
                    a.writerow(row)
                except UnicodeEncodeError: # e.g. 932240
                    pass

    def patchsets_csv(self):
        """Export Patch Sets data in CSV."""
        filename = self.file_base + "-patchsets.csv"
        path = os.path.join(self.base.dst, filename)
        with open(path, 'w') as fp:
            a = csv.writer(fp)
            a.writerow(('number', 'revision_number',
                        'revision', 'committer',
                        'date_commit', 'date_upload', 'message'))
            for c in self.data:
                number = c['_number']
                revisions = c['revisions'].keys()
                for revision in revisions:
                    p = c['revisions'][revision]
                    revision_number = p['_number']
                    details = p['commit']['committer']
                    committer = details['email']
                    date_commit = details['date']
                    message = rm_quotes(p['commit']['message'])
                    # In CSV, quotes '"' in `message` causes problems
                    message = unicode(message).encode("utf-8")
                    review_messages = c['messages']
                    date_upload = ''
                    for rmessage in review_messages:
                        if rmessage['message'] == \
                        REVMSG_UPLOADED % revision_number:
                            date_upload = rmessage['date']
                            break
                        if rmessage['message'] == \
                        REVMSG_UPDATE_MSG % revision_number:
                            date_upload = rmessage['date']
                            break
                        if rmessage['message'] == \
                        REVMSG_REBASED % (revision_number, revision_number - 1):
                            date_upload = rmessage['date']
                            break
                    row = (number, revision_number,
                                revision, committer,
                                date_commit, date_upload, message)
                    try:
                        a.writerow(row)
                    except UnicodeEncodeError: # e.g. 932240
                        pass

    def reviews_csv(self):
        """Export Review data in CSV."""
        filename = self.file_base + "-reviews.csv"
        path = os.path.join(self.base.dst, filename)
        with open(path, 'w') as fp:
            a = csv.writer(fp)
            a.writerow(('number', 'revision_number',
                        'reviewer', 'date',
                        'message'))
            for c in self.data:
                number = c['_number']
                reviews = c['messages']
                for review in reviews:
                    revision_number = review['_revision_number']
                    #TODO: Sometimes _revision_number does not exist like #125
                    if 'author' in review:
                        reviewer = review['author']['name']
                        reviewer = unicode(reviewer).encode("utf-8")
                    else:
                        reviewer = "Gerrit Code Review"
                    date = review['date']
                    message = rm_quotes(review['message'])
                    # In CSV, quotes '"' in `message` causes problems
                    try:
                        row = (number, revision_number,
                               reviewer, date,
                               message)
                        a.writerow(row)
                    except UnicodeEncodeError:
                        print reviewer

    def files_csv(self):
        """Export File data in CSV."""
        filename = self.file_base + "-files.csv"
        path = os.path.join(self.base.dst, filename)
        with open(path, 'w') as fp:
            a = csv.writer(fp)
            a.writerow(('number', 'revision_number',
                        'file', 'status',
                        'lines_add', 'lines_del'))
            for c in self.data:
                number = c['_number']
                revisions = c['revisions'].keys()
                for revision in revisions:
                    p = c['revisions'][revision]
                    revision_number = p['_number']
                    file_details = p['files']
                    file_names = file_details.keys()
                    for fname in file_names:
                        name = fname
                        detail = file_details[name]
                        lines_add = 0
                        lines_del = 0
                        status = ''
                        if 'lines_inserted' in detail:
                            lines_add = int(detail['lines_inserted'])
                        if 'lines_deleted' in detail:
                            lines_del = int(detail['lines_deleted'])
                        if 'status' in detail:
                            status = detail['status']
                        row = (number, revision_number,
                               name, status,
                               lines_add, lines_del)
                        try:
                            a.writerow(row)
                        except UnicodeEncodeError: # e.g. 932240
                            pass

class GerritAccessError(Exception):

    """Raise exception if something goes wrong."""
