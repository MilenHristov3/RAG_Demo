# Install project dependencies
```sh
python3 -m venv venv --without-pip
source venv/bin/activate
curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py
python3 get-pip.py

rm get-pip.py

pip install -r requirements.txt
```