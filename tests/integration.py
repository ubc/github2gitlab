#!/usr/bin/env python
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
from github2gitlab import main
import json
import logging
import os
import requests
import shutil
import sys
import tempfile

log = logging.getLogger('github2gitlab')


class Integration(object):

    def __init__(self, argv):
        self.g = main.GitHub2GitLab.factory(argv)
        self.remove_gitlab()
        d = tempfile.mkdtemp()
        try:
            os.chdir(d)
            self.reset_github()

            log.debug("---------- initial sync")
            self.create_pull_request()
            self.g.run()
            self.verify_create_pull_request()

            log.debug("---------- merged pull (not sync'ed when open, "
                      "sync'ed after it was merged)")
            number = self.create_pull_request_and_merge()
            self.g.run()
            self.verify_create_pull_request_and_merge(number)

            log.debug("---------- closed pull")
            self.close_pull_1()
            self.rebase_branches()
            self.modify_master()
            self.g = main.GitHub2GitLab.factory(argv +
                                                ['--branches=master,branch2'])
            self.g.run()
            self.verify_closed_pull()

            log.debug("---------- deleted branch")
            self.add_deleted_branch()
            self.g.run()
            self.verify_deleted_branch()

            log.debug("---------- merged pull (sync'ed when open, merged, "
                      "then sync'ed after merge)")
            self.merge_pull_4()
            self.g.run()
            self.verify_merge_pull()

        finally:
            shutil.rmtree(d)

    def create_pull_request(self):
        g = self.g.github
        url = g['url'] + "/repos/" + g['repo'] + "/pulls"
        query = {'access_token': g['token']}
        for i in (1, 2, 3, 4):
            data = {
                'title': u'title branch é {i}'.format(i=i),
                'head': 'branch' + str(i),
                'base': 'master',
                'body': u'body branch ëà {i}'.format(i=i),
            }
            r = requests.post(url, params=query, data=json.dumps(data))
            if r.status_code != 201:
                raise Exception(r.text)

    def rebase_branches(self):
        self.g.sh("""
git fetch origin
git commit -m "rebased branch1" --amend
git push --force origin master:branch1
git checkout branch2
git rebase origin/master
git push --force origin branch2
git checkout master
        """)

    def modify_master(self):
        self.g.sh("""
git fetch origin
git reset --hard origin/master
echo "# changed" >> README.md
git commit -m "add to master" README.md
git push origin master
        """)

    def verify_create_pull_request(self):
        g = self.g.gitlab
        merges = self.g.get(g['url'] + "/projects/" + g['repo'] +
                            "/merge_requests",
                            {'private_token': g['token'],
                             'state': 'open'},
                            cache=False)
        log.debug("merges " + str(merges))
        assert len(merges) == 4
        for merge in merges:
            assert 'pull/' in merge['source_branch']

    def create_pull_request_and_merge(self):
        g = self.g.github
        url = g['url'] + "/repos/" + g['repo'] + "/pulls"
        query = {'access_token': g['token']}
        i = 6
        data = {
            'title': u'title branch é {i}'.format(i=i),
            'head': 'branch' + str(i),
            'base': 'master',
            'body': u'body branch ëà {i}'.format(i=i),
        }
        r = requests.post(url, params=query, data=json.dumps(data))
        if r.status_code != 201:
            raise Exception(r.text)
        pull = r.json()
        number = str(pull['number'])
        url = g['url'] + "/repos/" + g['repo'] + "/pulls/" + number + "/merge"
        data = {'commit_message': 'COMMIT MESSAGE'}
        r = requests.put(url, params=query, data=json.dumps(data))
        log.debug("merge output for PR " + str(number) + ": " + r.text)
        r.raise_for_status()
        return number

    def verify_create_pull_request_and_merge(self, number):
        g = self.g.gitlab
        merges = self.g.get(g['url'] + "/projects/" + g['repo'] +
                            "/merge_requests",
                            {'private_token': g['token'],
                             'state': 'open'},
                            cache=False)
        log.debug("merges " + str(merges))
        merge = filter(lambda merge: (merge['source_branch'] == 'pull/' +
                                      number + '/head'),
                       merges)
        log.debug("merge " + str(merge))
        assert 'closed' == merge[0]['state']
        assert main.GitHub2GitLab.TAG_MERGED in merge[0]['description']

    def close_pull_1(self):
        g = self.g.github
        url = g['url'] + "/repos/" + g['repo'] + "/pulls/1"
        query = {'access_token': g['token']}
        data = {'state': 'closed'}
        requests.patch(url, params=query, data=json.dumps(data))

    def verify_closed_pull(self):
        g = self.g.gitlab
        merges = self.g.get(g['url'] + "/projects/" + g['repo'] +
                            "/merge_requests",
                            {'private_token': g['token'],
                             'state': 'all'},
                            cache=False)
        log.debug("merges " + str(merges))
        assert len(merges) == 5
        for merge in merges:
            log.debug("source_branch " + merge['source_branch'] +
                      " state " + merge['state'])
            if merge['source_branch'] in ('pull/1/head', 'pull/5/head'):
                assert merge['state'] == 'closed'
            else:
                assert merge['state'] == 'opened'

    def add_deleted_branch(self):
        g = self.g.github
        url = g['url'] + "/repos/" + g['repo'] + "/pulls"
        query = {'access_token': g['token']}
        data = {
            'title': u'title branch 5 on 3',
            'head': 'branch5',
            'base': 'branch3',
            'body': u'body branch ',
        }
        r = requests.post(url, params=query, data=json.dumps(data))
        if r.status_code != 201:
            raise Exception(r.text)
        self.g.sh("git push origin --delete branch3")
        self.g.sh("cd " + self.g.gitlab['name'] + " ; git branch -D branch3")

    def verify_deleted_branch(self):
        g = self.g.gitlab
        merges = self.g.get(g['url'] + "/projects/" + g['repo'] +
                            "/merge_requests",
                            {'private_token': g['token'],
                             'state': 'all'},
                            cache=False)
        log.debug("merges " + str(merges))
        assert len(merges) == 5

    def merge_pull_4(self):
        g = self.g.github
        url = g['url'] + "/repos/" + g['repo'] + "/pulls/4/merge"
        query = {'access_token': g['token']}
        data = {'commit_message': 'COMMIT MESSAGE'}
        r = requests.put(url, params=query, data=json.dumps(data))
        log.debug("merge output " + r.text)
        r.raise_for_status()

    def verify_merge_pull(self):
        g = self.g.gitlab
        merges = self.g.get(g['url'] + "/projects/" + g['repo'] +
                            "/merge_requests",
                            {'private_token': g['token'],
                             'state': 'all'},
                            cache=False)
        log.debug("merges " + str(merges))
        assert len(merges) == 5
        for merge in merges:
            if merge['source_branch'] in ('pull/1/head',
                                          'pull/3/head',
                                          'pull/5/head'):
                assert merge['state'] == 'closed'
            elif merge['source_branch'] == 'pull/4/head':
                assert merge['state'] == 'merged'
            else:
                assert merge['state'] == 'opened'

    def remove_gitlab(self):
        g = self.g.gitlab
        url = g['url'] + "/projects/" + g['repo']
        query = {'private_token': g['token']}
        assert requests.delete(url, params=query).status_code in (200, 404)

    def reset_github(self):
        g = self.g.github
        url = g['url'] + "/repos/" + g['repo']
        query = {'access_token': g['token']}
        assert requests.delete(url, params=query).status_code in (204, 404)
        url = g['url'] + "/user/repos"
        data = {'name': g['repo'].split('/')[1]}
        requests.post(url,
                      params=query,
                      data=json.dumps(data)).raise_for_status()
        self.g.sh("""
echo "# testrepo" >> README.md
git init
git add README.md
git commit -m "first commit"
git remote add origin git@github.com:{repo}.git
git push -u origin master
for i in $(seq 1 6) ; do
        touch file$i.txt
        git add file$i.txt
        git commit -m "commit $i"
        git push origin master:branch$i
        git reset --hard origin/master
done
        """.format(repo=g['repo']))

Integration(sys.argv[1:])
