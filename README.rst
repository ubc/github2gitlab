github2gitlab
=============

github2gitlab is a command line tool to mirror projects from GitHub
to GitLab. It does the following, in sequence:

* Upload the ~/.ssh/id_rsa.pub ssh key to gitlab if not found
* Create the gitlab project if it does not exist
* Mirror the github git repository to the gitlab git repository
* Create or update the GitLab merge requests to match the 
  GitHub pull requests

Examples
========

Mirror http://github.com/dachary/test to http://workbench.dachary.org/dachary/test

.. code:: sh

    github2gitlab \
       --gitlab-url http://workbench.dachary.org \
       --gitlab-token sxQJ67SQKihMrGWVf \
       --github-repo dachary/test 

Mirror http://github.com/ceph/ceph to
http://workbench.dachary.org/ceph/ceph-backports and use the GitHub
token to be allowed to do more requests than when anonymous.
Use --ignore-closed to get rid of pull requests that are closed and
were never merged.

.. code:: sh

    github2gitlab \
       --gitlab-url http://workbench.dachary.org \
       --gitlab-token sxQJ67SQKihMrGWVf \
       --gitlab-repo ceph/ceph-backports \
       --github-token 64933d355fda9844aadd4e224d \
       --github-repo ceph/ceph \
       --ignore-closed

Mirroring details
=================

The GitHub git repository contains a reference for each pull requests.
For instance the pull request 483 has the refs/pull/483/head reference
which is the tip of the branch that was pushed. If the pull request is
open and can be merged on the destination, the reference
refs/pull/483/merge also exists and is the result of the merge.

Instead of mirroring the refs/pull/\* references to GitLab, they are
moved to refs/heads/pull/\* so they become branches. If GitLab CI is
watching the project, it will run a job each time the pull/\*/head
reference is updated.

The pull requests title and description are mirrored exactly. The
state of the pull request cannot be mapped exactly and is translated
as follows::

  if the pull request is opened, the merge request is opened
  if the pull request is closed,
    if the pull request merged_at field is null,
      the merge request is closed
    else
      the merge request is merged

If a merge request is opened to mirror a pull request that has been
merged already, GitLab will refuse to set it to the merged state
because it notices that there would be nothing to merge. In this case
the merge request is set to the closed state and the :MERGED: string
is append to the description.

* GitLab API http://doc.gitlab.com/ce/api/
* GitHub API https://developer.github.com/v3/

Hacking
=======

* Get the code : git clone http://workbench.dachary.org/dachary/github2gitlab.git
* Run the unit tests : tox
* Run the integration tests. They require a gitlab token and a github token from 
  actual users with permissions to delete and create projects. The github project
  specified with --github-repo and the github project specified with --gitlab-repo
  will be removed and all their data and git repository lost during the test.

  PYTHONPATH=. tests/integration.py \
    --gitlab-url http://workbench.dachary.org \
    --gitlab-token XXXXXXXXX \
    --gitlab-repo dachary/testrepo2 \
    --github-token XXXXXXXXX \
    --github-repo dachary/testrepo \
    --ssh-public-key ~/.ssh/id_rsa.pub \
    --verbose  

* Tag a version

 - version=1.3.0 ; perl -pi -e "s/^version.*/version = $version/" setup.cfg ; for i in 1 2 ; do python setup.py sdist ; amend=$(git log -1 --oneline | grep --quiet "version $version" && echo --amend) ; git commit $amend -m "version $version" ChangeLog setup.cfg ; git tag -a -f -m "version $version" $version ; done

* Check the documentation : rst2html < README.rst > /tmp/a.html

* Publish a new version

 - python setup.py sdist upload --sign
 - git push ; git push --tags

* pypi maintenance

 - python setup.py register # if the project does not yet exist
 - trim old versions at https://pypi.python.org/pypi/github2gitlab
