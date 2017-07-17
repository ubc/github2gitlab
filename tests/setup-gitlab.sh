set -ex
DATA=$(pwd)/data
for i in test-gitlab test-mysql test-redis ; do sudo docker stop $i || true ; sudo docker rm $i || true ; done
mkdir -p $DATA
sudo docker run --name=test-redis -d sameersbn/redis:latest
sudo rm -fr $DATA/mysql
mkdir -p $DATA/mysql
sudo docker run --name=test-mysql -d -e 'DB_NAME=gitlabhq_production' -e 'DB_USER=gitlab' -e 'DB_PASS=Wrobyak4' -v $DATA/mysql/data:/var/lib/mysql sameersbn/mysql:latest
sudo rm -fr $DATA/gitlab
mkdir -p $DATA/gitlab
sudo docker run --name='test-gitlab' -it -d --link test-mysql:mysql --link test-redis:redisio -e 'GITLAB_SIGNUP=true' -e 'GITLAB_PORT=80' -e 'GITLAB_HOST=localhost' -e 'GITLAB_SSH_PORT=2222' -p 2222:22 -p 8181:80 -e GITLAB_SECRETS_DB_KEY_BASE=4W44tm7bJFRPWNMVzKngffxVWXRpVs49dxhFwgpx7FbCj3wXCMmsz47LzWsdr7nM -v /var/run/docker.sock:/run/docker.sock -v $DATA/gitlab/data:/home/git/data -v $(which docker):/bin/docker sameersbn/gitlab
sleep 60
