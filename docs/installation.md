# Installation

```sh
python3 -m venv venv --without-pip
source venv/bin/activate
curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py
python3 get-pip.py

rm get-pip.py

pip install -r requirements.txt
```

## Requirements

The project requires the following Python packages (listed in `requirements.txt`):

- `psycopg[binary]` - PostgreSQL adapter
- `pgvector` - PostgreSQL vector extension for embeddings
- `black` - Code formatter
- `python-dotenv` - Environment variable management
- `pymupdf` - PDF processing
- `pymupdf4llm` - PDF to Markdown conversion
- `requests` - HTTP client for downloading documents

## Environment Configuration

Create a `.env` file in the project root with your PostgreSQL connection details:

```env
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=your_database
POSTGRES_USER=your_user
POSTGRES_PASSWORD=your_password
```
## Install PostgreSQL and pgvector

Run comands:

```sh
cd project_namer
./scripts/setup_docker.sh
```

## Verify Installation

Test the database connection:

```sh
python src/db.py
```

You should see output confirming the PostgreSQL connection and version.