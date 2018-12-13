# -*- mode: python; coding: utf-8 -*-
#
# Copyright (C) 2015 <contact@redhat.com>
#
# Author: Loic Dachary <loic@dachary.org>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see `<http://www.gnu.org/licenses/>`.
#
import argparse
import git
import gitdb
import hashlib
import json
import logging
import os
import re
import requests
import six
from six.moves.urllib import parse
import subprocess
import time
import shutil

DESCRIPTION_MAX = 1024

logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s')

log = logging.getLogger(__name__)


class GitHub2GitLab(object):
    TAG_MERGED = ":MERGED:"

    STATE_EVENT2MERGE_STATE = {
        'merge': 'merged',
        'reopen': 'opened',
        'close': 'closed',
    }

    def __init__(self, args):
        self.args = args

        self.args.ssh_public_key = os.path.expanduser(
            self.args.ssh_public_key
        )

        if not self.args.gitlab_repo:
            self.args.gitlab_repo = self.args.github_repo
        (self.args.gitlab_namespace,
         self.args.gitlab_name) = self.args.gitlab_repo.split('/')
        self.args.gitlab_repo = parse.quote_plus(self.args.gitlab_repo)

        self.github = {
            'url': "https://api.github.com",
            'git': "https://github.com",
            'repo': self.args.github_repo,
            'token': self.args.github_token,
        }
        if self.args.branches:
            self.github['branches'] = self.args.branches.split(',')
        self.gitlab = {
            'git': self.args.gitlab_url.replace('http://', 'git@'),
            'host': self.args.gitlab_url,
            'name': self.args.gitlab_name,
            'namespace': self.args.gitlab_namespace,
            'url': self.args.gitlab_url + "/api/v4",
            'repo': self.args.gitlab_repo,
            'token': self.args.gitlab_token,
        }

        if self.args.verbose:
            level = logging.DEBUG
        else:
            level = logging.INFO

        logging.getLogger('github2gitlab').setLevel(level)

        self.tmpdir = "/tmp"

    @staticmethod
    def get_parser():
        parser = argparse.ArgumentParser(
            description="migrate projects from GitHub to GitLab")

        parser.add_argument('--gitlab-url',
                            help='Gitlab url',
                            required=True)
        parser.add_argument('--gitlab-token',
                            help='Gitlab authentication token',
                            required=True)
        parser.add_argument('--gitlab-repo',
                            help='Gitlab repo (for instance ceph/ceph)')
        parser.add_argument('--github-token',
                            help='GitHub authentication token')
        parser.add_argument('--github-repo',
                            help='GitHub repo (for instance ceph/ceph)',
                            required=True)
        parser.add_argument('--ssh-public-key',
                            default='~/.ssh/id_rsa.pub',
                            help='SSH public key')
        parser.add_argument('--branches',
                            help=('comma separated list of git branches '
                                  'to mirror (defaults to all)'))
        parser.add_argument('--ignore-closed', action='store_const',
                            const=True,
                            help='ignore pull requests closed and not merged')
        parser.add_argument('--skip-pull-requests', action='store_const',
                            const=True,
                            help='do not mirror PR to MR')
        parser.add_argument('--verbose', action='store_const',
                            const=True,
                            help='enable verbose (debug) logging')
        parser.add_argument('--cache', action='store_const',
                            const=True,
                            help='cache GitHub pull requests list')
        parser.add_argument('--clean', action='store_const',
                            const=True,
                            help='Remove the repo after sync')
        return parser

    @staticmethod
    def factory(argv):
        return GitHub2GitLab(GitHub2GitLab.get_parser().parse_args(argv))

    def run(self):
        self.add_key()
        if self.add_project():
            self.unprotect_branches()
        self.git_mirror()
        if not self.args.skip_pull_requests:
            self.pull_requests = self.get_pull_requests()
            self.merge_requests = self.get_merge_requests()
            self.update_merge_pull()
            self.sync()
        if self.args.clean:
            self.clean()
        return 0

    def sh(self, command):
        log.debug(":sh: " + command)
        proc = subprocess.Popen(
            args=command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            shell=True,
            bufsize=1)
        lines = []
        with proc.stdout:
            for line in iter(proc.stdout.readline, b''):
                line = line.decode('utf-8')
                lines.append(line)
                log.debug(str(line.strip()))
        if proc.wait() != 0:
            raise subprocess.CalledProcessError(
                returncode=proc.returncode,
                cmd=command
            )
        return "".join(lines)

    def gitlab_create_remote(self, repo):
        # when using access token, gitlab doesn't care the username
        url = self.gitlab['git'].replace(
            'https://', 'https://user:{}@'.format(self.gitlab['token']))
        repo.create_remote('gitlab',
                           url + ("/" if url.startswith('http') else ':') +
                           self.gitlab['namespace'] + "/" +
                           self.gitlab['name'] + ".git")

    def git_mirror(self):
        name = self.gitlab['name']
        if not os.path.exists(name):
            self.sh("git clone --bare " + self.github['git'] +
                    "/" + self.github['repo'] + " " + name)
        repo = git.Repo(name)
        os.chdir(name)
        if not hasattr(repo.remotes, 'gitlab'):
            self.gitlab_create_remote(repo)
        if 'branches' in self.github:
            branches_ref = " ".join([
                "+refs/heads/{b}:refs/heads/{b}".format(b=b)
                for b in self.github['branches']
            ])
        else:
            branches_ref = "+refs/heads/*:refs/heads/*"
        #
        # Fetch
        #
        self.sh("git fetch --force origin " +
                branches_ref +
                " +refs/tags/*:refs/tags/*")
        #
        # Track refs
        #
        if self.args.skip_pull_requests:
            self.git_mirror_optimize(repo)
        else:
            self.sh("git fetch origin +refs/pull/*:refs/heads/pull/*")
        #
        # Push
        #
        self.sh("git push --prune --force gitlab " +
                branches_ref + " " +
                "+refs/heads/pull/*:refs/heads/pull/* " +
                "+refs/tags/*:refs/tags/* ")
        os.chdir("..")
        self.revision2commit = {}

    def git_mirror_optimize(self, repo):
        self.sh("git fetch origin +refs/pull/*:refs/remotes/origin/pull/*")
        for head in repo.refs:
            pr = re.search('^origin/pull/(\d+)/head$', head.name)
            if not pr:
                continue
            pr = pr.group(1)
            merge_name = 'origin/pull/' + pr + '/merge'
            if merge_name not in repo.refs:
                log.debug(head.name + " cannot merge, ignore")
                continue
            merge = repo.commit(merge_name)
            if merge.parents[1] != head.commit:
                log.debug(head.name + " merge is obsolete, skip")
                continue
            known_head_name = 'pull/' + pr + '/head'
            try:
                known_head = repo.commit(known_head_name)
                if known_head == head.commit:
                    log.debug(head.name + " head has not moved, skip")
                    continue
                action = 'update'
            except gitdb.exc.BadName:
                action = 'create'
            log.debug(action + " ref " + known_head_name + "==" +
                      head.commit.hexsha)
            repo.git.update_ref('refs/' + known_head_name, head.commit)
            log.info(action + " branch " + 'pull/' + pr + "/merge == " +
                     merge.hexsha)
            repo.git.update_ref('refs/heads/pull/' + pr + '/merge', merge)

    def clean(self):
        log.info('Removing cloned repo...')
        shutil.rmtree(self.gitlab['name'])

    def add_key(self):
        "Add ssh key to gitlab if necessary"
        try:
            with open(self.args.ssh_public_key) as f:
                public_key = f.read().strip()
        except:
            log.debug("No key found in {}".format(self.args.ssh_public_key))
            return None
        g = self.gitlab
        url = g['url'] + "/user/keys"
        query = {'private_token': g['token']}
        keys = requests.get(url, params=query).json()
        log.debug("looking for '" + public_key + "' in " + str(keys))
        if (list(filter(lambda key: key['key'] == public_key, keys))):
            log.debug(self.args.ssh_public_key + " already exists")
            return None
        else:
            name = 'github2gitlab'
            log.info("add " + name + " ssh public key from " +
                     self.args.ssh_public_key)
            query['title'] = name
            query['key'] = public_key
            result = requests.post(url, query)
            if result.status_code != requests.codes.created:
                log.warn('Key {} already in GitLab. '
                         'Possible under a different user. Skipping...'
                         .format(self.args.ssh_public_key))
            return public_key

    def add_project(self):
        "Create project in gitlab if it does not exist"
        g = self.gitlab
        url = g['url'] + "/projects/" + g['repo']
        query = {'private_token': g['token']}
        if (requests.get(url, params=query).status_code == requests.codes.ok):
            log.debug("project " + url + " already exists")
            return None
        else:
            log.info("add project " + g['repo'])
            url = g['url'] + "/projects"
            query['public'] = 'true'
            query['namespace'] = g['namespace']
            query['name'] = g['name']
            result = requests.post(url, params=query)
            if result.status_code != requests.codes.created:
                raise ValueError(result.text)
            log.debug("project " + g['repo'] + " added: " +
                      result.text)
            return result.json()

    def unprotect_branches(self):
        "Unprotect branches of the GitLab project"
        g = self.gitlab
        url = g['url'] + "/projects/" + g['repo'] + "/repository/branches"
        query = {'private_token': g['token']}
        unprotected = 0
        r = requests.get(url, params=query)
        r.raise_for_status()
        for branch in r.json():
            if branch['protected']:
                r = requests.put(url + "/" + branch['name'] +
                                 "/unprotect", params=query)
                r.raise_for_status()
                unprotected += 1
        return unprotected

    def update_merge_pull(self):
        self.merge2pull = {}
        self.pull2merge = {}
        for (id, merge) in six.iteritems(self.merge_requests):
            pull = merge['source_branch'].split('/')
            if len(pull) == 3:
                number = pull[1]
                if number in self.pull_requests:
                    self.merge2pull[id] = self.pull_requests[number]
                    self.pull2merge[number] = self.merge_requests[id]

    @staticmethod
    def field_equal(pull, pull_field, pull_value,
                    merge, merge_field, merge_value):
        if pull_field == 'state':
            return ((pull_value == 'open' and
                     merge_value == 'opened') or
                    (pull_value == 'closed' and
                     merge_value in ('closed', 'merged')))
        if pull_field == 'body':
            if merge_value is None:
                merge_value = ''
            if pull_value is None:
                pull_value = ''
            merge_value = merge_value.replace(GitHub2GitLab.TAG_MERGED, '')
            return (pull_value[:DESCRIPTION_MAX] ==
                    merge_value[:DESCRIPTION_MAX])
        else:
            return pull_value == merge_value

    @staticmethod
    def field_update(pull, pull_field, pull_value,
                     merge, merge_field, merge_value):
        if pull_value is None:
            pull_value = ''
        if pull_field == 'state':
            if pull_value == 'open':
                value = 'reopen'
            elif pull_value == 'closed':
                if pull.get('merged_at'):
                    value = 'merge'
                else:
                    value = 'close'
            return ('state_event', value)
        elif pull_field == 'body':
            return (merge_field, pull_value[:DESCRIPTION_MAX])
        else:
            return (merge_field, pull_value)

    def sync(self):
        pull_f2merge_f = {
            'state': 'state',
            'body': 'description',
            'title': 'title',
        }
        for number in sorted(self.pull_requests.keys()):
            pull = self.pull_requests[number]
            merge = None
            if number in self.pull2merge:
                merge = self.pull2merge[number]
            else:
                source_branch = 'pull/' + number + '/head'
                target_branch = pull['base']['ref']
                if (self.rev_parse(pull, source_branch) and
                        self.rev_parse(pull, target_branch)):
                    data = {'title': pull['title'],
                            'source_branch': source_branch,
                            'target_branch': target_branch}
                    if pull['body']:
                        data['description'] = pull['body'][:DESCRIPTION_MAX]
                    merge = self.create_merge_request(data)

            if merge:
                updates = {}
                for (pull_field, merge_field) in six.iteritems(pull_f2merge_f):
                    if not self.field_equal(pull,
                                            pull_field,
                                            pull[pull_field],
                                            merge,
                                            merge_field,
                                            merge[merge_field]):
                        (key, value) = self.field_update(pull,
                                                         pull_field,
                                                         pull[pull_field],
                                                         merge,
                                                         merge_field,
                                                         merge[merge_field])
                        updates[key] = value
                if updates:
                    self.update_merge_request(merge, updates)
                else:
                    log.debug("https://github.com/" +
                              self.github['repo'] + "/" +
                              "pull/" + number + " == " +
                              self.gitlab['host'] + "/" +
                              parse.unquote(self.gitlab['repo']) + "/" +
                              "merge_requests/" + str(merge['iid']))

    def rev_parse(self, pull, revision):
        if revision in self.revision2commit:
            return True
        else:
            repo = git.Repo(self.gitlab['name'])
            try:
                repo.rev_parse("heads/" + revision)
                return True
            except gitdb.exc.BadName:
                log.debug("ignore https://github.com/" +
                          self.github['repo'] + "/pull/" +
                          str(pull['number']) + " because " +
                          revision + " is not a known revision")
                return False

    @staticmethod
    def json_loads(payload):
        "Log the payload that cannot be parsed"
        try:
            return json.loads(payload)
        except ValueError as e:
            log.error("unable to json.loads(" + payload + ")")
            raise e

    def get(self, url, query, cache):
        payloads_file = (self.tmpdir + "/" +
                         hashlib.sha1(url.encode('utf-8')).hexdigest() +
                         ".json")
        if (not cache or not os.access(payloads_file, 0) or
                time.time() - os.stat(payloads_file).st_mtime > 24 * 60 * 60):
            payloads = []
            next_query = query
            while next_query:
                log.debug(str(next_query))
                result = requests.get(url, params=next_query)
                payloads += result.json()
                next_query = None
                for link in result.headers.get('Link', '').split(','):
                    if 'rel="next"' in link:
                        m = re.search('<(.*)>', link)
                        if m:
                            parsed_url = parse.urlparse(m.group(1))
                            # append query in case it was not preserved
                            # (gitlab has that problem)
                            next_query = query
                            next_query.update(
                                dict(parse.parse_qsl(parsed_url.query))
                            )
            if cache:
                with open(payloads_file, 'w') as f:
                    json.dump(payloads, f)
        else:
            with open(payloads_file, 'r') as f:
                payloads = json.load(f)
        return payloads

    def get_pull_requests(self):
        "https://developer.github.com/v3/pulls/#list-pull-requests"
        g = self.github
        query = {'state': 'all'}
        if self.args.github_token:
            query['access_token'] = g['token']

        def f(pull):
            if self.args.ignore_closed:
                return (pull['state'] == 'opened' or
                        (pull['state'] == 'closed' and pull['merged_at']))
            else:
                return True
        pulls = filter(f,
                       self.get(g['url'] + "/repos/" + g['repo'] + "/pulls",
                                query, self.args.cache))
        return dict([(str(pull['number']), pull) for pull in pulls])

    def get_merge_requests(self):
        "http://doc.gitlab.com/ce/api/merge_requests.html"
        g = self.gitlab
        merges = self.get(g['url'] + "/projects/" +
                          g['repo'] + "/merge_requests",
                          {'private_token': g['token'],
                           'state': 'all'}, cache=False)
        return dict([(str(merge['id']), merge) for merge in merges])

    def create_merge_request(self, query):
        g = self.gitlab
        query['private_token'] = g['token']
        url = g['url'] + "/projects/" + g['repo'] + "/merge_requests"
        log.info('create_merge_request: ' + str(query))
        result = requests.post(url, params=query)
        if result.status_code != requests.codes.created:
            raise ValueError(result.text)
        merge = result.json()
        log.debug('merge ' + str(merge))
        for (key, value) in six.iteritems(query):
            if key == 'private_token':
                continue
            if value.strip().replace('\n', '').replace('\r', '') != merge.get(key).strip().replace('\n', '').replace('\r', ''):
                raise ValueError(url + " " + key + " expected " +
                                 value + " but is " + merge.get(key, 'None'))
        return merge

    def update_merge_request(self, merge_request, updates):
        state_event = updates.pop('state_event', None)
        if len(updates) == 0 or (len(updates) == 1 and 'private_token' in updates):
            result = merge_request
        else:
            result = self.put_merge_request(merge_request, updates)
        if (state_event == 'merge' and
                result['state'] == 'opened'):
            description = result['description'] or ''
            updates = {
                'state_event': 'close',
                'description': description + self.TAG_MERGED,
            }
            result = self.put_merge_request(merge_request, updates)
        self.verify_merge_update(updates, result)
        return result

    def put_merge_request(self, merge_request, updates):
        g = self.gitlab
        updates['private_token'] = g['token']
        url = (g['url'] + "/projects/" + g['repo'] + "/merge_requests/" +
               str(merge_request['iid']))
        log.info('update_merge_request: ' + url + ' <= ' + str(updates))
        return requests.put(url, params=updates).json()

    def verify_merge_update(self, updates, result):
        g = self.gitlab
        for (key, value) in six.iteritems(updates):
            if key == 'private_token':
                continue
            if key == 'state_event':
                key = 'state'
                value = self.STATE_EVENT2MERGE_STATE[updates['state_event']]
            result_value = result.get(key) or ''
            if value.strip() != result_value.strip():
                url = (g['host'] + "/" + parse.unquote(g['repo']) + "/" +
                       "merge_requests/" + str(result['iid']))
                raise ValueError("{url}: {key} value expected to be {value}"
                                 " but is {result}".format(
                                     url=url,
                                     key=key,
                                     value=value,
                                     result=result_value))

# Local Variables:
# compile-command: "cd .. ; virtualenv/bin/tox -e flake8"
# End:
