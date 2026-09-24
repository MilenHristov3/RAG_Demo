# Information about the project creation, chats, structure, steps, etc. 



### Chat with ChatGPT for initial setup and ...
https://chatgpt.com/share/6ab3af6c-a3a0-83ed-9f3d-6f825342343b



### Usefull commands
```sh
#Check what is using port 5432
sudo ss -ltnp | grep ':5432'


sudo systemctl status postgresql
sudo systemctl stop postgresql

docker compose ps

#checks if postgres is running and if extension is installed
docker compose exec postgres \
  psql -U postgres -d eu_rag \
  -c "SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';"

# remove docker
docker compose down -v

#check logs
docker compose logs --tail=50 postgres
```